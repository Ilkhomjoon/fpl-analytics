"""Pozitsiyaga qarab qiyinlik.

Asosiy fikr: **bitta uchrashuv ikki xil qiyinlikka ega.** Himoyachi uchun
raqibning HUJUMI muhim (gol uradimi?), hujumchi uchun raqibning HIMOYASI
(gol o'tkazadimi?). Bitta raqamni ikkalasiga qo'llash farqni yo'q qiladi.

Haqiqiy misol (GW3, 2026/27 jadvali):

    Leeds          3 o'yin, 3:2   — kam uradi, kam o'tkazadi
    Crystal Palace 3 o'yin, 4:8   — o'rtacha uradi, ko'p o'tkazadi

Leeds ga qarshi himoyachi uchun oson (ular kam gol uradi), hujumchi uchun
qiyin (ular kam gol o'tkazadi). Palace ga qarshi esa aksincha: hujumchi
uchun juda oson.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fplbrain.ratings import (                                    # noqa: E402
    difficulty_for_attack, difficulty_for_defence, positional_difficulty,
)


class Row:
    """Jadvaldagi bitta qator (kerakli qismi)."""

    def __init__(self, played: int, gf: int, ga: int) -> None:
        self.played, self.gf, self.ga = played, gf, ga


LEEDS = Row(3, 3, 2)            # kam uradi, kam o'tkazadi
PALACE = Row(3, 4, 8)           # ko'p o'tkazadi
ARSENAL = Row(3, 7, 1)          # ko'p uradi, kam o'tkazadi


# ------------------------------------------------------- himoya qiyinligi
def test_kam_gol_uradigan_raqib_himoyachiga_oson():
    kuchli_hujum = difficulty_for_defence(1.6, ARSENAL.gf / 3)
    zaif_hujum = difficulty_for_defence(1.0, LEEDS.gf / 3)
    assert zaif_hujum < kuchli_hujum


def test_himoya_qiyinligi_raqibning_otkazgan_goliga_bogliq_emas():
    """Palace ko'p gol o'tkazadi — bu himoyachiga hech narsa bermaydi."""
    a = difficulty_for_defence(1.2, PALACE.gf / 3)      # 1.33 uradi
    b = difficulty_for_defence(1.2, Row(3, 4, 1).gf / 3)  # xuddi shuncha uradi
    assert a == b                                        # o'tkazgani ahamiyatsiz


# ------------------------------------------------------- hujum qiyinligi
def test_kop_gol_otkazadigan_raqib_hujumchiga_oson():
    """`lam_for` ham raqibga bog'liq: teshik himoyaga qarshi ko'proq kutamiz.

    Shuning uchun sinovda ham mos qiymatlar beriladi — 1.2 ni ikkalasiga
    berish haqiqatda uchramaydigan holat bo'lardi.
    """
    mustahkam = difficulty_for_attack(1.1, LEEDS.ga / 3)     # 0.67 o'tkazadi
    teshik = difficulty_for_attack(1.9, PALACE.ga / 3)       # 2.67 o'tkazadi
    assert teshik < mustahkam
    assert teshik < 2.0 and mustahkam > 3.0

    # Faqat jadval o'zgarganda ham tartib saqlanadi
    assert difficulty_for_attack(1.4, PALACE.ga / 3) < difficulty_for_attack(
        1.4, LEEDS.ga / 3)


def test_hujum_qiyinligi_raqibning_urgan_goliga_bogliq_emas():
    a = difficulty_for_attack(1.4, LEEDS.ga / 3)
    b = difficulty_for_attack(1.4, Row(3, 9, 2).ga / 3)   # xuddi shuncha o'tkazadi
    assert a == b


# --------------------------------------------- ikkalasi birga: asosiy holat
def test_bitta_uchrashuv_ikki_xil_qiyinlik():
    """Leeds: himoyachiga oson, hujumchiga qiyin. Aynan shu farq kerak edi."""
    d_def, d_att = positional_difficulty(
        lam_for=1.2, lam_against=0.9, opp_row=LEEDS)
    assert d_def < d_att, (
        f"Leeds ga qarshi himoya {d_def}, hujum {d_att} — farq bo'lishi kerak")


def test_teshik_himoyali_raqib_teskari_natija_beradi():
    """Palace: hujumchiga oson, himoyachiga o'rtacha."""
    d_def, d_att = positional_difficulty(
        lam_for=1.8, lam_against=1.1, opp_row=PALACE)
    assert d_att < d_def


def test_kuchli_jamoa_ikkala_tomondan_ham_qiyin():
    d_def, d_att = positional_difficulty(
        lam_for=0.9, lam_against=1.7, opp_row=ARSENAL)
    assert d_def > 3.0 and d_att > 3.0


def test_jadval_bosh_bolsa_yiqilmaydi():
    d_def, d_att = positional_difficulty(1.4, 1.4, opp_row=None)
    assert 1.0 <= d_def <= 5.0 and 1.0 <= d_att <= 5.0
    d_def, d_att = positional_difficulty(1.4, 1.4, opp_row=Row(0, 0, 0))
    assert 1.0 <= d_def <= 5.0 and 1.0 <= d_att <= 5.0


def test_rasmiy_fdr_mavsum_boshida_kop_vazn_oladi():
    """O'yin kam bo'lsa rasmiy FDR ustunroq, ko'paygani sari so'nadi."""
    boshida = positional_difficulty(1.4, 1.4, Row(1, 1, 1), official_fdr=5)
    keyinroq = positional_difficulty(1.4, 1.4, Row(20, 20, 20), official_fdr=5)
    assert boshida[0] > keyinroq[0]


def test_qiyinlik_chegaradan_chiqmaydi():
    for lam in (0.0, 0.5, 1.4, 3.0, 6.0):
        for row in (LEEDS, PALACE, ARSENAL, Row(3, 0, 0), Row(3, 15, 15)):
            d_def, d_att = positional_difficulty(lam, lam, row, official_fdr=3)
            assert 1.0 <= d_def <= 5.0
            assert 1.0 <= d_att <= 5.0
