"""O'yinchi reytingi — joriy mavsumning barcha signallarini bitta baholashda.

Signallar (hammasi joriy mavsum):
  • egalik %          — bozorning roli haqidagi bahosi
  • narx              — bozorning sifat haqidagi bahosi
  • asosiy tarkib     — nechta o'yinda boshlagani
  • daqiqalar         — haqiqatda maydonda bo'lgan vaqti
  • gol + uzatma      — haqiqiy natija
  • xG / xA           — natija ortidagi asos (kelajakni yaxshiroq bashorat qiladi)
  • transfer oqimi    — shu tur oldidan kim olyapti, kim sotyapti

ENABLER MUAMMOSI. Menejerlar byudjetni to'ldirish uchun eng arzon o'yinchilarni
oladi — ular hech qachon o'ynamaydi. 4.0m lik himoyachi 40% egalikda bo'lishi
mumkin, lekin bu uning yaxshiligini bildirmaydi. Shuning uchun:

  1. Egalikning rol signali sifatidagi kuchi NARXGA qarab chegiriladi:
     arzon o'yinchida egalik rolni deyarli bashorat qilmaydi.
  2. Egalik DAQIQALAR bilan cheklanadi: o'ynamayotgan o'yinchini hech qanday
     egalik foizi "asosiy" qilib ko'rsata olmaydi.
"""

from __future__ import annotations

from dataclasses import dataclass

GK, DEF, MID, FWD = 1, 2, 3, 4
GOAL_POINTS = {GK: 6, DEF: 6, MID: 5, FWD: 4}
ASSIST_POINTS = 3

# Enabler chegaralari: shu narxdan arzon o'yinchilar byudjet to'ldirish uchun olinadi
ENABLER_PRICE = 4.6
ENABLER_MINUTES_SHARE = 0.35


def enabler_discount(price: float) -> float:
    """Egalikning rol signali sifatidagi ishonchliligi (0.25–1.0).

    4.0m → 0.25: bu narxda egalik "zaxira o'rindiq to'ldiruvchi" degani.
    5.5m dan yuqorida → 1.0: bunday o'yinchini hech kim shunchaki olmaydi.
    """
    if price <= 4.0:
        return 0.25
    if price >= 5.5:
        return 1.0
    return 0.25 + (price - 4.0) / 1.5 * 0.75


@dataclass
class PlayerRating:
    element: int
    name: str
    team: str
    position: int
    price: float

    # xom ko'rsatkichlar
    ownership: float
    starts: int
    minutes: int
    minutes_share: float          # jamoa o'ynagan daqiqalarning ulushi
    goals: int
    assists: int
    xg: float
    xa: float
    net_transfers: int

    # hisoblangan ko'rsatkichlar
    role: float                   # 0–1, qanchalik mustahkam asosiy tarkibda
    returns90: float              # haqiqiy gol+uzatma ochkosi / 90
    underlying90: float           # xG+xA asosidagi ochko / 90
    output90: float               # ikkalasining aralashmasi
    momentum: float               # egalarning necha % i shu tur harakat qildi
    value: float                  # 1m ga to'g'ri keladigan chiqim
    score: float                  # umumiy reyting (0–100)
    is_enabler: bool
    note: str = ""

    @property
    def overperforming(self) -> float:
        """Haqiqiy natija asosdan qancha yuqori (musbat = omadli davr)."""
        return round(self.returns90 - self.underlying90, 2)


def _f(value, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def rate_player(
    element: dict,
    team_matches: int,
    team_short: str = "",
    total_players: int = 0,
) -> PlayerRating:
    pos = element["element_type"]
    price = element["now_cost"] / 10.0
    minutes = element.get("minutes", 0) or 0
    starts = element.get("starts", 0) or 0
    nineties = minutes / 90.0
    ownership = _f(element.get("selected_by_percent"))

    available_minutes = max(1, team_matches) * 90
    minutes_share = min(1.0, minutes / available_minutes) if available_minutes else 0.0
    starts_share = min(1.0, starts / max(1, team_matches))

    # ---------------------------------------------------------------- rol
    # Egalik signali narxga qarab chegiriladi (enabler muammosi)
    own_signal = (ownership / (ownership + 6.0)) * enabler_discount(price)
    # Daqiqalar va asosiy tarkib — bevosita dalil
    played_signal = 0.6 * minutes_share + 0.4 * starts_share

    if team_matches <= 0:
        role = own_signal
    else:
        # Dalil to'planishi bilan egalikning vazni pasayadi
        w_market = 1.5 / (1.5 + team_matches)
        role = (1 - w_market) * played_signal + w_market * own_signal
        # Egalik hech qachon daqiqalarni "bosib o'tolmaydi": o'ynamagan
        # o'yinchi ommaviy bo'lsa ham asosiy tarkib deb baholanmaydi
        ceiling = min(1.0, minutes_share * 1.25 + 0.30)
        role = min(role, ceiling)
    role = max(0.0, min(1.0, role))

    is_enabler = (
        price <= ENABLER_PRICE
        and ownership >= 8.0
        and minutes_share < ENABLER_MINUTES_SHARE
    )

    # ------------------------------------------------------------- chiqim
    goals = element.get("goals_scored", 0) or 0
    assists = element.get("assists", 0) or 0
    xg, xa = _f(element.get("expected_goals")), _f(element.get("expected_assists"))

    goal_pts = GOAL_POINTS[pos]
    if nineties > 0:
        returns90 = (goals * goal_pts + assists * ASSIST_POINTS) / nineties
        underlying90 = (xg * goal_pts + xa * ASSIST_POINTS) / nineties
    else:
        returns90 = underlying90 = 0.0

    # xG/xA kichik namunada haqiqiy natijadan ko'ra barqarorroq bashorat beradi,
    # shuning uchun unga ko'proq vazn. Namuna o'sgani sari farq kamayadi.
    w_underlying = 0.75 if nineties < 8 else 0.6
    output90 = w_underlying * underlying90 + (1 - w_underlying) * returns90

    # ----------------------------------------------------------- momentum
    tin = element.get("transfers_in_event", 0) or 0
    tout = element.get("transfers_out_event", 0) or 0
    owners = ownership / 100.0 * total_players if total_players else 0
    momentum = ((tin - tout) / owners * 100) if owners > 500 else 0.0

    # -------------------------------------------------------------- reyting
    # Kutilayotgan haftalik chiqim = rol x 90 daqiqalik chiqim
    expected_weekly = role * output90
    value = expected_weekly / price if price else 0.0

    # 0–100 shkala: 6.0 ochko/tur — juda kuchli o'yinchi darajasi
    score = max(0.0, min(100.0, expected_weekly / 6.0 * 100))

    notes = []
    if is_enabler:
        notes.append("byudjet to'ldiruvchi — ommaviy, lekin o'ynamaydi")
    elif role < 0.45 and ownership > 12:
        notes.append("ommaviy, lekin o'yin vaqti kam")
    if nineties >= 2 and returns90 - underlying90 > 1.5:
        notes.append("natijasi asosdan yuqori — davom etmasligi mumkin")
    elif nineties >= 2 and underlying90 - returns90 > 1.5:
        notes.append("asosi natijadan yuqori — portlashi mumkin")
    if momentum >= 8:
        notes.append(f"bozor olyapti (+{momentum:.0f}%)")
    elif momentum <= -8:
        notes.append(f"bozor sotyapti ({momentum:.0f}%)")

    return PlayerRating(
        element=element["id"], name=element.get("web_name", "?"),
        team=team_short, position=pos, price=price,
        ownership=round(ownership, 1), starts=starts, minutes=minutes,
        minutes_share=round(minutes_share, 3),
        goals=goals, assists=assists, xg=round(xg, 2), xa=round(xa, 2),
        net_transfers=tin - tout,
        role=round(role, 3), returns90=round(returns90, 2),
        underlying90=round(underlying90, 2), output90=round(output90, 2),
        momentum=round(momentum, 1), value=round(value, 3),
        score=round(score, 1), is_enabler=is_enabler,
        note="; ".join(notes),
    )


def rate_all(
    elements: list[dict], played: dict[int, int], team_short: dict[int, str],
    total_players: int = 0,
) -> dict[int, PlayerRating]:
    out = {}
    for e in elements:
        if e.get("status") == "u":
            continue
        out[e["id"]] = rate_player(
            e, played.get(e["team"], 0), team_short.get(e["team"], "?"), total_players
        )
    return out


def best_by_position(
    ratings: dict[int, PlayerRating], position: int, top: int = 5,
    max_price: float | None = None, exclude_enablers: bool = True,
) -> list[PlayerRating]:
    rows = [
        r for r in ratings.values()
        if r.position == position
        and (max_price is None or r.price <= max_price)
        and not (exclude_enablers and r.is_enabler)
    ]
    rows.sort(key=lambda r: -r.score)
    return rows[:top]


def best_value(
    ratings: dict[int, PlayerRating], top: int = 8, min_role: float = 0.55,
) -> list[PlayerRating]:
    """Narxiga nisbatan eng samarali o'yinchilar (enablerlarsiz)."""
    rows = [
        r for r in ratings.values()
        if r.role >= min_role and not r.is_enabler and r.score > 0
    ]
    rows.sort(key=lambda r: -r.value)
    return rows[:top]


def market_movers(
    ratings: dict[int, PlayerRating], top: int = 5, min_ownership: float = 1.0,
) -> tuple[list[PlayerRating], list[PlayerRating]]:
    """Shu tur oldidan bozor eng ko'p olayotgan va sotayotgan o'yinchilar."""
    rows = [r for r in ratings.values() if r.ownership >= min_ownership]
    buying = sorted(rows, key=lambda r: -r.net_transfers)[:top]
    selling = sorted(rows, key=lambda r: r.net_transfers)[:top]
    return buying, selling
