"""«H2H» — model Free Hit tarkibi ekspertlarning «GW Team» tarkibiga qarshi.

Ma'lumot `data/store/h2h/` dan o'qiladi (`tools/h2h.py freeze | import`).
Hisob ekspertlar jadvalidagi qoida bilan: 11 lik + kapitan, zaxirasiz —
ikkala tomon uchun bir xil.

Model tomoni ikki xil bo'lishi mumkin va bu **ochiq ko'rsatiladi**:

* `live` — deadline'dan oldin muzlatilgan tarkib (haqiqiy sinov);
* `backtest` — orqaga qarab tuzilgan (jarohat xabarlarisiz, ya'ni taxminiy).
"""

from __future__ import annotations

import logging

from fplbrain import h2h

log = logging.getLogger(__name__)


def _stats(client, gw: int) -> dict[int, tuple[int, int]]:
    if not hasattr(client, "event_live"):
        return {}
    try:
        live = client.event_live(gw)
    except Exception as exc:
        log.warning("GW%s natijalari olinmadi: %s", gw, exc)
        return {}
    return {e["id"]: (int(e["stats"].get("minutes") or 0),
                      int(e["stats"].get("total_points") or 0))
            for e in live.get("elements", [])}


def _side(data: dict | None, stats, positions, names) -> dict | None:
    lineup = h2h.Lineup.from_dict(data)
    if not lineup:
        return None
    result = h2h.score_lineup(lineup, stats, positions, autosubs=False) if stats else None
    return {
        "expected": lineup.expected or None,
        "points": result["points"] if result else None,
        "captain": lineup.names.get(lineup.captain) or names.get(lineup.captain, "—"),
        "players": [{
            "element": i,
            "name": lineup.names.get(i) or names.get(i, "?"),
            "pos": positions.get(i, 0),
            "captain": i == lineup.captain,
            "points": result["per_player"].get(i) if result else None,
        } for i in sorted(lineup.xi, key=lambda i: positions.get(i, 9))],
    }


def build(client, cfg) -> dict:
    if not hasattr(client, "event_live"):
        # Demo rejimi: soxta bootstrapdagi ID lar haqiqiy saqlangan tarkiblarga
        # mos kelmaydi — aralashtirib ko'rsatgandan ko'ra bo'sh ko'rsatgan to'g'ri.
        return {"rows": [], "upcoming": None, "enough": False, "demo": True,
                "rule": "11 lik + kapitan, zaxirasiz (ekspertlar jadvali qoidasi)",
                "totals": {"model": 0, "experts": 0, "n": 0, "wins": 0, "draws": 0,
                           "live_n": 0, "live_model": 0, "live_experts": 0}}
    bootstrap = client.bootstrap()
    positions = {e["id"]: e["element_type"] for e in bootstrap["elements"]}
    names = {e["id"]: e.get("web_name", "?") for e in bootstrap["elements"]}
    events = {e["id"]: e for e in bootstrap["events"]}

    rows = []
    totals = {"model": 0, "experts": 0, "n": 0, "wins": 0, "draws": 0,
              "live_n": 0, "live_model": 0, "live_experts": 0}
    for record in h2h.all_records(cfg.store_dir):
        gw = record["gw"]
        finished = bool(events.get(gw, {}).get("finished"))
        stats = _stats(client, gw) if finished else {}
        live = bool(record.get("model"))
        model = _side(record.get("model") or record.get("model_backtest"),
                      stats, positions, names)
        experts = _side(record.get("experts"), stats, positions, names)
        # Shaxsiy tanlovlar faqat yig'ma ko'rinishda: o'rtacha va modelning o'rni
        each = []
        if stats:
            for item in h2h.load_private(cfg.store_dir, gw):
                lineup = h2h.Lineup.from_dict(item)
                if lineup:
                    each.append(h2h.score_lineup(lineup, stats, positions,
                                                 autosubs=False)["points"])
        m = model["points"] if model else None
        e = experts["points"] if experts else None
        rows.append({
            "gw": gw, "finished": finished, "live": live,
            "model": model, "experts": experts,
            "diff": (m - e) if (m is not None and e is not None) else None,
            "experts_avg": round(sum(each) / len(each), 1) if each else None,
            "experts_best": max(each) if each else None,
            "model_rank": (1 + sum(1 for s in each if s > m)) if (each and m is not None) else None,
            "field": len(each) + 1 if each else None,
            "fpl_average": events.get(gw, {}).get("average_entry_score"),
        })
        if m is not None and e is not None:
            totals["n"] += 1
            totals["model"] += m
            totals["experts"] += e
            totals["wins"] += m > e
            totals["draws"] += m == e
            if live:
                totals["live_n"] += 1
                totals["live_model"] += m
                totals["live_experts"] += e

    upcoming = next((r for r in reversed(rows) if not r["finished"]), None)
    return {
        "rows": rows,
        "totals": totals,
        "upcoming": upcoming,
        "enough": totals["live_n"] >= 8,
        "rule": "11 lik + kapitan, zaxirasiz (ekspertlar jadvali qoidasi)",
    }
