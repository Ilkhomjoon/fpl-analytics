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


# ------------------------------------------------ transferlar raqiblarga nisbatan
def test_transfer_belgisi_ommaviy_va_kam_uchraydigan():
    assert bands.move_profile([57], [5])["kind"] == "cover"         # Isak kabi: farqni yopadi
    assert bands.move_profile([4], [40])["kind"] == "differ"        # kam uchraydigan: farq yaratadi
    assert bands.move_profile([20], [18])["kind"] == "neutral"
    # Ikkita transfer: bittasi kam uchrasa, "xavfni yopadi" deyilmaydi
    assert bands.move_profile([60, 5], [10, 10])["kind"] != "cover"
    assert bands.move_profile([57], [5])["cover"] == 52


def _move(gain, cover, worth=True):
    return {"gain": gain, "worth_it": worth, "rank": {"cover": cover}}


def test_tartib_faqat_deyarli_teng_variantlar_orasida_ozgaradi():
    rows = [_move(5.0, -20), _move(4.6, +40), _move(2.0, +80)]
    # Himoya: 0.5 ochko farq chegarada (1.0) — farqni yopadigan oldinga chiqadi
    protect = bands.order_moves([dict(r, rank=dict(r["rank"])) for r in rows],
                                {"mode": "protect", "sacrifice": 0.25}, 4.0)
    assert [r["gain"] for r in protect] == [4.6, 5.0, 2.0]
    assert protect[0]["rank"].get("promoted") is True
    # 3 ochko orqadagi variant hech qachon oldinga chiqmaydi
    assert protect[-1]["gain"] == 2.0


def test_quvishda_farq_yaratadigan_oldinga_chiqadi():
    rows = [_move(5.0, +40), _move(4.6, -20)]
    chase = bands.order_moves(rows, {"mode": "chase", "sacrifice": 0.25}, 4.0)
    assert [r["gain"] for r in chase] == [4.6, 5.0]


def test_muvozanat_yoki_nol_chegara_tartibni_ozgartirmaydi():
    rows = [_move(5.0, -20), _move(4.9, +40)]
    assert bands.order_moves(list(rows), {"mode": "balanced", "sacrifice": 0.5}, 4.0) == rows
    assert bands.order_moves(list(rows), {"mode": "protect", "sacrifice": 0.0}, 4.0) == rows


def test_zararli_variant_rejim_uchun_ham_oldinga_chiqmaydi():
    rows = [_move(0.4, -20), _move(-0.2, +90, worth=False)]
    out = bands.order_moves(rows, {"mode": "protect", "sacrifice": 1.0}, 4.0)
    assert out[0]["gain"] == 0.4


def test_xavf_ostida_qanday_olish_korsatiladi(rank_payload):
    """Har xavf uchun: transfer (kimning o'rniga, foyda), yoki pul yetmasligi, yoki klub chegarasi."""
    assert rank_payload["threats"]
    for threat in rank_payload["threats"]:
        how = threat["how"]
        if how is None:
            continue
        assert ("short" in how and how["short"] > 0) or (
            how["out"] and how["worth_it"] == (how["gain"] > 0))


def test_transfer_takliflarida_raqiblar_belgisi():
    body = create_app(Config(), demo=True).test_client().get("/api/transfers").get_json()
    assert body["rank"]["mode"] in ("protect", "balanced", "chase")
    for move in body["moves"]:
        assert move["rank"]["kind"] in ("cover", "differ", "neutral")
        assert all("eo" in p for p in move["in"] + move["out"])

# ------------------------------------------------------- bir raqibga qarshi
@pytest.fixture(scope="module")
def duel_payload():
    return create_app(Config(), demo=True).test_client().get("/api/duel?rival=100007").get_json()


def test_duel_asosiy_qismlari(duel_payload):
    d = duel_payload
    assert d["rival"]["entry"] == 100007
    assert [e["event"] for e in d["per_event"]] and all(
        abs(e["edge"] - (e["mine"] - e["his"])) < 0.11 for e in d["per_event"])
    assert d["plan"]["mode"] in ("chase", "protect")
    assert 0 <= d["shared"] <= 15
    for key in ("horizon", "season"):
        assert d["ahead"][key] is None or 0 <= d["ahead"][key] <= 100


def test_duel_farq_qiladigan_oyinchilar_kesishmaydi(duel_payload):
    mine = {p["element"] for p in duel_payload["only_mine"]}
    his = {p["element"] for p in duel_payload["only_his"]}
    assert mine and his and not (mine & his)
    # Umumiylar + faqat mendagilar = mening 15 ligim
    assert len(mine) + duel_payload["shared"] == 15


def test_duel_rejasi_farq_yaratish_unda_yoq_oyinchilar(duel_payload):
    his_names = {p["name"] for p in duel_payload["only_his"]}
    differ, cover = duel_payload["plan"]["differ"], duel_payload["plan"]["cover"]
    assert all(m["in"] not in his_names for m in differ)
    assert all(m["in"] in his_names for m in cover)
    assert all(m["gain"] > 0 for m in differ + cover)
    # Bir o'yinchi bir ro'yxatda ikki marta sotilmaydi
    for moves in (differ, cover):
        outs = [m["out"] for m in moves]
        assert len(outs) == len(set(outs))


def test_duel_ozi_bilan_va_idsiz_rad_etiladi():
    client = create_app(Config(), demo=True).test_client()
    assert client.get("/api/duel").status_code == 400
    me = client.get("/api/squad").get_json()["entry_id"]
    assert "error" in client.get(f"/api/duel?rival={me}").get_json()


def test_ehtimol_farq_va_ustunlikka_mos():
    """Katta farq va manfiy ustunlik — past ehtimol; kichik farq va musbat ustunlik — yuqori."""
    from web import rivalsview
    assert rivalsview._normal_cdf(0) == pytest.approx(0.5)
    assert rivalsview._normal_cdf(2) > 0.97 and rivalsview._normal_cdf(-2) < 0.03