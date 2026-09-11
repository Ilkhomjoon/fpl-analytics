"""Noldan jamoa tuzish — qoidalar buzilmasligi SHART.

Bu modulning natijasi FPL ga kiritiladi va ekspertlarga qarshi H2H da
ishlatiladi. Shuning uchun qoidalar bo'yicha bitta ham "deyarli to'g'ri"
javob yaramaydi: byudjetdan 0.1m oshgan yoki bitta klubdan 4 o'yinchi
olingan jamoa umuman kiritilmaydi.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fplbrain import builder                                      # noqa: E402
from fplbrain.builder import MAX_PER_TEAM, SQUAD_SHAPE            # noqa: E402


@pytest.fixture(scope="module")
def built(world):
    """Soxta olamdan 100.0m byudjet bilan tuzilgan jamoa."""
    evs = list(world["ev"].values())
    return builder.build_squad(evs, world["events"], world["cfg"], budget=100.0)


# ------------------------------------------------------------- qoidalar
def test_tarkib_shakli_toppa_togri(built):
    shape: dict[int, int] = {}
    for p in built.players:
        shape[p.position] = shape.get(p.position, 0) + 1
    assert shape == SQUAD_SHAPE
    assert len(built.players) == 15


def test_byudjetdan_oshmaydi(built):
    assert built.cost <= 100.0 + 1e-9
    assert built.bank == pytest.approx(100.0 - built.cost, abs=0.05)


def test_bitta_klubdan_kopi_uchta(built):
    assert max(built.team_counts.values()) <= MAX_PER_TEAM


def test_bir_oyinchi_ikki_marta_olinmaydi(built):
    ids = [p.element for p in built.players]
    assert len(ids) == len(set(ids))


def test_ozini_ozi_tekshiradi(built):
    assert built.legal(100.0) is True
    assert built.legal(built.cost - 0.1) is False      # byudjet kichik bo'lsa


# ------------------------------------------------------------- 11 lik
def test_11_lik_va_zaxira_ajratilgan(built):
    assert len(built.xi) == 11
    assert len(built.bench) == 4
    ids = {p.element for p in built.xi} | {p.element for p in built.bench}
    assert ids == {p.element for p in built.players}


def test_11_likda_bitta_darvozabon(built):
    assert sum(1 for p in built.xi if p.position == 1) == 1


def test_kapitan_11_likdan_va_eng_yuqori_ev(built, world):
    event = world["events"][0]
    assert built.captain is not None
    assert built.captain.element in {p.element for p in built.xi}
    assert built.captain.ev.per_event.get(event, 0.0) == max(
        p.ev.per_event.get(event, 0.0) for p in built.xi)


# ------------------------------------------------------------- sifat
def test_qidiruv_boshlangichdan_yaxshiroq(world):
    """Mahalliy qidiruv ochko qo'shishi kerak — aks holda u keraksiz."""
    evs = list(world["ev"].values())
    pool = builder.candidate_pool(evs, world["cfg"])
    seed = builder._greedy_seed(pool, 100.0, world["events"], world["cfg"])
    assert seed is not None
    seed_score = builder.objective(seed, world["events"], world["cfg"])
    final = builder.build_squad(evs, world["events"], world["cfg"], budget=100.0)
    assert final.objective >= seed_score


def test_kop_byudjet_yaxshiroq_jamoa_beradi(world):
    """Monotonlik: pul ko'p bo'lsa natija yomonlashmasligi kerak."""
    evs = list(world["ev"].values())
    kam = builder.build_squad(evs, world["events"], world["cfg"], budget=85.0)
    kop = builder.build_squad(evs, world["events"], world["cfg"], budget=100.0)
    assert kop.objective > kam.objective
    assert kam.cost <= 85.0 + 1e-9


def test_maqsad_kapitanni_hisobga_oladi(world):
    """`objective` — `squad_ev` emas: kapitan ikkilanadi.

    Kapitansiz maqsad premium o'yinchini past baholardi — uning asosiy
    qiymati aynan ikkilanishida.
    """
    from fplbrain.squad import squad_ev, Squad

    evs = list(world["ev"].values())
    built = builder.build_squad(evs, world["events"], world["cfg"], budget=100.0)
    kapitansiz = squad_ev(
        Squad(players=built.players, bank=0.0, event=world["events"][0]),
        world["events"], world["cfg"])
    assert built.objective > kapitansiz


def test_nomzod_yetmasa_none_qaytadi(world):
    """Byudjet juda kichik bo'lsa — yolg'on javob emas, `None`."""
    evs = list(world["ev"].values())
    assert builder.build_squad(evs, world["events"], world["cfg"], budget=20.0) is None


def test_bosh_royxat_yiqilmaydi(world):
    assert builder.build_squad([], world["events"], world["cfg"]) is None
    assert builder.build_squad(list(world["ev"].values()), [], world["cfg"]) is None
