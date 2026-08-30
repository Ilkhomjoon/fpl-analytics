"""Strategik tahlil — "nega men shu o'rindaman va nima buni o'zgartiradi".

Bu modul alohida o'yinchilarni emas, **maydonga nisbatan holatni** baholaydi:
qaysi o'yinchilar sizni har hafta ortga tortadi, differensiallaringiz shuni
qoplayaptimi, tarkibingiz raqiblarnikidan qanchalik orqada.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .ev import DEF, FWD, GK, MID, PlayerEV
from .rivals import GroupStats
from .squad import Squad, SquadPlayer, best_eleven

FORMATIONS = [(1, 3, 4, 3), (1, 3, 5, 2), (1, 4, 4, 2), (1, 4, 3, 3), (1, 5, 3, 2)]


# ------------------------------------------------------------ strukturaviy farq
@dataclass
class Exposure:
    """Bitta o'yinchi bo'yicha maydonga nisbatan haftalik ochko oqimi."""
    element: int
    name: str
    eo: float                 # egalik + kapitanlik (%)
    ev: float                 # keyingi turdagi kutilayotgan ochko
    swing: float              # har tur menga nisbatan kutilayotgan farq (ochko)
    owned: bool


@dataclass
class GapReport:
    """Maydonga nisbatan holat.

    `net` — mening eng yaxshi 11 ligim bilan guruhning shablon 11 ligi orasidagi
    farq (ochko/tur). Bu **yagona to'g'ri umumiy o'lchov**: har ikkala tomon ham
    11 o'yinchi qo'yadi, shuning uchun taqqoslash asosli.

    `threats` va `edges` — o'sha farqning tarkibiy qismlari, ya'ni izoh. Ular
    alohida-alohida yig'ilmaydi: bir o'yinchining hissasi boshqasiniki bilan
    to'g'ridan-to'g'ri qo'shilmaydi.
    """
    group: str
    net: float = 0.0                                           # 11 lik farqi
    threats: list[Exposure] = field(default_factory=list)      # menda yo'q
    edges: list[Exposure] = field(default_factory=list)        # menda bor


def effective_ownership(stats: GroupStats, element: int) -> float:
    return stats.ownership.get(element, 0.0) + stats.captaincy.get(element, 0.0)


def structural_gap(
    squad: Squad,
    stats: GroupStats,
    ev_by_element: dict[int, PlayerEV],
    event: int,
    top: int = 5,
    min_eo: float = 15.0,
) -> GapReport:
    """Maydonga nisbatan haftalik ochko oqimini hisoblaydi.

    Mantiq: raqiblarning EO% i bor o'yinchi X ochko olsa, ular menga nisbatan
    o'rtacha `EO/100 * X` ochko yutadi (kapitanlik ikki barobar hisoblanadi,
    shuning uchun EO da alohida qo'shilgan). Menda bor va ularda yo'q o'yinchi
    esa teskari yo'nalishda ishlaydi.
    """
    mine = {p.element for p in squad.players}
    report = GapReport(group=stats.label)

    # Umumiy o'lchov — 11 likka 11 lik: bu yagona asosli taqqoslash
    _, _, _, my_xi_ev = best_eleven(squad.players, event)
    template_ev, _ = template_xi_ev(stats, ev_by_element, event)
    report.net = round(my_xi_ev - template_ev, 2)

    xi_ids = {p.element for p in best_eleven(squad.players, event)[0]}

    for element, own in stats.ownership.items():
        eo = effective_ownership(stats, element)
        pev = ev_by_element.get(element)
        if not pev or eo < min_eo:
            continue
        ev = pev.per_event.get(event, 0.0)
        if ev <= 0:
            continue
        if element in mine:
            continue
        report.threats.append(Exposure(
            element=element, name=pev.profile.name, eo=round(eo, 1),
            ev=round(ev, 2), swing=round(-(eo / 100.0) * ev, 2), owned=False,
        ))

    # Faqat asosiy 11 likdagilar: zaxiradagi o'yinchi maydonga ta'sir qilmaydi
    for player in squad.players:
        element = player.element
        if element not in xi_ids:
            continue
        eo = effective_ownership(stats, element)
        pev = ev_by_element.get(element)
        if not pev:
            continue
        ev = pev.per_event.get(event, 0.0)
        if ev <= 0.5:
            continue
        report.edges.append(Exposure(
            element=element, name=pev.profile.name, eo=round(eo, 1),
            ev=round(ev, 2), swing=round((1 - eo / 100.0) * ev, 2), owned=True,
        ))

    report.threats.sort(key=lambda e: e.swing)                 # eng manfiysi birinchi
    report.edges.sort(key=lambda e: -e.swing)
    report.threats = report.threats[:top]
    report.edges = report.edges[:top]
    return report


# ------------------------------------------------------------------- benchmark
def template_xi_ev(
    stats: GroupStats, ev_by_element: dict[int, PlayerEV], event: int
) -> tuple[float, list[str]]:
    """Guruhning "shablon" 11 ligi va uning EV si.

    Har pozitsiyada eng ko'p egallangan o'yinchilar olinadi — bu raqiblarning
    o'rtacha jamoasiga eng yaqin yaqinlashish.
    """
    by_pos: dict[int, list[tuple[float, PlayerEV]]] = {GK: [], DEF: [], MID: [], FWD: []}
    for element, own in stats.ownership.items():
        pev = ev_by_element.get(element)
        if pev:
            by_pos[pev.profile.position].append((own, pev))
    for pos in by_pos:
        by_pos[pos].sort(key=lambda x: -x[0])

    best_ev, best_names = 0.0, []
    for form in FORMATIONS:
        need = dict(zip((GK, DEF, MID, FWD), form))
        if any(len(by_pos[pos]) < n for pos, n in need.items()):
            continue
        picked = [pev for pos, n in need.items() for _, pev in by_pos[pos][:n]]
        total = sum(p.per_event.get(event, 0.0) for p in picked)
        if total > best_ev:
            best_ev = total
            best_names = [p.profile.name for p in picked]
    return round(best_ev, 2), best_names


@dataclass
class Benchmark:
    my_xi_ev: float
    template_ev: float
    group: str

    @property
    def gap(self) -> float:
        return round(self.my_xi_ev - self.template_ev, 2)


def benchmark_vs_template(
    squad: Squad, stats: GroupStats, ev_by_element: dict[int, PlayerEV], event: int
) -> Benchmark:
    _, _, _, my_ev = best_eleven(squad.players, event)
    template_ev, _ = template_xi_ev(stats, ev_by_element, event)
    return Benchmark(my_xi_ev=round(my_ev, 2), template_ev=template_ev, group=stats.label)


# --------------------------------------------------------------- fixture ko'rinishi
@dataclass
class TeamOutlook:
    short: str
    score: float              # o'rtacha (o'z gollari − kiritilgan gollari)
    marks: list[str]
    my_players: list[str] = field(default_factory=list)


def fixture_outlook(
    squad: Squad,
    views,
    ratings,
    events: list[int],
    ev_by_element: dict[int, PlayerEV],
) -> tuple[list[TeamOutlook], list[TeamOutlook]]:
    """(eng yaxshi turlar, eng yomon turlar) — mening o'yinchilarim belgilangan holda."""
    mine: dict[int, list[str]] = {}
    for p in squad.players:
        mine.setdefault(p.ev.profile.team, []).append(p.name)

    rows: list[TeamOutlook] = []
    for team_id, per_event in views.items():
        marks, scores = [], []
        for ev in events:
            fixtures = per_event.get(ev, [])
            if not fixtures:
                marks.append("—")
                continue
            for fx in fixtures:
                opponent = ratings[fx.opponent].short
                marks.append(f"{opponent}{'(u)' if fx.is_home else '(m)'}")
                scores.append(fx.lam_for - fx.lam_against)
        if not scores:
            continue
        rows.append(TeamOutlook(
            short=ratings[team_id].short,
            score=round(sum(scores) / len(scores), 2),
            marks=marks,
            my_players=mine.get(team_id, []),
        ))

    rows.sort(key=lambda r: -r.score)
    return rows[:6], rows[-5:][::-1]


# ------------------------------------------- shablon asosida sotish/olish
@dataclass
class TemplateMove:
    """Top-N shabloniga qarab tavsiya: kimni sotib, kimni olish."""
    out_element: int
    out_name: str
    out_price: float
    out_eo: float
    in_element: int
    in_name: str
    in_price: float
    in_eo: float
    ev_gain: float            # gorizont bo'yicha EV farqi
    eo_gain: float            # EO farqi (maydonga nisbatan himoya)
    affordable: bool
    reason: str


def template_moves(
    squad: Squad,
    stats: GroupStats,
    ev_by_element: dict[int, PlayerEV],
    event: int,
    bank: float,
    top: int = 5,
    min_eo: float = 25.0,
) -> list[TemplateMove]:
    """Top-N da ommaviy, menda yo'q o'yinchilarni tarkibimdagilarga solishtiradi.

    Mantiq: shablon o'yinchisi ikki tomonlama foyda beradi — EV odatda
    yuqoriroq, va u ochko olganda siz maydondan orqada qolmaysiz. Shuning
    uchun EV farqiga EO farqi ham qo'shib baholanadi.
    """
    mine = {p.element for p in squad.players}
    by_position: dict[int, list[SquadPlayer]] = {}
    for player in squad.players:
        by_position.setdefault(player.position, []).append(player)

    targets: list[tuple[float, PlayerEV]] = []
    for element, own in stats.ownership.items():
        eo = effective_ownership(stats, element)
        pev = ev_by_element.get(element)
        if element in mine or not pev or eo < min_eo:
            continue
        if pev.profile.availability < 0.6:
            continue
        targets.append((eo, pev))
    targets.sort(key=lambda x: -x[0])

    moves: list[TemplateMove] = []
    used_out: set[int] = set()
    for eo, pev in targets:
        candidates = by_position.get(pev.profile.position, [])
        if not candidates:
            continue
        # Shu pozitsiyada eng zaif, hali taklif qilinmagan o'yinchim
        pool = [p for p in candidates if p.element not in used_out]
        if not pool:
            continue
        weakest = min(pool, key=lambda p: p.ev.horizon_ev)
        budget = bank + weakest.selling_price
        out_eo = effective_ownership(stats, weakest.element)

        ev_gain = round(pev.horizon_ev - weakest.ev.horizon_ev, 2)
        eo_gain = round(eo - out_eo, 1)
        if ev_gain <= 0 and eo_gain <= 10:
            continue

        affordable = pev.profile.price <= budget + 1e-9
        if ev_gain > 0 and eo_gain > 0:
            reason = "EV ham, maydon himoyasi ham yaxshilanadi"
        elif ev_gain > 0:
            reason = "EV yuqoriroq"
        else:
            reason = "EV teng, lekin maydondan orqada qolmaysiz"
        if not affordable:
            reason += f" — {pev.profile.price - budget:.1f}m yetmaydi"

        moves.append(TemplateMove(
            out_element=weakest.element, out_name=weakest.name,
            out_price=weakest.selling_price, out_eo=round(out_eo, 1),
            in_element=pev.element, in_name=pev.profile.name,
            in_price=pev.profile.price, in_eo=round(eo, 1),
            ev_gain=ev_gain, eo_gain=eo_gain,
            affordable=affordable, reason=reason,
        ))
        used_out.add(weakest.element)
        if len(moves) >= top:
            break

    moves.sort(key=lambda m: (not m.affordable, -(m.ev_gain + m.eo_gain / 12)))
    return moves


# ------------------------------------------------- deadline oldidan xavf tekshiruvi
@dataclass
class RiskPlayer:
    name: str
    position: int
    p_start: float
    reason: str
    severity: int             # 3 = o'ynamaydi, 2 = jiddiy shubha, 1 = ehtiyot bo'ling


@dataclass
class SquadRisk:
    """Asosiy 11 likda o'yin vaqti xavfi bor o'yinchilar."""
    players: list[RiskPlayer] = field(default_factory=list)
    blank_teams: int = 0

    @property
    def serious(self) -> list[RiskPlayer]:
        return [p for p in self.players if p.severity >= 2]

    @property
    def headline(self) -> str:
        n = len(self.serious)
        if n == 0:
            return ""
        return f"⚠️ 11 likda {n} ta o'yinchi o'ynamasligi mumkin"


def squad_risk(squad: Squad, event: int, views=None) -> SquadRisk:
    """Deadline oldidan eng muhim tekshiruv: hamma o'ynaydimi?

    Bir turda uch o'yinchi maydonga chiqmasa, hisobot qanchalik chuqur
    bo'lishidan qat'i nazar, tur yo'qoladi. Shuning uchun bu tekshiruv
    hisobotning eng tepasida turadi.
    """
    risk = SquadRisk()
    xi, _, _, _ = best_eleven(squad.players, event)

    for player in xi:
        profile = player.ev.profile
        has_fixture = True
        if views is not None:
            has_fixture = bool(views.get(profile.team, {}).get(event))

        if not has_fixture:
            risk.blank_teams += 1
            risk.players.append(RiskPlayer(
                player.name, player.position, profile.p_start,
                "jamoasi bu turda o'ynamaydi (bo'sh tur)", 3,
            ))
            continue

        if profile.status in ("i", "s", "u", "n") or profile.availability <= 0.05:
            risk.players.append(RiskPlayer(
                player.name, player.position, profile.p_start,
                profile.news or "o'ynamaydi", 3,
            ))
        elif profile.availability < 0.8:
            risk.players.append(RiskPlayer(
                player.name, player.position, profile.p_start,
                profile.news or f"{profile.availability * 100:.0f}% ehtimol", 2,
            ))
        elif profile.p_start < 0.55:
            risk.players.append(RiskPlayer(
                player.name, player.position, profile.p_start,
                f"asosiy tarkib ehtimoli {profile.p_start * 100:.0f}%", 2,
            ))
        elif profile.p_start < 0.72:
            risk.players.append(RiskPlayer(
                player.name, player.position, profile.p_start,
                f"asosiy tarkib ehtimoli {profile.p_start * 100:.0f}%", 1,
            ))

    risk.players.sort(key=lambda p: (-p.severity, p.p_start))
    return risk
