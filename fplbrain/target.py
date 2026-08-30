"""Mavsum maqsadi — sur'at hisobi.

Savol oddiy: chempion bo'lish uchun har turda necha ochko kerak, men qanday
sur'atda ketyapman va yetakchidan qancha orqadaman.

O'tgan mavsum g'olibi 2506 ochko to'plagan, ya'ni turiga o'rtacha 66 ochko.
Bu — mo'ljal. Model shu mo'ljalga nisbatan holatni va **qolgan turlarda
qancha kerakligini** hisoblaydi.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TOTAL_GAMEWEEKS = 38
DEFAULT_TARGET = 2508          # 38 x 66 — o'tgan mavsum g'olibi darajasi


@dataclass
class GameweekRow:
    event: int
    points: int
    average: int               # FPL o'rtachasi
    rank: int | None
    leader_points: int | None = None


@dataclass
class SeasonPace:
    """Mavsum sur'ati — meniki, yetakchiniki va maqsad."""
    played: int
    remaining: int
    target: int

    my_total: int
    my_average: float
    my_best: int
    my_worst: int

    leader_total: int | None
    leader_average: float | None

    fpl_average_total: int          # o'rtacha menejer
    rows: list[GameweekRow] = field(default_factory=list)
    # Hali tugamagan tur — hisobga OLINMAYDI, faqat xabar berish uchun
    partial_event: int | None = None
    partial_points: int | None = None

    # ---------------------------------------------------------- hisoblar
    @property
    def required_average(self) -> float:
        """Maqsadga yetish uchun qolgan turlarda kerakli o'rtacha."""
        if self.remaining <= 0:
            return 0.0
        return (self.target - self.my_total) / self.remaining

    @property
    def projected_total(self) -> float:
        """Hozirgi sur'at saqlansa, mavsum oxirida qancha bo'ladi."""
        return self.my_total + self.my_average * self.remaining

    @property
    def shortfall(self) -> float:
        """Maqsaddan qancha kam (musbat = yetmaydi)."""
        return self.target - self.projected_total

    @property
    def live_total(self) -> int:
        """Jonli ochko — tugamagan turning oraliq natijasi ham qo'shilgan.

        Umumiy jadvaldagi yetakchining ochkosi ham jonli, shuning uchun
        farqni faqat shu ko'rsatkich bilan solishtirish to'g'ri bo'ladi.
        """
        return self.my_total + (self.partial_points or 0)

    @property
    def leader_gap(self) -> int | None:
        if self.leader_total is None:
            return None
        return self.leader_total - self.live_total

    @property
    def catch_leader_average(self) -> float | None:
        """Yetakchi shu sur'atda ketsa, uni quvib yetish uchun kerakli o'rtacha."""
        if self.leader_average is None or self.remaining <= 0:
            return None
        leader_projected = self.leader_total + self.leader_average * self.remaining
        return (leader_projected - self.my_total) / self.remaining

    @property
    def verdict(self) -> str:
        need = self.required_average
        if need <= self.my_average:
            return "sur'atingiz maqsadga yetarli"
        gap = need - self.my_average
        if gap <= 3:
            return "maqsad yaqin — turiga bir necha ochko qo'shish kerak"
        if gap <= 8:
            return "sur'atni sezilarli oshirish kerak"
        return "bu maqsad joriy sur'atda erishib bo'lmaydi"

    @property
    def realistic_target(self) -> int:
        """Joriy sur'at saqlansa erishiladigan yakuniy ochko."""
        return int(round(self.projected_total))


def build_pace(
    history: dict,
    target: int = DEFAULT_TARGET,
    leader_total: int | None = None,
    leader_played: int | None = None,
    finished_events: list[int] | None = None,
) -> SeasonPace | None:
    """`entry/{id}/history/` dan sur'at hisobini quradi.

    `finished_events` berilsa, **faqat yakunlangan turlar** hisobga olinadi.
    Yarim o'ynalgan turning jonli ochkosini yakuniy deb olish sur'atni
    keskin buzadi: 5 ta uchrashuvi hali bo'lmagan turda 12 ochko turishi
    mumkin, lekin bu "12 ochko oldingiz" degani emas.
    """
    current = [r for r in (history or {}).get("current", []) if r.get("event")]
    if finished_events is not None:
        allowed = set(finished_events)
        partial = [r for r in current if r["event"] not in allowed]
        current = [r for r in current if r["event"] in allowed]
    else:
        partial = []
    if not current:
        return None

    rows = [
        GameweekRow(
            event=r["event"],
            points=r.get("points", 0) or 0,
            average=r.get("average_entry_score", 0) or 0,
            rank=r.get("rank"),
        )
        for r in current
    ]
    played = len(rows)
    my_total = sum(r.points for r in rows)
    scores = [r.points for r in rows]

    # Yetakchining ochkosi ham jonli, ya'ni tugamagan turni qamrab oladi.
    # Shuning uchun o'rtachasi ham xuddi shuncha turga bo'linishi kerak.
    covered = played + (1 if partial else 0)
    leader_average = None
    if leader_total is not None:
        leader_average = leader_total / max(1, leader_played or covered)

    return SeasonPace(
        partial_event=partial[-1]["event"] if partial else None,
        partial_points=partial[-1].get("points", 0) if partial else None,
        played=played,
        remaining=max(0, TOTAL_GAMEWEEKS - played),
        target=target,
        my_total=my_total,
        my_average=my_total / played,
        my_best=max(scores),
        my_worst=min(scores),
        leader_total=leader_total,
        leader_average=leader_average,
        fpl_average_total=sum(r.average for r in rows),
        rows=rows,
    )


def fetch_leader(client, overall_league_id: int = 314) -> tuple[int, str] | None:
    """Umumiy jadval yetakchisining ochkosi va nomi."""
    try:
        data = client.league_standings(overall_league_id, page=1)
    except Exception:
        return None
    results = (data.get("standings") or {}).get("results") or []
    if not results:
        return None
    top = results[0]
    return top.get("total", 0), top.get("player_name", "?")
