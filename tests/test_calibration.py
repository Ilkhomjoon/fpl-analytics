"""Model raqamlari HAQIQIY darajaga to'g'ri keladimi?

Bu testlar modelning ichki mantiqini emas, **kattaligini** tekshiradi.
Mezonlar ochiq manbalardan olingan (FPL Review, FPL Copilot, OpenFPL
maqolasi, Premier League statistikasi):

* o'rtacha menejer bir turda **50-54** ochko oladi (kapitan bilan, zaxirasiz);
* premium yarim himoyachi **6.0-7.3**, mustahkam himoyachi **4.0-5.3**,
  darvozabon **3.0-4.5**, zaxira o'yinchi **2.5 dan past**;
* butun 11 lik + kapitan **48-58** oralig'ida bo'lishi kerak.

Model bu oraliqdan chiqib ketsa, aybdor odatda bitta: bonus, DefCon yoki
60 daqiqalik ochko noto'g'ri hisoblangan bo'ladi.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fplbrain.ev import (              # noqa: E402
    DEF, FWD, GK, MID, expected_floor, poisson_pmf,
)


# --------------------------------------------------- matematik to'g'rilik
def test_toxtatish_ochkosi_ortachani_bolish_emas():
    """E[floor(N/3)] ≠ E[N]/3. Bu 24% ga oshirib yuboradigan xato edi."""
    lam = 3.0
    notogri = lam / 3.0                       # 1.00
    togri = expected_floor(lam, 3)            # 0.665 — qo'lda tekshirilgan
    assert togri < notogri
    assert togri == pytest.approx(0.6646, abs=0.001)
    # Ya'ni o'rtachani bo'lish 50% oshirib yuborar edi
    assert notogri / togri == pytest.approx(1.5, abs=0.05)
    # va o'rtachani bo'lish har doim oshirib ko'rsatadi
    for lam in (1.0, 2.5, 4.0, 5.5):
        assert expected_floor(lam, 3) < lam / 3.0


def test_toxtatish_ochkosi_monoton():
    oldingi = -1.0
    for lam in (0.5, 1.5, 3.0, 4.5, 6.0):
        joriy = expected_floor(lam, 3)
        assert joriy > oldingi
        oldingi = joriy


def test_puasson_yigindisi_bir():
    assert sum(poisson_pmf(k, 2.5) for k in range(30)) == pytest.approx(1.0, abs=1e-6)


# ------------------------------------------------------- ochko jadvali
def test_darvozabon_goli_10_ochko():
    """2024/25 dan beri darvozabon goli 6 emas, 10 ochko."""
    from fplbrain.ev import GOAL_POINTS
    assert GOAL_POINTS[GK] == 10
    assert GOAL_POINTS[DEF] == 6
    assert GOAL_POINTS[MID] == 5
    assert GOAL_POINTS[FWD] == 4


def test_defcon_chegaralari_qoidaga_mos():
    """Himoyachi 10 CBIT, yarim himoyachi/hujumchi 12 CBIRT."""
    from fplbrain.ev import DEFCON_THRESHOLD
    assert DEFCON_THRESHOLD[DEF] == 10
    assert DEFCON_THRESHOLD[MID] == 12
    assert DEFCON_THRESHOLD[FWD] == 12
    assert GK not in DEFCON_THRESHOLD          # darvozabonda DefCon yo'q


# ------------------------------------------------------- kattalik mezonlari
def test_11_lik_ochkosi_haqiqiy_oralikda(world):
    """11 lik + kapitan ~48-58 oralig'ida bo'lishi kerak.

    O'rtacha menejer turiga 50-54 ochko oladi. Model 30 larda javob bersa —
    biror qism tushib qolgan; 70 larda javob bersa — oshirib yuborilgan.
    """
    from fplbrain.squad import best_eleven
    from tests.conftest import make_squad

    squad = make_squad(world)
    xi, _, _, xi_ev = best_eleven(squad.players, 3)
    kapitan = max(p.ev.per_event.get(3, 0.0) for p in xi)
    jami = xi_ev + kapitan
    assert 30 < jami < 75, f"11 lik + kapitan = {jami:.1f} — haqiqiy darajadan uzoq"


def test_pozitsiyalar_tartibi_haqiqiy(world):
    """Hujumchi > yarim himoyachi ~ himoyachi > darvozabon emas.

    Aniq qiymatlar soxta dunyoda tasodifiy, lekin TARTIB saqlanishi kerak:
    mustahkam o'yinchilar zaxiradagilardan yuqori.
    """
    ev = world["ev"]
    mustahkam = [p.next_ev for p in ev.values() if p.profile.p_start > 0.85]
    zaxira = [p.next_ev for p in ev.values() if p.profile.p_start < 0.30]
    assert sum(mustahkam) / len(mustahkam) > 2.0
    assert sum(zaxira) / len(zaxira) < 2.5
