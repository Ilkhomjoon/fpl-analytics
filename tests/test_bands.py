"""O'rin oraliqlari va o'ringa mos maslahat."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fplbrain import bands
from fplbrain.config import Config
from fplbrain.demo import FakeClient
from web.app import create_app

TOTAL = 11_000_000


# ------------------------------------------------------------------ oraliq
def test_oraliq_chegaralari():
    assert bands.band_for(1, TOTAL).label == "top 1k"
    assert bands.band_for(1_000, TOTAL).high == 1_000          # chegara yaxshi oraliqqa kiradi
    assert bands.band_for(1_001, TOTAL).low == 1_000
    band = bands.band_for(1_817_762, TOTAL)
    assert (band.low, band.high) == (1_000_000, 2_000_000)
    assert band.label == "1 mln – 2 mln"
    # Eng pastdagi oraliq butun qolgan jadvalni qamraydi
    last = bands.band_for(9_500_000, TOTAL)
    assert last.low == 4_000_000 and last.high == TOTAL


def test_kichik_ligada_ham_oraliq_topiladi():
    """Mavsum boshi yoki kichik o'yin: chegaralar o'yinchilar sonidan oshmaydi."""
    band = bands.band_for(700, 5_000)
    assert band.low == 1 and band.high == 1_000
    assert bands.band_for(4_000, 5_000).high == 5_000


def test_namuna_orinlari_oraliq_ichida_va_tarqalgan():
    band = bands.band_for(1_500_000, TOTAL)
    ranks = bands.sample_ranks(band)
    assert len(ranks) == bands.PAGES and ranks == sorted(ranks)
    assert all(band.low < r < band.high for r in ranks)
    assert ranks[-1] - ranks[0] > (band.high - band.low) * 0.7


# ------------------------------------------------------------- o'rin hisobi
def test_zichlik_bir_xil_ochkoli_sahifalarda_ham_hisoblanadi():
    """Pastki oraliqlarda yuz minglab jamoa bir xil ochkoda: farq 0 bo'lib qolmasin."""
    anchors = [(1_000_000, 645), (1_500_000, 630), (1_812_000, 622), (1_817_762, 622),
               (1_940_000, 617)]
    density = bands.rank_density(anchors, 1_817_762)
    assert density == pytest.approx((1_940_000 - 1_812_000) / 5)


def test_zichlik_malumot_yetmasa_nol():
    assert bands.rank_density([], 100) == 0.0
    assert bands.rank_density([(100, 50)], 100) == 0.0


def test_orin_prognozi_yonalishi_va_chegaralari():
    assert bands.projected_rank(100_000, +2.0, 5_000, TOTAL) == 90_000     # ustunlik → yuqoriga
    assert bands.projected_rank(100_000, -2.0, 5_000, TOTAL) == 110_000
    assert bands.projected_rank(100, +50.0, 5_000, TOTAL) == 1             # 1 dan yuqori bo'lmaydi
    assert bands.projected_rank(TOTAL - 10, -50.0, 5_000, TOTAL) == TOTAL


# ------------------------------------------------------------ xavf darajasi
def test_moslash_mavsum_oxiriga_qarab_kuchayadi():
    assert bands.adapt_intensity(5) == bands.MIN_INTENSITY
    assert bands.adapt_intensity(19) == bands.MIN_INTENSITY
    assert bands.MIN_INTENSITY < bands.adapt_intensity(27) < 1.0
    assert bands.adapt_intensity(34) == 1.0 == bands.adapt_intensity(38)


def test_xavf_rejimi_oringa_bogliq():
    assert bands.risk_advice(50_000, TOTAL, 30)["mode"] == "protect"
    assert bands.risk_advice(600_000, TOTAL, 30)["mode"] == "balanced"
    assert bands.risk_advice(3_000_000, TOTAL, 30)["mode"] == "chase"
    assert bands.risk_advice(None, None, 30)["mode"] == "balanced"


def test_himoyada_ev_dan_voz_kechilmaydi():
    """O'rinni saqlayotgan menejerga farq qiluvchi tanlov uchun EV yo'qotish tavsiya etilmaydi."""
    assert bands.risk_advice(50_000, TOTAL, 36)["sacrifice"] == 0.0


def test_mavsum_boshida_tavakkal_deyarli_nol():
    early = bands.risk_advice(3_000_000, TOTAL, 11)
    late = bands.risk_advice(3_000_000, TOTAL, 36)
    assert early["sacrifice"] < 0.25 < late["sacrifice"]
    assert "yumshoq" in early["stage"]


# ------------------------------------------------------------------ namuna
def test_namuna_egalik_kapitan_va_chiplarni_beradi():
    client = FakeClient()
    band = bands.band_for(245_133, 9_730_161)
    sample = bands.load_band(client, Config(), band, event=2, next_event=3)
    assert sample["size"] == bands.PAGES * bands.PER_PAGE
    assert sample["squads"] and len(sample["squads"][0]) == 15
    eo = bands.effective_ownership(sample)
    assert eo and all(0 <= v <= 2 for v in eo.values())
    # Kapitanliklar yig'indisi — har jamoada bitta kapitan
    assert sum(sample["captaincy"].values()) == pytest.approx(100, abs=1)
    assert set(sample["chips_used"]) <= {"wildcard", "bboost", "3xc", "freehit"}


def test_soxta_klient_diskka_kesh_yozmaydi(tmp_path):
    """Demo/test tarkiblari haqiqiy namuna o'rniga diskda qolib ketmasligi kerak."""
    cfg = Config()
    cfg.cache_dir = tmp_path
    bands.load_band(FakeClient(), cfg, bands.band_for(245_133, 9_730_161), 2, 3)
    assert not (tmp_path / "bands").exists()


# --------------------------------------------------------------------- web
@pytest.fixture(scope="module")
def rank_payload():
    return create_app(Config(), demo=True).test_client().get("/api/rank").get_json()


def test_orin_sahifasi_asosiy_qismlari(rank_payload):
    body = rank_payload
    assert body["rank"] == 245_133 and body["band"]["size"] > 0
    assert body["risk"]["mode"] in ("protect", "balanced", "chase")
    for key in ("mine", "field", "edge", "beat", "rank_after", "rank_change"):
        assert key in body["projection"]
    assert body["captain"]["pick"] and body["captain"]["why"]
    assert [c["chip"] for c in body["chips"]] == ["wildcard", "bboost", "3xc", "freehit"]


def test_xavf_menda_yoq_imkoniyat_asosiy_tarkibda(rank_payload):
    assert all(not r["mine"] and r["swing"] < 0 for r in rank_payload["threats"])
    assert all(r["in_xi"] and r["swing"] > 0 for r in rank_payload["chances"])
    # Eng katta xavf birinchi turadi
    swings = [r["swing"] for r in rank_payload["threats"]]
    assert swings == sorted(swings)


def test_orin_entry_id_siz_401():
    assert create_app(Config(), demo=False).test_client().get("/api/rank").status_code == 401


def test_ishlatilgan_chiplar_tarixdan_olinadi():
    """Loginsiz ham: to'rt chipini ishlatgan menejerga "hammasi mavjud" deyilmasin."""
    from types import SimpleNamespace
    from web import squadview

    class Client:
        def entry_history(self, entry_id):
            return {"chips": [{"name": n, "event": e} for n, e in
                              (("bboost", 1), ("3xc", 3), ("wildcard", 5), ("freehit", 8))]}

    squad = SimpleNamespace(chips_available=[], authenticated=False)
    assert squadview.chips_left(Client(), 1, squad, 11) == []
    # Ikkinchi yarim yillikda (GW20+) chiplar yangilanadi
    assert len(squadview.chips_left(Client(), 1, squad, 20)) == 4
