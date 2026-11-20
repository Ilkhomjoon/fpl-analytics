"""«Jamoa tuzish» — noldan 15 lik va uni ekspertlar bilan solishtirish.

Ikki maqsad:

1. **Wildcard** — butun jamoani qaytadan tuzish kerak bo'lganda;
2. **H2H sinov** — algoritm tuzgan jamoani haqiqiy ekspertlar tuzgan jamoaga
   qarshi qo'yish. Bir xil byudjet, bir xil qoidalar, bir xil tur.

Ikkinchisi model uchun eng halol tekshiruv. Shuning uchun natija shunchaki
o'yinchilar ro'yxati emas — **taqqoslashga yaroqli** shaklda beriladi:
qoidalarga muvofiqligi tekshirilgan, kapitani belgilangan, kutilayotgan
ochkosi yozilgan. Tur o'ynalgandan keyin haqiqiy natijani shu bilan yonma-yon
qo'yish mumkin bo'ladi.
"""

from __future__ import annotations

import logging

from fplbrain import builder as builder_mod

from . import squadview

log = logging.getLogger(__name__)

POS_SHORT = squadview.POS_SHORT
# Nomzodlar uchun batafsil tarix — faqat eng istiqbolliga, tezlik uchun
DEEPEN_PER_POSITION = 12


def _row(p, in_xi: bool, captain_id: int, order: int = 0,
         teams: dict | None = None) -> dict:
    pr = p.ev.profile
    return {
        "element": p.element,
        "name": pr.name,
        "team": pr.team,
        # Qisqa nom shu yerdan keladi — sahifa boshqa bo'limga bog'liq bo'lmasin
        "team_short": (teams or {}).get(pr.team, ""),
        "pos": pr.position,
        "pos_short": POS_SHORT.get(pr.position, "?"),
        "price": round(pr.price, 1),
        "ev": round(p.ev.next_ev, 2),
        "ev_horizon": round(p.ev.horizon_ev, 2),
        "outlook": squadview.outlook(p.ev, next(iter(p.ev.per_event), 0)),
        "p_start": round(pr.p_start * 100, 0),
        "ownership": pr.ownership,
        "form": squadview._num(getattr(pr, "form", 0)),
        "status": pr.status,
        "in_xi": in_xi,
        "is_captain": p.element == captain_id,
        "bench_order": order,
    }


def _deepen_candidates(world) -> list[int]:
    """Eng istiqbolli nomzodlar uchun batafsil tarix.

    Jamoa noldan tuzilayotgani uchun "mening 15 tam" degan tushuncha yo'q —
    nomzodlar butun ro'yxatdan keladi. Hammasi uchun tarix yuklash 600+
    so'rov bo'lardi, shuning uchun har pozitsiyadan eng yaxshilari olinadi.
    """
    by_pos: dict[int, list] = {}
    for pev in world.ev.values():
        pr = pev.profile
        if pr.availability < 0.7 or pr.p_start < 0.45:
            continue
        by_pos.setdefault(pr.position, []).append(pev)
    out: list[int] = []
    for items in by_pos.values():
        items.sort(key=lambda p: -p.horizon_ev)
        out += [p.element for p in items[:DEEPEN_PER_POSITION]]
        # arzon zaxira o'yinchilari ham kerak — 15 likning 4 tasi shular
        items.sort(key=lambda p: p.profile.price)
        out += [p.element for p in items[:4]]
    return out


def build(client, cfg, entry_id: int = 0, budget: float | None = None,
          world=None) -> dict:
    """Byudjet ichida eng yaxshi 15 lik. `budget` berilmasa — 100.0m."""
    budget = float(budget or getattr(cfg, "draft_budget", 0)
                   or builder_mod.DEFAULT_BUDGET)
    world = world or squadview.World(client, cfg, entry_id or 1)
    world.deepen(_deepen_candidates(world))

    built = builder_mod.build_squad(
        list(world.ev.values()), world.events, cfg, budget=budget)
    if built is None:
        return {"error": "Byudjetga sig'adigan qonuniy 15 lik topilmadi.",
                "budget": budget}

    teams = {t["id"]: t["short_name"] for t in world.bootstrap.get("teams", [])}
    cap_id = built.captain.element if built.captain else 0
    order = {p.element: i + 1 for i, p in enumerate(built.bench)}
    xi_ids = {p.element for p in built.xi}
    rows = [_row(p, p.element in xi_ids, cap_id, order.get(p.element, 0), teams)
            for p in built.players]
    rows.sort(key=lambda r: (not r["in_xi"], r["bench_order"], r["pos"], -r["ev"]))

    counts = built.team_counts
    return {
        "event": world.next_event,
        "budget": budget,
        "cost": built.cost,
        "bank": built.bank,
        "formation": f"{built.formation[1]}-{built.formation[2]}-{built.formation[3]}",
        "xi_ev": built.xi_ev,
        # H2H uchun asosiy raqam: 11 lik + kapitan (kapitan ikkilanadi)
        "expected_points": round(
            built.xi_ev + (built.captain.ev.per_event.get(world.next_event, 0.0)
                           if built.captain else 0.0), 1),
        "captain": built.captain.name if built.captain else "",
        "objective": built.objective,
        "legal": built.legal(budget),
        "players": rows,
        "clubs": sorted(
            ({"team": teams.get(tid, str(tid)), "count": n}
             for tid, n in counts.items() if n > 1),
            key=lambda r: -r["count"]),
        "search": {"passes": built.passes, "considered": built.considered},
    }
