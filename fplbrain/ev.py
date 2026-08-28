"""EV modeli — har bir o'yinchi uchun kelgusi turlarda kutilayotgan FPL ochkosi.

Model bo'laklari:
  1. Daqiqalar   — o'ynash va 60+ daqiqa o'ynash ehtimoli
  2. Hujum       — xG90/xA90 (shrinkage bilan) x uchrashuv koeffitsiyenti
  3. Himoya      — Poisson orqali "toza darvoza" va kiritilgan gol jarimasi
  4. DefCon      — himoya harakatlari chegarasidan o'tish ehtimoli
  5. Bonus       — 90 daqiqalik bonus tezligi (shrinkage bilan)
  6. Kartochka   — sariq kartochka jarimasi
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .config import Config
from .ratings import FixtureView, TeamRating

GK, DEF, MID, FWD = 1, 2, 3, 4

GOAL_POINTS = {GK: 6, DEF: 6, MID: 5, FWD: 4}
CS_POINTS = {GK: 4, DEF: 4, MID: 1, FWD: 0}
DEFCON_THRESHOLD = {DEF: 10, MID: 12, FWD: 12}          # GK uchun DefCon yo'q
ASSIST_POINTS = 3
DEFCON_POINTS = 2

# Pozitsiya bo'yicha priorlar (90 daqiqaga) — kam o'ynagan o'yinchini shu tomon tortamiz
PRIOR_XG90 = {GK: 0.0, DEF: 0.06, MID: 0.16, FWD: 0.34}
PRIOR_XA90 = {GK: 0.01, DEF: 0.08, MID: 0.16, FWD: 0.14}
PRIOR_BONUS90 = {GK: 0.28, DEF: 0.26, MID: 0.28, FWD: 0.34}
PRIOR_DC90 = {GK: 0.0, DEF: 6.4, MID: 6.0, FWD: 3.4}
PRIOR_YELLOW90 = 0.13
PRIOR_SAVES90 = 3.0


# --------------------------------------------------------------------- yordamchi
def poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam + k * math.log(lam) - math.lgamma(k + 1))


def poisson_tail(threshold: int, lam: float) -> float:
    """P(X >= threshold)."""
    if lam <= 0:
        return 0.0
    below = sum(poisson_pmf(k, lam) for k in range(threshold))
    return max(0.0, min(1.0, 1.0 - below))


def negbinom_tail(threshold: int, mean: float, dispersion: float = 1.8) -> float:
    """P(X >= threshold), dispersiyasi kattaroq taqsimot bilan.

    Himoya harakatlari (CBIT/CBIRT) Poisson dan ko'ra "tarqoq": bir o'yinda ko'p,
    boshqasida kam bo'ladi (o'yin uslubi, raqib bosimi). Shuning uchun
    manfiy binomial ishlatamiz — u chegaradan o'tish ehtimolini realroq beradi.
    """
    if mean <= 0:
        return 0.0
    if dispersion <= 1.0:
        return poisson_tail(threshold, mean)
    r = mean / (dispersion - 1.0)
    p = r / (r + mean)
    below = 0.0
    for k in range(threshold):
        log_pmf = (
            math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1)
            + r * math.log(p) + k * math.log(1 - p)
        )
        below += math.exp(log_pmf)
    return max(0.0, min(1.0, 1.0 - below))


def expected_conceded_penalty(lam: float, cap: int = 9) -> float:
    """E[floor(gollar / 2)] — har 2 golga -1 ochko."""
    return sum(poisson_pmf(k, lam) * (k // 2) for k in range(cap + 1))


def shrink(observed_total: float, nineties: float, prior_rate: float, k: float) -> float:
    """Empirik Bayes: kam o'ynagan bo'lsa prior tomon tortiladi."""
    if nineties <= 0:
        return prior_rate
    return (observed_total + prior_rate * k) / (nineties + k)


def _f(value, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------------------ profil
@dataclass
class PlayerProfile:
    """O'yinchining tezliklari — uchrashuvdan mustaqil holda."""
    element: int
    name: str
    team: int
    position: int
    price: float
    status: str
    availability: float
    p_start: float
    p_appear: float
    p60: float
    xmins: float
    xg90: float
    xa90: float
    dc90: float
    dc_hit_rate: float | None
    bonus90: float
    saves90: float
    yellow90: float
    is_pen_taker: bool
    is_set_piece: bool
    minutes: int
    nineties: float
    news: str = ""
    ownership: float = 0.0


def _history_window(history: list[dict], n: int = 6) -> list[dict]:
    return [h for h in history if h.get("minutes") is not None][-n:]


def build_profile(
    element: dict,
    summary: dict | None,
    cfg: Config,
    team_matches: int = 0,
) -> PlayerProfile:
    """team_matches — o'yinchi jamoasi mavsumda nechta o'yin o'ynagani (bootstrap teams.played)."""
    pos = element["element_type"]
    minutes = element.get("minutes", 0) or 0
    nineties = minutes / 90.0

    history = (summary or {}).get("history", []) or []
    past = (summary or {}).get("history_past", []) or []

    # ---------- 1. mavjudlik ----------
    status = element.get("status", "a")
    chance = element.get("chance_of_playing_next_round")
    if chance is not None:
        availability = _f(chance) / 100.0
    elif status == "a":
        availability = 1.0
    elif status in ("d",):
        availability = 0.5
    else:                      # i (jarohat), s (diskvalifikatsiya), u (klubdan ketgan), n
        availability = 0.0

    # ---------- 2. daqiqalar ----------
    window = _history_window(history, 6)
    recent_minutes = [h.get("minutes", 0) or 0 for h in window]
    recent_starts = [1 if (h.get("starts") or 0) > 0 else 0 for h in window]

    # Prior: o'tgan mavsum bo'lsa — o'shandan; bo'lmasa narxdan (qimmat o'yinchi = asosiy tarkib)
    price = element["now_cost"] / 10.0
    price_prior = max(0.28, min(0.88, 0.30 + (price - 4.0) / 9.0 * 0.55))
    prior_start_rate, prior_p60 = price_prior, price_prior * 0.92
    if past:
        last = past[-1]
        pm, ps = last.get("minutes", 0) or 0, last.get("starts", 0) or 0
        if pm > 0:
            prior_start_rate = min(1.0, ps / 38.0)
            prior_p60 = min(1.0, (pm / 38.0) / 78.0)

    sub_min = 18.0
    if recent_minutes:
        # batafsil tarix bor — oxirgi o'yinlar bo'yicha
        n = len(recent_minutes)
        obs_start = sum(recent_starts) / n
        obs_p60 = sum(1 for m in recent_minutes if m >= 60) / n
        start_minutes = [m for m, s in zip(recent_minutes, recent_starts) if s]
        avg_start_min = sum(start_minutes) / len(start_minutes) if start_minutes else 80.0
    elif team_matches > 0:
        # faqat mavsum yig'indisi bor (bootstrap) — starts/minutes dan chiqaramiz
        n = team_matches
        starts = element.get("starts", 0) or 0
        obs_start = min(1.0, starts / team_matches)
        avg_start_min = (minutes / starts) if starts else 80.0
        obs_p60 = min(1.0, (minutes / team_matches) / 78.0)
    else:
        n = 0
        obs_start, obs_p60, avg_start_min = prior_start_rate, prior_p60, 82.0

    if n:
        # Bayescha vazn: prior "k ta o'yinga teng dalil" sifatida qaraladi.
        # n=1 -> 0.75, n=3 -> 0.50, n=6 -> 0.33, n=12 -> 0.20.
        # Mavsum boshida bitta zaxiradan chiqish o'yinchini "yo'q" qilib
        # qo'ymasligi uchun shu shakl tanlandi.
        k = max(0.5, cfg.minutes_prior_matches)
        w_prior = min(0.85, k / (k + n))
        p_start = (1 - w_prior) * obs_start + w_prior * prior_start_rate
        p60 = (1 - w_prior) * obs_p60 + w_prior * prior_p60
    else:
        p_start, p60 = prior_start_rate, prior_p60

    p_start = max(0.0, min(1.0, p_start)) * availability
    p60 = max(0.0, min(p_start, p60 * availability))
    p_appear = min(1.0, p_start + (1 - p_start) * 0.30 * availability)
    xmins = p_start * avg_start_min + (p_appear - p_start) * sub_min

    # ---------- 3. hujum tezliklari ----------
    xg = _f(element.get("expected_goals"))
    xa = _f(element.get("expected_assists"))
    prior_xg, prior_xa = PRIOR_XG90[pos], PRIOR_XA90[pos]
    if past:
        last = past[-1]
        pm = (last.get("minutes", 0) or 0) / 90.0
        if pm >= 5:
            prior_xg = 0.5 * prior_xg + 0.5 * (_f(last.get("expected_goals")) / pm)
            prior_xa = 0.5 * prior_xa + 0.5 * (_f(last.get("expected_assists")) / pm)
    xg90 = shrink(xg, nineties, prior_xg, cfg.shrink_attack_90s)
    xa90 = shrink(xa, nineties, prior_xa, cfg.shrink_attack_90s)

    # ---------- 4. DefCon ----------
    cbit = _f(element.get("clearances_blocks_interceptions")) + _f(element.get("tackles"))
    actions = cbit + (_f(element.get("recoveries")) if pos in (MID, FWD) else 0.0)
    prior_dc = PRIOR_DC90[pos]
    if past:
        last = past[-1]
        pm = (last.get("minutes", 0) or 0) / 90.0
        if pm >= 5:
            past_actions = (
                _f(last.get("clearances_blocks_interceptions"))
                + _f(last.get("tackles"))
                + (_f(last.get("recoveries")) if pos in (MID, FWD) else 0.0)
            )
            prior_dc = 0.4 * prior_dc + 0.6 * (past_actions / pm)
    dc90 = shrink(actions, nineties, prior_dc, cfg.shrink_defcon_90s)

    # empirik: nechta o'yinda chegaradan o'tgan
    dc_hit_rate = None
    starts_played = [h for h in history if (h.get("minutes") or 0) >= 60]
    if len(starts_played) >= 4 and pos != GK:
        thr = DEFCON_THRESHOLD[pos]
        hits = 0
        for h in starts_played:
            act = _f(h.get("clearances_blocks_interceptions")) + _f(h.get("tackles"))
            if pos in (MID, FWD):
                act += _f(h.get("recoveries"))
            hits += 1 if act >= thr else 0
        dc_hit_rate = hits / len(starts_played)

    # ---------- 5. bonus, saqlash, kartochka ----------
    bonus90 = shrink(_f(element.get("bonus")), nineties, PRIOR_BONUS90[pos], cfg.shrink_bonus_90s)
    saves90 = shrink(_f(element.get("saves")), nineties, PRIOR_SAVES90, 4.0) if pos == GK else 0.0
    yellow90 = shrink(_f(element.get("yellow_cards")), nineties, PRIOR_YELLOW90, 6.0)

    return PlayerProfile(
        element=element["id"],
        name=element.get("web_name", "?"),
        team=element["team"],
        position=pos,
        price=element["now_cost"] / 10.0,
        status=status,
        availability=availability,
        p_start=p_start,
        p_appear=p_appear,
        p60=p60,
        xmins=xmins,
        xg90=xg90,
        xa90=xa90,
        dc90=dc90,
        dc_hit_rate=dc_hit_rate,
        bonus90=bonus90,
        saves90=saves90,
        yellow90=yellow90,
        is_pen_taker=(element.get("penalties_order") == 1),
        is_set_piece=(
            element.get("corners_and_indirect_freekicks_order") == 1
            or element.get("direct_freekicks_order") == 1
        ),
        minutes=minutes,
        nineties=nineties,
        news=element.get("news") or "",
        ownership=_f(element.get("selected_by_percent")),
    )


# ------------------------------------------------------------------ EV hisobi
@dataclass
class FixtureEV:
    event: int
    opponent: str
    is_home: bool
    ev: float
    parts: dict[str, float] = field(default_factory=dict)
    p_haul: float = 0.0        # 10+ ochko ehtimoli (taxminiy)
    p_return: float = 0.0      # gol yoki uzatma ehtimoli


def fixture_ev(
    profile: PlayerProfile,
    fx: FixtureView,
    ratings: dict[int, TeamRating],
    team_neutral_lam_for: float,
    team_neutral_lam_against: float,
) -> FixtureEV:
    pos = profile.position
    share = profile.xmins / 90.0

    # uchrashuv koeffitsiyentlari: neytral holatga nisbatan
    att_mult = fx.lam_for / team_neutral_lam_for if team_neutral_lam_for else 1.0
    def_mult = fx.lam_against / team_neutral_lam_against if team_neutral_lam_against else 1.0

    xg = profile.xg90 * share * att_mult
    xa = profile.xa90 * share * att_mult

    pts_goals = xg * GOAL_POINTS[pos]
    pts_assists = xa * ASSIST_POINTS

    # toza darvoza — 60+ daqiqa talab qilinadi
    p_cs = math.exp(-fx.lam_against)
    pts_cs = p_cs * CS_POINTS[pos] * profile.p60

    # kiritilgan gollar (faqat GK/DEF)
    pts_conceded = 0.0
    if pos in (GK, DEF):
        pts_conceded = -expected_conceded_penalty(fx.lam_against * share)

    # darvozabon to'xtatishlari
    pts_saves = 0.0
    if pos == GK:
        pts_saves = (profile.saves90 * share * def_mult) / 3.0

    # DefCon
    pts_dc = 0.0
    if pos in DEFCON_THRESHOLD:
        thr = DEFCON_THRESHOLD[pos]
        lam_actions = profile.dc90 * share
        p_model = negbinom_tail(thr, lam_actions)
        if profile.dc_hit_rate is not None:
            p_dc = 0.5 * p_model + 0.5 * (profile.dc_hit_rate * min(1.0, share / 0.75))
        else:
            p_dc = p_model
        pts_dc = p_dc * DEFCON_POINTS

    pts_bonus = profile.bonus90 * share * (0.6 + 0.4 * att_mult)
    pts_cards = -profile.yellow90 * share
    pts_appearance = profile.p_appear * 1.0 + profile.p60 * 1.0

    total = (
        pts_appearance + pts_goals + pts_assists + pts_cs
        + pts_conceded + pts_saves + pts_dc + pts_bonus + pts_cards
    )

    p_goal = 1 - math.exp(-xg)
    p_assist = 1 - math.exp(-xa)
    p_return = 1 - (1 - p_goal) * (1 - p_assist)
    # taxminiy "haul" ehtimoli: 2+ hissa yoki gol + toza darvoza
    p_multi = 1 - math.exp(-(xg + xa)) - (xg + xa) * math.exp(-(xg + xa))
    p_haul = min(0.6, p_multi + 0.35 * p_goal * (p_cs if pos in (GK, DEF, MID) else 0))

    return FixtureEV(
        event=fx.event,
        opponent=ratings[fx.opponent].short,
        is_home=fx.is_home,
        ev=round(total, 3),
        parts={
            "ishtirok": round(pts_appearance, 2),
            "gol": round(pts_goals, 2),
            "uzatma": round(pts_assists, 2),
            "toza_darvoza": round(pts_cs, 2),
            "kiritilgan": round(pts_conceded, 2),
            "to'xtatish": round(pts_saves, 2),
            "defcon": round(pts_dc, 2),
            "bonus": round(pts_bonus, 2),
            "kartochka": round(pts_cards, 2),
        },
        p_haul=round(p_haul, 3),
        p_return=round(p_return, 3),
    )


@dataclass
class PlayerEV:
    profile: PlayerProfile
    per_event: dict[int, float]                 # GW -> EV (DGW da yig'indi)
    fixtures: dict[int, list[FixtureEV]]
    horizon_ev: float                           # decay bilan vaznlangan yig'indi
    next_ev: float

    @property
    def element(self) -> int:
        return self.profile.element

    @property
    def value(self) -> float:
        """1.0m ga to'g'ri keladigan EV — narx samaradorligi."""
        return self.horizon_ev / self.profile.price if self.profile.price else 0.0


class EVEngine:
    def __init__(
        self,
        cfg: Config,
        ratings: dict[int, TeamRating],
        views: dict[int, dict[int, list[FixtureView]]],
    ) -> None:
        self.cfg = cfg
        self.ratings = ratings
        self.views = views
        self._neutral = self._neutral_lambdas()

    def _neutral_lambdas(self) -> dict[int, tuple[float, float]]:
        """Har jamoa uchun "o'rtacha raqib" bilan kutilayotgan gollar."""
        out = {}
        avg_att = sum(r.attack for r in self.ratings.values()) / len(self.ratings)
        avg_def = sum(r.defence for r in self.ratings.values()) / len(self.ratings)
        base = (self.cfg.home_base_goals + self.cfg.away_base_goals) / 2
        for tid, r in self.ratings.items():
            out[tid] = (
                max(0.2, base * r.attack * avg_def),
                max(0.2, base * avg_att * r.defence),
            )
        return out

    def evaluate(self, profile: PlayerProfile, events: list[int]) -> PlayerEV:
        neutral_for, neutral_against = self._neutral[profile.team]
        per_event: dict[int, float] = {}
        fixtures: dict[int, list[FixtureEV]] = {}
        team_views = self.views.get(profile.team, {})

        for ev in events:
            fxs = team_views.get(ev, [])
            evs = [
                fixture_ev(profile, fx, self.ratings, neutral_for, neutral_against)
                for fx in fxs
            ]
            fixtures[ev] = evs
            per_event[ev] = round(sum(f.ev for f in evs), 3)

        decay = self.cfg.horizon_decay
        horizon = sum(per_event.get(ev, 0.0) * (decay ** i) for i, ev in enumerate(events))
        return PlayerEV(
            profile=profile,
            per_event=per_event,
            fixtures=fixtures,
            horizon_ev=round(horizon, 3),
            next_ev=round(per_event.get(events[0], 0.0), 3) if events else 0.0,
        )
