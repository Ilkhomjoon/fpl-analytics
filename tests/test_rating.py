"""O'yinchi reytingi — ayniqsa "byudjet to'ldiruvchi" (enabler) muammosi."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fplbrain.priors import enabler_discount, role_prior
from fplbrain.rating import market_movers, best_value, rate_player

TOTAL = 10_000_000


def element(**kw):
    base = {
        "id": 1, "web_name": "Test", "team": 1, "element_type": 3,
        "now_cost": 65, "status": "a", "minutes": 180, "starts": 2,
        "goals_scored": 0, "assists": 0,
        "expected_goals": 0.4, "expected_assists": 0.3,
        "selected_by_percent": "10.0",
        "transfers_in_event": 0, "transfers_out_event": 0,
    }
    base.update(kw)
    return base


# ------------------------------------------------------- enabler muammosi
def test_arzon_ommaviy_oynamaydigan_oyinchi_enabler_deb_belgilanadi():
    """4.0m, 40% egalik, 0 daqiqa — bu byudjet to'ldiruvchi, yaxshi o'yinchi emas."""
    r = rate_player(element(now_cost=40, element_type=2, selected_by_percent="40.0",
                            minutes=0, starts=0, expected_goals=0.0,
                            expected_assists=0.0), team_matches=3, total_players=TOTAL)
    assert r.is_enabler is True
    assert r.role < 0.35, f"enabler yuqori rol oldi: {r.role}"
    assert "to'ldiruvchi" in r.note


def test_qimmat_ommaviy_oyinchi_enabler_emas():
    r = rate_player(element(now_cost=125, selected_by_percent="45.0",
                            minutes=270, starts=3), team_matches=3, total_players=TOTAL)
    assert r.is_enabler is False
    assert r.role > 0.85


def test_arzon_lekin_oynaydigan_oyinchi_enabler_emas():
    """Arzon bo'lsa ham muntazam o'ynasa — bu haqiqiy pik."""
    r = rate_player(element(now_cost=45, element_type=2, selected_by_percent="30.0",
                            minutes=270, starts=3), team_matches=3, total_players=TOTAL)
    assert r.is_enabler is False
    assert r.role > 0.75


def test_egalik_daqiqalarni_bosib_otolmaydi():
    """Ommaviy, lekin kam o'ynagan o'yinchi yuqori rol ololmaydi."""
    ko_p = rate_player(element(selected_by_percent="60.0", minutes=45, starts=0),
                       team_matches=3, total_players=TOTAL)
    assert ko_p.role <= 0.55


def test_enabler_chegirmasi_narx_bilan_osadi():
    assert enabler_discount(4.0) == 0.25
    assert enabler_discount(4.0) < enabler_discount(4.8) < enabler_discount(5.5)
    assert enabler_discount(9.0) == 1.0


def test_prior_arzon_oyinchida_egalikka_kam_ishonadi():
    """Bir xil egalik: arzon o'yinchida prior pastroq bo'lishi kerak."""
    assert role_prior(40, 4.0) < role_prior(40, 6.5)


# ----------------------------------------------------------------- chiqim
def test_xg_haqiqiy_natijadan_kop_vazn_oladi():
    """Kichik namunada asos (xG) natijadan barqarorroq."""
    omadli = rate_player(element(goals_scored=3, expected_goals=0.3,
                                 expected_assists=0.1), team_matches=2,
                         total_players=TOTAL)
    assert omadli.returns90 > omadli.underlying90
    # aralashma asos tomonga tortilgan bo'lishi kerak
    assert omadli.output90 < (omadli.returns90 + omadli.underlying90) / 2
    assert "asosdan yuqori" in omadli.note


def test_asosi_yuqori_oyinchi_belgilanadi():
    kutilmoqda = rate_player(element(goals_scored=0, assists=0,
                                     expected_goals=1.8, expected_assists=0.9),
                             team_matches=2, total_players=TOTAL)
    assert kutilmoqda.underlying90 > kutilmoqda.returns90
    assert "portlashi mumkin" in kutilmoqda.note


def test_oynamagan_oyinchida_bolinish_xatosi_yoq():
    r = rate_player(element(minutes=0, starts=0), team_matches=0, total_players=0)
    assert r.returns90 == 0.0 and r.output90 == 0.0
    assert r.score >= 0.0


# ---------------------------------------------------------------- momentum
def test_transfer_oqimi_egalarga_nisbatan_olchanadi():
    """100k transfer 1% egalikda katta, 50% egalikda kichik voqea."""
    kam = rate_player(element(selected_by_percent="1.0",
                              transfers_in_event=50_000, transfers_out_event=0),
                      team_matches=2, total_players=TOTAL)
    kop = rate_player(element(selected_by_percent="50.0",
                              transfers_in_event=50_000, transfers_out_event=0),
                      team_matches=2, total_players=TOTAL)
    assert kam.momentum > kop.momentum
    assert "bozor olyapti" in kam.note


def test_sotilayotgan_oyinchi_belgilanadi():
    r = rate_player(element(selected_by_percent="20.0",
                            transfers_in_event=0, transfers_out_event=400_000),
                    team_matches=2, total_players=TOTAL)
    assert r.momentum < 0
    assert "bozor sotyapti" in r.note


def test_bozor_harakati_royxati():
    ratings = {
        1: rate_player(element(id=1, selected_by_percent="10",
                               transfers_in_event=200_000), 2, total_players=TOTAL),
        2: rate_player(element(id=2, selected_by_percent="10",
                               transfers_out_event=150_000), 2, total_players=TOTAL),
    }
    buying, selling = market_movers(ratings, top=2)
    assert buying[0].element == 1
    assert selling[0].element == 2


# ------------------------------------------------------------------ samara
def test_samara_royxatida_enabler_yoq():
    ratings = {
        1: rate_player(element(id=1, now_cost=40, element_type=2,
                               selected_by_percent="45", minutes=0, starts=0),
                       3, total_players=TOTAL),
        2: rate_player(element(id=2, now_cost=55, minutes=270, starts=3,
                               expected_goals=1.5, expected_assists=0.8),
                       3, total_players=TOTAL),
    }
    rows = best_value(ratings)
    assert all(not r.is_enabler for r in rows)
    assert rows and rows[0].element == 2


def test_samara_narxga_boliq():
    """Bir xil chiqim, turli narx — arzoni samaraliroq."""
    arzon = rate_player(element(id=1, now_cost=50, minutes=270, starts=3,
                                expected_goals=1.2, expected_assists=0.6),
                        3, total_players=TOTAL)
    qimmat = rate_player(element(id=2, now_cost=110, minutes=270, starts=3,
                                 expected_goals=1.2, expected_assists=0.6),
                         3, total_players=TOTAL)
    assert arzon.value > qimmat.value
    # chiqim bir xil; reyting rolda ozgina farq qiladi (arzonda egalik signali chegirilgan)
    assert arzon.output90 == pytest.approx(qimmat.output90)
