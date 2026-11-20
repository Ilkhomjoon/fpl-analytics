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
import math

from fplbrain import bands, rivals
from fplbrain.ev import combine_distributions, points_distribution
from fplbrain.squad import SquadPlayer, best_eleven
from fplbrain.transfers import best_move_for, evaluate_moves

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


# ------------------------------------------------------------ bir raqibga qarshi
DUEL_MOVES = 3
EDGE_PERSISTENCE = 0.5      # gorizontdan keyin bugungi ustunlikning qancha qismi saqlanadi


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _lineup(elements: list[int], ev_by_element: dict, event: int):
    """15 likdan eng yaxshi 11 lik va kapitan: (o'yinchi → ulush, kutilayotgan ochko)."""
    players = [SquadPlayer(ev=ev_by_element[el], purchase_price=0.0, selling_price=0.0)
               for el in elements if el in ev_by_element]
    if len(players) < 11:
        return {}, 0.0
    xi, _, _, xi_ev = best_eleven(players, event)
    captain = max(xi, key=lambda p: p.ev.per_event.get(event, 0.0), default=None)
    exposure = {p.element: 1.0 for p in xi}
    if captain:
        exposure[captain.element] = 2.0
    return exposure, xi_ev + (captain.ev.per_event.get(event, 0.0) if captain else 0.0)


def _variance(pev, event: int) -> float:
    fixtures = pev.fixtures.get(event, [])
    if not fixtures:
        return 0.0
    dist = combine_distributions([points_distribution(f.inputs) for f in fixtures])
    mean = dist.mean()
    return sum(p * (k - mean) ** 2 for k, p in dist.pmf.items())


def duel(client, cfg, entry_id: int, rival_id: int, world=None) -> dict:
    """Bitta raqibga qarshi: farq, kimda nima bor, quvib yetish ehtimoli va reja.

    Ehtimollar — **taxminiy**: raqib tarkibini o'zgartirmaydi deb olinadi (kelgusi
    tur tarkiblari yopiq), tur natijalari esa bir-biridan mustaqil va normal
    taqsimlangan deb. Umumiy o'yinchilar hisobdan chiqib ketadi: ikkalangizda
    ham bor o'yinchi qancha ochko olmasin, orangizdagi farq o'zgarmaydi —
    farqni faqat **farq qiladigan** o'yinchilar hal qiladi.
    """
    world = world or squadview.World(client, cfg, entry_id)
    event, picks_event, events = world.next_event, world.picks_event, world.events
    if rival_id == entry_id:
        return {"error": "Bu sizning jamoangiz."}

    rival_picks = (client.entry_picks(rival_id, picks_event) or {}).get("picks") or []
    if not rival_picks:
        return {"error": "Raqib tarkibi olinmadi.",
                "hint": "U shu turda o'ynamagan yoki FPL javob bermadi."}
    his = [p["element"] for p in rival_picks]
    world.deepen(his)                       # raqib o'yinchilari ham batafsil baholansin
    squad = world.squad()
    mine = [p.element for p in squad.players]

    def info(eid: int) -> dict:
        try:
            return client.entry(eid) or {}
        except Exception as exc:
            log.warning("jamoa %s olinmadi: %s", eid, exc)
            return {}

    me, him = info(entry_id), info(rival_id)
    my_total, his_total = me.get("summary_overall_points"), him.get("summary_overall_points")
    gap = (his_total - my_total) if (my_total is not None and his_total is not None) else None

    # ---- gorizont bo'yicha kutilma: har tur uchun ikkala tomon eng yaxshi 11 ligini qo'yadi
    per_event = []
    for ev in events:
        _, my_ev = _lineup(mine, world.ev, ev)
        _, his_ev = _lineup(his, world.ev, ev)
        per_event.append({"event": ev, "mine": round(my_ev, 1), "his": round(his_ev, 1),
                          "edge": round(my_ev - his_ev, 1)})
    edge_next = per_event[0]["edge"] if per_event else 0.0
    edge_avg = (sum(e["edge"] for e in per_event) / len(per_event)) if per_event else 0.0

    # ---- farq qiladigan o'yinchilar va tur ichidagi tebranish
    my_x, _ = _lineup(mine, world.ev, event)
    his_x, _ = _lineup(his, world.ev, event)
    variance = 0.0
    for el in set(my_x) | set(his_x):
        delta = my_x.get(el, 0.0) - his_x.get(el, 0.0)
        if delta and el in world.ev:
            variance += delta * delta * _variance(world.ev[el], event)
    sd = math.sqrt(variance)

    remaining = max(1, bands.SEASON_EVENTS - picks_event)

    def ahead_after(k: int) -> float | None:
        """`k` turdan keyin oldinda bo'lish ehtimoli (0..100).

        Gorizontdan naridagi turlarda ustunlikning faqat `EDGE_PERSISTENCE`
        qismi saqlanadi deb olinadi: tarkiblar o'zgaradi, raqib ham transfer
        qiladi — bugungi 5 turlik ustunlikni 28 turga cho'zib bo'lmaydi.
        """
        if gap is None or sd <= 0:
            return None
        near = min(k, len(events))
        expected = near * edge_avg + (k - near) * edge_avg * EDGE_PERSISTENCE
        return round(100 * _normal_cdf((expected - gap) / (sd * math.sqrt(k))))

    def row(el: int, exposure: dict) -> dict:
        pev = world.ev[el]
        return {
            "element": el, "name": pev.profile.name, "pos": pev.profile.position,
            "pos_short": squadview.POS_SHORT.get(pev.profile.position, "?"),
            "team": world.team_ratings[pev.profile.team].short,
            "ev": round(pev.per_event.get(event, 0.0), 2),
            "ev_horizon": round(pev.horizon_ev, 1),
            "share": exposure.get(el, 0.0),          # 0 — zaxirada, 1 — 11 likda, 2 — kapitan
        }

    only_mine = sorted((row(el, my_x) for el in set(mine) - set(his) if el in world.ev),
                       key=lambda r: -r["ev_horizon"])
    only_his = sorted((row(el, his_x) for el in set(his) - set(mine) if el in world.ev),
                      key=lambda r: -r["ev_horizon"])

    # ---- reja: oldinda bo'lsangiz — yoping, ortda bo'lsangiz — farq yarating
    behind = gap is not None and gap > 0
    # Har ro'yxatda bir o'yinchi bir marta sotiladi — takliflar birga bajarsa bo'ladigan bo'lsin
    cover = []
    for target in only_his[:8]:
        move, short = best_move_for(squad, world.ev[target["element"]], events, cfg)
        if (move and move.gain > 0
                and not any(c["out"] == move.out_players[0].name for c in cover)):
            cover.append({"in": target["name"], "out": move.out_players[0].name,
                          "gain": move.gain, "hit": move.hit, "bank_after": move.bank_after})
        if len(cover) >= DUEL_MOVES:
            break
    differ = []
    his_set = set(his)
    for move in evaluate_moves(squad, list(world.ev.values()), events, cfg, max_transfers=1):
        target = move.in_players[0]
        if target.element in his_set or move.gain <= 0:
            continue
        if any(d["in"] == target.profile.name or d["out"] == move.out_players[0].name
               for d in differ):
            continue
        differ.append({"in": target.profile.name, "out": move.out_players[0].name,
                       "gain": move.gain, "hit": move.hit, "bank_after": move.bank_after})
        if len(differ) >= DUEL_MOVES:
            break

    need = round(gap / remaining, 1) if behind else 0.0
    if gap is None:
        verdict = "Ochkolar ma'lum emas — faqat tarkiblar solishtirildi."
    elif not behind:
        verdict = (f"Siz {-gap} ochko oldindasiz. U bilan farqni kamaytirsangiz — ya'ni undagi "
                   "kuchli o'yinchilarni olsangiz — ustunligingiz xavfsizroq bo'ladi."
                   if gap < 0 else "Ochkolaringiz teng.")
    elif edge_avg > 0:
        turns = math.ceil(gap / edge_avg)
        verdict = (f"{gap} ochko ortdasiz. Hozirgi tarkiblar bilan turiga o'rtacha "
                   f"{edge_avg:+.1f} ochko yutyapsiz — o'rtacha hisobda ~{turns} turda yetasiz"
                   + (" (mavsum tugaguncha ulgurmaysiz)." if turns > remaining else "."))
    else:
        verdict = (f"{gap} ochko ortdasiz va hozirgi tarkiblar bilan turiga {edge_avg:+.1f} "
                   "ochko yo'qotyapsiz. Bir xil o'yinchilar bilan quvib yetib bo'lmaydi — "
                   "unda yo'q, kuchli o'yinchilar kerak.")

    return {
        "entry_id": entry_id, "event": event, "picks_event": picks_event,
        "rival": {"entry": rival_id, "name": him.get("name", "?"),
                  "manager": " ".join(x for x in (him.get("player_first_name"),
                                                  him.get("player_last_name")) if x),
                  "total": his_total},
        "me": {"name": me.get("name", "?"), "total": my_total},
        "gap": gap, "behind": behind, "remaining": remaining, "need_per_event": need,
        "shared": len(set(mine) & set(his)),
        "per_event": per_event, "edge_next": edge_next, "edge_avg": round(edge_avg, 1),
        "sd": round(sd, 1),
        "win_next": (round(100 * _normal_cdf(edge_next / sd)) if sd > 0 else None),
        "ahead": {"horizon": ahead_after(len(events)), "season": ahead_after(remaining),
                  "horizon_events": len(events)},
        "only_mine": only_mine, "only_his": only_his,
        "plan": {"mode": "chase" if behind else "protect", "cover": cover, "differ": differ},
        "verdict": verdict,
    }


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
