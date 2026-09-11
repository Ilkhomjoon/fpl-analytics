"""«Sur'at» — mavsum maqsadi va jamoa ko'rsatkichlari.

Bo'lim ikki savolga javob beradi:

1. **Maqsadga nisbatan qayerdaman?** — o'lchagich, reja belgisi va qolgan
   turlardagi talab;
2. **Jamoam qanday ishlayapti?** — o'rtacha menejerdan farq, minuslarga
   ketgan ochko, zaxirada qolgani, o'rin harakati, barqarorlik.

Ikkinchisi muhim, chunki maqsad yolg'iz o'zi **nimani tuzatish kerakligini**
aytmaydi. "191 ochko ortdasiz" — bu muammo. "Minuslarga 24 ochko ketdi va
zaxirada 51 ochko qoldi" — bu **sabab**.
"""

from __future__ import annotations

import logging

from fplbrain import pace as pace_mod

log = logging.getLogger(__name__)


def _event_row(e) -> dict:
    return {
        "event": e.event,
        "points": e.points,
        "hit": e.hit,
        "net": e.net,
        "total": e.total,
        "rank": e.rank,
        "gw_rank": e.gw_rank,
        "bench": e.bench,
        "transfers": e.transfers,
        "value": e.value,
        "bank": e.bank,
        "average": e.average,
        "vs_average": e.vs_average,
        "chip": e.chip,
    }


def build(client, cfg, entry_id: int) -> dict:
    history = client.entry_history(entry_id)
    try:
        bootstrap = client.bootstrap()
    except Exception as exc:                 # o'rtacha bo'lmasa ham ishlaydi
        log.warning("bootstrap olinmadi: %s", exc)
        bootstrap = {}

    target = int(getattr(cfg, "season_target", 0) or pace_mod.DEFAULT_TARGET)
    p = pace_mod.from_history(history, target=target, bootstrap=bootstrap)
    matn, holat = p.grade()

    leader = pace_mod.leader_pace(client, cfg)
    lead_gap = round(p.average - leader["average"], 1) if (leader and p.played) else None
    # Yig'indi bo'yicha farq — "u mendan qancha oldinda" degan savolga javob
    lead_total_gap = (p.points - leader["points"]) if leader else None

    needed = p.needed_per_event
    best, worst = p.best, p.worst
    return {
        "entry_id": entry_id,
        "target": target,
        "points": p.points,
        "played": p.played,
        "total_events": p.total_events,
        "per_event_needed": round(p.per_event_needed, 1),
        "on_pace_points": round(p.on_pace_points, 0),
        "delta": round(p.delta, 0),
        "ratio": round(p.ratio, 3),
        "average": round(p.average, 1),
        "projected": round(p.projected, 0),
        "remaining_events": p.remaining_events,
        # Cheksiz qiymat JSON da yaroqsiz — maqsad qo'ldan ketganini `None` aytadi
        "needed_per_event": (None if needed == float("inf") else round(needed, 1)),
        "progress": round(p.progress, 4),
        "season_progress": round(p.season_progress, 4),
        "grade": matn,
        "status": holat,
        # --- jamoa ko'rsatkichlari ---
        "rank": p.rank,
        "best_rank": p.best_rank,
        "value": p.value,
        "hits_paid": p.hits_paid,
        "bench_lost": p.bench_lost,
        "transfers_made": p.transfers_made,
        "vs_average_total": p.vs_average_total,
        "beat_average": p.beat_average,
        "consistency": round(p.consistency, 1),
        "best": _event_row(best) if best else None,
        "worst": _event_row(worst) if worst else None,
        # Barcha turlar — grafiklar shu ro'yxatdan quriladi
        "events": [_event_row(e) for e in p.events],
        "leader": leader,
        "leader_gap": lead_gap,
        "leader_total_gap": lead_total_gap,
    }
