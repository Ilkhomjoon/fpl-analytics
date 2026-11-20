"""«Chiplar» — WC / BB / TC / FH ni qaysi turda ishlatish.

Har chip uchun gorizontdagi har bir tur baholanadi: chip qo'shadigan taxminiy
ochko. Qaror chegarasi — `WORTH_IT`: undan past bo'lsa, kutgan ma'qul, chunki
ikki o'yinli (DGW) tur kelishi mumkin.

Cheklov: gorizont `config.horizon` tur (odatda 5). Undan naridagi DGW/BGW bu
yerda ko'rinmaydi — FPL ularni odatda bir necha hafta oldin e'lon qiladi.
"""

from __future__ import annotations

from fplbrain import chips as chips_mod

from . import squadview

WORTH_IT = 8.0          # shundan ko'p ochko qo'shsa — ishlatishga arziydi
CHIP_ORDER = ["wildcard", "freehit", "bboost", "3xc"]


def build(client, cfg, entry_id: int, world=None) -> dict:
    world = world or squadview.World(client, cfg, entry_id)
    squad = world.squad()
    events = world.events
    available = squadview.chips_left(client, entry_id, squad, events[0])
    # `advise` bo'sh ro'yxatni "hammasi mavjud" deb o'qiydi — bo'sh bo'lsa chaqirilmaydi
    advice = (chips_mod.advise(squad, list(world.ev.values()), events, world.views,
                               cfg, available) if available else [])

    teams = {tid: r.short for tid, r in world.team_ratings.items()}
    doubles = chips_mod.double_gameweeks(world.views, events)
    blanks = chips_mod.blank_gameweeks(world.views, events)

    rows = []
    for chip in CHIP_ORDER:
        mine = sorted((a for a in advice if a.chip == chip), key=lambda a: a.event)
        if chip not in available:
            rows.append({"chip": chip, "name": chips_mod.CHIP_NAMES[chip],
                         "available": False, "by_event": [], "best": None,
                         "verdict": "bu yarim yillikda ishlatilgan"})
            continue
        best = max(mine, key=lambda a: a.value, default=None)
        verdict = "ma'lumot yo'q"
        if best:
            if best.value >= WORTH_IT:
                when = "shu turda" if best.event == events[0] else f"GW{best.event} da"
                verdict = f"{when} ishlatishga arziydi (+{best.value:.0f})"
            else:
                verdict = (f"hozircha kuting — eng yaxshi variant +{best.value:.0f}, "
                           f"chegara +{WORTH_IT:.0f}")
        rows.append({
            "chip": chip, "name": chips_mod.CHIP_NAMES[chip], "available": True,
            "by_event": [{"event": a.event, "value": a.value, "reason": a.reason}
                         for a in mine],
            "best": ({"event": best.event, "value": best.value, "reason": best.reason}
                     if best else None),
            "worth_it": bool(best and best.value >= WORTH_IT),
            "verdict": verdict,
        })

    return {
        "entry_id": entry_id, "event": events[0], "events": events,
        "authenticated": squad.authenticated,
        "half": chips_mod.chip_half(events[0]),
        "refresh_event": chips_mod.SECOND_HALF_START,
        "threshold": WORTH_IT,
        "chips": rows,
        "doubles": [{"event": ev, "teams": sorted(teams.get(t, "?") for t in tids)}
                    for ev, tids in sorted(doubles.items())],
        "blanks": [{"event": ev, "teams": sorted(teams.get(t, "?") for t in tids)}
                   for ev, tids in sorted(blanks.items())],
    }
