"""Chip (WC / BB / TC / FH) uchun eng qulay turni baholash."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .ev import PlayerEV
from .squad import Squad, best_eleven

CHIP_NAMES = {
    "wildcard": "Wildcard",
    "bboost": "Bench Boost",
    "3xc": "Triple Captain",
    "freehit": "Free Hit",
}
ALL_CHIPS = ["wildcard", "bboost", "3xc", "freehit"]
SECOND_HALF_START = 20      # chiplar GW20 da yangilanadi (mavsum ikkiga bo'lingan)


def chip_half(event: int) -> int:
    """Chip yarim yilligi: 1 (GW1-19) yoki 2 (GW20-38)."""
    return 1 if event < SECOND_HALF_START else 2


def available_chips(chips_history: list[dict], event: int) -> list[str]:
    """Shu yarim yillikda hali ishlatilmagan chiplar.

    `entry/{id}/history/` dagi chips ro'yxati: [{"name": "bboost", "event": 1}, ...].
    Bir yarim yillikda ishlatilgan chip o'sha yarimlikda boshqa mavjud emas.
    """
    used = {
        c["name"] for c in (chips_history or [])
        if c.get("event") is not None and chip_half(c["event"]) == chip_half(event)
    }
    return [c for c in ALL_CHIPS if c not in used]


@dataclass
class ChipAdvice:
    chip: str
    event: int
    value: float           # taxminiy qo'shimcha ochko
    reason: str


def double_gameweeks(views, events: list[int]) -> dict[int, list[int]]:
    """event -> ikki marta o'ynaydigan jamoalar; bo'sh turlar ham shu yerdan ko'rinadi."""
    out: dict[int, list[int]] = {}
    for ev in events:
        teams = [tid for tid, per in views.items() if len(per.get(ev, [])) >= 2]
        if teams:
            out[ev] = teams
    return out


def blank_gameweeks(views, events: list[int]) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    for ev in events:
        teams = [tid for tid, per in views.items() if len(per.get(ev, [])) == 0]
        if teams:
            out[ev] = teams
    return out


def advise(
    squad: Squad,
    all_ev: list[PlayerEV],
    events: list[int],
    views,
    cfg: Config,
    available_chips: list[str] | None = None,
) -> list[ChipAdvice]:
    available = available_chips or ["wildcard", "bboost", "3xc", "freehit"]
    advice: list[ChipAdvice] = []
    dgw = double_gameweeks(views, events)
    bgw = blank_gameweeks(views, events)

    for ev in events:
        xi, bench, _, xi_ev = best_eleven(squad.players, ev)
        bench_ev = sum(p.ev.per_event.get(ev, 0.0) for p in bench)
        playing_xi = sum(1 for p in xi if p.ev.per_event.get(ev, 0.0) > 0.5)

        # Bench Boost — zaxira nechta ochko qo'shadi
        if "bboost" in available:
            reason = f"zaxira {len(bench)} o'yinchi, {bench_ev:.1f} EV"
            if ev in dgw:
                reason += f"; {len(dgw[ev])} jamoada DGW"
            advice.append(ChipAdvice("bboost", ev, round(bench_ev, 2), reason))

        # Triple Captain — eng yaxshi kapitanning qo'shimcha nusxasi
        if "3xc" in available and xi:
            best_cap = max(xi, key=lambda p: p.ev.per_event.get(ev, 0.0))
            val = best_cap.ev.per_event.get(ev, 0.0)
            fx = len(best_cap.ev.fixtures.get(ev, []))
            advice.append(
                ChipAdvice("3xc", ev, round(val, 2),
                           f"{best_cap.name} — {fx} ta o'yin, {val:.1f} EV")
            )

        # Free Hit — bo'sh turda yoki tarkib qulab tushganda
        budget = squad.value - BENCH_RESERVE
        if "freehit" in available:
            # 0.97 — bir haftalik ideal tarkib deyarli to'liq yig'iladi
            ideal = _ideal_xi_ev(all_ev, ev, budget) * 0.97
            gap = ideal - xi_ev
            reason = f"ideal 11 lik ≈{ideal:.1f} vs meniki {xi_ev:.1f}"
            if playing_xi < 11:
                reason += f"; faqat {playing_xi} o'yinchi o'ynaydi"
            blank_teams = set(bgw.get(ev, []))
            my_blank = sum(1 for p in squad.players if p.ev.profile.team in blank_teams)
            if my_blank:
                reason += f"; {my_blank} o'yinchimning jamoasi bu turda o'ynamaydi"
            advice.append(ChipAdvice("freehit", ev, round(gap, 2), reason))

        # Wildcard — gorizont bo'yicha tarkibning umumiy orqada qolishi
        if "wildcard" in available:
            # 0.88 — bitta 15 lik bilan har turda ideal 11 likni yig'ib bo'lmaydi,
            # shuning uchun yuqori chegarani pasaytiramiz
            ideal_sum = sum(_ideal_xi_ev(all_ev, e, budget) for e in events if e >= ev) * 0.88
            mine_sum = sum(best_eleven(squad.players, e)[3] for e in events if e >= ev)
            span = len([e for e in events if e >= ev])
            advice.append(
                ChipAdvice("wildcard", ev, round(ideal_sum - mine_sum, 2),
                           f"{span} tur bo'yicha jami farq, turiga ≈"
                           f"{(ideal_sum - mine_sum) / max(span, 1):.1f}")
            )

    advice.sort(key=lambda a: -a.value)
    return advice


BENCH_RESERVE = 17.0        # 4 ta arzon zaxira uchun taxminiy pul


def _ideal_xi_ev(all_ev: list[PlayerEV], event: int, budget: float) -> float:
    """Byudjet va "jamoadan 3 tadan ko'p emas" qoidasiga mos eng yaxshi 11 lik.

    Aniq yechim (knapsack) o'rniga ochko'z yaxshilash ishlatiladi: eng arzon
    qonuniy tarkibdan boshlanadi, so'ng har qadamda 1 pulga eng ko'p EV
    qo'shadigan almashtirish tanlanadi. Bu Free Hit / Wildcard salohiyatini
    real byudjet doirasida baholaydi.
    """
    pool: dict[int, list[PlayerEV]] = {1: [], 2: [], 3: [], 4: []}
    for p in all_ev:
        if p.profile.availability < 0.6 or p.per_event.get(event, 0.0) <= 0:
            continue
        pool[p.profile.position].append(p)
    for pos in pool:
        pool[pos].sort(key=lambda p: (p.profile.price, -p.per_event.get(event, 0.0)))

    best_total = 0.0
    for form in [(1, 3, 4, 3), (1, 3, 5, 2), (1, 4, 4, 2), (1, 4, 3, 3), (1, 5, 3, 2)]:
        need = dict(zip((1, 2, 3, 4), form))
        if any(len(pool[pos]) < n for pos, n in need.items()):
            continue

        squad: list[PlayerEV] = []
        teams: dict[int, int] = {}
        ok = True
        for pos, n in need.items():
            taken = 0
            for cand in pool[pos]:
                if taken >= n:
                    break
                if teams.get(cand.profile.team, 0) >= 3:
                    continue
                squad.append(cand)
                teams[cand.profile.team] = teams.get(cand.profile.team, 0) + 1
                taken += 1
            if taken < n:
                ok = False
        if not ok:
            continue

        spent = sum(p.profile.price for p in squad)
        for _ in range(40):                       # ochko'z yaxshilashlar
            remaining = budget - spent
            best_swap = None
            for i, cur in enumerate(squad):
                cur_ev = cur.per_event.get(event, 0.0)
                for cand in pool[cur.profile.position]:
                    if cand.element in {p.element for p in squad}:
                        continue
                    delta_cost = cand.profile.price - cur.profile.price
                    delta_ev = cand.per_event.get(event, 0.0) - cur_ev
                    if delta_ev <= 0 or delta_cost > remaining:
                        continue
                    new_teams = dict(teams)
                    new_teams[cur.profile.team] -= 1
                    if new_teams.get(cand.profile.team, 0) >= 3:
                        continue
                    score = delta_ev / max(delta_cost, 0.1)
                    if best_swap is None or score > best_swap[0]:
                        best_swap = (score, i, cand, delta_cost)
            if best_swap is None:
                break
            _, idx, cand, delta_cost = best_swap
            old = squad[idx]
            teams[old.profile.team] -= 1
            teams[cand.profile.team] = teams.get(cand.profile.team, 0) + 1
            squad[idx] = cand
            spent += delta_cost

        best_total = max(best_total, sum(p.per_event.get(event, 0.0) for p in squad))
    return round(best_total, 2)
