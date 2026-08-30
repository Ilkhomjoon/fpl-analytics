"""Daqiqalar modeli — regressiya sinovlari.

Model o'tgan mavsumga tayanmaydi. Prior ikkita JORIY signaldan quriladi:
egalik foizi (rol) va narx (sifat). Bu fayl aynan shu xatti-harakatni
qulflab qo'yadi — ilgari o'tgan mavsum `starts/38` priori 25% egalikdagi
asosiy qanotni (Tzolis) zaxira o'yinchi darajasiga tushirib qo'ygan edi.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fplbrain.config import Config
from fplbrain.ev import build_profile
from fplbrain.priors import role_prior

CFG = Config()


def profile(*, price=8.0, position=3, ownership=10.0,
            gw_minutes=(), gw_started=(), team_matches=1, news="", chance=None):
    """O'yinchi profili: joriy mavsumda o'ynalgan turlar + bozor ma'lumoti."""
    element = {
        "id": 1, "web_name": "Test", "team": 1, "element_type": position,
        "now_cost": int(price * 10), "status": "a" if not news else "d",
        "chance_of_playing_next_round": chance, "news": news,
        "minutes": sum(gw_minutes), "starts": sum(1 for s in gw_started if s),
        "expected_goals": 0.4 * len(gw_minutes), "expected_assists": 0.2 * len(gw_minutes),
        "clearances_blocks_interceptions": 2, "tackles": 1, "recoveries": 3,
        "bonus": 1, "saves": 0, "yellow_cards": 0,
        "selected_by_percent": str(ownership),
        "penalties_order": None, "cost_change_start": 0,
    }
    summary = {
        "history": [
            {"round": i + 1, "minutes": m, "starts": 1 if s else 0,
             "clearances_blocks_interceptions": 2, "tackles": 1, "recoveries": 3,
             "expected_goals": 0.4, "expected_assists": 0.2, "bonus": 1}
            for i, (m, s) in enumerate(zip(gw_minutes, gw_started))
        ],
        "history_past": [],
    }
    return build_profile(element, summary, CFG, team_matches)


# ------------------------------------------------------------------ prior
def test_egalik_rol_priorini_oshiradi():
    """Ko'p menejer olgan o'yinchi zaxirada o'tirmaydi."""
    assert role_prior(0.5, 6.5) < role_prior(8, 6.5) < role_prior(25, 6.5)
    assert role_prior(25, 6.5) >= 0.75
    assert role_prior(0.3, 4.5) <= 0.45
    # chegaralar
    assert 0.20 <= role_prior(0, 4.0) <= 0.93
    assert role_prior(90, 15.0) <= 0.93


def test_narx_ham_rol_haqida_gapiradi():
    """Egalik past bo'lsa ham, qimmat o'yinchi zaxirada o'tirmaydi."""
    assert role_prior(1.0, 12.0) > role_prior(1.0, 4.5)


def test_otgan_mavsum_hisobga_olinmaydi():
    """use_last_season=False bo'lganda tarix natijaga ta'sir qilmasin."""
    element = {
        "id": 1, "web_name": "T", "team": 1, "element_type": 4, "now_cost": 90,
        "status": "a", "chance_of_playing_next_round": None, "news": "",
        "minutes": 90, "starts": 1, "expected_goals": 0.5, "expected_assists": 0.1,
        "clearances_blocks_interceptions": 1, "tackles": 0, "recoveries": 2,
        "bonus": 1, "saves": 0, "yellow_cards": 0, "selected_by_percent": "20",
        "penalties_order": None, "cost_change_start": 0,
    }
    history = [{"round": 1, "minutes": 90, "starts": 1, "expected_goals": 0.5,
                "expected_assists": 0.1, "bonus": 1,
                "clearances_blocks_interceptions": 1, "tackles": 0, "recoveries": 2}]
    bosh = build_profile(element, {"history": history, "history_past": []}, CFG, 1)
    boy = build_profile(element, {"history": history, "history_past": [
        {"minutes": 3200, "starts": 36, "expected_goals": 20.0, "expected_assists": 8.0}
    ]}, CFG, 1)
    assert bosh.p_start == pytest.approx(boy.p_start)
    assert bosh.xg90 == pytest.approx(boy.xg90)


# ------------------------------------------------------------------ holatlar
def test_ommaviy_arzon_qanot_asosiy_deb_baholanadi():
    """Tzolis holati: 6.5m, 25% egalik, GW1 da 88 daqiqa.

    Eski model 0.33 berardi (o'tgan mavsum natijasi yo'qligi uchun).
    """
    p = profile(price=6.5, position=3, ownership=25.0,
                gw_minutes=(88,), gw_started=(True,))
    assert p.p_start >= 0.78, f"ommaviy asosiy qanot past baholandi: {p.p_start:.2f}"
    assert p.xmins >= 68


def test_ommabop_bolmagan_zaxira_past_qoladi():
    """Kam egalik + zaxiradan qisqa chiqish = past baho."""
    p = profile(price=5.0, position=4, ownership=1.5,
                gw_minutes=(14,), gw_started=(False,))
    assert p.p_start <= 0.35, f"zaxira o'yinchi yuqori baholandi: {p.p_start:.2f}"
    assert p.xmins <= 26


def test_premium_oyinchi_yuqori_baholanadi():
    p = profile(price=12.5, position=3, ownership=45.0, team_matches=2,
                gw_minutes=(90, 87), gw_started=(True, True))
    assert p.p_start >= 0.90
    assert p.p60 >= 0.85


def test_ketma_ket_asosiy_tarkib_ishonchni_oshiradi():
    base = dict(price=6.5, position=3, ownership=12.0)
    one = profile(**base, team_matches=1, gw_minutes=(90,), gw_started=(True,))
    two = profile(**base, team_matches=2, gw_minutes=(90, 90), gw_started=(True, True))
    three = profile(**base, team_matches=3, gw_minutes=(90, 90, 88),
                    gw_started=(True, True, True))
    assert one.p_start < two.p_start < three.p_start
    assert three.p_start >= 0.88


def test_ketma_ketlik_uzilsa_ishonch_tushadi():
    steady = profile(ownership=12.0, team_matches=3,
                     gw_minutes=(90, 90, 90), gw_started=(True, True, True))
    dropped = profile(ownership=12.0, team_matches=3,
                      gw_minutes=(90, 90, 10), gw_started=(True, True, False))
    assert dropped.p_start < steady.p_start


def test_jarohat_xabari_hamma_narsani_bosadi():
    p = profile(position=4, ownership=40.0, gw_minutes=(90,), gw_started=(True,),
                news="Knee injury - Unknown return date", chance=0)
    assert p.p_start == 0.0
    assert p.xmins == 0.0


def test_qisman_shubha_proporsional_pasaytiradi():
    p75 = profile(position=4, ownership=40.0, gw_minutes=(90,), gw_started=(True,),
                  news="Knock - 75% chance", chance=75)
    full = profile(position=4, ownership=40.0, gw_minutes=(90,), gw_started=(True,))
    assert p75.p_start == pytest.approx(full.p_start * 0.75, rel=0.01)


def test_narx_hujum_priorini_belgilaydi():
    """Qimmat hujumchidan ko'proq gol kutiladi — o'yin o'ynamagan bo'lsa ham."""
    arzon = profile(price=4.5, position=4, ownership=2.0)
    qimmat = profile(price=14.0, position=4, ownership=50.0)
    assert qimmat.xg90 > arzon.xg90 * 3


def test_egalik_hujum_chiqimiga_tasir_qilmaydi():
    """Egalik faqat ROL signali. Aks holda model shablonni takrorlardi."""
    kam = profile(price=8.0, position=3, ownership=1.0,
                  gw_minutes=(90,), gw_started=(True,))
    kop = profile(price=8.0, position=3, ownership=55.0,
                  gw_minutes=(90,), gw_started=(True,))
    assert kam.xg90 == pytest.approx(kop.xg90)
    assert kam.xa90 == pytest.approx(kop.xa90)
