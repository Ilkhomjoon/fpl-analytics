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

from . import priors
from .config import Config
from .ratings import FixtureView, TeamRating

GK, DEF, MID, FWD = 1, 2, 3, 4

# Darvozabon goli 2024/25 dan beri 6 emas, **10** ochko
GOAL_POINTS = {GK: 10, DEF: 6, MID: 5, FWD: 4}
CS_POINTS = {GK: 4, DEF: 4, MID: 1, FWD: 0}
DEFCON_THRESHOLD = {DEF: 10, MID: 12, FWD: 12}          # GK uchun DefCon yo'q
ASSIST_POINTS = 3
DEFCON_POINTS = 2
SAVES_PER_POINT = 3
# Qiyin uchrashuv himoya harakatlarini oshiradi, lekin to'liq emas —
# raqib kuchi 20% ortsa, CBIT ~12% ortadi
DC_FIXTURE_TILT = 0.6
# Bonus voqeaga bog'liq: gol/uzatma bergan o'yinchi BPS da yuqoriga chiqadi,
# toza darvoza esa himoyachiga +12 BPS beradi. Lift o'yinchining O'Z neytral
# uchrashuviga nisbatan olinadi (pastga qarang) — shunda uning umumiy bonus
# tezligi o'zgarmaydi, faqat uchrashuvga qarab qayta taqsimlanadi.
BONUS_RETURN_LIFT = 1.10
BONUS_CS_LIFT = 0.55

# FPL "uzatma"si xA dan kengroq: to'siqdan qaytgan to'p, ishlab berilgan
# penalti/shtrafnoy, raqibning o'z darvozasiga goli ham uzatma sanaladi.
# 2026/27 GW1-10: jami uzatma / jami xA = 1.37, hujumchilarda esa 2.8.
# Bitta formula uchala pozitsiyani tushuntiradi: uzatma/90 ≈ xA/90 + 0.22·xG/90
# (HIM 0.071 vs 0.067, YAR 0.159 vs 0.159, HUJ 0.156 vs 0.175).
ASSIST_FROM_XG = 0.22

# DefCon: BIR o'yinchining o'yindan o'yinga tarqoqligi (dispersiya/o'rtacha).
# O'lchangan: HIM 1.34, YAR 1.39, HUJ 1.16. Ilgari 1.8 edi — u o'yinchilar
# ORASIDAGI farqni ham o'z ichiga olgan, o'yinchining o'z tezligi esa
# allaqachon profilda bor.
DC_DISPERSION = 1.4
# O'yinchilar orasidagi tezlik farqi (standart chetlanish / o'rtacha ≈ 0.35:
# p10 4.3, mediana 7.3, p90 11.0) va uni aniqlash uchun kerak bo'ladigan dalil
DC_RATE_CV = 0.35
DC_RATE_K = 2.0

# Futbolda 0 gol Puasson kutganidan biroz ko'proq uchraydi (Dixon–Coles
# past hisob tuzatishi). GW2-10: haqiqiy 0.283, Puasson 0.273.
CS_LOW_SCORE_LIFT = 1.04

# --- daqiqalar ---
# Asosiy tarkibda boshlagan o'yinchining 60+ daqiqa o'ynash ehtimoli va
# o'rtacha daqiqasi (o'lchangan, GW1-10)
P60_GIVEN_START = {1: 0.99, 2: 0.94, 3: 0.91, 4: 0.93}
DEFAULT_START_MIN = {1: 90.0, 2: 85.0, 3: 79.0, 4: 79.0}
SHORT_MINUTES = 22.0         # 60 daqiqaga yetmagan chiqishning o'rtacha davomiyligi
# Boshlamagan o'yinchining zaxiradan chiqish ehtimoli: so'nggi o'yinlardagi
# ishtirok ulushiga chiziqli bog'liq (0 → 0.20, 1.0 → 0.55)
SUB_BASE, SUB_SLOPE = 0.20, 0.35

# --- rotatsiya (jadval zichligi) ---
ROTATION_NEUTRAL = 0.55      # "kim o'ynashi noma'lum" holatidagi ehtimol
ROTATION_PULL = 0.28         # eng zich haftada shu ulushda neytralga tortiladi
ROTATION_EARLY_SUB = 0.10    # zich haftada erta almashtirish ehtimoli
ROTATION_MINUTES = 0.08      # kutilayotgan daqiqalarning o'zgarishi

# Pozitsiya bo'yicha priorlar (90 daqiqaga) — kam o'ynagan o'yinchini shu tomon tortamiz
PRIOR_XG90 = {GK: 0.0, DEF: 0.06, MID: 0.16, FWD: 0.34}
PRIOR_XA90 = {GK: 0.01, DEF: 0.08, MID: 0.16, FWD: 0.14}
PRIOR_BONUS90 = {GK: 0.28, DEF: 0.26, MID: 0.28, FWD: 0.34}
PRIOR_DC90 = {GK: 0.0, DEF: 7.7, MID: 7.6, FWD: 4.6}
PRIOR_YELLOW90 = 0.13
# Pozitsiya bo'yicha (o'lchangan): darvozabon deyarli kartochka olmaydi
PRIOR_YELLOW90_POS = {GK: 0.035, DEF: 0.195, MID: 0.205, FWD: 0.175}
PRIOR_SAVES90 = 3.0
# Kam uchraydigan, lekin haqiqiy ochkolar
RED_POINTS = -3
OG_POINTS = -2
PEN_MISS_POINTS = -2
PEN_SAVE_POINTS = 5
PRIOR_RED90 = 0.012
PRIOR_OG90 = 0.008
PRIOR_PENMISS90 = 0.010
PRIOR_PENSAVE90 = 0.020

# Penalti va standart pozitsiyalar — **priorga** qo'shiladi, xom xG ustiga emas.
# Sabab: FPL ning `expected_goals` i penaltilarni ALLAQACHON o'z ichiga oladi
# (penalti xG ~0.79). Ustiga qo'shilsa ikki marta hisoblangan bo'lardi.
# Bo'shliq boshqa joyda: endigina penaltichi etib tayinlangan o'yinchi.
# Uning statistikasida penalti yo'q, model esa uni narx priori tomon tortadi
# va penalti huquqini umuman ko'rmaydi.
PEN_XG90 = 0.11          # jamoa ~6-7 o'yinda bitta penalti oladi × 0.79 xG
SETPIECE_XA90 = 0.05     # burchak/shtrafnilarni oladigan o'yinchi


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


def negbinom_tail(threshold: int, mean: float, dispersion: float = DC_DISPERSION) -> float:
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


def expected_floor(lam: float, per_point: int, cap: int = 20) -> float:
    """E[floor(N / per_point)], N ~ Puasson(lam).

    **E[N]/per_point EMAS.** Farqi katta: lam=3 va per_point=3 bo'lganda
    o'rtachani bo'lish 1.00 beradi, to'g'ri qiymat esa 0.665 — ya'ni 50%
    oshirib yuborilgan bo'lardi. Sabab: 2 ta to'xtatish ham, 0 ta ham
    bir xil — 0 ochko. Xuddi shu xato kiritilgan gol jarimasida ham
    bo'lishi mumkin edi, u yerda boshidan to'g'ri hisoblangan.
    """
    if lam <= 0 or per_point <= 0:
        return 0.0
    return sum(poisson_pmf(k, lam) * (k // per_point) for k in range(cap + 1))


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
    dc_hit_rate: float | None          # 60+ o'ynagan o'yinlarda chegaradan o'tish ulushi
    bonus90: float
    saves90: float
    yellow90: float
    is_pen_taker: bool
    is_set_piece: bool
    minutes: int
    nineties: float
    news: str = ""
    ownership: float = 0.0
    form: float = 0.0                 # FPL ning "form" maydoni (30 kunlik ochko)
    # Kam uchraydigan hodisalar (90 daqiqaga)
    red90: float = 0.0
    og90: float = 0.0
    penmiss90: float = 0.0
    pensave90: float = 0.0
    # Mavsumdagi sariq kartochkalar soni — 5 tasi diskvalifikatsiya
    yellow_total: int = 0
    # Asosiy tarkibda boshlagandagi o'rtacha daqiqa va DefCon namunasi hajmi
    start_mins: float = 82.0
    dc_hit_n: int = 0


def state_start_prob(recent_minutes: list[int], recent_starts: list[int]) -> float:
    """Keyingi o'yinda boshlash ehtimoli — so'nggi o'yin holati bo'yicha.

    Koeffitsiyentlar o'lchangan (2026/27 GW1-10, ~3000 o'yinchi-o'yin): har
    holat uchun haqiqiy boshlash ulushi, so'nggi 6 o'yindagi boshlash ulushi
    `r` ga qarab. Eski qoidalar ancha saxiy edi: "o'tgan turda o'ynamadi"
    holatiga 0.45 gacha ruxsat berilardi, haqiqatda esa 0.16 (doimiy asosiy
    o'yinchi bo'lsa 0.41, zaxira bo'lsa 0.09).
    """
    window_m, window_s = recent_minutes[-6:], recent_starts[-6:]
    r = sum(window_s) / len(window_s)
    streak = 0
    for m, s in zip(reversed(recent_minutes), reversed(recent_starts)):
        if s and m >= 60:
            streak += 1
        else:
            break
    last_m, last_s = recent_minutes[-1], bool(recent_starts[-1])
    if streak >= 3:
        return 0.60 + 0.33 * r
    if streak == 2:
        return 0.80 + 0.06 * r
    if streak == 1:
        return 0.66 + 0.10 * r
    if last_s and last_m >= 30:
        return 0.48                       # boshladi, lekin erta almashtirildi
    if last_m == 0:
        missed = 0
        for m in reversed(recent_minutes):
            if m == 0:
                missed += 1
            else:
                break
        return (0.05 + 0.42 * r) if missed == 1 else (0.03 + 0.28 * r)
    if last_m >= 25:
        return 0.36 + 0.40 * r            # zaxiradan uzoq chiqish
    return 0.11 + 0.22 * r                # zaxiradan qisqa chiqish


def _interp(points: tuple[tuple[float, float], ...], x: float) -> float:
    """Bo'lakli-chiziqli interpolyatsiya (nuqtalar x bo'yicha o'sish tartibida)."""
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0) if x1 > x0 else y1
    return points[-1][1]


# Batafsil tarixsiz (faqat bootstrap) boshlash ehtimoli: mavsumdagi boshlash
# ulushi `s` va **o'tgan turdagi ochko** bo'yicha. Ochko — so'nggi o'yin
# holatining bootstrapdagi yagona izi: 0 → o'ynamagan (91%), 1 → qisqa chiqish,
# 2+ → 60+ daqiqa (95%). O'lchangan ulushlar, GW3-10, ~3600 o'yinchi-tur.
# Usiz model o'rnini yo'qotgan o'yinchini mavsum o'rtachasi bilan baholardi.
_START_BY_LAST = {
    0: ((0.0, 0.07), (0.3, 0.095), (0.6, 0.25), (0.9, 0.66), (1.0, 0.75)),
    1: ((0.0, 0.15), (0.32, 0.36), (0.62, 0.52), (1.0, 0.75)),
    2: ((0.0, 0.30), (0.1, 0.38), (0.33, 0.73), (0.64, 0.81), (1.0, 0.92)),
}
_SUB_BY_LAST = {0: 0.23, 1: 0.60, 2: 0.50}


def _history_window(history: list[dict], n: int = 6) -> list[dict]:
    return [h for h in history if h.get("minutes") is not None][-n:]


def form_multiplier(form: float, baseline: float, weight: float) -> float:
    """Formaning hujum tezliklariga kichik ta'siri (1.0 = ta'sirsiz).

    **Nega kichik?** FPL "form" — so'nggi 30 kunda olingan **ochko**, ya'ni
    natija. Unda omad ham bor: xG dan ortiq urgan o'yinchi keyingi turda
    o'rtachaga qaytadi. Shuning uchun forma modelni **boshqarmaydi**, faqat
    biroz suradi — xG hali ko'rmagan o'zgarishni (yangi rol, penalti huquqi,
    standart pozitsiyalar) ushlab qolish uchun.

    Bazaviy qiymat o'zi hisoblanadi (o'ynayotgan o'yinchilarning medianasi),
    shuning uchun tur o'tishi bilan eskirmaydi.
    """
    if weight <= 0 or baseline <= 0:
        return 1.0
    ratio = max(0.4, min(2.0, form / baseline))
    return max(1.0 - weight, min(1.0 + weight, 1.0 + weight * (ratio - 1.0)))


def form_baseline(elements: list[dict], min_minutes: int = 180) -> float:
    """O'ynayotgan o'yinchilarning forma medianasi — taqqoslash uchun baza.

    Qattiq yozilgan son emas: mavsum davomida ham, turlar orasida ham
    o'zgaradi (masalan bo'sh turdan keyin hammaning formasi tushadi).
    """
    values = sorted(
        _f(e.get("form")) for e in elements or []
        if (e.get("minutes") or 0) >= min_minutes
    )
    if not values:
        return 0.0
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2.0


def build_profile(
    element: dict,
    summary: dict | None,
    cfg: Config,
    team_matches: int = 0,
    form_base: float = 0.0,
    last_event_played: bool | None = None,
) -> PlayerProfile:
    """team_matches — o'yinchi jamoasi mavsumda nechta o'yin o'ynagani (bootstrap teams.played).

    last_event_played — jamoa oxirgi turda o'ynab **bo'lganmi**. `True` bo'lsa
    `event_points` so'nggi o'yin holati sifatida ishlatiladi (batafsil tarix
    yo'q paytda). `None`/`False` — ishlatilmaydi: tur davom etayotgan yoki
    jamoa bo'sh turda bo'lsa, 0 ochko "o'ynamadi" degani emas.
    """
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

    # ---- Prior: joriy bozordan (egalik + narx), o'tgan mavsumsiz ----
    # Egalik ROL ni bashorat qiladi: 25% menejer olgan o'yinchi zaxirada
    # o'tirmaydi. Narx esa SIFAT ni. Ikkalasi ham joriy mavsum ma'lumoti.
    price = element["now_cost"] / 10.0
    ownership = _f(element.get("selected_by_percent"))
    prior_start_rate = priors.role_prior(ownership, price)
    prior_p60 = min(0.95, prior_start_rate * 0.94)

    if cfg.use_last_season and past:
        # Ixtiyoriy: o'tgan mavsum daqiqalar ulushi bilan to'ldirish
        last = past[-1]
        pm = last.get("minutes", 0) or 0
        if pm > 0:
            history_role = max(0.05, min(0.95, (pm / (38 * 90)) * 1.35))
            prior_start_rate = max(prior_start_rate, history_role)
            prior_p60 = min(0.95, prior_start_rate * 0.94)

    sub_min = 18.0
    default_start_min = DEFAULT_START_MIN[pos]
    appear_rate: float | None = None      # so'nggi o'yinlarda maydonga tushish ulushi
    if recent_minutes:
        # batafsil tarix bor — oxirgi o'yinlar bo'yicha
        n = len(recent_minutes)
        obs_start = sum(recent_starts) / n
        obs_p60 = sum(1 for m in recent_minutes if m >= 60) / n
        start_minutes = [m for m, s in zip(recent_minutes, recent_starts) if s]
        # Bir-ikki o'yindan olingan o'rtacha tasodifga boy — pozitsiya
        # o'rtachasi tomon tortiladi (2 o'yinga teng dalil)
        avg_start_min = ((sum(start_minutes) + default_start_min * 2)
                         / (len(start_minutes) + 2))
        last4 = recent_minutes[-4:]
        appear_rate = sum(1 for m in last4 if m > 0) / len(last4)
    elif team_matches > 0:
        # faqat mavsum yig'indisi bor (bootstrap) — starts/minutes dan chiqaramiz
        n = team_matches
        starts = element.get("starts", 0) or 0
        obs_start = min(1.0, starts / team_matches)
        raw_start_min = min(90.0, minutes / starts) if starts else default_start_min
        avg_start_min = ((raw_start_min * starts + default_start_min * 2)
                         / (starts + 2))
        obs_p60 = obs_start * P60_GIVEN_START[pos]
        # Zaxiradan chiqishlar soni: boshlanmagan o'yinlarga to'g'ri kelgan daqiqalar
        sub_apps = max(0.0, minutes - starts * default_start_min) / 20.0
        appear_rate = min(1.0, (starts + sub_apps) / team_matches)
    else:
        n = 0
        obs_start, obs_p60, avg_start_min = prior_start_rate, prior_p60, default_start_min

    state_based = len(recent_minutes) >= 3
    # Bootstrap rejimi: o'tgan turdagi ochko so'nggi o'yin holatini aytadi
    last_class: int | None = None
    if (not recent_minutes and last_event_played and team_matches >= 2
            and element.get("event_points") is not None):
        last_points = int(_f(element.get("event_points")))
        last_class = 0 if last_points == 0 else (1 if last_points == 1 else 2)

    if state_based:
        # Yetarli tarix bor: so'nggi o'yin holati + so'nggi 6 o'yindagi boshlash
        # ulushi. Bu — o'lchangan ulushlar (`state_start_prob` ga qarang).
        p_start = state_start_prob(recent_minutes, recent_starts)
        if pos == GK and recent_starts[-1] and recent_minutes[-1] >= 60:
            # Darvozabon almashmaydi: o'tgan turda o'ynagan bo'lsa, yana o'ynaydi
            p_start = max(p_start, 0.95 if p_start < 0.85 else 0.97)
        p60 = p_start * P60_GIVEN_START[pos]
    elif last_class is not None:
        p_start = _interp(_START_BY_LAST[last_class], obs_start)
        if pos == GK and last_class == 2 and obs_start >= 0.5:
            p_start = max(p_start, 0.95)
        p60 = p_start * P60_GIVEN_START[pos]
    elif n:
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

    # ---- Egalik daqiqalarni bosib o'tolmaydi ----
    # Ommaviy, lekin o'ynamayotgan o'yinchi (byudjet to'ldiruvchi) yuqori
    # baholanmasligi kerak: prior faqat dalil YO'Q joyni to'ldiradi.
    if team_matches > 0:
        minutes_share = min(1.0, minutes / (team_matches * 90))
        p_start = min(p_start, minutes_share * 1.25 + 0.30)
        p60 = min(p60, p_start)

    # ---- So'nggi o'yin: eng kuchli yagona dalil ----
    # Mavsum boshida statistika kam, lekin "o'tgan turda 90 daqiqa o'ynadi"
    # degan fakt o'tgan mavsumning butun o'rtachasidan ko'ra ko'proq narsani
    # aytadi. Shuning uchun so'nggi o'yin quyi/yuqori chegara qo'yadi.
    # Faqat 1-2 o'yinlik tarix bo'lganda (mavsumning ilk turlari): holat
    # modeliga dalil yetmaydi, shuning uchun prior + quyi/yuqori chegaralar.
    if recent_minutes and not state_based:
        last_minutes = recent_minutes[-1]
        last_started = bool(recent_starts[-1])

        # Ketma-ket asosiy tarkibda chiqishlar soni — o'rin qanchalik mustahkam
        streak = 0
        for m, s in zip(reversed(recent_minutes), reversed(recent_starts)):
            if s and m >= 60:
                streak += 1
            else:
                break

        if streak == 2:
            p_start, p60 = max(p_start, 0.82), max(p60, 0.78)
        elif streak == 1:
            p_start, p60 = max(p_start, 0.75), max(p60, 0.70)
        elif last_started and last_minutes >= 30:
            p_start = max(p_start, 0.50)
        elif last_minutes == 0:
            p_start = min(p_start, 0.30)          # o'ynamadi — ehtiyot bo'lamiz
        elif not last_started and last_minutes < 25:
            p_start = min(p_start, 0.30)          # zaxiradan qisqa chiqish

    p_start = max(0.0, min(1.0, p_start)) * availability
    p60 = max(0.0, min(p_start, p60 * availability))
    # Zaxiradan chiqish: doim ishtirok etayotgan o'yinchi boshlamasa ham
    # ko'pincha maydonga tushadi (0.55), umuman o'ynamayotgani esa kam (0.20)
    if pos == GK:
        p_sub = 0.02
    elif last_class is not None:
        p_sub = _SUB_BY_LAST[last_class]
    elif appear_rate is None:
        p_sub = 0.30
    else:
        p_sub = SUB_BASE + SUB_SLOPE * appear_rate
    p_appear = min(1.0, p_start + (1 - p_start) * p_sub * availability)
    xmins = p_start * avg_start_min + (p_appear - p_start) * sub_min

    # ---------- 3. hujum tezliklari ----------
    xg = _f(element.get("expected_goals"))
    xa = _f(element.get("expected_assists"))
    # Prior narxdan: bozor o'yinchini qanchalik qimmat baholasa, shuncha
    # ko'p hujum chiqimi kutiladi. Egalik bu yerda ISHLATILMAYDI — aks holda
    # model shablonni takrorlab qolardi.
    prior_xg = priors.xg90_prior(price, pos)
    prior_xa = priors.xa90_prior(price, pos)
    # Penaltichi va standart pozitsiya egasi — priorni ko'taradi (yuqoridagi
    # izohga qarang: xom xG ga qo'shish ikki marta hisoblash bo'lardi)
    if element.get("penalties_order") == 1 and pos != GK:
        prior_xg += PEN_XG90
    if (element.get("corners_and_indirect_freekicks_order") == 1
            or element.get("direct_freekicks_order") == 1):
        prior_xa += SETPIECE_XA90
    if cfg.use_last_season and past:
        last = past[-1]
        past_90s = (last.get("minutes", 0) or 0) / 90.0
        if past_90s >= 5:
            prior_xg = shrink(_f(last.get("expected_goals")), past_90s, prior_xg, 8.0)
            prior_xa = shrink(_f(last.get("expected_assists")), past_90s, prior_xa, 8.0)
    xg90 = shrink(xg, nineties, prior_xg, cfg.shrink_attack_90s)
    xa90 = shrink(xa, nineties, prior_xa, cfg.shrink_attack_90s)
    # Forma — kichik tuzatish. Faqat hujum tezliklariga: toza darvoza
    # uchrashuvga bog'liq, daqiqalarning esa o'z modeli bor.
    fm = form_multiplier(_f(element.get("form")), form_base,
                         float(getattr(cfg, "form_weight", 0.0) or 0.0))
    xg90 *= fm
    xa90 *= fm

    # ---------- 4. DefCon ----------
    cbit = _f(element.get("clearances_blocks_interceptions")) + _f(element.get("tackles"))
    actions = cbit + (_f(element.get("recoveries")) if pos in (MID, FWD) else 0.0)
    prior_dc = priors.dc90_prior(price, pos)
    dc90 = shrink(actions, nineties, prior_dc, cfg.shrink_defcon_90s)

    # empirik: nechta o'yinda chegaradan o'tgan
    dc_hit_rate = None
    starts_played = [h for h in history if (h.get("minutes") or 0) >= 60]
    dc_hit_n = len(starts_played) if pos != GK else 0
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
    bonus90 = shrink(_f(element.get("bonus")), nineties,
                     priors.bonus90_prior(price, pos), cfg.shrink_bonus_90s) * fm
    saves90 = shrink(_f(element.get("saves")), nineties, PRIOR_SAVES90, 4.0) if pos == GK else 0.0
    yellow90 = shrink(_f(element.get("yellow_cards")), nineties,
                      PRIOR_YELLOW90_POS.get(pos, PRIOR_YELLOW90), 6.0)
    # Kam uchraydigan hodisalar: kuchli siqiladi (k=10), aks holda bitta
    # qizil kartochka butun mavsumga tarqalib ketardi
    red90 = shrink(_f(element.get("red_cards")), nineties, PRIOR_RED90, 10.0)
    og90 = shrink(_f(element.get("own_goals")), nineties, PRIOR_OG90, 10.0)
    penmiss90 = (shrink(_f(element.get("penalties_missed")), nineties,
                        PRIOR_PENMISS90, 10.0)
                 if element.get("penalties_order") == 1 else 0.0)
    pensave90 = (shrink(_f(element.get("penalties_saved")), nineties,
                        PRIOR_PENSAVE90, 10.0) if pos == GK else 0.0)
    # Sariq kartochkalar yig'indisi: 5 tasi — bir o'yinlik diskvalifikatsiya.
    # Bu KEYINGI o'yinlarga tegishli, shuning uchun EV ga qo'shilmaydi —
    # ogohlantirish sifatida ko'rsatiladi.
    yellow_total = int(_f(element.get("yellow_cards")))

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
        form=_f(element.get("form")),
        red90=red90,
        og90=og90,
        penmiss90=penmiss90,
        pensave90=pensave90,
        yellow_total=yellow_total,
        start_mins=avg_start_min,
        dc_hit_n=dc_hit_n,
    )


# ------------------------------------------------------------------ EV hisobi
@dataclass
class FixtureInputs:
    """Ochko taqsimotini qurish uchun kerakli xom ehtimolliklar."""
    xg: float = 0.0
    xa: float = 0.0
    p_cs: float = 0.0
    p_dc: float = 0.0
    p_appear: float = 0.0
    p60: float = 0.0
    bonus_mean: float = 0.0
    lam_conceded: float = 0.0
    saves_mean: float = 0.0
    position: int = MID


@dataclass
class FixtureEV:
    event: int
    opponent: str
    is_home: bool
    ev: float
    parts: dict[str, float] = field(default_factory=dict)
    p_haul: float = 0.0        # 10+ ochko ehtimoli
    p_return: float = 0.0      # gol yoki uzatma ehtimoli
    inputs: FixtureInputs = field(default_factory=FixtureInputs)
    fdr: int = 3               # FPL ning rasmiy qiyinligi
    eff_fdr: float = 3.0       # model bahosi (jadval bilan tuzatilgan)
    opp_position: int = 0      # raqibning jadvaldagi o'rni (0 = noma'lum)


def _rotation_adjust(profile: PlayerProfile, rotation: float):
    """Rotatsiya xavfini hisobga olib (p_start, p60, daqiqa ulushi) qaytaradi.

    Zichlik tarkibni **noaniqroq** qiladi: ehtimollar neytral qiymat tomon
    tortiladi. Bundan tashqari, zich haftada boshlagan o'yinchi ham erta
    almashtiriladi — shuning uchun 60 daqiqa o'ynash ehtimoli alohida
    pasayadi (u ishtirok ochkosini, toza darvozani va DefCon ni ushlab
    turadi, ya'ni eng qimmat qismi aynan shu).
    """
    if rotation <= 0:
        return profile.p_start, profile.p60, profile.xmins / 90.0
    pull = ROTATION_PULL * rotation
    p_start = profile.p_start + pull * (ROTATION_NEUTRAL - profile.p_start)
    p_start = max(0.0, min(1.0, p_start))
    # Erta almashtirish: boshlaganda ham 60 daqiqagacha yetib bormasligi mumkin
    ratio = (p_start / profile.p_start) if profile.p_start > 0 else 1.0
    p60 = min(p_start, profile.p60 * ratio * (1.0 - ROTATION_EARLY_SUB * rotation))
    share = (profile.xmins / 90.0) * (1.0 - ROTATION_MINUTES * rotation * (
        1.0 if profile.p_start >= ROTATION_NEUTRAL else -1.0))
    return p_start, max(0.0, p60), max(0.0, share)


def fixture_ev(
    profile: PlayerProfile,
    fx: FixtureView,
    ratings: dict[int, TeamRating],
    team_neutral_lam_for: float,
    team_neutral_lam_against: float,
) -> FixtureEV:
    pos = profile.position
    # Jadval zichligi: rotatsiya ehtimolini oshiradi. Bu **jazo emas**,
    # noaniqlikka tortish — zich haftada mumkin bo'lgan tarkiblar soni ortadi,
    # ya'ni mustahkam o'yinchi biroz yo'qotadi, chetdagi biroz yutadi.
    rotation = max(0.0, min(1.0, getattr(fx, "rotation", 0.0) or 0.0))
    p_start, p60, share = _rotation_adjust(profile, rotation)

    # uchrashuv koeffitsiyentlari: neytral holatga nisbatan
    att_mult = fx.lam_for / team_neutral_lam_for if team_neutral_lam_for else 1.0
    def_mult = fx.lam_against / team_neutral_lam_against if team_neutral_lam_against else 1.0

    # Ishtirok: zaxiradan chiqish ehtimoli rotatsiya bilan birga siljiydi
    p_appear = min(1.0, max(p_start, profile.p_appear
                            - (profile.p_start - p_start) * 0.4))
    # Chegarali (pog'onali) ochkolar — o'tkazilgan gol, to'xtatish, DefCon —
    # "kutilayotgan daqiqa ulushi" bilan EMAS, **o'ynagan holat** bo'yicha
    # hisoblanadi: 60+ o'ynasa uzoq (`long`), aks holda qisqa (`short`) chiqish.
    # Sabab — 5-xatodagi bilan bir xil (E[⌊N/3⌋] ≠ E[N]/3): tezlikni 0.85 ga
    # ko'paytirib chegaradan o'tish ehtimolini hisoblash natijani keskin
    # pasaytiradi. Backtestda aynan shu uchun DefCon ~3 barobar, o'tkazilgan
    # gol jarimasi ~2 barobar kam chiqqan edi.
    long = max(60.0, min(90.0, profile.start_mins)) / 90.0
    short = SHORT_MINUTES / 90.0
    p_short = max(0.0, p_appear - p60)

    xg = profile.xg90 * share * att_mult
    # FPL uzatmasi xA dan kengroq (qaytgan to'p, ishlab berilgan penalti…)
    xa = (profile.xa90 + ASSIST_FROM_XG * profile.xg90) * share * att_mult

    pts_goals = xg * GOAL_POINTS[pos]
    pts_assists = xa * ASSIST_POINTS

    # Toza darvoza — 60+ daqiqa talab qilinadi. O'yinchining toza darvozasi
    # jamoanikidan TEZ-TEZ uchraydi: 70-daqiqada almashtirilgan himoyachi
    # jamoa 85-daqiqada gol o'tkazsa ham ochkosini saqlab qoladi. Shuning
    # uchun gol kutilmasi o'yinchi maydonda bo'lgan vaqtga ko'paytiriladi.
    # (O'lchangan: jamoa 0.283, 60+ o'ynagan DRV/HIM 0.308.)
    p_cs = min(1.0, math.exp(-fx.lam_against * long) * CS_LOW_SCORE_LIFT)
    pts_cs = p_cs * CS_POINTS[pos] * p60

    # kiritilgan gollar (faqat GK/DEF) — maydonda bo'lgan vaqtdagi gollar
    pts_conceded = 0.0
    if pos in (GK, DEF):
        pts_conceded = -(
            p60 * expected_conceded_penalty(fx.lam_against * long)
            + p_short * expected_conceded_penalty(fx.lam_against * short))

    # darvozabon to'xtatishlari (har 3 tasi = 1 ochko) va penalti to'xtatish
    pts_saves = 0.0
    lam_saves = 0.0
    if pos == GK:
        lam_saves = profile.saves90 * long * def_mult
        pts_saves = p60 * expected_floor(lam_saves, SAVES_PER_POINT)
        pts_saves += profile.pensave90 * share * def_mult * PEN_SAVE_POINTS

    # DefCon. Uchrashuv qiyinligi bu yerda **teskari** ishlaydi: kuchli
    # raqibga qarshi toza darvoza ehtimoli tushadi, lekin himoya harakatlari
    # (CBIT/CBIRT) ortadi — to'p ko'proq o'z yarim maydonimizda bo'ladi.
    # Bitta "qiyinlik koeffitsiyenti" ni butun o'yinchiga qo'llash shu yerda
    # xato bo'lardi.
    pts_dc = 0.0
    p_dc = 0.0
    if pos in DEFCON_THRESHOLD:
        thr = DEFCON_THRESHOLD[pos]
        lam_actions = profile.dc90 * long * (1.0 + DC_FIXTURE_TILT * (def_mult - 1.0))
        # Tezlikning o'zi ham noaniq: 2 o'yin o'ynagan o'yinchining haqiqiy
        # tezligi priordan ancha farq qilishi mumkin. Chegaradan o'tish
        # ehtimoli qavariq bo'lgani uchun bu noaniqlik ehtimolni OSHIRADI —
        # shuning uchun u dispersiyaga qo'shiladi va dalil ko'paygan sari so'nadi.
        rate_var = (DC_RATE_CV * profile.dc90) ** 2 * DC_RATE_K / (profile.nineties + DC_RATE_K)
        dispersion = DC_DISPERSION + (rate_var / profile.dc90 if profile.dc90 > 0 else 0.0)
        p_given = negbinom_tail(thr, lam_actions, dispersion)   # 60+ o'ynagan holatda
        if profile.dc_hit_rate is not None:
            # O'yinchining haqiqiy ulushi — namuna qancha katta bo'lsa, vazni
            # shuncha ortadi (4 o'yin → 0.33, 8 → 0.50), yarmidan oshmaydi
            n_hit = max(4, profile.dc_hit_n)
            w_hit = min(0.5, n_hit / (n_hit + 8.0))
            p_given = (1 - w_hit) * p_given + w_hit * profile.dc_hit_rate
        # Qisqa chiqishda chegaraga yetish deyarli mumkin emas
        p_dc = p60 * p_given
        pts_dc = p_dc * DEFCON_POINTS

    # Bonus. Avval bu shunchaki 90 daqiqalik o'rtacha edi — ya'ni bonus
    # o'yinda nima bo'lishidan qat'i nazar bir xil chiqardi. Aslida bonus
    # **voqeaga bog'liq**: gol yoki uzatma bergan o'yinchi BPS reytingida
    # deyarli har doim yuqoriga chiqadi, toza darvoza esa himoyachiga +12 BPS
    # beradi. Shuning uchun o'rtacha tezlik shartli holatlarga taqsimlanadi.
    #
    # Lift o'yinchining **o'z neytral uchrashuviga** nisbatan olinadi. Ilgari
    # u "o'rtacha o'yinchi" ga nisbatan edi (doimiy 1.30 ga bo'linardi) va
    # ko'p gol uradigan o'yinchi ikki marta mukofotlanardi: uning yuqori
    # bonus tezligi allaqachon `bonus90` da bor. Backtestda EV ≥ 5 bo'lgan
    # o'yinchilarda bonus 0.87 bashorat qilingan, haqiqatda 0.38 chiqqan.
    def lift(p_return: float, p_clean: float) -> float:
        return 1.0 + BONUS_RETURN_LIFT * p_return + BONUS_CS_LIFT * p_clean

    p_ret = 1 - math.exp(-(xg + xa))
    p_cs_eff = p_cs * p60 if pos in (GK, DEF) else 0.0
    neutral_att = (xg + xa) / att_mult if att_mult > 0 else (xg + xa)
    p_ret_neutral = 1 - math.exp(-neutral_att)
    p_cs_neutral = (math.exp(-team_neutral_lam_against) * p60
                    if pos in (GK, DEF) else 0.0)
    event_lift = lift(p_ret, p_cs_eff) / lift(p_ret_neutral, p_cs_neutral)
    pts_bonus = profile.bonus90 * share * event_lift
    # Kartochkalar: sariq −1, qizil −3. Qizil kam uchraydi, lekin bor.
    pts_cards = -(profile.yellow90 * share) + profile.red90 * share * RED_POINTS
    # O'z darvozasiga gol va o'tkazib yuborilgan penalti
    pts_misc = (profile.og90 * share * OG_POINTS
                + profile.penmiss90 * share * PEN_MISS_POINTS)
    pts_appearance = p_appear * 1.0 + p60 * 1.0

    total = (
        pts_appearance + pts_goals + pts_assists + pts_cs
        + pts_conceded + pts_saves + pts_dc + pts_bonus + pts_cards + pts_misc
    )

    p_goal = 1 - math.exp(-xg)
    p_assist = 1 - math.exp(-xa)
    p_return = 1 - (1 - p_goal) * (1 - p_assist)

    # Taqsimot `p_appear` ga shartli quriladi, shuning uchun DefCon va
    # o'tkazilgan gollar ham "maydonga tushgan" holat uchun beriladi.
    played = (p60 * long + p_short * short) / p_appear if p_appear > 0 else 0.0
    inputs = FixtureInputs(
        xg=xg, xa=xa, p_cs=p_cs,
        p_dc=(p_dc / p_appear) if p_appear > 0 else 0.0,
        p_appear=p_appear, p60=p60,
        bonus_mean=pts_bonus, lam_conceded=fx.lam_against * played,
        saves_mean=lam_saves if pos == GK else 0.0,
        position=pos,
    )
    # Arzon taxmin — har o'yinchi uchun hisoblanadi. Aniq taqsimot kerak bo'lganda
    # (kapitan tanlash) points_distribution() alohida chaqiriladi.
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
            "boshqa": round(pts_misc, 2),
        },
        p_haul=round(p_haul, 3),
        p_return=round(p_return, 3),
        inputs=inputs,
        fdr=getattr(fx, "fdr", 3),
        eff_fdr=getattr(fx, "eff_fdr", 3.0),
        opp_position=getattr(fx, "opp_position", 0),
    )


# ------------------------------------------------- ochkoning to'liq taqsimoti
# Bonus qaytim bilan kuchli bog'langan: gol/uzatma bergan o'yinchi bonus olishi
# ehtimoli ancha yuqori. Shuning uchun ikki xil shartli taqsimot ishlatiladi.
BONUS_PMF_RETURN = (0.30, 0.20, 0.20, 0.30)      # 0, 1, 2, 3 bonus
BONUS_PMF_BLANK = (0.88, 0.07, 0.03, 0.02)
AVG_BONUS_PER_START = 0.45


def _bonus_pmf(returned: bool, quality: float) -> tuple[float, ...]:
    """Bonus taqsimoti; `quality` o'yinchining bonus yig'ish moyilligi (1.0 = o'rtacha)."""
    base = BONUS_PMF_RETURN if returned else BONUS_PMF_BLANK
    scaled = [base[0]] + [p * quality for p in base[1:]]
    total = sum(scaled)
    if total <= 0:
        return (1.0, 0.0, 0.0, 0.0)
    return tuple(p / total for p in scaled)


class PointsDistribution:
    """Bitta uchrashuvda o'yinchi oladigan ochkolarning to'liq taqsimoti."""

    def __init__(self, pmf: dict[int, float]) -> None:
        self.pmf = pmf

    def mean(self) -> float:
        return sum(k * p for k, p in self.pmf.items())

    def tail(self, threshold: int) -> float:
        """P(ochko >= threshold)."""
        return sum(p for k, p in self.pmf.items() if k >= threshold)

    def percentile(self, q: float) -> int:
        acc = 0.0
        for k in sorted(self.pmf):
            acc += self.pmf[k]
            if acc >= q:
                return k
        return max(self.pmf) if self.pmf else 0


def points_distribution(inp: FixtureInputs) -> PointsDistribution:
    """Ochko taqsimotini sanab chiqadi (gol, uzatma, toza darvoza, DefCon, bonus).

    Kartochka hisobga olinmaydi — u o'rtachani biroz pasaytiradi, taqsimot
    shaklini esa deyarli o'zgartirmaydi.

    Toza darvoza va kiritilgan gol jarimasi **bitta** tasodifiy miqdordan
    chiqariladi (kiritilgan gollar soni), shuning uchun ular o'zaro zid bo'lmaydi.
    """
    pos = inp.position
    pmf: dict[int, float] = {}

    def add(points: int, prob: float) -> None:
        if prob > 1e-12:
            pmf[points] = pmf.get(points, 0.0) + prob

    p_appear = max(0.0, min(1.0, inp.p_appear))
    add(0, 1.0 - p_appear)
    if p_appear <= 0:
        return PointsDistribution(pmf)

    p60_given = max(0.0, min(1.0, inp.p60 / p_appear)) if p_appear else 0.0
    quality = max(0.3, min(2.2, inp.bonus_mean / AVG_BONUS_PER_START))

    goal_pts = GOAL_POINTS[pos]
    cs_pts = CS_POINTS[pos]

    goals = [(g, poisson_pmf(g, inp.xg)) for g in range(0, 6)]
    assists = [(a, poisson_pmf(a, inp.xa)) for a in range(0, 5)]
    conceded = [(c, poisson_pmf(c, inp.lam_conceded)) for c in range(0, 7)]
    saves = (
        [(s, poisson_pmf(s, inp.saves_mean)) for s in range(0, 10)]
        if pos == GK else [(0, 1.0)]
    )
    dc_options = [(True, inp.p_dc), (False, 1 - inp.p_dc)] if pos in DEFCON_THRESHOLD \
        else [(False, 1.0)]

    for played_60, p_min in ((True, p60_given), (False, 1 - p60_given)):
        if p_min <= 1e-9:
            continue
        appearance = 2 if played_60 else 1
        for g, pg in goals:
            for a, pa in assists:
                returned = (g + a) > 0
                bonus_pmf = _bonus_pmf(returned, quality)
                attack_pts = g * goal_pts + a * ASSIST_POINTS
                for c, pc in conceded:
                    defence_pts = 0
                    if pos in (GK, DEF):
                        defence_pts -= c // 2
                    if c == 0 and played_60:
                        defence_pts += cs_pts
                    for s, ps in saves:
                        save_pts = (s // 3) if pos == GK else 0
                        for got_dc, pdc in dc_options:
                            dc_pts = DEFCON_POINTS if got_dc else 0
                            base = appearance + attack_pts + defence_pts + save_pts + dc_pts
                            weight = p_appear * p_min * pg * pa * pc * ps * pdc
                            if weight <= 1e-12:
                                continue
                            for b, pb in enumerate(bonus_pmf):
                                add(base + b, weight * pb)

    # Poisson quyruqlari chekli oraliqda kesilgani uchun yig'indi 1 dan biroz
    # kam chiqadi — normallashtiramiz, aks holda tail() ehtimolliklari pasayadi.
    total = sum(pmf.values())
    if total > 0:
        pmf = {k: v / total for k, v in pmf.items()}
    return PointsDistribution(pmf)


def combine_distributions(dists: list[PointsDistribution]) -> PointsDistribution:
    """Bir necha uchrashuv (DGW) ochkolarini birlashtiradi."""
    if not dists:
        return PointsDistribution({0: 1.0})
    result = dists[0].pmf
    for d in dists[1:]:
        merged: dict[int, float] = {}
        for k1, p1 in result.items():
            for k2, p2 in d.pmf.items():
                merged[k1 + k2] = merged.get(k1 + k2, 0.0) + p1 * p2
        result = merged
    return PointsDistribution(result)


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
