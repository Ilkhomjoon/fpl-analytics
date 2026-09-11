"""Mavsum sur'ati — maqsadga nisbatan qayerdaman.

Asosiy fikr: o'rtacha ochko yolg'iz o'zi hech narsa aytmaydi. "5-turda 300
ochko" yaxshimi yoki yomonmi — javob **shu paytgacha kerak bo'lgan** ochko
bilan solishtirganda chiqadi.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fplbrain import pace as pace_mod                             # noqa: E402


def history(points_per_gw: list[int], hits: list[int] | None = None) -> dict:
    """`entry/{id}/history/` javobining kerakli qismi."""
    hits = hits or [0] * len(points_per_gw)
    rows, total = [], 0
    for i, (pts, hit) in enumerate(zip(points_per_gw, hits), start=1):
        total += pts - hit
        rows.append({"event": i, "points": pts, "event_transfers_cost": hit,
                     "total_points": total, "overall_rank": 100_000})
    return {"current": rows, "chips": []}


# --------------------------------------------------------------- normalar
def test_norma_maqsaddan_chiqadi():
    p = pace_mod.from_history(history([74]), target=2810)
    assert p.per_event_needed == pytest.approx(2810 / 38)
    assert round(p.per_event_needed, 1) == 73.9


def test_aniq_rejada_borayotgan_menejer():
    """Har turda 74 ochko — aynan rejada."""
    p = pace_mod.from_history(history([74] * 10), target=2810)
    assert p.points == 740
    assert p.delta == pytest.approx(740 - 73.9 * 10, abs=1.0)
    assert p.ratio == pytest.approx(1.0, abs=0.01)
    assert p.grade()[0] in ("rejada", "a'lo")


def test_ortda_qolgan_menejer():
    p = pace_mod.from_history(history([50] * 10), target=2810)
    assert p.delta < 0
    assert p.grade()[1] in ("warning", "serious", "critical")
    # Qolgan turlarda talab OSHISHI kerak — bu eng foydali signal
    assert p.needed_per_event > p.per_event_needed


def test_oldinda_ketayotgan_menejer():
    p = pace_mod.from_history(history([90] * 10), target=2810)
    assert p.delta > 0
    assert p.grade() == ("a'lo", "good")
    assert p.needed_per_event < p.per_event_needed


def test_talab_ortda_qolgan_sari_osadi():
    """Orqada qolgan sari maqsad qiyinlashadi — model buni ko'rsatishi kerak."""
    oldingi = None
    for turlar in (5, 10, 20, 30):
        p = pace_mod.from_history(history([50] * turlar), target=2810)
        if oldingi is not None:
            assert p.needed_per_event > oldingi
        oldingi = p.needed_per_event


# ------------------------------------------------------------------ minus
def test_minuslar_ayiriladi():
    """FPL ning `total_points` i minuslar ayirilgan yakuniy ochko."""
    p = pace_mod.from_history(history([60, 60], hits=[0, 8]), target=2810)
    assert p.points == 112                    # 60 + (60 - 8)
    assert p.events[-1].hit == 8
    assert p.events[-1].net == 52


# ------------------------------------------------------------ chekka holat
def test_oyin_boshlanmagan():
    p = pace_mod.from_history({"current": []}, target=2810)
    assert p.played == 0
    assert p.points == 0
    assert p.average == 0
    assert p.grade() == ("boshlanmadi", "warning")
    assert p.progress == 0


def test_maqsad_bajarilgan_bolsa_talab_nol():
    p = pace_mod.from_history(history([100] * 30), target=2810)
    assert p.points == 3000
    assert p.needed_per_event == 0.0
    assert p.progress > 1.0


def test_mavsum_tugagan_va_maqsad_bajarilmagan():
    """38 tur o'ynalgan, maqsad uzoq — bo'linish xatosi bo'lmasin."""
    p = pace_mod.from_history(history([50] * 38), target=2810)
    assert p.remaining_events == 0
    assert p.needed_per_event == float("inf")


def test_bosh_javob_yiqilmaydi():
    p = pace_mod.from_history(None, target=2810)
    assert p.played == 0
    p = pace_mod.from_history({}, target=2810)
    assert p.played == 0


def test_turlar_tartiblanadi():
    """Javob tartibsiz kelsa ham oxirgi tur to'g'ri aniqlansin."""
    h = history([50, 60, 70])
    h["current"].reverse()
    p = pace_mod.from_history(h, target=2810)
    assert [e.event for e in p.events] == [1, 2, 3]
    assert p.points == 180


# ---------------------------------------------------- birinchi o'rin bilan
def test_birinchi_orin_surati_olinadi():
    from fplbrain.demo import FakeClient
    from fplbrain.config import Config

    leader = pace_mod.leader_pace(FakeClient(played=6), Config())
    assert leader["entry_id"] > 0
    assert leader["average"] > 0
    assert leader["played"] == 6
    # `projected` yaxlitlanmagan o'rtachadan hisoblanadi, `average` esa
    # ko'rsatish uchun yaxlitlangan — shuning uchun kichik farq normal
    assert leader["projected"] == pytest.approx(
        leader["points"] / leader["played"] * 38, abs=1)


def test_liga_ochilmasa_taqqoslash_tashlab_ketiladi():
    """Taqqoslash ixtiyoriy: xatolik asosiy sur'atni yiqitmasligi kerak."""
    from fplbrain.config import Config

    class Broken:
        def league_standings(self, league_id, page=1):
            raise RuntimeError("tarmoq yo'q")

    assert pace_mod.leader_pace(Broken(), Config()) == {}

    class Empty:
        def league_standings(self, league_id, page=1):
            return {"standings": {"results": []}}

    assert pace_mod.leader_pace(Empty(), Config()) == {}


# --------------------------------------------------- jamoa ko'rsatkichlari
def rich(points, hits=None, bench=None, ranks=None) -> dict:
    """Boyroq tarix — ko'rsatkichlar uchun."""
    n = len(points)
    hits = hits or [0] * n
    bench = bench or [0] * n
    ranks = ranks or [500_000 - i * 10_000 for i in range(n)]
    rows, total = [], 0
    for i in range(n):
        total += points[i] - hits[i]
        rows.append({
            "event": i + 1, "points": points[i], "event_transfers_cost": hits[i],
            "total_points": total, "overall_rank": ranks[i], "rank": 900_000 - i * 1000,
            "points_on_bench": bench[i], "event_transfers": 1 if i else 0,
            "value": 1000 + i, "bank": 5,
        })
    return {"current": rows, "chips": [{"event": 2, "name": "wildcard"}]}


BOOTSTRAP = {"events": [{"id": i, "average_entry_score": 50} for i in range(1, 39)]}


def test_ortacha_menejerdan_farq_hisoblanadi():
    p = pace_mod.from_history(rich([60, 40, 70]), bootstrap=BOOTSTRAP)
    assert [e.average for e in p.events] == [50, 50, 50]
    assert [e.vs_average for e in p.events] == [10, -10, 20]
    assert p.vs_average_total == 20
    assert p.beat_average == 2


def test_minus_va_zaxira_yigindisi():
    p = pace_mod.from_history(rich([60, 60, 60], hits=[0, 4, 8], bench=[3, 10, 1]))
    assert p.hits_paid == 12
    assert p.bench_lost == 14
    assert p.transfers_made == 2


def test_eng_yaxshi_va_eng_yomon_tur():
    p = pace_mod.from_history(rich([60, 90, 30]))
    assert p.best.event == 2 and p.best.net == 90
    assert p.worst.event == 3 and p.worst.net == 30


def test_minus_eng_yaxshi_turni_ozgartiradi():
    """Sof ochko bo'yicha solishtiriladi — minus olingan tur pastroq turadi."""
    p = pace_mod.from_history(rich([80, 78], hits=[8, 0]))
    assert p.best.event == 2          # 72 < 78


def test_orin_harakati():
    p = pace_mod.from_history(rich([60] * 4, ranks=[900_000, 400_000, 600_000, 500_000]))
    assert p.rank == 500_000          # joriy
    assert p.best_rank == 400_000     # eng yaxshisi


def test_chip_turga_biriktiriladi():
    p = pace_mod.from_history(rich([60, 60, 60]))
    assert p.events[1].chip == "wildcard"
    assert p.events[0].chip == ""


def test_tebranish_olchovi():
    barqaror = pace_mod.from_history(rich([60, 60, 60, 60]))
    notinch = pace_mod.from_history(rich([20, 100, 30, 90]))
    assert barqaror.consistency == 0.0
    assert notinch.consistency > 30


def test_ortacha_yoq_bolsa_farq_nol():
    """Bootstrap berilmasa taqqoslash tashlanadi, qolgani ishlayveradi."""
    p = pace_mod.from_history(rich([60, 70]))
    assert p.vs_average_total == 0
    assert p.beat_average == 0
    assert p.points == 130


# ------------------------------------------ yetakchi bilan yig'indi farqi
# Taqqoslash **maqsad o'lchagichida** bo'ladi: 2810 shkalasida mening
# yig'indim va yetakchining yig'indisi yonma-yon turadi. Turlar grafigida
# emas — u yerda savol boshqa: "shu hafta normani berdimmi".
def test_yetakchining_yigindisi_qaytariladi():
    from fplbrain.config import Config
    from fplbrain.demo import FakeClient

    leader = pace_mod.leader_pace(FakeClient(played=5), Config())
    assert leader["points"] > 0
    assert leader["played"] == 5
    assert leader["average"] > 0
    # Turma-tur ma'lumot endi kerak emas — o'lchagichda faqat yig'indi ishlatiladi
    assert "events" not in leader


def test_yigindi_boyicha_farq_hisoblanadi():
    from fplbrain.config import Config
    from fplbrain.demo import FakeClient
    from web import paceview

    payload = paceview.build(FakeClient(played=4), Config(), 1)
    assert payload["leader_total_gap"] == payload["points"] - payload["leader"]["points"]
    assert payload["leader_total_gap"] < 0          # demo da yetakchi kuchliroq


def test_turlar_royxatida_yetakchi_yoq():
    """Yetakchi ma'lumoti turlar grafigiga QO'SHILMAYDI."""
    from fplbrain.config import Config
    from fplbrain.demo import FakeClient
    from web import paceview

    payload = paceview.build(FakeClient(played=4), Config(), 1)
    for row in payload["events"]:
        assert "leader" not in row
        assert "vs_leader" not in row
    # lekin o'rtacha menejer qoladi — u turma-tur taqqoslash uchun kerak
    assert all("average" in row and "vs_average" in row
               for row in payload["events"])


def test_yetakchi_yoq_bolsa_olchagich_baribir_chiziladi():
    from fplbrain.config import Config
    from fplbrain.demo import FakeClient
    from web import paceview

    class NoLeague(FakeClient):
        def league_standings(self, league_id, page=1):
            raise RuntimeError("yopiq")

    payload = paceview.build(NoLeague(played=3), Config(), 1)
    assert payload["leader"] == {}
    assert payload["leader_total_gap"] is None
    assert payload["points"] > 0            # asosiy qism baribir ishlaydi
    assert payload["progress"] > 0
