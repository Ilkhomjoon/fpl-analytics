"""«Mening jamoam» — tarkib, tavsiya etilgan 11 lik va har bir qaror izohi.

Bu modul aynan shu savolga javob beradi: **kim o'ynaydi va nima uchun.**
Har o'yinchi yonida uchta narsa turadi:

* **EV** — keyingi turda kutilayotgan ochko;
* **tarkib %** — asosiy tarkibda boshlash ehtimoli (daqiqalar modeli);
* **raqib va qiyinlik** — rasmiy FDR emas, raqibning jadvaldagi o'rni va
  joriy natijalari bilan tuzatilgan baho.

Zaxiradagilar uchun sabab ham yoziladi. Shunda "nega Raya zaxirada?" degan
savol javobsiz qolmaydi — model qaroriga qarshi chiqish mumkin bo'ladi.

Tezlik: EV butun ro'yxat uchun bootstrap ma'lumotidan quriladi (so'rovsiz),
keyin **faqat sizning 15 o'yinchingiz** uchun batafsil tarix yuklanadi.
Batafsil tarix daqiqalar modeliga kerak: "ketma-ket 3 tur 60+ daqiqa" degan
dalil bootstrap yig'indisida ko'rinmaydi.
"""

from __future__ import annotations

import logging

from fplbrain import congestion
from fplbrain import ratings as ratings_mod
from fplbrain import table as table_mod
from fplbrain.ev import (CS_POINTS, EVEngine, build_profile, combine_distributions,
                         form_baseline, points_distribution)
from fplbrain.squad import bench_reason, best_eleven, load_squad

log = logging.getLogger(__name__)

POS_SHORT = {1: "DRV", 2: "HIM", 3: "YAR", 4: "HUJ"}


def _num(value) -> float:
    """FPL raqamlarni matn sifatida beradi ("4.5"). Bo'sh bo'lsa — 0."""
    try:
        return round(float(value or 0), 1)
    except (TypeError, ValueError):
        return 0.0


def pick_events(bootstrap: dict, horizon: int) -> tuple[int, int, list[int]]:
    """(tarkiblar qulflangan GW, keyingi GW, gorizont GW lari).

    `picks_event` — deadline'i o'tgan tur (hali o'ynalayotgan bo'lishi mumkin),
    tarkiblar shundan olinadi.
    """
    events = bootstrap["events"]
    finished = [e["id"] for e in events if e.get("finished")]
    nxt = next((e for e in events if e.get("is_next")), None)
    cur = next((e for e in events if e.get("is_current")), None)
    if nxt is None:
        nxt = next((e for e in events if not e.get("finished")), events[-1])
    picks_event = cur["id"] if cur else (max(finished) if finished else 1)
    horizon_events = list(range(nxt["id"], min(38, nxt["id"] + horizon - 1) + 1))
    return picks_event, nxt["id"], horizon_events


def teams_done_last_event(bootstrap: dict, fixtures: list[dict]) -> set[int]:
    """Joriy turda o'yinini **tugatgan** jamoalar.

    Bootstrapdagi `event_points` — joriy turdagi ochko. Uni "so'nggi o'yin
    holati" deb o'qish faqat jamoa shu turda o'ynab bo'lgan bo'lsa to'g'ri:
    tur davom etayotgan yoki jamoa bo'sh turda bo'lsa, 0 ochko "o'ynamadi"
    degani emas. Bunday jamoalar to'plamga kirmaydi va model ular uchun
    mavsum o'rtachasiga qaytadi.
    """
    current = next((e["id"] for e in bootstrap.get("events", [])
                    if e.get("is_current")), None)
    if current is None:
        return set()
    done: dict[int, bool] = {}
    for f in fixtures or []:
        if f.get("event") != current:
            continue
        finished = bool(f.get("finished") or f.get("finished_provisional"))
        for side in ("team_h", "team_a"):
            team = f.get(side)
            done[team] = done.get(team, True) and finished
    return {team for team, ok in done.items() if ok}


def fixture_note(player, event: int, views=None) -> dict:
    """Raqib, uning jadvaldagi o'rni va **pozitsiyaga mos** qiyinlik.

    Qiyinlik pozitsiyaga bog'liq: himoyachi uchun raqibning hujumi, hujumchi
    uchun raqibning himoyasi hal qiladi. Bitta raqamni ikkalasiga ham
    ko'rsatish chalg'itardi — Leeds ga qarshi himoyachi uchun oson, hujumchi
    uchun qiyin bo'lishi mumkin.
    """
    fixtures = player.ev.fixtures.get(event, [])
    if not fixtures:
        return {"opponent": "—", "home": None, "eff_fdr": None,
                "fdr": None, "opp_position": 0, "blank": True}
    first = fixtures[0]
    pos = player.ev.profile.position
    # FixtureEV da pozitsiyaviy qiyinlik yo'q — uni FixtureView dan olamiz
    view = None
    if views:
        for v in views.get(player.ev.profile.team, {}).get(event, []):
            if v.opponent == getattr(first, "opponent_id", v.opponent):
                view = v
                break
        view = view or (views.get(player.ev.profile.team, {}).get(event) or [None])[0]
    return {
        "opponent": ", ".join(
            f"{f.opponent}{'(u)' if f.is_home else '(m)'}" for f in fixtures),
        "home": first.is_home,
        # Pozitsiyaga mos qiyinlik; topilmasa umumiy bahoga qaytamiz
        "eff_fdr": (view.difficulty_for(pos) if view is not None
                    else getattr(first, "eff_fdr", None)),
        "eff_fdr_def": getattr(view, "eff_fdr_def", None) if view else None,
        "eff_fdr_att": getattr(view, "eff_fdr_att", None) if view else None,
        "fdr": getattr(first, "fdr", None),
        "opp_position": getattr(first, "opp_position", 0) or 0,
        "blank": False,
        # Jadval zichligi: 0..1. Yuqori bo'lsa tarkib kutilganidan boshqacha
        # bo'lishi mumkin — chorshanba o'yini, Yevropa, yoki DGW
        "rotation": round(max(
            (getattr(f, "rotation", 0.0) or 0.0) for f in fixtures), 2),
    }


def ev_detail(player, event: int) -> dict:
    """EV nimalardan yig'ilgani + "toza darvoza bo'lsa" degan shartli raqam.

    EV — **o'rtacha**, ya'ni toza darvoza bo'lgan va bo'lmagan holatlarning
    aralashmasi. Himoyachining EV si 4 ga yaqin bo'lishi normal; 6-7 ochko
    esa toza darvoza RO'Y BERGAN holatdagi natija. Ikkalasi ham ko'rsatiladi,
    chunki bittasi tanlash uchun, ikkinchisi kutish uchun kerak.
    """
    fixtures = player.ev.fixtures.get(event, [])
    if not fixtures:
        return {"parts": {}, "p_cs": 0.0, "p_return": 0.0, "p_haul": 0.0,
                "if_cs": 0.0}

    parts: dict[str, float] = {}
    for f in fixtures:                      # DGW da qismlar qo'shiladi
        for key, value in (f.parts or {}).items():
            parts[key] = round(parts.get(key, 0.0) + value, 2)

    pos = player.ev.profile.position
    p60 = player.ev.profile.p60
    ev_now = sum(f.ev for f in fixtures)
    # Toza darvoza kafolatlangan holat: CS ochkosi to'liq, o'tkazilgan gol jazosi yo'q
    if_cs = ev_now - parts.get("toza_darvoza", 0.0) - parts.get("kiritilgan", 0.0) \
        + CS_POINTS.get(pos, 0) * p60 * len(fixtures)
    first = fixtures[0]
    return {
        "parts": parts,
        "p_cs": round(getattr(first.inputs, "p_cs", 0.0) * 100, 0),
        "p_return": round(max(f.p_return for f in fixtures) * 100, 0),
        "p_haul": round(max(f.p_haul for f in fixtures) * 100, 0),
        "if_cs": round(if_cs, 1),
    }


def chips_left(client, entry_id: int, squad, event: int) -> list[str]:
    """Shu yarim yillikda hali ishlatilmagan chiplar.

    Ochiq `entry/{id}/history/` dan olinadi — loginsiz ham aniq. `squad.chips_available`
    ga tayanib bo'lmaydi: u loginsiz bo'sh keladi, bo'sh ro'yxat esa "hammasi
    ishlatilgan" degani ham bo'lishi mumkin. Ikkalasini `or` bilan ajratib
    bo'lmaydi — ilgari shu sabab to'rt chipini ham ishlatgan menejerga
    "hammasi mavjud" deb ko'rsatilgan.
    """
    from fplbrain import chips as chips_mod
    try:
        history = client.entry_history(entry_id).get("chips") or []
    except Exception as exc:
        log.warning("chiplar tarixi olinmadi: %s", exc)
        return list(squad.chips_available) if squad.authenticated else list(chips_mod.ALL_CHIPS)
    return chips_mod.available_chips(history, event)


def outlook(pev, event: int) -> dict:
    """Natija qanday taqsimlanadi — EV ning yonida turadigan rasm.

    EV — o'rtacha, va u ko'pincha **eng kam uchraydigan** natija: EV si 4 bo'lgan
    himoyachi 42% holatda 1-2 ochko, 34% holatda 6+ oladi, 3-5 esa atigi 23%
    (backtest, GW3-10). Shuning uchun "5" ko'rsatib qo'yish chalg'itadi —
    yonida "yaxshi kunda nechta" va "6+ ehtimoli" bo'lishi kerak. EV ning
    o'zi ko'tarilmaydi: u haqiqiy o'rtachaga mos (bashorat 4.0, haqiqat 3.99)
    va tanlov, transfer, kapitan hisoblari shunga tayanadi.

    `good` — 80-foizli natija: besh o'yindan birida shuncha yoki ko'proq.
    Ehtimollar biroz optimistik (model 35% deganida haqiqatda ~29%).
    """
    fixtures = pev.fixtures.get(event, [])
    if not fixtures:
        return {"good": 0, "low": 0, "mid": 0, "p6": 0, "p10": 0}
    dist = combine_distributions([points_distribution(f.inputs) for f in fixtures])
    p6, p10 = dist.tail(6), dist.tail(10)
    low = 1.0 - dist.tail(3)
    return {
        "good": int(dist.percentile(0.80)),
        "low": round(low * 100), "mid": round(max(0.0, 1.0 - low - p6) * 100),
        "p6": round(p6 * 100), "p10": round(p10 * 100),
    }


class World:
    """Bir marta quriladigan umumiy asos: reyting, uchrashuvlar, EV lar.

    Tarkib ham, transfer ham aynan shu asosdan foydalanadi — ikki marta
    qurish tarmoq so'rovlarini ikkilantiradi va, yomoni, ikki modul bir xil
    o'yinchiga boshqa-boshqa EV berishi mumkin edi.
    """

    def __init__(self, client, cfg, entry_id: int) -> None:
        self.client, self.cfg, self.entry_id = client, cfg, entry_id
        self.bootstrap = client.bootstrap()
        try:
            self.fixtures = client.fixtures()
        except Exception as exc:
            log.warning("fixtures olinmadi: %s", exc)
            self.fixtures = []

        self.picks_event, self.next_event, self.events = pick_events(
            self.bootstrap, cfg.horizon)
        self.elements = self.bootstrap["elements"]
        self.by_id = {e["id"]: e for e in self.elements}

        self.table = table_mod.build_table(self.bootstrap, self.fixtures)
        self.team_ratings = ratings_mod.build_team_ratings(
            self.bootstrap, cfg, self.table)
        # Jadval zichligi: o'ynalgan o'yinlar ham kerak, chunki "oldingi
        # o'yindan keyin necha kun o'tdi" degan savol shulardan javob oladi
        self.views = ratings_mod.build_fixture_views(
            self.fixtures, self.team_ratings, cfg, self.events[0], self.events[-1],
            schedules=congestion.build_schedules(self.fixtures),
            european=congestion.european_team_ids(
                cfg, self.bootstrap.get("teams", [])),
            table=self.table,
        )
        self.engine = EVEngine(cfg, self.team_ratings, self.views)
        self.played = {tid: row.played for tid, row in self.table.items()}
        # Forma bazasi bir marta — o'ynayotgan o'yinchilarning medianasi
        self.form_base = form_baseline(self.elements)
        self.last_done = teams_done_last_event(self.bootstrap, self.fixtures)

        # 1-bosqich: hamma uchun tez EV (qo'shimcha so'rovsiz)
        self.ev: dict[int, object] = {}
        for e in self.elements:
            if e.get("status") == "u":                  # klubdan ketgan
                continue
            profile = build_profile(e, None, cfg, self.played.get(e["team"], 0),
                                    form_base=self.form_base,
                                    last_event_played=e["team"] in self.last_done)
            self.ev[e["id"]] = self.engine.evaluate(profile, self.events)

        self.my_ids = self._my_ids()
        self.detailed: set[int] = set()
        self.deepen(self.my_ids)

    def _my_ids(self) -> list[int]:
        my_team = (self.client.my_team(self.entry_id)
                   if hasattr(self.client, "my_team") else None)
        if my_team and my_team.get("picks"):
            return [p["element"] for p in my_team["picks"]]
        picks = self.client.entry_picks(self.entry_id, self.picks_event)
        return [p["element"] for p in picks.get("picks", [])]

    def deepen(self, ids) -> None:
        """Berilgan o'yinchilar uchun batafsil tarix yuklaydi va EV ni qayta hisoblaydi.

        Batafsil tarix daqiqalar modeliga kerak: "ketma-ket 3 tur 60+ daqiqa"
        degan dalil bootstrap yig'indisida ko'rinmaydi. Har o'yinchi uchun
        alohida so'rov ketadi, shuning uchun faqat kerakli o'yinchilarga.
        """
        yangi = [i for i in ids if i in self.by_id and i not in self.detailed]
        if not yangi:
            return
        summaries = self.client.gather(yangi, self.client.element_summary)
        for element_id, summary in (summaries or {}).items():
            self.detailed.add(element_id)
            if not summary or element_id not in self.by_id:
                continue
            element = self.by_id[element_id]
            profile = build_profile(
                element, summary, self.cfg, self.played.get(element["team"], 0),
                form_base=self.form_base)
            self.ev[element_id] = self.engine.evaluate(profile, self.events)

    def squad(self):
        return load_squad(self.client, self.cfg, self.entry_id,
                          self.picks_event, self.ev, self.by_id)


def build(client, cfg, entry_id: int, world: World | None = None) -> dict:
    """Tarkib + 11 lik + izohlar. Tarmoq so'rovlari: bootstrap, fixtures, 15 ta summary."""
    world = world or World(client, cfg, entry_id)
    bootstrap, by_id = world.bootstrap, world.by_id
    next_event, events = world.next_event, world.events
    team_ratings, ev_by_element = world.team_ratings, world.ev

    squad = world.squad()
    xi, bench, formation, xi_ev = best_eleven(squad.players, next_event)
    # Kapitan — 11 likdagi eng yuqori EV li o'yinchi (jamoadagi bandaj emas,
    # model tavsiyasi). Uning ochkosi ikki barobar hisoblanadi.
    captain = max(xi, key=lambda p: p.ev.per_event.get(next_event, 0.0), default=None)
    captain_ev = captain.ev.per_event.get(next_event, 0.0) if captain else 0.0
    captain_name = captain.name if captain else ""
    xi_ids = {p.element for p in xi}
    xi_min_ev = min((p.ev.per_event.get(next_event, 0.0) for p in xi), default=0.0)
    bench_order = {p.element: i + 1 for i, p in enumerate(bench)}

    rows = []
    for player in squad.players:
        profile = player.ev.profile
        element = by_id.get(player.element, {})
        in_xi = player.element in xi_ids
        rows.append({
            "element": player.element,
            "name": player.name,
            "full_name": " ".join(x for x in (
                element.get("first_name"), element.get("second_name")) if x),
            "team": team_ratings[profile.team].short,
            "team_position": team_ratings[profile.team].position,
            "pos": profile.position,
            "pos_short": POS_SHORT.get(profile.position, "?"),
            "price": profile.price,
            "selling": player.selling_price,
            "purchase": player.purchase_price,
            "ev": round(player.ev.per_event.get(next_event, 0.0), 2),
            "ev_horizon": player.ev.horizon_ev,
            "p_start": round(profile.p_start * 100, 0),
            "p60": round(profile.p60 * 100, 0),
            "ownership": profile.ownership,
            # Forma — FPL ning o'zi hisoblagan so'nggi 30 kunlik o'rtacha ball.
            # Model bahosi emas, xolis raqam: EV bilan yonma-yon turgani ma'qul.
            "form": _num(element.get("form")),
            "ppg": _num(element.get("points_per_game")),
            "total_points": int(element.get("total_points") or 0),
            "net_transfers": (int(element.get("transfers_in_event") or 0)
                              - int(element.get("transfers_out_event") or 0)),
            "status": profile.status,
            "news": profile.news,
            "is_captain": player.is_captain,
            "is_vice": player.is_vice,
            "in_xi": in_xi,
            "bench_order": 0 if in_xi else bench_order.get(player.element, 0),
            "reason": "" if in_xi else bench_reason(player, next_event, xi_min_ev),
            "fixture": fixture_note(player, next_event, world.views),
            "detail": ev_detail(player, next_event),
            "outlook": outlook(player.ev, next_event),
            "pen": bool(profile.is_pen_taker),
            "set_piece": bool(profile.is_set_piece),
            # 5 ta sariq — bir o'yinlik diskvalifikatsiya (GW19 gacha)
            "yellow_total": int(getattr(profile, "yellow_total", 0)),
            "ban_risk": int(getattr(profile, "yellow_total", 0)) == 4,
        })

    order = {1: 0, 2: 1, 3: 2, 4: 3}
    rows.sort(key=lambda r: (not r["in_xi"], r["bench_order"],
                             order[r["pos"]], -r["ev"]))

    return {
        "entry_id": entry_id,
        "event": next_event,
        "picks_event": world.picks_event,
        "authenticated": squad.authenticated,
        "bank": squad.bank,
        "value": squad.value,
        "free_transfers": squad.free_transfers,
        "transfers_made": squad.transfers_made,
        "unlimited_transfers": squad.unlimited_transfers,
        # FPL ning xom raqamlari — maxfiy emas, lekin talqini hujjatlashtirilmagan.
        # Sahifadagi son noto'g'ri chiqsa, sabab shu yerda ko'rinadi.
        "raw_transfers": {
            "status": squad.transfers_status,
            "cost": squad.transfers_cost,
            "value": squad.api_value,
            "made": squad.transfers_made,
        },
        # FT config dan olingan bo'lsa — buni aytish kerak, aks holda
        # noto'g'ri raqamning sababi ko'rinmay qoladi
        "ft_override": squad.override_used,
        "chips_available": squad.chips_available,
        "chips_used": squad.chips_used,
        "formation": f"{formation[1]}-{formation[2]}-{formation[3]}",
        "xi_ev": round(xi_ev, 2),
        # Kapitan ochkosi IKKI barobar. Buni qo'shmaslik butun jamoa
        # bahosini ~5 ochkoga past ko'rsatardi va haqiqiy o'rtacha bilan
        # (turiga 50-54 ochko) solishtirib bo'lmasdi.
        "xi_ev_captain": round(xi_ev + captain_ev, 2),
        # Tarkibdagi barcha 15 o'yinchining yig'indisi (kapitansiz, zaxira
        # bilan). Bu "olinadigan ochko" EMAS — zaxira ochkosi faqat
        # avtoalmashtirishda hisobga kiradi; u tarkibning umumiy chuqurligini
        # ko'rsatadi.
        "squad_ev": round(sum(
            p.ev.per_event.get(next_event, 0.0) for p in squad.players), 2),
        "bench_ev": round(sum(
            p.ev.per_event.get(next_event, 0.0) for p in bench), 2),
        "captain": captain_name,
        "players": rows,
    }
