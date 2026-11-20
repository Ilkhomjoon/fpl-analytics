"""«O'rnim» — menejerning o'rniga mos maslahat.

Bitta savolga javob beradi: **mening o'rnimdagi raqiblarga nisbatan nima
qilishim kerak?** Asos — o'rin oralig'idagi 40 ta jamoa namunasi (`bands`).

Qismlar:

* **Xavf va imkoniyat** — har o'yinchi uchun "tebranish": u ochko olsa, siz
  raqiblarga nisbatan qancha yutasiz yoki yo'qotasiz;
* **O'rin prognozi** — model nazarida shu turda raqiblardan necha ochko
  oldindasiz va bu taxminan nechta o'ringa teng;
* **Xavf darajasi** — himoya / muvozanat / quvish, mavsum bosqichiga qarab;
* **O'ringa mos kapitan** — raqiblar tanlovi shu oraliqdan olinadi;
* **Chiplar** — atrofdagilarning qanchasi qaysi chipni ishlatib bo'lgan.

Halollik uchun: raqiblar tarkibi o'tgan deadline holatida; "kutilayotgan
ochko" hammaga bir xil qoida bilan hisoblanadi — har kim o'z 15 ligidan eng
yaxshi 11 lik va kapitanni qo'yadi deb olinadi.
"""

from __future__ import annotations

import logging

from fplbrain import bands, captain as captain_mod, chips as chips_mod
from fplbrain.squad import SquadPlayer, best_eleven
from fplbrain.transfers import best_move_for

from . import squadview

log = logging.getLogger(__name__)

LIST_SIZE = 8
DEEPEN_POPULAR = 24          # raqiblarda eng ko'p uchraydigan shuncha o'yinchi chuqur baholanadi
DIFFERENTIAL_EO = 15.0       # shundan kam kapitanlik ulushi — "farq qiluvchi"
POPULAR_EO = 30.0            # shundan ko'p — "ommaviy"


def _best_projection(elements: list[int], ev_by_element: dict, event: int) -> float | None:
    """15 likdan eng yaxshi 11 lik + kapitan — model bahosi bo'yicha."""
    players = [SquadPlayer(ev=ev_by_element[el], purchase_price=0.0, selling_price=0.0)
               for el in elements if el in ev_by_element]
    if len(players) < 11:
        return None
    try:
        xi, _, _, xi_ev = best_eleven(players, event)
    except Exception:
        return None
    captain = max((p.ev.per_event.get(event, 0.0) for p in xi), default=0.0)
    return xi_ev + captain


def _captain_pick(options, risk: dict) -> tuple[dict | None, str]:
    """O'ringa mos kapitan: EV bo'yicha eng yaxshisi, yoki ruxsat etilgan
    chegarada farq qiluvchi variant (faqat quvish/muvozanat rejimida)."""
    if not options:
        return None, ""
    best = max(options, key=lambda o: o["ev"])
    if risk["sacrifice"] <= 0 or best["eo"] < POPULAR_EO:
        why = ("eng yuqori kutilayotgan ochko" if best["eo"] < POPULAR_EO
               else "ommaviy tanlov — o'rinni saqlaydi")
        return best, why
    alternatives = [o for o in options
                    if o["element"] != best["element"] and o["eo"] <= DIFFERENTIAL_EO
                    and best["ev"] - o["ev"] <= risk["sacrifice"]]
    if not alternatives:
        return best, (f"farq qiluvchi variantlar {risk['sacrifice']:.1f} ochkodan ko'proq "
                      "yo'qotadi — hozircha arzimaydi")
    pick = max(alternatives, key=lambda o: o["p10"])
    return pick, (f"{best['name']} dan atigi {best['ev'] - pick['ev']:.1f} ochko past, lekin "
                  f"raqiblarning {pick['eo']:.0f}% ida kapitan — tushsa, o'rin ko'tariladi")


def build(client, cfg, entry_id: int, world=None) -> dict:
    world = world or squadview.World(client, cfg, entry_id)
    squad = world.squad()
    event, picks_event = world.next_event, world.picks_event

    entry = {}
    try:
        entry = client.entry(entry_id) or {}
    except Exception as exc:
        log.warning("jamoa ma'lumoti olinmadi: %s", exc)
    rank = entry.get("summary_overall_rank")
    my_total = entry.get("summary_overall_points")
    total_players = world.bootstrap.get("total_players") or entry.get("player_count") or 0
    if not rank or not total_players:
        return {"error": "Umumiy o'rin noma'lum.",
                "hint": "Mavsum boshlanmagan yoki jamoa hali o'ynamagan bo'lishi mumkin."}

    band = bands.band_for(rank, total_players)
    sample = bands.load_band(client, cfg, band, picks_event, event)
    if not sample.get("size"):
        return {"error": "Raqiblar namunasi olinmadi.",
                "hint": "FPL javob bermadi — birozdan keyin qayta urining."}
    eo = bands.effective_ownership(sample)
    risk = bands.risk_advice(rank, total_players, event)
    # Raqiblarda eng ko'p uchraydigan o'yinchilar batafsil tarix bilan baholanadi:
    # xavf ro'yxati va "qanday olish" hisobi aynan shularga tayanadi.
    popular = sorted(eo, key=lambda el: -eo[el])[:DEEPEN_POPULAR]
    world.deepen(popular)
    squad = world.squad()

    # ---- mening tarkibim: model tavsiya etgan 11 lik va kapitan
    xi, _, _, xi_ev = best_eleven(squad.players, event)
    captain = max(xi, key=lambda p: p.ev.per_event.get(event, 0.0), default=None)
    exposure = {p.element: 1.0 for p in xi}
    if captain:
        exposure[captain.element] = 2.0
    mine = {p.element for p in squad.players}
    my_projection = xi_ev + (captain.ev.per_event.get(event, 0.0) if captain else 0.0)

    # ---- raqiblar: har biri o'z 15 ligidan eng yaxshisini qo'yadi deb olinadi
    projections = [x for x in (
        _best_projection([p["e"] for p in s], world.ev, event) for s in sample["squads"])
        if x is not None]
    field = sum(projections) / len(projections) if projections else 0.0
    edge = my_projection - field if projections else 0.0
    beat = (sum(1 for x in projections if my_projection > x) / len(projections)
            if projections else 0.0)

    anchors = [tuple(a) for a in sample.get("anchors", [])]
    if my_total:
        anchors.append((rank, my_total))
    density = bands.rank_density(anchors, rank)
    after = bands.projected_rank(rank, edge, density, total_players)

    # ---- xavf va imkoniyat: tebranish = (mening ulushim − raqiblarniki) × EV
    def row(element: int) -> dict:
        pev = world.ev[element]
        ev_points = pev.per_event.get(event, 0.0)
        share = eo.get(element, 0.0)
        return {
            "element": element, "name": pev.profile.name, "pos": pev.profile.position,
            "pos_short": squadview.POS_SHORT.get(pev.profile.position, "?"),
            "team": world.team_ratings[pev.profile.team].short,
            "ev": round(ev_points, 2), "eo": round(share * 100),
            "mine": element in mine, "in_xi": element in exposure,
            "swing": round((exposure.get(element, 0.0) - share) * ev_points, 2),
        }

    rows = [row(el) for el in set(eo) | set(exposure) if el in world.ev]
    threats = sorted((r for r in rows if not r["mine"] and r["swing"] < 0),
                     key=lambda r: r["swing"])[:LIST_SIZE]
    chances = sorted((r for r in rows if r["in_xi"] and r["swing"] > 0),
                     key=lambda r: -r["swing"])[:LIST_SIZE]

    # ---- har xavf uchun: uni qanday olish mumkin (bitta transfer bilan)
    for threat in threats:
        move, short = best_move_for(squad, world.ev[threat["element"]], world.events, cfg)
        if move:
            out = move.out_players[0]
            threat["how"] = {
                "out": out.name, "gain": move.gain, "raw_gain": move.raw_gain,
                "hit": move.hit, "bank_after": move.bank_after,
                "worth_it": move.gain > 0,
            }
        elif short > 0:
            threat["how"] = {"short": short}
        else:
            threat["how"] = None             # klub chegarasi (bitta jamoadan 3 ta)

    # ---- oraliq chegaralari: yuqoriga chiqish va pastga tushish uchun ochko
    def total_at(target: int) -> int | None:
        try:
            page = client.league_page_for_rank(bands.OVERALL_LEAGUE, target)
            first = ((page.get("standings") or {}).get("results") or [{}])[0]
            return first.get("total")
        except Exception:
            return None

    remaining = max(1, bands.SEASON_EVENTS - picks_event)
    climb = None
    if band.low > 1 and my_total:
        need = total_at(band.low)
        if need is not None:
            gap = max(0, need - my_total)
            climb = {"rank": band.low, "points": gap, "per_event": round(gap / remaining, 1)}
    cushion = None
    if band.high < total_players and my_total:
        floor = total_at(band.high)
        if floor is not None:
            cushion = {"rank": band.high, "points": max(0, my_total - floor)}

    # ---- kapitan: raqiblar tanlovi shu oraliqdan
    captaincy = {int(k): v for k, v in sample.get("captaincy", {}).items()}
    strategy = {"protect": "safe", "balanced": "balanced", "chase": "aggressive"}[risk["mode"]]
    options = []
    for o in captain_mod.rank_captains(squad, event, captaincy, strategy, limit=5,
                                       ev_by_element=world.ev):
        profile = o.player.ev.profile
        options.append({
            "element": o.player.element, "name": o.name, "pos": profile.position,
            "pos_short": squadview.POS_SHORT.get(profile.position, "?"),
            "team": world.team_ratings[profile.team].short,
            "ev": o.ev, "p10": round(o.p10 * 100), "eo": o.eo,
        })
    pick, why = _captain_pick(options, risk)

    # ---- chiplar: atrofdagilar nimani ishlatib bo'lgan
    available = set(squadview.chips_left(client, entry_id, squad, event))
    chip_rows = [{
        "chip": chip, "name": chips_mod.CHIP_NAMES[chip],
        "mine_used": chip not in available,
        "field_used": sample.get("chips_used", {}).get(chip, 0),
    } for chip in chips_mod.ALL_CHIPS]

    return {
        "entry_id": entry_id, "event": event, "picks_event": picks_event,
        "rank": rank, "total_players": total_players, "points": my_total,
        "percentile": round(rank / total_players * 100, 1),
        "band": dict(sample["band"], size=sample["size"]),
        "risk": risk,
        "projection": {
            "mine": round(my_projection, 1), "field": round(field, 1),
            "edge": round(edge, 1), "beat": round(beat * 100),
            "density": round(density), "rank_after": after,
            "rank_change": rank - after,
        },
        "climb": climb, "cushion": cushion, "remaining": remaining,
        "horizon": len(world.events),
        "free_transfers": squad.free_transfers, "bank": round(squad.bank, 1),
        "threats": threats, "chances": chances,
        "captain": {"pick": pick, "why": why, "options": options},
        "chips": chip_rows,
    }
