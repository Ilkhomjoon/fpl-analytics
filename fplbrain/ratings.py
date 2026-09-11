"""Jamoa kuchi va uchrashuv bo'yicha kutilayotgan gollar (Poisson lambda).

Jamoa kuchi uchta manbadan yig'iladi:

  1. **Prior** — FPL ning `strength_*` qiymatlari (mavsum boshida belgilangan);
  2. **Jarayon** — joriy mavsum xG / xGC (natijadan barqarorroq);
  3. **Natija** — joriy mavsum jadvali: urilgan/kiritilgan gollar va forma.

O'ynalgan o'yinlar ko'paygani sari 2 va 3 ning vazni ortadi (shrinkage), ya'ni
mavsum boshida prior, keyinroq esa haqiqiy o'yin ustun turadi.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import congestion
from .config import Config
from .table import TableRow


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
    # --- jadvaldan ---
    position: int = 0      # 0 = hali o'yin yo'q
    points: int = 0
    form_ppg: float = 0.0
    form_string: str = ""
    gf_per_match: float = 0.0
    ga_per_match: float = 0.0

    @property
    def rank_label(self) -> str:
        return f"{self.position}-o'rin" if self.position else "jadval yo'q"


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
    fdr: int = 3           # FPL ning rasmiy FDR si (mavsum boshida qotib qolgan)
    eff_fdr: float = 3.0   # modelning bahosi: lambda + raqibning jadvaldagi o'rni
    opp_position: int = 0  # raqibning jadvaldagi o'rni (0 = noma'lum)
    rotation: float = 0.0  # 0..1 — jadval zichligidan kelib chiqqan rotatsiya xavfi
    # Qiyinlik pozitsiyaga bog'liq: himoyachi uchun raqibning HUJUMI,
    # hujumchi uchun raqibning HIMOYASI muhim. Bir raqam ikkalasini
    # ifodalay olmaydi.
    eff_fdr_def: float = 3.0   # DRV/HIM uchun
    eff_fdr_att: float = 3.0   # YAR/HUJ uchun

    def difficulty_for(self, position: int) -> float:
        """Berilgan pozitsiya uchun tegishli qiyinlik (1 = GK, 2 = DEF, ...)."""
        return self.eff_fdr_def if position in (1, 2) else self.eff_fdr_att


def _mean(values: list[float]) -> float:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else 0.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def build_team_ratings(
    bootstrap: dict,
    cfg: Config,
    table: dict[int, TableRow] | None = None,
) -> dict[int, TeamRating]:
    """FPL strength priori + joriy mavsum xG + jadval natijalarini birlashtiradi."""
    teams = bootstrap["teams"]
    elements = bootstrap["elements"]
    table = table or {}

    # ---------------------------------------------------------------- 1. prior
    # FPL ning strength qiymatlari juda "siqilgan": eng kuchli va eng zaif jamoa
    # orasida atigi ~15% farq bor. Haqiqatda esa gol tezliklari ikki barobar
    # farq qiladi (kuchli jamoa ~2.2 gol, zaif jamoa ~0.9 gol). Nisbatni
    # `strength_spread` darajasiga ko'tarish shu tarqalishni tiklaydi.
    # Bu tuzatilmasa **hamma jamoa o'rtacha ko'rinadi** — Arsenal ham, tepaga
    # chiqolmayotgan jamoa ham. Aynan shu sabab kuchli jamoa futbolchilari
    # asossiz ravishda zaxiraga tushib qolgan edi.
    gamma = max(1.0, float(getattr(cfg, "strength_spread", 2.3)))

    att_vals = [(t["strength_attack_home"] + t["strength_attack_away"]) / 2 for t in teams]
    def_vals = [(t["strength_defence_home"] + t["strength_defence_away"]) / 2 for t in teams]
    att_avg, def_avg = _mean(att_vals) or 1.0, _mean(def_vals) or 1.0

    prior: dict[int, tuple[float, float]] = {}
    for t in teams:
        a_ratio = ((t["strength_attack_home"] + t["strength_attack_away"]) / 2) / att_avg
        d_ratio = ((t["strength_defence_home"] + t["strength_defence_away"]) / 2) / def_avg
        # d_ratio kattaroq = kuchli himoya -> gol kamroq kiradi, shuning uchun teskarisi
        prior[t["id"]] = (
            _clamp(a_ratio ** gamma, 0.55, 1.70),
            _clamp((1.0 / d_ratio if d_ratio else 1.0) ** gamma, 0.55, 1.70),
        )

    # ------------------------------------------------- 2. joriy mavsum: xG va gollar
    played: dict[int, int] = {}
    for t in teams:
        row = table.get(t["id"])
        played[t["id"]] = row.played if row else max(t.get("played", 0) or 0, 0)

    xgf: dict[int, float] = {t["id"]: 0.0 for t in teams}
    best_gk: dict[int, tuple[int, float]] = {}   # team -> (minutes, xgc_per_90)

    for e in elements:
        tid = e["team"]
        if tid not in xgf:
            continue
        try:
            xgf[tid] += float(e.get("expected_goals") or 0)
        except (TypeError, ValueError):
            pass
        if e["element_type"] == 1:
            mins = e.get("minutes", 0) or 0
            if mins > best_gk.get(tid, (0, 0.0))[0]:
                best_gk[tid] = (mins, float(e.get("expected_goals_conceded_per_90") or 0))

    # Natija (gol) va jarayon (xG) birga: xG barqarorroq, gol esa haqiqat.
    w_xg = 0.55
    # So'nggi o'yinlarga urg'u: jadvalning vaznli formasi va oddiy o'rtachasi.
    w_form = 0.6

    def goal_rates(tid: int) -> tuple[float, float]:
        row = table.get(tid)
        if row is None or not row.played:
            return (0.0, 0.0)
        gf = w_form * row.form_gf_rate + (1 - w_form) * row.gf_rate
        ga = w_form * row.form_ga_rate + (1 - w_form) * row.ga_rate
        return (gf, ga)

    obs_att: dict[int, float] = {}
    obs_def: dict[int, float] = {}
    for t in teams:
        tid, n = t["id"], played[t["id"]]
        if not n:
            continue
        gf_pm, ga_pm = goal_rates(tid)
        xg_pm = xgf[tid] / n

        if gf_pm:
            obs_att[tid] = w_xg * xg_pm + (1 - w_xg) * gf_pm
        else:
            obs_att[tid] = xg_pm

        gk = best_gk.get(tid)
        gk_xgc = gk[1] if (gk and gk[0] >= 45) else 0.0
        if gk_xgc and ga_pm:
            obs_def[tid] = w_xg * gk_xgc + (1 - w_xg) * ga_pm
        elif gk_xgc:
            obs_def[tid] = gk_xgc
        elif ga_pm or table.get(tid):
            obs_def[tid] = ga_pm

    att_obs_avg = _mean(list(obs_att.values()))
    def_obs_avg = _mean(list(obs_def.values()))

    # ------------------------------------------------------------ 3. birlashtirish
    k = max(0.5, float(cfg.team_form_shrink_matches))
    ratings: dict[int, TeamRating] = {}
    for t in teams:
        tid = t["id"]
        n = played[tid]
        w = n / (n + k) if (n + k) else 0.0        # joriy mavsum ma'lumotining vazni

        a_prior, d_prior = prior[tid]
        a_obs = (obs_att[tid] / att_obs_avg) if (tid in obs_att and att_obs_avg) else a_prior
        d_obs = (obs_def[tid] / def_obs_avg) if (tid in obs_def and def_obs_avg) else d_prior

        attack = (1 - w) * a_prior + w * a_obs
        defence = (1 - w) * d_prior + w * d_obs

        row = table.get(tid)
        gk = best_gk.get(tid)
        ratings[tid] = TeamRating(
            team_id=tid,
            name=t["name"],
            short=t["short_name"],
            attack=_clamp(attack, 0.40, 2.0),
            defence=_clamp(defence, 0.40, 2.0),
            matches=n,
            xgf_per_match=(xgf[tid] / n) if n else 0.0,
            xga_per_match=gk[1] if gk else 0.0,
            position=row.position if row else 0,
            points=row.points if row else 0,
            form_ppg=round(row.form_ppg, 2) if row else 0.0,
            form_string=row.form_string if row else "",
            gf_per_match=round(row.gf_rate, 2) if row else 0.0,
            ga_per_match=round(row.ga_rate, 2) if row else 0.0,
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
    return _clamp(lam_for, 0.20, 3.60), _clamp(lam_against, 0.20, 3.60)


# ------------------------------------------------------------ samarali qiyinlik
def neutral_lambdas_vs(
    opponent: TeamRating, is_home: bool, cfg: Config
) -> tuple[float, float]:
    """**O'rtacha** jamoa shu raqibga qarshi shu maydonda nechta gol kutadi.

    Nega o'rtacha jamoa? Qiyinlik — raqibning xususiyati, o'zimizning emas.
    Aks holda "kuchli jamoaning jadvali oson" degan aylanma xulosa chiqadi va
    FDR ro'yxati oddiy kuch reytingiga aylanib qoladi.
    """
    base_for = cfg.home_base_goals if is_home else cfg.away_base_goals
    base_against = cfg.away_base_goals if is_home else cfg.home_base_goals
    return (
        _clamp(base_for * opponent.defence, 0.20, 3.60),
        _clamp(base_against * opponent.attack, 0.20, 3.60),
    )


def difficulty_from_lambdas(lam_for: float, lam_against: float) -> float:
    """Kutilayotgan gol farqini 1..5 qiyinlik shkalasiga o'tkazadi.

    +1.6 gol ustunlik -> 1.0 (juda oson), -1.6 -> 5.0 (juda qiyin).
    """
    return _clamp(3.0 - (lam_for - lam_against) * 1.25, 1.0, 5.0)


def difficulty_from_position(opp_position: int, team_count: int = 20) -> float:
    """Raqibning jadvaldagi o'rni: 1-o'rin -> 5.0, oxirgi o'rin -> 1.0."""
    if not opp_position or team_count < 2:
        return 3.0
    # position_index: 1-o'rin -> 1.0, oxirgi o'rin -> 0.0
    share = (team_count - opp_position) / (team_count - 1)
    return _clamp(1.0 + 4.0 * share, 1.0, 5.0)


def effective_difficulty(
    lam_for: float,
    lam_against: float,
    opp_position: int,
    opp_played: int,
    official_fdr: int | None = None,
    team_count: int = 20,
    max_table_weight: float = 0.45,
) -> float:
    """Uchrashuv qiyinligining model bahosi — 1.0 (oson) .. 5.0 (qiyin).

    Uchta manba qo'shiladi:

    * **model** — kutilayotgan gol farqi (jamoa reytingi: prior + xG + natija);
    * **jadval** — raqibning jadvaldagi joriy o'rni;
    * **rasmiy FDR** — FPL ning mavsum boshidagi bahosi.

    Vaznlar o'yin soniga qarab siljiydi. Mavsum boshida jadval bo'sh, shuning
    uchun rasmiy FDR ustunroq turadi; o'yinlar o'ynalgani sari rasmiy FDR ning
    vazni kamayadi, jadvalniki esa ortadi.

    Nega bu kerak? Rasmiy FDR mavsum boshida qotib qoladi va keyin
    yangilanmaydi. Arsenal — Aston Villa o'yinida u 4 ("qiyin") deb turgan edi,
    holbuki Villa mavsumni Brighton dan 0:4 yutqazib boshlagandi. Jadval buni
    ko'radi, rasmiy FDR esa ko'rmaydi.

    Nega jadvalga to'liq ishonmaymiz? 2-3 o'yinlik jadval ham aldaydi. Uning
    vazni ishonch bilan birga o'sadi: 3 o'yinda ~0.19, 10 o'yinda ~0.32.
    """
    d_model = difficulty_from_lambdas(lam_for, lam_against)
    played = max(0, int(opp_played or 0))

    # rasmiy FDR — mavsum boshidagi taxmin, vazni vaqt bilan so'nadi
    w_off = 0.0
    if official_fdr:
        w_off = 0.30 * (4.0 / (played + 4.0))

    # jadval — o'yin ko'paygan sari ishonchliroq
    w_tab = 0.0
    if opp_position and played > 0:
        w_tab = max_table_weight * (played / (played + 4.0))

    w_model = max(0.30, 1.0 - w_off - w_tab)
    total = w_model + w_off + w_tab

    value = w_model * d_model
    if w_off:
        value += w_off * _clamp(float(official_fdr), 1.0, 5.0)
    if w_tab:
        value += w_tab * difficulty_from_position(opp_position, team_count)
    return round(_clamp(value / total, 1.0, 5.0), 2)


# --------------------------------------------- pozitsiyaga qarab qiyinlik
# Premer Liga da bir jamoa o'rtacha bir o'yinda shuncha gol uradi
LEAGUE_GOALS_PER_MATCH = 1.42
# Gol tezligining 1 birlik farqi qiyinlikni shuncha o'zgartiradi
GOAL_RATE_SLOPE = 1.6


def difficulty_for_defence(lam_against: float, opp_gf_rate: float | None = None) -> float:
    """Himoyachi/darvozabon uchun qiyinlik: **raqib gol ura oladimi?**

    Toza darvoza raqibning hujumiga bog'liq, bizning hujumimizga emas.
    Shuning uchun bu yerda raqibning URGAN gollari qaraladi.
    """
    d = _clamp(1.0 + lam_against * 2.0, 1.0, 5.0)
    if opp_gf_rate is None:
        return d
    d_tab = _clamp(3.0 + (opp_gf_rate - LEAGUE_GOALS_PER_MATCH) * GOAL_RATE_SLOPE,
                   1.0, 5.0)
    return _clamp((d + d_tab) / 2.0, 1.0, 5.0)


def difficulty_for_attack(lam_for: float, opp_ga_rate: float | None = None) -> float:
    """Yarim himoyachi/hujumchi uchun qiyinlik: **raqib gol o'tkazadimi?**

    Gol va uzatma raqibning himoyasiga bog'liq. Shuning uchun bu yerda
    raqibning O'TKAZGAN gollari qaraladi — urganlari emas.
    """
    d = _clamp(3.0 - (lam_for - LEAGUE_GOALS_PER_MATCH) * GOAL_RATE_SLOPE, 1.0, 5.0)
    if opp_ga_rate is None:
        return d
    d_tab = _clamp(3.0 - (opp_ga_rate - LEAGUE_GOALS_PER_MATCH) * GOAL_RATE_SLOPE,
                   1.0, 5.0)
    return _clamp((d + d_tab) / 2.0, 1.0, 5.0)


def positional_difficulty(
    lam_for: float,
    lam_against: float,
    opp_row=None,
    official_fdr: int | None = None,
    max_table_weight: float = 0.45,
) -> tuple[float, float]:
    """(himoya uchun qiyinlik, hujum uchun qiyinlik).

    Bitta uchrashuv ikki xil qiyinlikka ega bo'lishi **normal**: mudofaasi
    mustahkam, lekin hujumi zaif jamoaga qarshi himoyachi uchun oson,
    hujumchi uchun qiyin. Bitta raqamni butun o'yinchiga qo'llash aynan shu
    farqni yo'q qilardi.

    Misol (GW3, 2026/27): Leeds 3 o'yinda 3 gol urib, 2 gol o'tkazgan.
    Ularga qarshi HIMOYACHI uchun oson (kam gol uradi), HUJUMCHI uchun esa
    qiyin (kam gol o'tkazadi). Rasmiy FDR ikkalasiga bir xil raqam beradi.
    """
    played = getattr(opp_row, "played", 0) or 0
    gf_rate = ga_rate = None
    if played > 0:
        gf_rate = getattr(opp_row, "gf", 0) / played
        ga_rate = getattr(opp_row, "ga", 0) / played

    d_def = difficulty_for_defence(lam_against, gf_rate)
    d_att = difficulty_for_attack(lam_for, ga_rate)

    # Rasmiy FDR — mavsum boshidagi taxmin; vazni o'yin ko'paygani sari so'nadi
    if official_fdr:
        w_off = 0.30 * (4.0 / (played + 4.0))
        official = _clamp(float(official_fdr), 1.0, 5.0)
        d_def = (1 - w_off) * d_def + w_off * official
        d_att = (1 - w_off) * d_att + w_off * official
    return round(_clamp(d_def, 1.0, 5.0), 2), round(_clamp(d_att, 1.0, 5.0), 2)


def build_fixture_views(
    fixtures: list[dict],
    ratings: dict[int, TeamRating],
    cfg: Config,
    from_event: int,
    to_event: int,
    schedules: dict | None = None,
    european: set[int] | None = None,
    table: dict | None = None,
) -> dict[int, dict[int, list[FixtureView]]]:
    """team_id -> event -> uchrashuvlar ro'yxati (DGW/BGW avtomatik hisobga olinadi).

    `schedules` va `european` berilsa, har uchrashuvga rotatsiya xavfi ham
    qo'shiladi. Berilmasa xavf 0 bo'ladi — eski chaqiruvlar ishlayveradi.
    """
    out: dict[int, dict[int, list[FixtureView]]] = {tid: {} for tid in ratings}
    team_count = len(ratings) or 20
    schedules = schedules or {}
    european = european or set()
    table = table or {}

    table_weight = float(getattr(cfg, "table_weight", 0.45))

    def view(team: int, opp: int, home: bool, ev: int, lf: float, la: float, f: dict) -> FixtureView:
        opp_rating = ratings[opp]
        official = f.get("team_h_difficulty" if home else "team_a_difficulty", 3) or 3
        # Qiyinlik raqib bo'yicha o'lchanadi: o'rtacha jamoa shu raqibga
        # qarshi nima kutadi. lf/la esa aynan BIZNING jamoa uchun.
        n_for, n_against = neutral_lambdas_vs(opp_rating, home, cfg)
        # Pozitsiyaga qarab ikki xil qiyinlik: himoyachiga raqibning HUJUMI,
        # hujumchiga raqibning HIMOYASI muhim
        d_def, d_att = positional_difficulty(
            n_for, n_against, table.get(opp), official_fdr=official,
            max_table_weight=table_weight,
        )
        return FixtureView(
            event=ev,
            team=team,
            opponent=opp,
            is_home=home,
            lam_for=lf,
            lam_against=la,
            kickoff=f.get("kickoff_time"),
            fdr=official,
            eff_fdr=effective_difficulty(
                n_for, n_against, opp_rating.position, opp_rating.matches,
                official_fdr=official, team_count=team_count,
                max_table_weight=table_weight,
            ),
            opp_position=opp_rating.position,
            rotation=congestion.rotation_risk(
                schedules.get(team), f.get("kickoff_time"), team in european),
            eff_fdr_def=d_def,
            eff_fdr_att=d_att,
        )

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
        out[h].setdefault(ev, []).append(view(h, a, True, ev, lh, la, f))
        out[a].setdefault(ev, []).append(view(a, h, False, ev, la, lh, f))
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
