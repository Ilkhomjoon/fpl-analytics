"""«Raqiblar» — mini-liga: kim oldinda, kimda nima bor, qayerda farq qilasiz.

Uch savolga javob beradi:

* **Xavf** — raqiblarda ko'p, sizda yo'q o'yinchilar: ular ochko olsa, siz
  ortda qolasiz;
* **Imkoniyat** — sizda bor, raqiblarda kam: ular ochko olsa, oldinga o'tasiz;
* **Har raqib bo'yicha** — orada necha ochko, nechta o'yinchi umumiy va
  kelgusi turda kimdan qancha kutilmoqda.

Raqiblar tarkibi **o'tgan deadline** holatida: kelgusi tur tarkiblari FPL da
deadline'gacha yopiq. "Kutilayotgan ochko" — o'sha tarkib o'zgarmasa.
"""

from __future__ import annotations

import logging

from fplbrain import rivals

from . import squadview

log = logging.getLogger(__name__)

MAX_RIVALS = 50
NEIGHBOUR_SPAN = 7        # katta ligada: o'rningizdan shuncha tepa va pastdagilar


def leagues_of(client, entry_id: int) -> list[dict]:
    """Menejerning klassik ligalari — avval xususiylari (do'stlar ligasi)."""
    try:
        classic = (client.entry(entry_id).get("leagues") or {}).get("classic") or []
    except Exception as exc:
        log.warning("ligalar olinmadi: %s", exc)
        return []
    rows = [{"id": lg["id"], "name": lg.get("name", f"Liga {lg['id']}"),
             "rank": lg.get("entry_rank"), "private": lg.get("league_type") == "x"}
            for lg in classic if lg.get("id")]
    rows.sort(key=lambda r: (not r["private"], r["name"].lower()))
    return rows


def _neighbours(client, cfg, league_id: int, entry_id: int, leagues: list[dict],
                event: int, skip: set[int], span: int = NEIGHBOUR_SPAN) -> list:
    """Ligadagi o'rningizdan `span` ta tepada va pastdagi menejerlar (o'zingiz bilan)."""
    my_rank = next((lg.get("rank") for lg in leagues if lg["id"] == league_id), None)
    if not my_rank or not hasattr(client, "league_page_for_rank"):
        return []
    try:
        data = client.league_page_for_rank(league_id, my_rank)
    except Exception as exc:
        log.warning("liga sahifasi olinmadi: %s", exc)
        return []
    rows = (data.get("standings") or {}).get("results", [])
    near = [r for r in rows
            if abs((r.get("rank") or 0) - my_rank) <= span or r.get("entry") == entry_id]
    entries = [e for e in rivals._entries_from_standings(near) if e.entry not in skip]
    if not entries:
        return []
    _, filled = rivals.fetch_group(client, cfg, entries, event, "atrofdagilar")
    return filled


def _projected(picks: list[dict], ev_by_element: dict, event: int) -> float:
    """Shu tarkib o'zgarmasa kelgusi turda kutilayotgan ochko (11 lik, kapitan ikkilanadi)."""
    total = 0.0
    for p in picks:
        if p.get("position", 16) > 11:
            continue
        pev = ev_by_element.get(p["element"])
        if pev:
            total += pev.per_event.get(event, 0.0) * max(1, p.get("multiplier") or 1)
    return total


def build(client, cfg, entry_id: int, league_id: int | None = None, world=None) -> dict:
    world = world or squadview.World(client, cfg, entry_id)
    squad = world.squad()
    event, picks_event = world.next_event, world.picks_event
    leagues = leagues_of(client, entry_id)

    known = {lg["id"] for lg in leagues}
    if not league_id:
        preferred = [i for i in (getattr(cfg, "mini_league_ids", None) or [])
                     if i in known or not known]
        league_id = (preferred[0] if preferred
                     else next((lg["id"] for lg in leagues if lg["private"]), None)
                     or (leagues[0]["id"] if leagues else None))
    if not league_id:
        return {"error": "Liga topilmadi.",
                "hint": "config.yaml dagi mini_league_ids ga liga ID sini yozing.",
                "leagues": leagues}

    stats, managers, name = rivals.mini_league(client, cfg, league_id, picks_event)
    managers = managers[:MAX_RIVALS]
    # Katta ligada siz birinchi sahifada bo'lmasligingiz mumkin. Unda yetakchilar
    # (xavf/imkoniyat hisobi ular bo'yicha) yoniga **o'rningiz atrofidagilar**
    # qo'shiladi — haqiqiy raqiblaringiz aynan shular.
    if not any(m.entry == entry_id for m in managers):
        managers += _neighbours(client, cfg, league_id, entry_id, leagues, picks_event,
                                {m.entry for m in managers})
    mine = {p.element for p in squad.players}
    my_captain = next((p.element for p in squad.players if p.is_captain), None)
    comparison = rivals.compare(squad, stats, my_captain, top=8)
    gain, loss = rivals.swing_estimate(comparison, world.ev, event)

    def player(element: int, eo: float | None = None) -> dict:
        pev = world.ev.get(element)
        raw = world.by_id.get(element, {})
        row = {
            "element": element,
            "name": pev.profile.name if pev else raw.get("web_name", "?"),
            "pos": pev.profile.position if pev else raw.get("element_type", 0),
            "pos_short": squadview.POS_SHORT.get(
                pev.profile.position if pev else raw.get("element_type", 0), "?"),
            "team": (world.team_ratings[pev.profile.team].short if pev else ""),
            "ev": round(pev.per_event.get(event, 0.0), 2) if pev else 0.0,
        }
        if eo is not None:
            row["eo"] = round(eo, 0)
        return row

    me = next((m for m in managers if m.entry == entry_id), None)
    my_total = me.total if me else None
    my_projected = _projected(me.picks, world.ev, event) if me else None

    rows = []
    for m in managers:
        theirs = {p["element"] for p in m.picks}
        only = sorted((el for el in theirs - mine if el in world.ev),
                      key=lambda el: -world.ev[el].per_event.get(event, 0.0))
        projected = _projected(m.picks, world.ev, event)
        rows.append({
            "entry": m.entry, "name": m.name, "manager": m.player_name,
            "rank": m.rank, "total": m.total,
            "gap": (m.total - my_total) if (m.total is not None and my_total is not None) else None,
            "is_me": m.entry == entry_id,
            "captain": player(m.captain)["name"] if m.captain else "—",
            "chip": m.chip or "",
            "shared": len(theirs & mine),
            "projected": round(projected, 1),
            "edge": (round(my_projected - projected, 1)
                     if my_projected is not None and m.entry != entry_id else None),
            "differs": [player(el) for el in only[:3]],
        })
    rows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0))

    return {
        "entry_id": entry_id, "event": event, "picks_event": picks_event,
        "league": {"id": league_id, "name": name, "size": stats.size},
        "leagues": leagues,
        "me": {"rank": me.rank if me else None, "total": my_total,
               "projected": round(my_projected, 1) if my_projected is not None else None,
               "in_league": me is not None},
        # Yetakchilar va atrofdagilar orasida uzilish bormi (katta liga)
        "split": bool(me and me.rank and me.rank > MAX_RIVALS),
        "leader_gap": ((rows[0]["total"] - my_total)
                       if rows and my_total is not None and rows[0]["total"] is not None else None),
        "threats": [player(el, eo) for el, eo in comparison.threats],
        "differentials": [player(el, eo) for el, eo in comparison.differentials],
        "captains": [dict(player(el), share=round(pct, 0))
                     for el, pct in comparison.captain_split],
        "my_captain_share": round(comparison.my_captain_eo, 0),
        "swing": {"gain": gain, "loss": loss},
        "chips_played": stats.chips,
        "managers": rows,
    }
