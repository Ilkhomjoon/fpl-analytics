"""Forma modelga qanday kiradi.

Forma — FPL ning "form" maydoni, ya'ni so'nggi 30 kunda olingan **ochko**.
Bu natija, bashorat emas: xG dan ortiq urgan o'yinchi keyingi turda
o'rtachaga qaytadi. Shuning uchun u modelni boshqarmaydi, faqat biroz
suradi — xG hali ko'rmagan o'zgarishni (yangi rol, penalti huquqi) ushlab
qolish uchun.

Uchta narsa tekshiriladi:

1. Forma yuqori bo'lsa EV **biroz** ortadi;
2. Ta'sir **cheklangan** — yaxshi forma zaif asosni qoplab ketolmaydi;
3. `form_weight: 0` bo'lsa model butunlay eski holatga qaytadi.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fplbrain.config import Config                                # noqa: E402
from fplbrain.ev import (                                         # noqa: E402
    build_profile, form_baseline, form_multiplier,
)


# ------------------------------------------------------------ koeffitsiyent
def test_ortacha_forma_hech_narsani_ozgartirmaydi():
    assert form_multiplier(3.5, 3.5, 0.10) == pytest.approx(1.0)


def test_yuqori_forma_kotaradi_past_forma_tushiradi():
    assert form_multiplier(7.0, 3.5, 0.10) > 1.0
    assert form_multiplier(1.0, 3.5, 0.10) < 1.0


def test_tasir_cheklangan():
    """Forma qanchalik baland bo'lmasin, ±10% dan oshmaydi."""
    for form in (0.0, 0.1, 5.0, 12.0, 50.0):
        m = form_multiplier(form, 3.5, 0.10)
        assert 0.90 <= m <= 1.10


def test_vazn_nol_bolsa_ochiriladi():
    for form in (0.0, 3.5, 12.0):
        assert form_multiplier(form, 3.5, 0.0) == 1.0


def test_baza_yoq_bolsa_yiqilmaydi():
    assert form_multiplier(9.0, 0.0, 0.10) == 1.0


# ------------------------------------------------------------------- baza
def test_baza_mediana_va_kam_oynaganlarni_sanamaydi():
    elements = [
        {"form": "5.0", "minutes": 900},
        {"form": "3.0", "minutes": 900},
        {"form": "1.0", "minutes": 900},
        {"form": "99.0", "minutes": 20},      # bir o'yin chiqqan — sanalmaydi
    ]
    assert form_baseline(elements) == 3.0
    assert form_baseline([]) == 0.0
    assert form_baseline([{"form": "9.0", "minutes": 10}]) == 0.0


# ------------------------------------------------------- profilga ta'siri
def _element(form: str, **kwargs) -> dict:
    base = {
        "id": 1, "web_name": "Test", "first_name": "T", "second_name": "P",
        "team": 1, "element_type": 3, "now_cost": 70, "status": "a",
        "minutes": 900, "starts": 10, "form": form,
        "expected_goals": "3.0", "expected_assists": "2.0",
        "selected_by_percent": "10.0", "bonus": 6,
    }
    base.update(kwargs)
    return base


def test_forma_hujum_tezligini_suradi():
    cfg = Config()
    zaif = build_profile(_element("1.0"), None, cfg, 10, form_base=3.5)
    kuchli = build_profile(_element("8.0"), None, cfg, 10, form_base=3.5)
    assert kuchli.xg90 > zaif.xg90
    assert kuchli.xa90 > zaif.xa90
    assert kuchli.bonus90 > zaif.bonus90
    # lekin farq kichik — bu xG ni almashtirmaydi
    assert kuchli.xg90 / zaif.xg90 < 1.25


def test_forma_daqiqalarga_tegmaydi():
    """Daqiqalarning o'z modeli bor — forma unga aralashmasligi kerak."""
    cfg = Config()
    zaif = build_profile(_element("0.5"), None, cfg, 10, form_base=3.5)
    kuchli = build_profile(_element("9.0"), None, cfg, 10, form_base=3.5)
    assert kuchli.p_start == zaif.p_start
    assert kuchli.p60 == zaif.p60
    assert kuchli.xmins == zaif.xmins


def test_forma_yomon_asosni_qoplamaydi():
    """Yuqori forma, lekin past xG — bu past xG li o'yinchini yuqoriga chiqarmasin."""
    cfg = Config()
    kam_xg_yaxshi_forma = build_profile(
        _element("9.0", expected_goals="0.5", expected_assists="0.3"),
        None, cfg, 10, form_base=3.5)
    kop_xg_yomon_forma = build_profile(
        _element("1.0", expected_goals="6.0", expected_assists="4.0"),
        None, cfg, 10, form_base=3.5)
    assert kop_xg_yomon_forma.xg90 > kam_xg_yaxshi_forma.xg90


def test_sozlama_ochirilsa_model_eski_holatiga_qaytadi():
    cfg_on, cfg_off = Config(), Config()
    cfg_off.form_weight = 0.0
    a = build_profile(_element("9.0"), None, cfg_off, 10, form_base=3.5)
    b = build_profile(_element("0.5"), None, cfg_off, 10, form_base=3.5)
    assert a.xg90 == b.xg90                    # forma umuman ta'sir qilmaydi
    c = build_profile(_element("9.0"), None, cfg_on, 10, form_base=3.5)
    assert c.xg90 > a.xg90                     # yoqilganda esa qiladi
