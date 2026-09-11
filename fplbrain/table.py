"""Joriy mavsum jadvali — tugagan uchrashuvlardan qurib olinadi.

Nega kerak? FPL ning rasmiy FDR si **mavsum boshida** belgilanadi va butun
mavsum davomida o'zgarmaydi. Ya'ni u faktni emas, taxminni bildiradi.

Aniq misol: Arsenal — Aston Villa uchrashuvida rasmiy FDR 4 ("qiyin") edi.
Lekin Aston Villa mavsumni Brighton dan 0:4 mag'lubiyat bilan boshlagan.
Rasmiy FDR buni bilmaydi, jadval esa biladi. Shuning uchun raqibning
qiyinligini baholashda uning **jadvaldagi o'rni va joriy natijalari** ham
hisobga olinishi kerak.

Bu modul faqat ma'lumot yig'adi (kim nechta ochko oldi, nechta gol urdi).
Uni reytingga aylantirish `ratings.py` ning vazifasi.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# So'nggi o'yinlar ko'proq narsani aytadi: har bir eski o'yin vazni shu
# koeffitsiyentga ko'paytiriladi (5 o'yin oldingisi ~0.44 vazn oladi).
FORM_DECAY = 0.85
FORM_WINDOW = 6


@dataclass
class Match:
    """Bitta jamoa nuqtai nazaridan tugagan uchrashuv."""
    event: int
    opponent: int
    is_home: bool
    scored: int
    conceded: int

    @property
    def points(self) -> int:
        if self.scored > self.conceded:
            return 3
        return 1 if self.scored == self.conceded else 0

    @property
    def result(self) -> str:
        return "G" if self.points == 3 else ("D" if self.points == 1 else "M")


@dataclass
class TableRow:
    """Jamoaning jadvaldagi holati va joriy formasi."""
    team_id: int
    short: str
    name: str
    matches: list[Match] = field(default_factory=list)
    position: int = 0            # 1 = birinchi o'rin; 0 = hali o'yin yo'q

    # ---------------------------------------------------------- oddiy hisob
    @property
    def played(self) -> int:
        return len(self.matches)

    @property
    def points(self) -> int:
        return sum(m.points for m in self.matches)

    @property
    def won(self) -> int:
        return sum(1 for m in self.matches if m.points == 3)

    @property
    def drawn(self) -> int:
        return sum(1 for m in self.matches if m.points == 1)

    @property
    def lost(self) -> int:
        return sum(1 for m in self.matches if m.points == 0)

    @property
    def gf(self) -> int:
        return sum(m.scored for m in self.matches)

    @property
    def ga(self) -> int:
        return sum(m.conceded for m in self.matches)

    @property
    def gd(self) -> int:
        return self.gf - self.ga

    @property
    def ppg(self) -> float:
        return self.points / self.played if self.played else 0.0

    @property
    def gf_rate(self) -> float:
        return self.gf / self.played if self.played else 0.0

    @property
    def ga_rate(self) -> float:
        return self.ga / self.played if self.played else 0.0

    # ------------------------------------------------------- forma (vaznli)
    def _weights(self) -> list[tuple[Match, float]]:
        window = self.matches[-FORM_WINDOW:]
        n = len(window)
        return [(m, FORM_DECAY ** (n - 1 - i)) for i, m in enumerate(window)]

    def _weighted(self, value) -> float:
        pairs = self._weights()
        total_w = sum(w for _, w in pairs)
        if not total_w:
            return 0.0
        return sum(value(m) * w for m, w in pairs) / total_w

    @property
    def form_ppg(self) -> float:
        """So'nggi o'yinlarga ko'proq vazn beruvchi o'rtacha ochko."""
        return self._weighted(lambda m: float(m.points))

    @property
    def form_gf_rate(self) -> float:
        return self._weighted(lambda m: float(m.scored))

    @property
    def form_ga_rate(self) -> float:
        return self._weighted(lambda m: float(m.conceded))

    @property
    def form_string(self) -> str:
        """Oxirgi 5 o'yin: eng yangisi oxirida (masalan `M D G G G`)."""
        return " ".join(m.result for m in self.matches[-5:])

    def last_results(self, n: int = 3) -> list[str]:
        """Inson o'qiy oladigan ko'rinish: `0:4 BHA(m)` — eng yangisi oxirida."""
        out = []
        for m in self.matches[-n:]:
            side = "u" if m.is_home else "m"
            out.append(f"{m.scored}:{m.conceded} ({side})")
        return out


def build_table(bootstrap: dict, fixtures: list[dict]) -> dict[int, TableRow]:
    """team_id -> TableRow. Faqat **tugagan** uchrashuvlar hisobga olinadi.

    Davom etayotgan tur natijaga kirmaydi: yarim o'ynalgan o'yin jadvalni
    buzadi (bu xatoga GW2 tahlilida bir marta tushib bo'lganmiz).
    """
    rows: dict[int, TableRow] = {
        t["id"]: TableRow(team_id=t["id"], short=t["short_name"], name=t["name"])
        for t in bootstrap.get("teams", [])
    }

    ordered = sorted(
        (f for f in fixtures if f.get("event") is not None),
        key=lambda f: (f.get("event") or 0, f.get("kickoff_time") or ""),
    )
    for f in ordered:
        if not (f.get("finished") or f.get("finished_provisional")):
            continue
        h, a = f.get("team_h"), f.get("team_a")
        gh, ga = f.get("team_h_score"), f.get("team_a_score")
        if h not in rows or a not in rows or gh is None or ga is None:
            continue
        event = f["event"]
        rows[h].matches.append(Match(event, a, True, int(gh), int(ga)))
        rows[a].matches.append(Match(event, h, False, int(ga), int(gh)))

    rank(rows)
    return rows


def rank(rows: dict[int, TableRow]) -> list[TableRow]:
    """Jadval tartibi: ochko, gol farqi, urilgan gol. `position` ni yozib qo'yadi."""
    order = sorted(
        rows.values(), key=lambda r: (-r.points, -r.gd, -r.gf, r.short)
    )
    played_any = any(r.played for r in rows.values())
    for i, row in enumerate(order, start=1):
        row.position = i if played_any else 0
    return order


def position_index(row: TableRow | None, team_count: int = 20) -> float:
    """Jadvaldagi o'rin 0..1 oralig'ida (1.0 = birinchi o'rin, 0.0 = oxirgi).

    O'yin o'ynalmagan bo'lsa 0.5 — ya'ni "bilmayman, o'rtacha deb hisoblayman".
    """
    if row is None or not row.position or team_count < 2:
        return 0.5
    return (team_count - row.position) / (team_count - 1)
