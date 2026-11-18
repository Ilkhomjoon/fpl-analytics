"""Backtest topgan xatolar — qaytib kelmasligi uchun qulflangan.

`tools/backtest.py` 2026/27 ning GW3-10 turlarida modelni haqiqiy ochko
bilan solishtirdi (~2800 o'yinchi-tur). Har bir test o'sha yerda topilgan
bitta aniq kamchilikka mos keladi: raqamlar izohlarda.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fplbrain import priors, ratings
from fplbrain.config import Config
from fplbrain.ev import (DEF, FWD, GK, MID, PlayerProfile, build_profile,
                         fixture_ev, state_start_prob)
from fplbrain.ratings import FixtureView, TeamRating
from web import squadview

CFG = Config()


# ------------------------------------------------------------ jamoa kuchi
def _teams(detailed: bool) -> list[dict]:
    """Uch jamoa: kuchli, o'rta, zaif. `detailed=False` — 2026/27 dagi kabi
    hujum/himoya kuchi 0, faqat umumiy kuch (2..5) bor."""
    out = []
    for tid, overall, att in ((1, 5, 1350), (2, 3, 1150), (3, 2, 1050)):
        out.append({
            "id": tid, "name": f"T{tid}", "short_name": f"T{tid}", "played": 0,
            "strength_attack_home": att if detailed else 0,
            "strength_attack_away": att if detailed else 0,
            "strength_defence_home": att if detailed else 0,
            "strength_defence_away": att if detailed else 0,
            "strength_overall_home": overall, "strength_overall_away": overall,
        })
    return out


def test_strength_nol_bolsa_hujum_pastga_yopishmaydi():
    """FPL hujum/himoya kuchini 0 qilib bersa ham liga o'rtachasi 1.0 qoladi.

    Ilgari hamma jamoaning hujum priori quyi chegaraga (0.55) yopishib,
    kutilayotgan gollar ~20% kam chiqardi (bashorat 1.07, haqiqat 1.35).
    """
    got = ratings.build_team_ratings({"teams": _teams(False), "elements": []}, CFG)
    attack = [r.attack for r in got.values()]
    defence = [r.defence for r in got.values()]
    assert abs(sum(attack) / 3 - 1.0) < 0.02
    assert abs(sum(defence) / 3 - 1.0) < 0.02
    # Umumiy kuch zaxira sifatida ishlaydi: kuchli jamoa ko'p uradi, kam o'tkazadi
    assert got[1].attack > got[2].attack > got[3].attack
    assert got[1].defence < got[2].defence < got[3].defence


def test_batafsil_strength_bolsa_ham_ortacha_bir():
    got = ratings.build_team_ratings({"teams": _teams(True), "elements": []}, CFG)
    assert abs(sum(r.attack for r in got.values()) / 3 - 1.0) < 0.02
    assert got[1].attack > got[3].attack


# -------------------------------------------------------------- daqiqalar
def test_otgan_turda_oynamagan_zaxira_boshlamaydi():
    """O'ynamagan zaxira o'yinchi: haqiqiy boshlash ulushi 0.09 (eski chegara 0.45)."""
    assert state_start_prob([0, 12, 0, 20, 0], [0, 0, 0, 0, 0]) < 0.12


def test_dam_olgan_asosiy_oyinchi_zaxiradan_ustun():
    """Bir tur o'tkazib yuborgan doimiy asosiy o'yinchi (0.41) zaxiradan (0.09) yuqori."""
    regular = state_start_prob([90, 90, 90, 90, 0], [1, 1, 1, 1, 0])
    fringe = state_start_prob([0, 15, 0, 10, 0], [0, 0, 0, 0, 0])
    assert 0.30 < regular < 0.50
    assert regular > fringe * 3


def test_zaxiradan_qisqa_chiqish_boshlashni_anglatmaydi():
    """Zaxiradan 10 daqiqa: boshlash ulushi 0.13 (eski chegara 0.55)."""
    assert state_start_prob([0, 8, 12, 10], [0, 0, 0, 0]) < 0.20


def test_mustahkam_oyinchi_yuqori_qoladi():
    assert state_start_prob([90] * 6, [1] * 6) >= 0.90


def _element(**over) -> dict:
    base = {
        "id": 7, "web_name": "X", "team": 1, "element_type": MID, "now_cost": 60,
        "status": "a", "chance_of_playing_next_round": None, "news": "",
        "minutes": 810, "starts": 9, "expected_goals": 2.0, "expected_assists": 1.5,
        "clearances_blocks_interceptions": 10, "tackles": 10, "recoveries": 40,
        "bonus": 3, "saves": 0, "yellow_cards": 1, "selected_by_percent": "12.0",
        "penalties_order": None, "event_points": 2,
    }
    base.update(over)
    return base


def test_event_points_songgi_oyin_holatini_aytadi():
    """Batafsil tarixsiz: o'tgan turda 0 ochko olgan o'yinchi pastroq baholanadi."""
    played = build_profile(_element(event_points=6), None, CFG, 10, last_event_played=True)
    benched = build_profile(_element(event_points=0), None, CFG, 10, last_event_played=True)
    assert played.p_start > 0.85
    assert benched.p_start < played.p_start - 0.15


def test_event_points_jamoa_oynamagan_bolsa_ishlatilmaydi():
    """Tur davom etayotgan yoki bo'sh tur: 0 ochko "o'ynamadi" degani emas."""
    zero = build_profile(_element(event_points=0), None, CFG, 10, last_event_played=False)
    six = build_profile(_element(event_points=6), None, CFG, 10, last_event_played=False)
    assert zero.p_start == six.p_start
    assert zero.p_start > 0.75


def test_teams_done_faqat_tugatgan_jamoalar():
    bootstrap = {"events": [{"id": 4, "is_current": True}]}
    fixtures = [
        {"event": 4, "team_h": 1, "team_a": 2, "finished": True},
        {"event": 4, "team_h": 3, "team_a": 4, "finished": False},
        {"event": 3, "team_h": 5, "team_a": 6, "finished": True},
    ]
    assert squadview.teams_done_last_event(bootstrap, fixtures) == {1, 2}
    assert squadview.teams_done_last_event({"events": []}, fixtures) == set()


# ------------------------------------------------------------ EV qismlari
def _profile(pos: int, **over) -> PlayerProfile:
    base = dict(
        element=1, name="P", team=1, position=pos, price=5.0, status="a",
        availability=1.0, p_start=0.92, p_appear=0.95, p60=0.86, xmins=78.0,
        xg90=0.10, xa90=0.10, dc90=7.7, dc_hit_rate=None, bonus90=0.2,
        saves90=3.0 if pos == GK else 0.0, yellow90=0.1, is_pen_taker=False,
        is_set_piece=False, minutes=810, nineties=9.0, start_mins=85.0)
    base.update(over)
    return PlayerProfile(**base)


def _view(lam_for=1.4, lam_against=1.4) -> FixtureView:
    return FixtureView(event=5, team=1, opponent=2, is_home=True,
                       lam_for=lam_for, lam_against=lam_against)


RATINGS = {2: TeamRating(team_id=2, name="Opp", short="OPP", attack=1.0,
                         defence=1.0, matches=9)}


def _ev(profile: PlayerProfile, **view):
    return fixture_ev(profile, _view(**view), RATINGS, 1.4, 1.4)


def test_defcon_asosiy_himoyachida_haqiqatga_yaqin():
    """O'rtacha himoyachi (7.7 CBIT/90) chegaradan ~25-35% o'tadi.

    Ilgari tezlik "daqiqa ulushi"ga ko'paytirilib, keyin chegara ehtimoli
    hisoblanardi — natija 0.11 chiqardi, haqiqatda esa 0.30.
    """
    got = _ev(_profile(DEF))
    p_given_60 = got.parts["defcon"] / 2 / 0.86
    assert 0.20 <= p_given_60 <= 0.40


def test_defcon_markaziy_himoyachi_ancha_yuqori():
    """11 CBIT/90 lik markaziy himoyachi (p90) chegaradan yarmidan ko'p o'tadi."""
    elite = _ev(_profile(DEF, dc90=11.0)).parts["defcon"]
    average = _ev(_profile(DEF, dc90=7.7)).parts["defcon"]
    assert elite > 0.9 and elite > average * 1.6


def test_defcon_dalil_kam_bolsa_noaniqlik_ehtimolni_oshiradi():
    """Ikki o'yinlik namuna: haqiqiy tezlik noma'lum → chegaradan o'tish ehtimoli yuqoriroq."""
    early = _ev(_profile(DEF, nineties=2.0)).parts["defcon"]
    late = _ev(_profile(DEF, nineties=20.0)).parts["defcon"]
    assert early > late


def test_otkazilgan_gol_jarimasi_oynagan_holat_boyicha():
    """Jarima E[⌊gol/2⌋] — maydonda bo'lgan vaqt uchun, daqiqa ulushi uchun emas."""
    got = _ev(_profile(DEF), lam_against=1.4)
    full = sum(math.exp(-1.4 * 85 / 90) * (1.4 * 85 / 90) ** k / math.factorial(k) * (k // 2)
               for k in range(12))
    assert got.parts["kiritilgan"] <= -0.86 * full * 0.98
    # Eski hisob (lam × 0.87) bundan ~30% kichik chiqardi
    assert got.parts["kiritilgan"] < -0.22


def test_toza_darvoza_oyinchi_maydondagi_vaqtga_bogliq():
    """Erta almashtiriladigan o'yinchining toza darvoza ehtimoli jamoanikidan yuqori."""
    team_cs = math.exp(-1.4)
    got = _ev(_profile(DEF, start_mins=75.0))
    assert got.inputs.p_cs > team_cs * 1.1


def test_fpl_uzatmasi_xa_dan_keng():
    """Hujumchi: xA past bo'lsa ham xG tufayli uzatma kutiladi (qaytgan to'p, penalti)."""
    striker = _ev(_profile(FWD, xg90=0.45, xa90=0.06))
    share = striker.inputs.xa
    assert share > 0.06 * 0.87 * 1.5            # sof xA dan kamida 1.5 barobar
    assert striker.parts["uzatma"] > 0.35


def test_bonus_qimmat_oyinchini_ikki_marta_mukofotlamaydi():
    """Neytral uchrashuvda bonus = o'yinchining o'z tezligi × daqiqa ulushi.

    Ilgari lift "o'rtacha o'yinchi"ga nisbatan olinardi va ko'p gol uradigan
    o'yinchining bonusi ikki barobar oshib ketardi (0.87 vs haqiqiy 0.38).
    """
    star = _profile(FWD, xg90=0.8, xa90=0.3, bonus90=0.8)
    got = _ev(star)                               # neytral: lam = neytral lam
    assert abs(got.parts["bonus"] - 0.8 * 78 / 90) < 0.02


def test_bonus_yaxshi_uchrashuvda_ortadi():
    star = _profile(FWD, xg90=0.8, xa90=0.3, bonus90=0.8)
    assert _ev(star, lam_for=2.4).parts["bonus"] > _ev(star, lam_for=0.8).parts["bonus"]


def test_darvozabon_kam_kartochka_oladi():
    gk = build_profile(_element(element_type=GK, yellow_cards=0, minutes=0, starts=0),
                       None, CFG, 0)
    mid = build_profile(_element(element_type=MID, yellow_cards=0, minutes=0, starts=0),
                        None, CFG, 0)
    assert gk.yellow90 < mid.yellow90 / 3


# ------------------------------------------------------------------ priorlar
def test_defcon_priori_olchangan_darajada():
    assert 7.0 <= priors.dc90_prior(4.5, DEF) <= 8.5
    # Arzon yarim himoyachi — tayanch, qimmati — hujumkor
    assert priors.dc90_prior(5.0, MID) > priors.dc90_prior(9.0, MID) + 2.0


def test_hujumchi_bonus_priori_yuqori():
    assert priors.bonus90_prior(7.0, FWD) > 0.6
    assert priors.bonus90_prior(4.5, DEF) < 0.25
