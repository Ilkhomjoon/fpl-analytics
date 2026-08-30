"""Strategik tahlil sinovlari — maydonga nisbatan holat."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fplbrain import insight
from fplbrain.rivals import GroupStats
from tests.conftest import make_squad as _make_squad


def _stats(ownership, captaincy=None, label="Test guruh", size=100):
    captaincy = captaincy or {}
    eo = {el: ownership.get(el, 0) + captaincy.get(el, 0) for el in ownership}
    return GroupStats(label=label, size=size, ownership=ownership,
                      captaincy=captaincy, eo=eo, avg_total=100.0)


def test_egalik_kapitanlik_bilan_qoshiladi():
    st = _stats({7: 60.0}, {7: 40.0})
    assert insight.effective_ownership(st, 7) == 100.0
    assert insight.effective_ownership(st, 999) == 0.0


def test_menda_yoq_ommaviy_oyinchi_tahdid_sifatida_chiqadi(world):
    """Yuqori EO li, menda yo'q o'yinchi manfiy hissa bilan ro'yxatga tushsin."""
    squad = _make_squad(world)
    ev = world["ev"]
    mine = {p.element for p in squad.players}
    outsider = next(
        p for p in sorted(ev.values(), key=lambda x: -x.per_event[3])
        if p.element not in mine
    )
    st = _stats({outsider.element: 80.0}, {outsider.element: 30.0})

    gap = insight.structural_gap(squad, st, ev, 3)
    names = [t.name for t in gap.threats]
    assert outsider.profile.name in names
    threat = next(t for t in gap.threats if t.element == outsider.element)
    assert threat.swing < 0
    # EO 110% -> hissa taxminan -1.1 * EV
    assert threat.swing == pytest.approx(-1.10 * outsider.per_event[3], rel=0.02)


def test_mendagi_oyinchi_ustunlik_sifatida_chiqadi(world):
    squad = _make_squad(world)
    ev = world["ev"]
    xi = insight.best_eleven(squad.players, 3)[0]
    target = max(xi, key=lambda p: p.ev.per_event[3])
    st = _stats({target.element: 4.0})          # deyarli hech kimda yo'q

    gap = insight.structural_gap(squad, st, ev, 3)
    edge = next((e for e in gap.edges if e.element == target.element), None)
    assert edge is not None
    assert edge.swing == pytest.approx(0.96 * target.ev.per_event[3], rel=0.02)


def test_zaxiradagi_oyinchi_ustunlikka_qoshilmaydi(world):
    """Zaxirada o'tirgan o'yinchi maydonga ta'sir qilmaydi."""
    squad = _make_squad(world)
    ev = world["ev"]
    bench = insight.best_eleven(squad.players, 3)[1]
    st = _stats({p.element: 3.0 for p in bench})

    gap = insight.structural_gap(squad, st, ev, 3)
    bench_ids = {p.element for p in bench}
    assert not (bench_ids & {e.element for e in gap.edges})


def test_net_11_likka_11_lik_farqi(world):
    """net — mening 11 ligim va shablon 11 lik orasidagi farq."""
    squad = _make_squad(world)
    ev = world["ev"]
    st = _stats({el: 50.0 for el in list(ev)[:60]})

    gap = insight.structural_gap(squad, st, ev, 3)
    bench = insight.benchmark_vs_template(squad, st, ev, 3)
    assert gap.net == pytest.approx(bench.gap, abs=0.01)
    assert bench.my_xi_ev == pytest.approx(insight.best_eleven(squad.players, 3)[3], abs=0.01)


def test_fixture_korinishi_mening_oyinchilarimni_belgilaydi(world):
    squad = _make_squad(world)
    best, worst = insight.fixture_outlook(
        squad, world["views"], world["rt"], world["events"], world["ev"]
    )
    assert best and worst
    assert best[0].score >= best[-1].score
    assert worst[0].score <= worst[-1].score
    # kamida bitta jamoada mening o'yinchim bo'lishi kerak
    tagged = [r for r in best + worst if r.my_players]
    assert tagged


# --------------------------------------------------------- mavsum sur'ati
def test_surat_hisobi():
    from fplbrain.target import build_pace

    history = {"current": [
        {"event": 1, "points": 57, "average_entry_score": 50, "rank": 2434400},
        {"event": 2, "points": 61, "average_entry_score": 55, "rank": 2100000},
    ]}
    pace = build_pace(history, target=2508, leader_total=140, leader_played=2)

    assert pace.played == 2 and pace.remaining == 36
    assert pace.my_total == 118
    assert pace.my_average == pytest.approx(59.0)
    assert pace.my_best == 61 and pace.my_worst == 57
    assert pace.fpl_average_total == 105
    # maqsad uchun kerakli o'rtacha
    assert pace.required_average == pytest.approx((2508 - 118) / 36)
    # hozirgi sur'atda yakuniy natija
    assert pace.projected_total == pytest.approx(118 + 59 * 36)
    assert pace.leader_gap == 22
    # yetakchini quvish uchun kerakli o'rtacha undan yuqori bo'lishi kerak
    assert pace.catch_leader_average > pace.leader_average


def test_surat_maqsadga_yetgan_holat():
    from fplbrain.target import build_pace

    history = {"current": [{"event": i, "points": 80, "average_entry_score": 50}
                           for i in range(1, 11)]}
    pace = build_pace(history, target=2508)
    assert pace.my_average == 80
    assert pace.required_average < pace.my_average
    assert "yetarli" in pace.verdict
    assert pace.shortfall < 0


def test_surat_bosh_tarix():
    from fplbrain.target import build_pace
    assert build_pace({"current": []}) is None
    assert build_pace({}) is None


# ------------------------------------------------- shablon bilan tenglashish
def test_shablon_tavsiyasi_ommaviy_oyinchini_taklif_qiladi(world):
    from fplbrain.insight import template_moves

    squad = _make_squad(world)
    ev = world["ev"]
    mine = {p.element for p in squad.players}
    # menda yo'q, yuqori EV li o'yinchi — uni ommaviy qilib ko'rsatamiz
    outsider = max(
        (p for p in ev.values() if p.element not in mine
         and p.profile.availability >= 0.6),
        key=lambda p: p.horizon_ev,
    )
    st = _stats({outsider.element: 70.0}, {outsider.element: 20.0})

    moves = template_moves(squad, st, ev, 3, bank=100.0)
    assert moves
    assert moves[0].in_element == outsider.element
    assert moves[0].eo_gain > 0
    assert moves[0].affordable is True


def test_shablon_byudjetni_belgilaydi(world):
    """Pul yetmasa ham ko'rsatiladi, lekin belgilanadi va pastga tushadi."""
    from fplbrain.insight import template_moves

    squad = _make_squad(world)
    ev = world["ev"]
    mine = {p.element for p in squad.players}
    pricey = max(
        (p for p in ev.values() if p.element not in mine
         and p.profile.availability >= 0.6),
        key=lambda p: p.profile.price,
    )
    st = _stats({pricey.element: 60.0})
    moves = template_moves(squad, st, ev, 3, bank=0.0)
    if moves:
        target = next((m for m in moves if m.in_element == pricey.element), None)
        if target and target.in_price > 0:
            assert target.affordable is False
            assert "yetmaydi" in target.reason


def test_shablon_bir_oyinchini_ikki_marta_sotmaydi(world):
    from fplbrain.insight import template_moves

    squad = _make_squad(world)
    ev = world["ev"]
    mine = {p.element for p in squad.players}
    outsiders = [p for p in sorted(ev.values(), key=lambda x: -x.horizon_ev)
                 if p.element not in mine][:6]
    st = _stats({p.element: 50.0 for p in outsiders})
    moves = template_moves(squad, st, ev, 3, bank=100.0, top=6)
    out_ids = [m.out_element for m in moves]
    assert len(out_ids) == len(set(out_ids))


# ------------------------------------------------- o'yin vaqti xavfi
def test_oynamaydigan_oyinchi_xavf_royxatiga_tushadi(world):
    """GW2 dagi 12 ochkolik halokat aynan shundan: 11 likda o'ynamaganlar."""
    squad = _make_squad(world)
    xi = insight.best_eleven(squad.players, 3)[0]
    xi[0].ev.profile.status = "i"
    xi[0].ev.profile.availability = 0.0
    xi[0].ev.profile.news = "Knee injury"

    risk = insight.squad_risk(squad, 3, world["views"])
    names = [p.name for p in risk.players]
    assert xi[0].name in names
    top = next(p for p in risk.players if p.name == xi[0].name)
    assert top.severity == 3
    assert "11 likda" in risk.headline


def test_bosh_turdagi_jamoa_belgilanadi(world):
    """Jamoasi o'ynamaydigan o'yinchi eng yuqori xavf darajasini oladi."""
    squad = _make_squad(world)
    xi = insight.best_eleven(squad.players, 3)[0]
    views = {tid: dict(per) for tid, per in world["views"].items()}
    views[xi[0].ev.profile.team] = {}          # bu jamoada uchrashuv yo'q

    risk = insight.squad_risk(squad, 3, views)
    assert risk.blank_teams >= 1
    entry = next(p for p in risk.players if p.name == xi[0].name)
    assert entry.severity == 3
    assert "bo'sh tur" in entry.reason


def test_sogʻlom_tarkibda_xavf_yoq(world):
    squad = _make_squad(world)
    for p in squad.players:
        p.ev.profile.status = "a"
        p.ev.profile.availability = 1.0
        p.ev.profile.p_start = 0.95
        p.ev.profile.news = ""
    risk = insight.squad_risk(squad, 3, world["views"])
    assert risk.serious == []
    assert risk.headline == ""


def test_jiddiy_va_yengil_xavf_ajratiladi(world):
    squad = _make_squad(world)
    xi = insight.best_eleven(squad.players, 3)[0]
    for p in squad.players:
        p.ev.profile.status = "a"
        p.ev.profile.availability = 1.0
        p.ev.profile.p_start = 0.95
        p.ev.profile.news = ""
    xi[0].ev.profile.p_start = 0.40          # jiddiy
    xi[1].ev.profile.p_start = 0.65          # yengil

    risk = insight.squad_risk(squad, 3, world["views"])
    levels = {p.name: p.severity for p in risk.players}
    assert levels[xi[0].name] == 2
    assert levels[xi[1].name] == 1
    assert len(risk.serious) == 1


def test_tugamagan_tur_suratga_qoshilmaydi():
    """Yarim o'ynalgan turning jonli ochkosi yakuniy deb olinmasin.

    GW2 da 10 uchrashuvdan 5 tasi hali bo'lmaganda 12 ochko turishi mumkin —
    bu "12 ochko oldingiz" degani emas.
    """
    from fplbrain.target import build_pace

    history = {"current": [
        {"event": 1, "points": 57, "average_entry_score": 50},
        {"event": 2, "points": 12, "average_entry_score": 45},
    ]}
    pace = build_pace(history, target=2508, finished_events=[1])
    assert pace.played == 1
    assert pace.my_total == 57
    assert pace.my_average == 57.0
    assert pace.partial_event == 2
    assert pace.partial_points == 12
    assert pace.live_total == 69


def test_yetakchi_farqi_jonli_ochko_bilan_solishtiriladi():
    """Umumiy jadvaldagi yetakchi ochkosi ham jonli — bir asosda solishtirish."""
    from fplbrain.target import build_pace

    history = {"current": [
        {"event": 1, "points": 57, "average_entry_score": 50},
        {"event": 2, "points": 12, "average_entry_score": 45},
    ]}
    pace = build_pace(history, leader_total=175, finished_events=[1])
    # 175 - (57 + 12), 175 - 57 EMAS
    assert pace.leader_gap == 106
    # yetakchi o'rtachasi ham ikki turga bo'linadi
    assert pace.leader_average == pytest.approx(87.5)


def test_hamma_tur_tugagan_holat():
    from fplbrain.target import build_pace

    history = {"current": [
        {"event": 1, "points": 57, "average_entry_score": 50},
        {"event": 2, "points": 61, "average_entry_score": 55},
    ]}
    pace = build_pace(history, leader_total=175, finished_events=[1, 2])
    assert pace.played == 2
    assert pace.partial_event is None
    assert pace.live_total == pace.my_total == 118
    assert pace.leader_average == pytest.approx(87.5)
