"""Jamoa kuchi va uchrashuv bo'yicha kutilayotgan gollar (Poisson lambda)."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config


@dataclass
class TeamRating:
    team_id: int
    name: str
    short: str
    attack: float          # 1.0 = o'rtacha hujum
    defence: float         # 1.0 = o'rtacha himoya (kattasi — yomonroq himoya)
    matches: int = 0
    xgf_per_match: float = 0.0
    xga_per_match: float = 0.0


@dataclass
class FixtureView:
    """Bitta jamoa nuqtai nazaridan bitta uchrashuv."""
    event: int
    team: int
    opponent: int
    is_home: bool
    lam_for: float         # o'z jamoasi uradigan gollar
    lam_against: float     # o'z darvozasiga kiradigan gollar
    kickoff: str | None = None
    fdr: int = 3


def _mean(values: list[float]) -> float:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else 0.0


def build_team_ratings(bootstrap: dict, cfg: Config) -> dict[int, TeamRating]:
    """FPL ning strength qiymatlari + joriy mavsum xG ma'lumotini birlashtiradi."""
    teams = bootstrap["teams"]
    elements = bootstrap["elements"]

    # 1) Pre-season prior: FPL strength qiymatlari
    att_vals = [(t["strength_attack_home"] + t["strength_attack_away"]) / 2 for t in teams]
    def_vals = [(t["strength_defence_home"] + t["strength_defence_away"]) / 2 for t in teams]
    att_avg, def_avg = _mean(att_vals), _mean(def_vals)

    prior: dict[int, tuple[float, float]] = {}
    for t in teams:
        a = ((t["strength_attack_home"] + t["strength_attack_away"]) / 2) / (att_avg or 1)
        d = ((t["strength_defence_home"] + t["strength_defence_away"]) / 2) / (def_avg or 1)
        # d kattaroq = kuchli himoya -> gol kamroq kiradi, shuning uchun teskarisi
        prior[t["id"]] = (a, 1.0 / d if d else 1.0)

    # 2) Joriy mavsum: hujum uchun jamoa xG yig'indisi, himoya uchun darvozabon xGC/90
    played: dict[int, int] = {t["id"]: max(t.get("played", 0), 0) for t in teams}
    xgf: dict[int, float] = {t["id"]: 0.0 for t in teams}
    best_gk: dict[int, tuple[int, float]] = {}   # team -> (minutes, xgc_per_90)

    for e in elements:
        tid = e["team"]
        try:
            xgf[tid] += float(e.get("expected_goals") or 0)
        except (TypeError, ValueError):
            pass
        if e["element_type"] == 1:
            mins = e.get("minutes", 0)
            if mins > best_gk.get(tid, (0, 0.0))[0]:
                best_gk[tid] = (mins, float(e.get("expected_goals_conceded_per_90") or 0))

    league_xg_per_match = cfg.home_base_goals + cfg.away_base_goals
    ratings: dict[int, TeamRating] = {}
    obs_xgf, obs_xga = [], []
    for t in teams:
        n = played[t["id"]]
        if n:
            obs_xgf.append(xgf[t["id"]] / n)
        gk = best_gk.get(t["id"])
        if gk and gk[0] >= 45:
            obs_xga.append(gk[1])
    obs_xgf_avg = _mean(obs_xgf) or (league_xg_per_match / 2)
    obs_xga_avg = _mean(obs_xga) or (league_xg_per_match / 2)

    k = cfg.team_form_shrink_matches
    for t in teams:
        tid = t["id"]
        n = played[tid]
        w = n / (n + k) if (n + k) else 0.0        # joriy mavsum ma'lumotining vazni

        a_prior, d_prior = prior[tid]
        a_obs = (xgf[tid] / n / obs_xgf_avg) if n and obs_xgf_avg else a_prior
        gk = best_gk.get(tid)
        d_obs = (gk[1] / obs_xga_avg) if (gk and gk[0] >= 45 and obs_xga_avg) else d_prior

        attack = (1 - w) * a_prior + w * a_obs
        defence = (1 - w) * d_prior + w * d_obs
        ratings[tid] = TeamRating(
            team_id=tid,
            name=t["name"],
            short=t["short_name"],
            attack=max(0.35, min(2.2, attack)),
            defence=max(0.35, min(2.2, defence)),
            matches=n,
            xgf_per_match=(xgf[tid] / n) if n else 0.0,
            xga_per_match=gk[1] if gk else 0.0,
        )
    return ratings


def fixture_lambdas(
    ratings: dict[int, TeamRating], team: int, opponent: int, is_home: bool, cfg: Config
) -> tuple[float, float]:
    """(o'z gollari, kiritgan gollari) — Poisson kutilmasi."""
    me, opp = ratings[team], ratings[opponent]
    base_for = cfg.home_base_goals if is_home else cfg.away_base_goals
    base_against = cfg.away_base_goals if is_home else cfg.home_base_goals
    lam_for = base_for * me.attack * opp.defence
    lam_against = base_against * opp.attack * me.defence
    return max(0.15, min(4.5, lam_for)), max(0.15, min(4.5, lam_against))


def build_fixture_views(
    fixtures: list[dict],
    ratings: dict[int, TeamRating],
    cfg: Config,
    from_event: int,
    to_event: int,
) -> dict[int, dict[int, list[FixtureView]]]:
    """team_id -> event -> uchrashuvlar ro'yxati (DGW/BGW avtomatik hisobga olinadi)."""
    out: dict[int, dict[int, list[FixtureView]]] = {tid: {} for tid in ratings}
    for f in fixtures:
        ev = f.get("event")
        if ev is None or ev < from_event or ev > to_event:
            continue
        if f.get("finished") or f.get("finished_provisional"):
            continue
        h, a = f["team_h"], f["team_a"]
        if h not in ratings or a not in ratings:
            continue
        lh, la = fixture_lambdas(ratings, h, a, True, cfg)
        out[h].setdefault(ev, []).append(
            FixtureView(ev, h, a, True, lh, la, f.get("kickoff_time"), f.get("team_h_difficulty", 3))
        )
        out[a].setdefault(ev, []).append(
            FixtureView(ev, a, h, False, la, lh, f.get("kickoff_time"), f.get("team_a_difficulty", 3))
        )
    return out


def fixture_ticker(
    views: dict[int, dict[int, list[FixtureView]]],
    ratings: dict[int, TeamRating],
    events: list[int],
) -> list[tuple[str, float, list[str]]]:
    """Har jamoa uchun kelgusi turlar qiyinligi: (jamoa, o'rtacha qiyinlik, belgilar)."""
    rows = []
    for tid, per_event in views.items():
        marks, scores = [], []
        for ev in events:
            fx = per_event.get(ev, [])
            if not fx:
                marks.append("—")
                continue
            for f in fx:
                opp = ratings[f.opponent].short
                marks.append(f"{opp}{'(u)' if f.is_home else '(m)'}")
                # qiyinlik: raqibga qarshi kutilayotgan gol farqi
                scores.append(f.lam_for - f.lam_against)
        rows.append((ratings[tid].short, sum(scores) / len(scores) if scores else 0.0, marks))
    return sorted(rows, key=lambda r: -r[1])
