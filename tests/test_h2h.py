"""H2H: tarkibni o'qish, FPL qoidalari bo'yicha hisob va aniq jamoa tuzuvchi."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fplbrain import builder, h2h
from fplbrain.config import Config
from fplbrain.ev import PlayerEV, PlayerProfile

GK, DEF, MID, FWD = 1, 2, 3, 4


def _element(i, name, pos, own=5.0, second=None, cost=50):
    return {"id": i, "web_name": name, "second_name": second or name, "first_name": "A",
            "element_type": pos, "selected_by_percent": str(own), "status": "a",
            "now_cost": cost}


ELEMENTS = [
    _element(1, "Raya", GK), _element(2, "Dubravka", GK),
    _element(3, "Gabriel", DEF, own=40), _element(4, "Gabriel", DEF, own=1, second="Gabriel Jesus"),
    _element(5, "Tarkowski", DEF), _element(6, "De Cuyper", DEF),
    _element(7, "Konsa", DEF), _element(8, "Van Hecke", DEF),
    _element(9, "Rogers", MID), _element(10, "Tavernier", MID),
    _element(11, "Dewsbury-Hall", MID), _element(12, "Groß", MID), _element(13, "Gomez", MID),
    _element(14, "Haaland", FWD), _element(15, "Barry", FWD), _element(16, "Evanilson", FWD),
]
POSITIONS = {e["id"]: e["element_type"] for e in ELEMENTS}
TEXT = ("Raya, Gabriel, Tarkowski, De Cupyer, Rogers, Tavernier (v), Dewsburry-hall, "
        "Grob, Haaland (c), Barry, Evanilson | Dubravka, Konsa, Van Hecke, Gomez")


# ------------------------------------------------------------------ o'qish
def test_tarkib_imlo_xatolari_bilan_ham_oqiladi():
    """Jadvaldagi yozuv: «De Cupyer», «Dewsburry-hall», «Grob» (Groß)."""
    lineup, errors = h2h.parse_lineup(TEXT, ELEMENTS)
    assert errors == []
    assert lineup.xi == [1, 3, 5, 6, 9, 10, 11, 12, 14, 15, 16]
    assert lineup.bench == [2, 7, 8, 13]
    assert lineup.captain == 14 and lineup.vice == 10


def test_bir_xil_ismda_mashhuri_olinadi():
    ids, missing = h2h.resolve_names(["Gabriel"], ELEMENTS)
    assert ids == [3] and missing == []


def test_notanish_ism_xato_beradi_va_taxmin_qilinmaydi():
    lineup, errors = h2h.parse_lineup(TEXT.replace("Barry", "Zzzzqqq"), ELEMENTS)
    assert any("Zzzzqqq" in e for e in errors)


def test_kapitansiz_yoki_notogri_sonli_tarkib_rad_etiladi():
    _, errors = h2h.parse_lineup(TEXT.replace(" (c)", ""), ELEMENTS)
    assert any("kapitan" in e for e in errors)
    _, errors = h2h.parse_lineup(TEXT.replace("Evanilson |", "|"), ELEMENTS)
    assert any("11 emas" in e for e in errors)


# ------------------------------------------------------------------- hisob
def _lineup() -> h2h.Lineup:
    return h2h.parse_lineup(TEXT, ELEMENTS)[0]


def _stats(**over) -> dict:
    stats = {i: (90, 2) for i in POSITIONS}
    stats.update(over)
    return stats


def test_kapitan_ikkilanadi():
    stats = _stats()
    stats[14] = (90, 10)
    result = h2h.score_lineup(_lineup(), stats, POSITIONS)
    assert result["points"] == 10 * 2 + 10 * 2          # 10 o'yinchi × 2 + kapitan 10 × 2
    assert result["armband"] == 14 and result["subs"] == []


def test_kapitan_oynamasa_vitse_ikkilanadi():
    stats = _stats()
    stats[14] = (0, 0)                                   # Haaland o'ynamadi
    stats[10] = (90, 7)                                  # vitse Tavernier
    result = h2h.score_lineup(_lineup(), stats, POSITIONS)
    assert result["armband"] == 10
    # Haaland o'rniga zaxiradagi birinchi mos o'yinchi (Konsa) chiqadi
    assert result["subs"] == [(14, 7)]
    assert result["points"] == 9 * 2 + 7 * 2 + 2


def test_avtoalmashtirish_sxemani_buzmaydi():
    """Uch himoyachidan biri o'ynamasa, o'rniga yarim himoyachi chiqa olmaydi."""
    lineup = _lineup()
    lineup.bench = [2, 13, 7, 8]                         # zaxirada birinchi — Gomez (YAR)
    stats = _stats()
    stats[5] = (0, 0)                                    # Tarkowski o'ynamadi: 2 HIM qoladi
    result = h2h.score_lineup(lineup, stats, POSITIONS)
    assert result["subs"] == [(5, 7)]                    # Gomez emas, Konsa


def test_darvozabon_faqat_darvozabon_bilan_almashadi():
    stats = _stats()
    stats[1] = (0, 0)
    stats[2] = (90, 6)
    result = h2h.score_lineup(_lineup(), stats, POSITIONS)
    assert result["subs"] == [(1, 2)]


def test_oynamagan_zaxira_chiqmaydi():
    stats = _stats()
    stats[15] = (0, 0)                                   # Barry o'ynamadi
    stats[7] = (0, 0)                                    # Konsa ham
    result = h2h.score_lineup(_lineup(), stats, POSITIONS)
    assert result["subs"] == [(15, 8)]                   # keyingisi — Van Hecke


def test_jadval_qoidasi_zaxirasiz_va_vitsesiz():
    """Ekspertlar jadvali: 11 lik + kapitan. O'ynamagan kapitan 0 × 2 = 0, almashtirish yo'q."""
    stats = _stats()
    stats[14] = (0, 0)
    result = h2h.score_lineup(_lineup(), stats, POSITIONS, autosubs=False)
    assert result["subs"] == [] and result["armband"] == 14
    assert result["points"] == 10 * 2


# ----------------------------------------------------------- jadval (xlsx)
def test_taxallus_va_bosh_harfli_ism_topiladi():
    elements = ELEMENTS + [
        _element(20, "Calvert-Lewin", FWD),
        {**_element(21, "Andrey Santos", MID, second="Santos"), "first_name": "Andrey"},
        {**_element(22, "Santos", MID, second="Santos"), "first_name": "Bruno"},
    ]
    index = h2h.build_index(elements)
    assert [e["id"] for e in h2h.find_candidates("DCL", index)] == [20]
    assert [e["id"] for e in h2h.find_candidates("CLW", index)] == [20]
    assert [e["id"] for e in h2h.find_candidates("A.Santos", index)] == [21]


def _workbook(path):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "7"
    head = ["Darvozabonlar", "1-o'rin", "2-o'rin", "GW Team", "Foiz", "Ballar"]
    blocks = [
        [("Raya", 1, 1, 1, 6)],
        [("Gabriel", 1, 1, 1, 8), ("Tarkowski", 1, 0, 1, 2), ("De Cupyer", 1, 1, 1, 6),
         ("Konsa", 0, 1, 0, 1)],
        [("Rogers", 1, 1, 1, 2), ("Tavernier", 1, 1, 1, 3), ("Dewsburry-hall", 1, 1, 1, 9),
         ("Grob", 1, 1, 1, 10)],
        [("Haaland", 2, 1, 2, 2), ("Barry", 1, 2, 1, 16), ("Evanilson", 1, 1, 1, 9)],
    ]
    sheet.append([])
    for n, block in enumerate(blocks):
        sheet.append(head if n == 0 else ["Column1", "Column2", "Column3", "Column4", "Foiz", "Ballar"])
        for name, a, b, team, ball in block:
            sheet.append([name, a or None, b or None, team or None, 1.0, ball, None, "Maestro"])
        sheet.append([])
    sheet.append([None, 12, 12, 12])
    sheet.append([None, 75, 88, 75])
    empty = book.create_sheet("8")                      # hali to'ldirilmagan tur
    empty.append(head)
    book.save(path)


def test_jadvaldan_tarkib_va_kapitan_oqiladi(tmp_path):
    path = tmp_path / "gw.xlsx"
    _workbook(path)
    records = h2h.read_workbook(path, ELEMENTS)
    assert [r["gw"] for r in records] == [7]            # bo'sh varaq tashlab ketiladi
    rec = records[0]
    assert rec["missing"] == []
    assert rec["team"].xi == [1, 3, 5, 6, 9, 10, 11, 12, 14, 15, 16]
    assert rec["team"].captain == 14
    assert rec["experts"][1].captain == 15 and 7 in rec["experts"][1].xi
    assert rec["sheet_scores"][-1] == 75
    stats = {i: (90, p) for i, p in rec["sheet_points"].items()}
    assert h2h.score_lineup(rec["team"], stats, POSITIONS, autosubs=False)["points"] == 75


def test_adash_familiya_ochko_boyicha_ajratiladi(tmp_path):
    """Ikki «Gabriel»: jadvaldagi «Ballar» qaysi biri ekanini aytadi."""
    path = tmp_path / "gw.xlsx"
    _workbook(path)
    points = {7: {3: 1, 4: 8}}                          # 8 ochkoni kam egalikdagisi olgan
    rec = h2h.read_workbook(path, ELEMENTS, points)[0]
    assert 4 in rec["team"].xi and 3 not in rec["team"].xi


def test_shaxsiy_tanlovlar_alohida_papkada(tmp_path):
    h2h.save_private(tmp_path, 7, [{"xi": [1], "manager": "Maestro"}])
    assert h2h.load_private(tmp_path, 7)[0]["manager"] == "Maestro"
    assert "h2h_private" in str(h2h.private_path(tmp_path, 7))
    assert h2h.all_records(tmp_path) == []              # ochiq yozuvlarga aralashmaydi


# ----------------------------------------------------------------- saqlash
def test_ikki_tomon_bitta_faylda_va_bir_birini_ochirmaydi(tmp_path):
    lineup = _lineup()
    h2h.save(tmp_path, 11, "experts", lineup)
    h2h.save(tmp_path, 11, "model", lineup, note="narx 99.5m")
    record = h2h.load(tmp_path, 11)
    assert h2h.Lineup.from_dict(record["experts"]).captain == 14
    assert record["model"]["note"] == "narx 99.5m"
    assert [r["gw"] for r in h2h.all_records(tmp_path)] == [11]


# ------------------------------------------------------- aniq jamoa tuzuvchi
def _pev(i, pos, price, ev, team) -> PlayerEV:
    profile = PlayerProfile(
        element=i, name=f"P{i}", team=team, position=pos, price=price, status="a",
        availability=1.0, p_start=0.9, p_appear=0.95, p60=0.85, xmins=80.0,
        xg90=0.1, xa90=0.1, dc90=5.0, dc_hit_rate=None, bonus90=0.2, saves90=0.0,
        yellow90=0.1, is_pen_taker=False, is_set_piece=False, minutes=900, nineties=10.0)
    return PlayerEV(profile=profile, per_event={1: ev}, fixtures={}, horizon_ev=ev, next_ev=ev)


def _market() -> list[PlayerEV]:
    """Arzon o'rtamiyona o'yinchilar + bitta juda qimmat yulduz.

    Yulduzni olish uchun bir necha o'rinni birdan arzonlashtirish kerak —
    mahalliy qidiruv aynan shu yerda tiqilib qolardi.
    """
    out, i = [], 1
    for pos, count in ((GK, 4), (DEF, 10), (MID, 10), (FWD, 6)):
        for n in range(count):
            # ikki narx pog'onasi: 4.5m → 2.5 ochko, 7.0m → 4.0 ochko
            pricey = n % 2 == 0
            out.append(_pev(i, pos, 7.0 if pricey else 4.5, 4.0 if pricey else 2.5, team=i))
            i += 1
    out.append(_pev(i, FWD, 15.0, 9.0, team=i))
    return out


def test_aniq_yechim_qonuniy_va_yulduzni_oladi():
    pytest.importorskip("pulp")
    cfg = Config()
    market = _market()
    built = builder.build_squad(market, [1], cfg, budget=85.0)
    assert built is not None and built.legal(85.0)
    assert built.captain.element == market[-1].element       # 15.0m lik yulduz kapitan


def test_aniq_yechim_mahalliy_qidiruvdan_yomon_emas():
    pytest.importorskip("pulp")
    cfg = Config()
    market = _market()
    exact = builder.build_squad(market, [1], cfg, budget=85.0)
    local = builder.build_squad(market, [1], cfg, budget=85.0, exact=False)
    assert exact.objective >= local.objective - 1e-6


# ------------------------------------------------------------ web ko'rinishi
class _LiveClient:
    """`h2hview` ga yetarli soxta klient: bootstrap + tur natijalari."""

    def bootstrap(self):
        return {"elements": ELEMENTS,
                "events": [{"id": 7, "finished": True, "average_entry_score": 50},
                           {"id": 8, "finished": False, "average_entry_score": 0}]}

    def event_live(self, gw):
        return {"elements": [{"id": i, "stats": {"minutes": 90, "total_points": 2}}
                             for i in POSITIONS]}


def test_h2h_korinishi_jonli_va_orqaga_qarabni_ajratadi(tmp_path):
    from fplbrain.config import Config as _Config
    from web import h2hview
    cfg = _Config()
    cfg.store_dir = tmp_path
    lineup = _lineup()
    h2h.save(tmp_path, 7, "experts", lineup)
    record = h2h.load(tmp_path, 7)
    record["model_backtest"] = lineup.as_dict()            # orqaga qarab tuzilgan
    h2h.path_for(tmp_path, 7).write_text(__import__("json").dumps(record), encoding="utf-8")
    h2h.save(tmp_path, 8, "model", lineup)                 # jonli, hali o'ynalmagan
    h2h.save_private(tmp_path, 7, [lineup.as_dict(), lineup.as_dict()])

    body = h2hview.build(_LiveClient(), cfg)
    done, coming = body["rows"]
    assert done["gw"] == 7 and done["live"] is False
    assert done["model"]["points"] == done["experts"]["points"] == 24   # 11 × 2 + kapitan 2
    assert done["diff"] == 0 and done["model_rank"] == 1 and done["field"] == 3
    assert coming["live"] is True and coming["model"]["points"] is None
    assert body["upcoming"]["gw"] == 8
    # Jonli hisobga faqat muzlatilgan turlar kiradi
    assert body["totals"]["n"] == 1 and body["totals"]["live_n"] == 0
    assert body["enough"] is False

def test_kutilma_11_lik_va_kapitan_ikkilanadi():
    """Ekspertlar tarkibi ham model bahosi bilan o'lchanadi — modelniki bilan bir xil qoida."""
    from types import SimpleNamespace
    lineup = _lineup()
    evs = {i: SimpleNamespace(per_event={12: 3.0}) for i in lineup.xi}
    evs[lineup.captain] = SimpleNamespace(per_event={12: 7.0})
    evs.pop(lineup.xi[0])                                # bahosi yo'q o'yinchi — 0
    assert h2h.expected_points(lineup, evs, 12) == pytest.approx(9 * 3.0 + 7.0 * 2)
    assert h2h.expected_points(lineup, evs, 13) == 0.0   # boshqa tur uchun baho yo'q