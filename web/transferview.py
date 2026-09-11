"""«Transferlar» — kimni sotib, kimni olish, va bu arziydimi.

Modul bitta savolga javob beradi: **shu turda nima qilsam ochko ko'proq
bo'ladi?** Javob uch qismdan iborat:

1. **Zaif bo'g'inlar** — tarkibdagi eng past baholangan o'yinchilar, nima
   uchun zaifligi izohi bilan. Izoh mutlaq EV ga emas, shu narx darajasidagi
   alternativalarga nisbatan beriladi: "10.5 EV" o'zi hech narsa demaydi.
2. **Takliflar** — har biri uchun sof foyda (hit ayirilgan holda), narx farqi
   va qolgan bank.
3. **Hit arziydimi** — erkin transfer yetmasa, −4 ochkoni qoplaydimi.

TEZLIK. Nomzodlar butun ro'yxatdan qidiriladi, lekin batafsil tarix (har
o'yinchi uchun alohida so'rov) faqat **eng istiqbolli bir nechtasi** uchun
yuklanadi. Aks holda 600+ so'rov ketardi. Tanlash ikki bosqichda:
avval bootstrap EV si bo'yicha saralanadi, keyin tanlanganlar chuqurlashadi
va **shundan keyin** yakuniy hisob qilinadi.

NARXLAR. Sotishda **sotish narxi** (yarim o'sish qoidasi bilan), olishda
**joriy narx** ishlatiladi. Login bo'lmasa sotish narxi transfer tarixidan
tiklanadi va taxminiy bo'ladi — sahifada shu haqda aytiladi.
"""

from __future__ import annotations

import logging

from fplbrain.squad import best_eleven
from fplbrain.transfers import evaluate_moves, weak_links

from . import squadview

log = logging.getLogger(__name__)

POS_SHORT = squadview.POS_SHORT
# Har pozitsiya uchun batafsil tarix yuklanadigan nomzodlar soni.
# Ko'paytirilsa aniqroq, lekin sekinroq — har biri bitta so'rov.
DEEPEN_PER_POSITION = 8
MAX_SUGGESTIONS = 8


def _player_row(pev, price: float, selling: float | None = None) -> dict:
    pr = pev.profile
    return {
        "element": pev.element,
        "name": pr.name,
        "team": pr.team,
        "pos": pr.position,
        "pos_short": POS_SHORT.get(pr.position, "?"),
        "price": round(price, 1),
        "selling": round(selling if selling is not None else price, 1),
        "ev": round(pev.next_ev, 2),
        "ev_horizon": round(pev.horizon_ev, 2),
        "p_start": round(pr.p_start * 100, 0),
        "ownership": pr.ownership,
        "status": pr.status,
        "news": pr.news,
    }


def _candidates_to_deepen(world, squad) -> list[int]:
    """Byudjetga sig'adigan, eng istiqbolli nomzodlar.

    Byudjet: bank + tarkibdagi eng qimmat o'yinchining sotish narxi. Ya'ni
    "hech bo'lmaganda bitta o'yinchini sotib olsa bo'ladimi" degan chegara.
    """
    owned = {p.element for p in squad.players}
    eng_qimmat = max((p.selling_price for p in squad.players), default=0.0)
    budget = squad.bank + eng_qimmat

    by_pos: dict[int, list] = {1: [], 2: [], 3: [], 4: []}
    for pev in world.ev.values():
        pr = pev.profile
        if pev.element in owned or pr.position not in by_pos:
            continue
        if pr.price > budget + 1e-9:
            continue
        if pr.availability < 0.6 or pr.p_start < 0.35:
            continue
        by_pos[pr.position].append(pev)

    out: list[int] = []
    for pos, items in by_pos.items():
        items.sort(key=lambda p: -p.horizon_ev)
        out += [p.element for p in items[:DEEPEN_PER_POSITION]]
    return out


def _move_row(move, squad_by_element) -> dict:
    outs = [_player_row(p.ev, p.ev.profile.price, p.selling_price)
            for p in move.out_players]
    ins = [_player_row(p, p.profile.price) for p in move.in_players]
    return {
        "out": outs,
        "in": ins,
        "n": move.n,
        "gain": round(move.gain, 2),          # hit ayirilgan sof foyda
        "raw_gain": round(move.raw_gain, 2),  # hit siz
        "hit": move.hit,
        "cost": round(move.cost, 1),          # + = qimmatlashadi
        "bank_after": round(move.bank_after, 1),
        "worth_it": move.gain > 0,
    }


def _distinct(moves) -> list:
    """Bir xil o'yinchi qayta-qayta chiqmasin.

    Xom ro'yxatda bitta o'yinchi uchun o'nlab variant bo'ladi va ular bir
    biriga o'xshaydi. Foydalanuvchiga kerak bo'lgani boshqa: **har bir
    sotiladigan o'yinchi uchun eng yaxshi bitta variant** — shunda ro'yxat
    "kimni sotsam bo'ladi" degan savolga javob beradi, "NEW44 ni kimga
    almashtirsam" degan savolga emas.
    """
    korilgan_out: set = set()
    korilgan_in: set = set()
    out: list = []
    for m in moves:                          # allaqachon foyda bo'yicha saralangan
        out_key = tuple(sorted(p.element for p in m.out_players))
        in_key = tuple(sorted(p.element for p in m.in_players))
        if out_key in korilgan_out or in_key in korilgan_in:
            continue
        korilgan_out.add(out_key)
        korilgan_in.add(in_key)
        out.append(m)
    return out


def build(client, cfg, entry_id: int, world=None) -> dict:
    """Transfer tahlili. `world` berilsa qayta qurilmaydi (tarkib bilan birga)."""
    world = world or squadview.World(client, cfg, entry_id)
    squad = world.squad()

    # 1-bosqich: nomzodlarni tanlab, ularni chuqurlashtiramiz
    nomzodlar = _candidates_to_deepen(world, squad)
    world.deepen(nomzodlar)
    # Chuqurlashgandan keyin tarkib EV lari ham yangilanishi kerak
    squad = world.squad()

    all_ev = list(world.ev.values())
    # Ikkita transfer varianti HAR DOIM ko'riladi, FT yo'q bo'lsa ham:
    # −8 ochkoni oqlaydigan juftlik bo'lishi mumkin va uni ko'rsatmaslik
    # qarorni foydalanuvchidan yashirish bo'lardi.
    moves = evaluate_moves(squad, all_ev, world.events, cfg, max_transfers=2)
    weak = weak_links(squad, world.events, cfg, all_ev)

    by_element = {p.element: p for p in squad.players}
    rows = [_move_row(m, by_element) for m in _distinct(moves)[:MAX_SUGGESTIONS]]

    # Hech narsa qilmaslik ham qaror: eng yaxshi taklif foyda bermasa,
    # buni aytish kerak — "transfer qilmang" ham tavsiya.
    eng_yaxshi = rows[0] if rows else None
    tavsiya = "hold"
    if eng_yaxshi and eng_yaxshi["worth_it"]:
        tavsiya = "transfer"

    xi, _, _, xi_ev = best_eleven(squad.players, world.next_event)
    return {
        "entry_id": entry_id,
        "event": world.next_event,
        "authenticated": squad.authenticated,
        "free_transfers": squad.free_transfers,
        "transfers_made": squad.transfers_made,
        "unlimited_transfers": squad.unlimited_transfers,
        "transfers_status": squad.transfers_status,
        "transfers_cost": squad.transfers_cost,
        "bank": round(squad.bank, 1),
        "value": squad.value,
        "hit_cost": int(getattr(cfg, "hit_cost", 4)),
        "xi_ev": round(xi_ev, 2),
        "recommendation": tavsiya,
        "horizon": len(world.events),
        "moves": rows,
        "weak": [
            {**_player_row(p.ev, p.ev.profile.price, p.selling_price),
             "horizon_ev": round(hev, 2), "reason": reason}
            for p, hev, reason in weak[:5]
        ],
        "candidates_deepened": len(nomzodlar),
    }
