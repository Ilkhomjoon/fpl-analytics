"""Mavsum sur'ati — maqsadga nisbatan qayerdaman?

SAVOL: "2810 ochko 38 turda" degan maqsad bir turga **74 ochko**ni anglatadi.
Lekin o'rtacha son yolg'iz o'zi hech narsa aytmaydi: 5-turda 300 ochkom bor
desam, bu yaxshimi yoki yomonmi? Javob **shu paytgacha kerak bo'lgan** ochko
bilan solishtirganda chiqadi.

Shuning uchun uchta raqam hisoblanadi:

* **rejadagi** ochko — `o'ynalgan turlar x turga to'g'ri keladigan norma`;
* **farq** — haqiqiy minus rejadagi (musbat bo'lsa oldindasiz);
* **qolgan normalar** — maqsadga yetish uchun endi turiga nechta kerak.

Oxirgisi eng foydalisi: orqada qolgan sari talab o'sib boradi va maqsad
qachon real emasligini o'zi ko'rsatadi.

TAQQOSLASH. O'z sur'atini bilish yetarli emas — **birinchi o'rindagi menejer**
turiga o'rtacha nechta olayotgani ham kerak. U real chegarani ko'rsatadi:
maqsad haqiqatan yetib bo'ladigan darajadami yoki yo'q.

XIT (hit) HAQIDA. FPL ning `total_points` i **minuslar ayirilgan** yakuniy
ochko. Sur'at ham shu bo'yicha o'lchanadi: maqsad ham, natija ham bir xil
birlikda bo'lishi kerak.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TOTAL_EVENTS = 38
DEFAULT_TARGET = 2810

# Sur'at bahosi: haqiqiy / rejadagi nisbati
GRADE_BANDS = (
    (1.05, "a'lo", "good"),
    (1.00, "rejada", "good"),
    (0.92, "ortda", "warning"),
    (0.80, "sezilarli ortda", "serious"),
    (0.00, "juda ortda", "critical"),
)


@dataclass
class EventPoint:
    """Bitta turning natijasi."""
    event: int
    points: int              # shu turdagi ochko (minuslar AYIRILMAGAN)
    total: int               # mavsum boshidan yig'ilgan (minuslar ayirilgan)
    hit: int = 0             # shu turda olingan minus
    rank: int = 0            # umumiy o'rin
    gw_rank: int = 0         # shu turdagi o'rin
    bench: int = 0           # zaxirada qolib ketgan ochko
    transfers: int = 0       # qilingan transferlar
    value: float = 0.0       # jamoa qiymati (mln)
    bank: float = 0.0        # bankdagi pul (mln)
    average: int = 0         # o'sha turda hamma menejerlarning o'rtachasi
    chip: str = ""           # ishlatilgan chip

    @property
    def net(self) -> int:
        """Shu turda qo'lga kiritilgan sof ochko."""
        return self.points - self.hit

    @property
    def vs_average(self) -> int:
        """O'rtachadan farq — eng tez o'qiladigan ko'rsatkich."""
        return self.net - self.average if self.average else 0


@dataclass
class Pace:
    target: int
    played: int
    total_events: int
    points: int
    events: list[EventPoint] = field(default_factory=list)

    # ------------------------------------------------------------- normalar
    @property
    def per_event_needed(self) -> float:
        """Mavsum boshidagi norma — maqsad / 38."""
        return self.target / self.total_events if self.total_events else 0.0

    @property
    def on_pace_points(self) -> float:
        """Shu paytgacha rejada nechta bo'lishi kerak edi."""
        return self.per_event_needed * self.played

    @property
    def delta(self) -> float:
        """Rejadan farq. Musbat — oldindasiz."""
        return self.points - self.on_pace_points

    @property
    def ratio(self) -> float:
        """Haqiqiy / rejadagi. Sur'at bahosi shundan chiqadi."""
        planned = self.on_pace_points
        return (self.points / planned) if planned > 0 else 0.0

    @property
    def remaining_events(self) -> int:
        return max(0, self.total_events - self.played)

    @property
    def needed_per_event(self) -> float:
        """Maqsadga yetish uchun QOLGAN turlarda turiga nechta kerak.

        Eng foydali raqam: orqada qolgan sari talab o'sadi va maqsadning
        realligini o'zi ko'rsatadi.
        """
        left = self.target - self.points
        if left <= 0:
            return 0.0
        if self.remaining_events <= 0:
            return float("inf")             # turlar tugadi, maqsad qo'lda emas
        return left / self.remaining_events

    @property
    def average(self) -> float:
        return self.points / self.played if self.played else 0.0

    @property
    def projected(self) -> float:
        """Shu sur'at davom etsa mavsum oxirida nechta bo'ladi."""
        return self.average * self.total_events

    def grade(self) -> tuple[str, str]:
        """(matn, holat) — holat: good / warning / serious / critical.

        Rang yolg'iz ma'no tashimaydi: matn har doim yonida turadi.
        """
        if not self.played:
            return "boshlanmadi", "warning"
        for chegara, matn, holat in GRADE_BANDS:
            if self.ratio >= chegara:
                return matn, holat
        return "juda ortda", "critical"

    @property
    def progress(self) -> float:
        """Maqsadning necha foizi bajarildi (0..1 dan oshishi ham mumkin)."""
        return self.points / self.target if self.target else 0.0

    @property
    def season_progress(self) -> float:
        """Mavsumning necha foizi o'tdi."""
        return self.played / self.total_events if self.total_events else 0.0

    # ------------------------------------------------- jamoa ko'rsatkichlari
    @property
    def hits_paid(self) -> int:
        """Mavsum davomida minusga ketgan ochko — to'g'ridan-to'g'ri yo'qotish."""
        return sum(e.hit for e in self.events)

    @property
    def bench_lost(self) -> int:
        """Zaxirada qolib ketgan ochko.

        Bu "yo'qotish" emas — zaxirani 11 likka qo'yish har doim ham mumkin
        emas edi. Lekin katta son tarkib tanlashda muammo borligini aytadi.
        """
        return sum(e.bench for e in self.events)

    @property
    def transfers_made(self) -> int:
        return sum(e.transfers for e in self.events)

    @property
    def vs_average_total(self) -> int:
        """Mavsum bo'yicha o'rtacha menejerdan farq."""
        return sum(e.vs_average for e in self.events if e.average)

    @property
    def beat_average(self) -> int:
        """Nechta turda o'rtachadan yuqori chiqdim."""
        return sum(1 for e in self.events if e.average and e.net > e.average)

    @property
    def best(self) -> EventPoint | None:
        return max(self.events, key=lambda e: e.net, default=None)

    @property
    def worst(self) -> EventPoint | None:
        return min(self.events, key=lambda e: e.net, default=None)

    @property
    def rank(self) -> int:
        """Joriy umumiy o'rin."""
        return self.events[-1].rank if self.events else 0

    @property
    def best_rank(self) -> int:
        ranks = [e.rank for e in self.events if e.rank]
        return min(ranks) if ranks else 0

    @property
    def value(self) -> float:
        return self.events[-1].value if self.events else 0.0

    @property
    def consistency(self) -> float:
        """Natijalarning standart chetlanishi — barqarorlik o'lchovi.

        Past qiymat "har turda taxminan bir xil" degani. FPL da yuqori
        o'rin uchun barqarorlik ham, portlashlar ham kerak, shuning uchun
        bu raqam baho emas — kuzatuv.
        """
        if len(self.events) < 2:
            return 0.0
        vals = [e.net for e in self.events]
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)
        return var ** 0.5


def from_history(history: dict, target: int = DEFAULT_TARGET,
                 total_events: int = TOTAL_EVENTS,
                 bootstrap: dict | None = None) -> Pace:
    """`entry/{id}/history/` javobidan sur'atni hisoblaydi.

    `bootstrap` berilsa har turning **umumiy o'rtachasi** ham qo'shiladi
    (`events[].average_entry_score`) — "men o'rtachadan qanchaman" degan
    savol maqsaddan ham tezroq o'qiladi.
    """
    averages = {}
    for e in (bootstrap or {}).get("events", []) or []:
        if e.get("id"):
            averages[int(e["id"])] = int(e.get("average_entry_score") or 0)

    chips = {}
    for c in (history or {}).get("chips", []) or []:
        if c.get("event"):
            chips[int(c["event"])] = str(c.get("name") or "")

    rows = []
    for row in (history or {}).get("current", []) or []:
        event = row.get("event")
        if event is None:
            continue
        event = int(event)
        rows.append(EventPoint(
            event=event,
            points=int(row.get("points") or 0),
            total=int(row.get("total_points") or 0),
            hit=int(row.get("event_transfers_cost") or 0),
            rank=int(row.get("overall_rank") or 0),
            gw_rank=int(row.get("rank") or 0),
            bench=int(row.get("points_on_bench") or 0),
            transfers=int(row.get("event_transfers") or 0),
            value=round((row.get("value") or 0) / 10.0, 1),
            bank=round((row.get("bank") or 0) / 10.0, 1),
            average=averages.get(event, 0),
            chip=chips.get(event, ""),
        ))
    rows.sort(key=lambda r: r.event)
    # `total_points` allaqachon minuslar ayirilgan yakuniy ochko
    points = rows[-1].total if rows else 0
    return Pace(target=target, played=len(rows), total_events=total_events,
                points=points, events=rows)


def leader_pace(client, cfg, total_events: int = TOTAL_EVENTS) -> dict:
    """Umumiy jadvalning **birinchi o'rnidagi** menejer sur'ati.

    Ikki so'rov: umumiy liganing birinchi sahifasi, so'ng o'sha menejerning
    tarixi. Xatolik bo'lsa bo'sh lug'at qaytadi — asosiy sur'at baribir
    ko'rsatiladi, taqqoslash esa ixtiyoriy qism.
    """
    try:
        standings = client.league_standings(
            getattr(cfg, "overall_league_id", 314), page=1)
        results = ((standings or {}).get("standings") or {}).get("results") or []
        if not results:
            return {}
        top = results[0]
        entry_id = int(top.get("entry") or 0)
        if not entry_id:
            return {}
        history = client.entry_history(entry_id)
    except Exception:
        return {}

    pace = from_history(history, target=0, total_events=total_events)
    if not pace.played:
        return {}
    return {
        "entry_id": entry_id,
        "name": top.get("entry_name") or "",
        "manager": top.get("player_name") or "",
        "points": pace.points,
        "played": pace.played,
        "average": round(pace.average, 1),
        "projected": round(pace.projected, 0),
    }
