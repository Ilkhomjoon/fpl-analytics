"""Kapitan tanlash.

Kapitanlikda o'rtacha EV emas, **taqsimotning tepasi** hal qiladi: ochko
ikkilanadi, shuning uchun 6 ochkoni kafolatlaydigan o'yinchidan ko'ra 15 ochko
berish ehtimoli yuqori bo'lgani afzalroq bo'lishi mumkin.

Ikkinchi o'lchov — **maydondan ustunlik**. Agar raqiblarning yarmi Haalandni
kapitan qilgan bo'lsa, siz ham qilsangiz o'rin o'zgarmaydi; boshqasini
qilsangiz — tavakkal. Qaysi biri to'g'riligi sizning o'rningizga bog'liq.
"""

from __future__ import annotations

from dataclasses import dataclass

from .ev import GK, combine_distributions, points_distribution
from .squad import Squad, SquadPlayer, best_eleven


@dataclass
class CaptainOption:
    player: SquadPlayer
    ev: float
    p10: float                # 10+ ochko ehtimoli
    p15: float                # 15+ ochko ehtimoli
    ceiling: float            # 90-foizli natija
    eo: float                 # raqiblar orasida kapitanlik ulushi (%)
    edge: float               # maydonning kutilayotgan kapitani ustidan ustunlik
    score: float
    verdict: str

    @property
    def name(self) -> str:
        return self.player.name


def player_distribution(player: SquadPlayer, event: int):
    """O'yinchining shu turdagi ochko taqsimoti (DGW bo'lsa birlashtiriladi)."""
    fixtures = player.ev.fixtures.get(event, [])
    return combine_distributions([points_distribution(f.inputs) for f in fixtures])


def field_captain_ev(
    squad_lookup, captain_eo: dict[int, float], event: int, ev_by_element
) -> float:
    """Raqiblarning kapitan tanlovidan kutilayotgan o'rtacha ochko.

    Bu — solishtirish nuqtasi: mening kapitanim shundan qancha yuqori yoki past.
    """
    total_weight, total_ev = 0.0, 0.0
    for element, pct in captain_eo.items():
        pev = ev_by_element.get(element)
        if not pev:
            continue
        total_weight += pct
        total_ev += pct * pev.per_event.get(event, 0.0)
    if total_weight <= 0:
        return 0.0
    # qolgan ulush — o'rtacha kapitan (taxminan 5 ochko)
    remainder = max(0.0, 100.0 - total_weight)
    return (total_ev + remainder * 5.0) / 100.0


def rank_strategy(my_rank: int | None, total_players: int | None) -> tuple[str, str]:
    """O'ringa qarab tavsiya etiladigan strategiya: (nom, izoh)."""
    if not my_rank or not total_players:
        return "balanced", "o'rin noma'lum — muvozanatli yondashuv"
    pct = my_rank / total_players * 100
    if pct <= 1:
        return "safe", (
            f"yuqori {pct:.1f}% dasiz — asosiy vazifa o'rinni saqlash, "
            "ommaviy kapitandan chetlashish qimmatga tushadi"
        )
    if pct <= 10:
        return "balanced", (
            f"yuqori {pct:.1f}% dasiz — o'rinni saqlab, tanlab tavakkal qiling"
        )
    return "aggressive", (
        f"yuqori {pct:.1f}% dasiz — ommaviy tanlov sizni yuqoriga ko'tarmaydi, "
        "o'rin ko'tarish uchun farq kerak"
    )


def rank_captains(
    squad: Squad,
    event: int,
    captain_eo: dict[int, float] | None = None,
    strategy: str = "balanced",
    limit: int = 5,
    ev_by_element: dict | None = None,
) -> list[CaptainOption]:
    captain_eo = captain_eo or {}
    xi, _, _, _ = best_eleven(squad.players, event)

    # Darvozabon kapitan bo'lmaydi: tepasi yo'q (P(10+) ≈ 1%).
    candidates = [p for p in xi if p.position != GK] or xi

    field_ev = (
        field_captain_ev(squad, captain_eo, event, ev_by_element)
        if ev_by_element else 0.0
    )

    options: list[CaptainOption] = []
    for p in candidates:
        dist = player_distribution(p, event)
        ev = dist.mean()
        p10, p15 = dist.tail(10), dist.tail(15)
        ceiling = dist.percentile(0.90)
        eo = captain_eo.get(p.element, 0.0)
        edge = ev - field_ev if field_ev else 0.0

        # Strategiya tepaga va ommaviylikka berilgan vaznni o'zgartiradi
        if strategy == "safe":
            score = ev + 2.0 * p10 + 0.020 * eo
        elif strategy == "aggressive":
            score = ev + 6.0 * p10 + 4.0 * p15 - 0.015 * eo
        else:
            score = ev + 4.0 * p10 + 1.5 * p15

        options.append(CaptainOption(
            player=p, ev=round(ev, 2), p10=round(p10, 3), p15=round(p15, 3),
            ceiling=ceiling, eo=round(eo, 1), edge=round(edge, 2),
            score=round(score, 2), verdict="",
        ))

    options.sort(key=lambda o: -o.score)
    best_ev = max((o.ev for o in options), default=0.0)
    for o in options:
        o.verdict = _verdict(o, best_ev, strategy)
    return options[:limit]


def _verdict(o: CaptainOption, best_ev: float, strategy: str) -> str:
    if o.p10 < 0.06:
        return "tepasi yo'q — kapitanlikka yaramaydi"
    if o.eo >= 35:
        return f"maydon tanlovi ({o.eo:.0f}%) — o'rinni saqlaydi, ko'tarmaydi"
    if o.eo <= 10 and o.p10 >= 0.20:
        return f"differensial — {o.p10*100:.0f}% ehtimol bilan 10+, o'rin ko'taradi"
    if o.ev < best_ev - 1.2:
        return "EV bo'yicha orqada"
    return "muvozanatli variant"
