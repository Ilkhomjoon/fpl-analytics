"""Jadval zichligi va rotatsiya xavfi."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fplbrain import congestion                                   # noqa: E402
from fplbrain.ev import ROTATION_NEUTRAL, _rotation_adjust        # noqa: E402


def fixture(team_h: int, team_a: int, kickoff: str) -> dict:
    return {"team_h": team_h, "team_a": team_a, "kickoff_time": kickoff}


# Bir jamoa (1) uchun uch xil jadval
BEMALOL = [                              # har hafta bitta o'yin
    fixture(1, 2, "2026-09-05T14:00:00Z"),
    fixture(3, 1, "2026-09-12T14:00:00Z"),
    fixture(1, 4, "2026-09-19T14:00:00Z"),
]
ZICH = [                                 # shanba → chorshanba → shanba
    fixture(1, 2, "2026-09-05T14:00:00Z"),
    fixture(3, 1, "2026-09-09T19:00:00Z"),
    fixture(1, 4, "2026-09-12T14:00:00Z"),
    fixture(5, 1, "2026-09-16T19:00:00Z"),
]


def test_bemalol_jadvalda_rotatsiya_xavfi_yoq():
    sch = congestion.build_schedules(BEMALOL)
    risk = congestion.rotation_risk(sch[1], "2026-09-12T14:00:00Z")
    assert risk == 0.0


def test_zich_jadvalda_xavf_yuqori():
    sch = congestion.build_schedules(ZICH)
    risk = congestion.rotation_risk(sch[1], "2026-09-09T19:00:00Z")
    assert risk > 0.5, f"chorshanba o'yinida xavf past chiqdi: {risk}"


def test_keyingi_oyin_yaqin_bolsa_ham_xavf_bor():
    """Bugun dam yetarli, lekin 3 kundan keyin yana o'yin bo'lsa — asraydi."""
    sch = congestion.build_schedules(ZICH)
    risk = congestion.rotation_risk(sch[1], "2026-09-05T14:00:00Z")
    assert risk > 0.0


def test_yevropa_xavfni_oshiradi():
    sch = congestion.build_schedules(BEMALOL)
    oddiy = congestion.rotation_risk(sch[1], "2026-09-12T14:00:00Z", in_europe=False)
    yevropa = congestion.rotation_risk(sch[1], "2026-09-12T14:00:00Z", in_europe=True)
    assert yevropa > oddiy


def test_xavf_har_doim_0_1_oraligida():
    sch = congestion.build_schedules(ZICH)
    for f in ZICH:
        risk = congestion.rotation_risk(sch[1], f["kickoff_time"], in_europe=True)
        assert 0.0 <= risk <= 1.0


def test_vaqt_yoq_bolsa_yiqilmaydi():
    assert congestion.rotation_risk(None, None) == 0.0
    assert congestion.build_schedules([{"team_h": 1, "team_a": 2}]) == {}
    assert congestion.rotation_risk(None, "buzuq-sana") == 0.0


# ---------------------------------------------------- jamoa nomlarini o'qish
TEAMS = [{"id": 1, "short_name": "ARS", "name": "Arsenal"},
         {"id": 2, "short_name": "LIV", "name": "Liverpool"},
         {"id": 3, "short_name": "BUR", "name": "Burnley"}]


def test_yevropa_royxati_nom_va_id_ni_tushunadi():
    class Cfg:
        european_teams = ["ARS", "Liverpool", 3]
    assert congestion.european_team_ids(Cfg(), TEAMS) == {1, 2, 3}


def test_yevropa_royxati_bosh_bolsa_hech_kim_belgilanmaydi():
    class Cfg:
        european_teams = []
    assert congestion.european_team_ids(Cfg(), TEAMS) == set()


def test_notanish_nom_etiborsiz_qoladi():
    class Cfg:
        european_teams = ["ARS", "Real Madrid"]
    assert congestion.european_team_ids(Cfg(), TEAMS) == {1}


# ------------------------------------------------------- EV ga ta'siri
class FakeProfile:
    def __init__(self, p_start, p60, xmins):
        self.p_start, self.p60, self.xmins = p_start, p60, xmins


def test_rotatsiya_mustahkam_oyinchini_pasaytiradi():
    p = FakeProfile(0.95, 0.90, 85)
    p_start, p60, share = _rotation_adjust(p, 1.0)
    assert p_start < 0.95
    assert p60 < 0.90
    assert share < 85 / 90


def test_rotatsiya_chetdagi_oyinchini_kotaradi():
    """Rotatsiya jazo emas: kimdir tushsa, kimdir ko'tariladi."""
    p = FakeProfile(0.30, 0.20, 30)
    p_start, _, _ = _rotation_adjust(p, 1.0)
    assert p_start > 0.30
    assert p_start < ROTATION_NEUTRAL      # neytraldan oshib ketmaydi


def test_xavf_nol_bolsa_hech_narsa_ozgarmaydi():
    p = FakeProfile(0.95, 0.90, 85)
    assert _rotation_adjust(p, 0.0) == (0.95, 0.90, 85 / 90)


def test_zichlik_fixture_view_gacha_yetib_boradi(world):
    """Uchidan-uchiga: zich jadval → FixtureView.rotation → pastroq EV."""
    from fplbrain import ratings as ratings_mod

    cfg, ratings = world["cfg"], world["rt"]
    ikki = sorted(ratings)[:2]

    zich = [
        {"event": 3, "team_h": ikki[0], "team_a": ikki[1], "finished": False,
         "kickoff_time": "2026-09-05T14:00:00Z",
         "team_h_difficulty": 3, "team_a_difficulty": 3},
        {"event": 4, "team_h": ikki[1], "team_a": ikki[0], "finished": False,
         "kickoff_time": "2026-09-08T19:00:00Z",       # 3 kundan keyin
         "team_h_difficulty": 3, "team_a_difficulty": 3},
    ]
    views = ratings_mod.build_fixture_views(
        zich, ratings, cfg, 3, 4,
        schedules=congestion.build_schedules(zich),
        european=set(),
    )
    assert views[ikki[0]][4][0].rotation > 0.5

    # Zichliksiz o'sha uchrashuv — xavf 0
    tinch = ratings_mod.build_fixture_views(zich, ratings, cfg, 3, 4)
    assert tinch[ikki[0]][4][0].rotation == 0.0


def test_ehtimollar_chegaradan_chiqmaydi():
    for p_start, p60 in ((1.0, 1.0), (0.0, 0.0), (0.5, 0.5)):
        a, b, c = _rotation_adjust(FakeProfile(p_start, p60, 90), 1.0)
        assert 0.0 <= a <= 1.0
        assert 0.0 <= b <= a + 1e-9        # p60 hech qachon p_start dan oshmaydi
        assert c >= 0.0
