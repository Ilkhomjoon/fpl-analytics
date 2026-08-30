"""Model va transfer dvigateli uchun sinovlar (tarmoqsiz, soxta ma'lumot bilan)."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fplbrain import ratings
from fplbrain.captain import rank_captains
from fplbrain.ev import (
    DEF, FWD, GK, MID, build_profile, expected_conceded_penalty,
    poisson_pmf, poisson_tail, shrink,
)
from fplbrain.squad import best_eleven, selling_price, squad_ev
from fplbrain.transfers import evaluate_moves
from tests.conftest import make_squad as _make_squad
from tests.fake import make_picks


# ------------------------------------------------------------------ matematika
def test_poisson_pmf_yigindisi_bir():
    lam = 1.7
    total = sum(poisson_pmf(k, lam) for k in range(30))
    assert math.isclose(total, 1.0, abs_tol=1e-9)


def test_poisson_tail_monoton():
    assert poisson_tail(10, 6.0) > poisson_tail(12, 6.0)
    assert poisson_tail(10, 9.0) > poisson_tail(10, 5.0)
    assert 0.0 <= poisson_tail(10, 6.0) <= 1.0


def test_negbinom_dispersiyani_hisobga_oladi():
    from fplbrain.ev import negbinom_tail
    # o'rtacha chegaradan past bo'lganda tarqoq taqsimot ko'proq imkon beradi
    assert negbinom_tail(10, 6.0) > poisson_tail(10, 6.0)
    # o'rtacha chegaradan yuqori bo'lganda esa kamroq (og'irlik dumga ketadi)
    assert negbinom_tail(10, 12.0) < poisson_tail(10, 12.0)
    assert 0.0 <= negbinom_tail(12, 7.0) <= 1.0
    assert negbinom_tail(10, 0.0) == 0.0


def test_kiritilgan_gol_jarimasi():
    # lambda=0 bo'lsa jarima yo'q; lambda oshsa jarima ham oshadi
    assert expected_conceded_penalty(0.0) == 0.0
    assert expected_conceded_penalty(3.0) > expected_conceded_penalty(1.0)
    # 2 gol o'rtacha bo'lsa jarima ~1 ochko atrofida
    assert 0.6 < expected_conceded_penalty(2.0) < 1.2


def test_shrinkage_prior_tomon_tortadi():
    # o'yin o'ynamagan o'yinchi to'liq prior oladi
    assert shrink(0.0, 0.0, 0.5, 6.0) == 0.5
    # ko'p o'ynagan o'yinchi o'z tezligiga yaqinlashadi
    assert shrink(20.0, 20.0, 0.2, 6.0) > 0.7
    # bitta o'yindagi portlash prior tomon tortiladi
    assert shrink(1.5, 1.0, 0.2, 6.0) < 0.5


# --------------------------------------------------------------- jamoa reytingi
def test_jamoa_reytinglari_oqilona(world):
    rt = world["rt"]
    assert len(rt) == 20
    for r in rt.values():
        assert 0.3 < r.attack < 2.3
        assert 0.3 < r.defence < 2.3


def test_uy_maydonida_kutilgan_gol_koproq(world):
    cfg, rt = world["cfg"], world["rt"]
    a, b = 1, 2
    home_for, _ = ratings.fixture_lambdas(rt, a, b, True, cfg)
    away_for, _ = ratings.fixture_lambdas(rt, a, b, False, cfg)
    assert home_for > away_for


def test_fixture_views_har_turda_10_ta_oyin(world):
    views, events = world["views"], world["events"]
    for ev in events:
        count = sum(len(per.get(ev, [])) for per in views.values())
        assert count == 20        # 10 o'yin x 2 jamoa


# ------------------------------------------------------------------- EV modeli
def test_ev_musbat_va_oqilona(world):
    evs = [p.next_ev for p in world["ev"].values() if p.profile.p_start > 0.8]
    assert evs
    assert all(0 < e < 12 for e in evs), f"chegaradan chiqdi: {max(evs)}"
    assert 2.0 < sum(evs) / len(evs) < 7.0


def test_hujumchi_himoyachidan_kop_gol_kutadi(world):
    ev = world["ev"]
    fwd = [p for p in ev.values() if p.profile.position == FWD and p.profile.p_start > 0.8]
    dfd = [p for p in ev.values() if p.profile.position == DEF and p.profile.p_start > 0.8]
    fwd_goal = sum(f.fixtures[3][0].parts["gol"] for f in fwd if f.fixtures[3]) / len(fwd)
    def_goal = sum(d.fixtures[3][0].parts["gol"] for d in dfd if d.fixtures[3]) / len(dfd)
    assert fwd_goal > def_goal


def test_himoyachi_defcon_va_toza_darvoza_oladi(world):
    ev = world["ev"]
    dfd = sorted(
        (p for p in ev.values() if p.profile.position == DEF),
        key=lambda p: -p.profile.p_start,
    )
    sample = dfd[0].fixtures[3][0]
    assert sample.parts["toza_darvoza"] > 0
    assert sample.parts["defcon"] > 0
    assert sample.parts["kiritilgan"] <= 0


def test_ojiz_oyinchi_past_ev(world):
    ev = world["ev"]
    benchers = [p for p in ev.values() if p.profile.p_start < 0.3]
    starters = [p for p in ev.values() if p.profile.p_start > 0.85]
    assert (sum(p.next_ev for p in benchers) / len(benchers)) < (
        sum(p.next_ev for p in starters) / len(starters)
    )


def test_jarohatlangan_oyinchi_nol_ev(world):
    cfg, bs, engine, events = world["cfg"], world["bs"], world["engine"], world["events"]
    e = dict(bs["elements"][10])
    e["status"] = "i"
    e["chance_of_playing_next_round"] = 0
    p = build_profile(e, None, cfg, 2)
    assert engine.evaluate(p, events).next_ev == pytest.approx(0.0, abs=0.01)


# ------------------------------------------------------------------- tarkib
def test_eng_yaxshi_11_qoidaga_mos(world):
    squad = _make_squad(world)
    xi, bench, form, total = best_eleven(squad.players, 3)
    assert len(xi) == 11 and len(bench) == 4
    assert sum(1 for p in xi if p.position == GK) == 1
    assert 3 <= sum(1 for p in xi if p.position == DEF) <= 5
    assert 2 <= sum(1 for p in xi if p.position == MID) <= 5
    assert 1 <= sum(1 for p in xi if p.position == FWD) <= 3
    # 11 lik zaxiradan kuchli bo'lishi shart
    assert min(p.ev.per_event[3] for p in xi) >= max(
        p.ev.per_event[3] for p in bench if p.position != GK
    ) - 1e-9


def test_zaxira_darvozabon_oxirida(world):
    squad = _make_squad(world)
    _, bench, _, _ = best_eleven(squad.players, 3)
    assert bench[-1].position == GK


def test_sotish_narxi_qoidasi():
    assert selling_price(6.0, 63) == 6.1        # +0.3 -> yarmi (pastga) = +0.1
    assert selling_price(6.0, 64) == 6.2
    assert selling_price(6.0, 58) == 5.8        # tushgan narx to'liq
    assert selling_price(6.0, 60) == 6.0


def test_squad_ev_musbat(world):
    squad = _make_squad(world)
    assert squad_ev(squad, world["events"], world["cfg"]) > 50


def test_kesh_fayl_nomi_windowsda_yaroqli(tmp_path):
    """`?` va `=` belgilari fayl nomiga tushmasligi kerak (Windows [Errno 22])."""
    from fplbrain.api import FplClient

    client = FplClient(tmp_path)
    path = client._cache_path(
        "https://fantasy.premierleague.com/api/leagues-classic/314/standings/?page_standings=1"
    )
    forbidden = set('?<>:"|*\\')
    assert not (forbidden & set(path.name)), path.name
    path.write_text("{}", encoding="utf-8")     # haqiqatan yozilishini tekshiramiz
    assert path.exists()
    # turli so'rov qatorlari turli faylga tushsin
    other = client._cache_path(
        "https://fantasy.premierleague.com/api/leagues-classic/314/standings/?page_standings=2"
    )
    assert other.name != path.name


def test_my_team_ishlatilsa_aniq_narx_olinadi(world):
    """Sessiya bo'lsa sotish narxi va FT taxmin emas, aniq qiymatdan olinadi."""
    from fplbrain.squad import load_squad

    bs, ev = world["bs"], world["ev"]
    by_id = {e["id"]: e for e in bs["elements"]}
    picks = make_picks(bs)

    class AuthClient:
        def my_team(self, entry_id):
            return {
                "picks": [
                    {**p, "selling_price": by_id[p["element"]]["now_cost"] - 2,
                     "purchase_price": by_id[p["element"]]["now_cost"] - 3}
                    for p in picks
                ],
                "transfers": {"limit": 4, "bank": 25, "value": 1000},
                "chips": [
                    {"name": "bboost", "status_for_entry": "available"},
                    {"name": "3xc", "status_for_entry": "played"},
                ],
            }

        def entry_history(self, entry_id):
            return {"current": [], "chips": []}

        def entry_picks(self, entry_id, event):
            raise AssertionError("sessiya bor ekan, ochiq endpointga murojaat qilinmasin")

    squad = load_squad(AuthClient(), world["cfg"], 1, 3, ev, by_id)
    assert squad.authenticated is True
    assert squad.free_transfers == 4
    assert squad.bank == 2.5
    assert squad.chips_available == ["bboost"]
    first = squad.players[0]
    assert first.selling_price == round((by_id[first.element]["now_cost"] - 2) / 10, 1)


# ---------------------------------------------------------------- transferlar
def test_transfer_taklifi_foydali(world):
    squad = _make_squad(world)
    moves = evaluate_moves(squad, list(world["ev"].values()), world["events"], world["cfg"])
    assert moves, "hech qanday variant topilmadi"
    best = moves[0]
    assert best.gain > 0
    assert best.raw_gain >= best.gain
    # byudjet buzilmasin
    assert best.bank_after >= -1e-9


def test_transfer_byudjetni_hurmat_qiladi(world):
    squad = _make_squad(world)
    squad.bank = 0.0
    moves = evaluate_moves(squad, list(world["ev"].values()), world["events"], world["cfg"])
    for m in moves[:40]:
        budget = sum(p.selling_price for p in m.out_players)
        assert sum(p.profile.price for p in m.in_players) <= budget + 1e-9


def test_jamoadan_uchtadan_kop_olinmaydi(world):
    squad = _make_squad(world)
    moves = evaluate_moves(squad, list(world["ev"].values()), world["events"], world["cfg"])
    for m in moves[:40]:
        out_ids = {p.element for p in m.out_players}
        counts: dict[int, int] = {}
        for p in squad.players:
            if p.element in out_ids:
                continue
            counts[p.ev.profile.team] = counts.get(p.ev.profile.team, 0) + 1
        for pev in m.in_players:
            counts[pev.profile.team] = counts.get(pev.profile.team, 0) + 1
        assert max(counts.values()) <= 3


def test_hit_hisobga_olinadi(world):
    squad = _make_squad(world)
    squad.free_transfers = 0
    moves = evaluate_moves(squad, list(world["ev"].values()), world["events"], world["cfg"])
    assert all(m.hit >= 4 for m in moves if m.n == 1)
    assert all(m.gain == pytest.approx(m.raw_gain - m.hit, abs=0.011) for m in moves[:20])


# ------------------------------------------------------------------- kapitan
def test_kapitan_reytingi(world):
    squad = _make_squad(world)
    options = rank_captains(squad, 3, {}, "balanced", limit=5)
    assert len(options) == 5
    assert options[0].score >= options[-1].score
    assert all(0 <= o.p10 <= 1 for o in options)
    assert all(0 <= o.p15 <= o.p10 + 1e-9 for o in options)   # 15+ hech qachon 10+ dan ko'p emas


def test_darvozabon_kapitan_taklif_qilinmaydi(world):
    squad = _make_squad(world)
    options = rank_captains(squad, 3, {}, "balanced", limit=11)
    assert all(o.player.position != GK for o in options)


def test_aggressive_strategiya_differensialni_koradi(world):
    squad = _make_squad(world)
    xi, _, _, _ = best_eleven(squad.players, 3)
    popular = next(p for p in xi if p.position != GK).element
    eo = {popular: 80.0}
    safe = rank_captains(squad, 3, eo, "safe", limit=11)
    aggro = rank_captains(squad, 3, eo, "aggressive", limit=11)
    safe_pos = [o.player.element for o in safe].index(popular)
    aggro_pos = [o.player.element for o in aggro].index(popular)
    assert safe_pos <= aggro_pos


def test_chip_tavsiyasi_faqat_mavjudlaridan(world):
    """Ishlatilgan chip tavsiyalar ro'yxatiga tushmasligi kerak."""
    from fplbrain.chips import advise

    squad = _make_squad(world)
    advice = advise(squad, list(world["ev"].values()), world["events"],
                    world["views"], world["cfg"], available_chips=["freehit"])
    assert advice
    assert {a.chip for a in advice} == {"freehit"}


# --------------------------------------------------- ochko taqsimoti (kapitan)
def test_taqsimot_yigindisi_bir_va_tepasi_mantiqiy():
    """Taqsimot to'liq bo'lishi va pozitsiyalar orasidagi farqni ko'rsatishi kerak."""
    from fplbrain.ev import FixtureInputs, points_distribution

    forward = points_distribution(FixtureInputs(
        xg=0.95, xa=0.20, p_cs=0.35, p_appear=0.97, p60=0.93,
        bonus_mean=0.95, lam_conceded=1.0, position=FWD))
    keeper = points_distribution(FixtureInputs(
        xg=0.0, xa=0.01, p_cs=0.40, p_appear=0.99, p60=0.99,
        bonus_mean=0.45, lam_conceded=0.95, saves_mean=3.0, position=GK))

    assert abs(sum(forward.pmf.values()) - 1.0) < 1e-3
    assert abs(sum(keeper.pmf.values()) - 1.0) < 1e-3
    # premium hujumchida "haul" real, darvozabonda deyarli imkonsiz
    assert 0.20 < forward.tail(10) < 0.45
    assert keeper.tail(10) < 0.05
    # o'rtacha EV yo'li bilan hisoblangan qiymatga yaqin bo'lsin
    assert 6.5 < forward.mean() < 8.5
    # tepasi past chegaradan yuqori
    assert forward.percentile(0.90) >= 10


def test_taqsimot_oynamaydigan_oyinchida_nolga_yigiladi():
    from fplbrain.ev import FixtureInputs, points_distribution

    d = points_distribution(FixtureInputs(
        xg=0.5, xa=0.3, p_cs=0.3, p_appear=0.0, p60=0.0, position=FWD))
    assert d.pmf.get(0, 0) == pytest.approx(1.0)
    assert d.mean() == pytest.approx(0.0)


def test_toza_darvoza_va_kiritilgan_gol_zid_emas():
    """CS va kiritilgan gol jarimasi bitta tasodifiy miqdordan chiqadi."""
    from fplbrain.ev import FixtureInputs, points_distribution

    # deyarli aniq toza darvoza -> jarima bo'lmasligi kerak
    clean = points_distribution(FixtureInputs(
        xg=0.0, xa=0.0, p_cs=1.0, p_appear=1.0, p60=1.0,
        bonus_mean=0.0, lam_conceded=0.001, position=DEF))
    # 2 ochko ishtirok + 4 toza darvoza = 6 (bonussiz)
    assert clean.pmf.get(6, 0) > 0.8

    leaky = points_distribution(FixtureInputs(
        xg=0.0, xa=0.0, p_cs=0.0, p_appear=1.0, p60=1.0,
        bonus_mean=0.0, lam_conceded=4.0, position=DEF))
    assert leaky.mean() < clean.mean()


def test_strategiya_orinaga_qarab_tanlanadi():
    from fplbrain.captain import rank_strategy

    assert rank_strategy(5_000, 10_000_000)[0] == "safe"
    assert rank_strategy(500_000, 10_000_000)[0] == "balanced"
    assert rank_strategy(2_400_000, 10_000_000)[0] == "aggressive"
    assert rank_strategy(None, None)[0] == "balanced"
