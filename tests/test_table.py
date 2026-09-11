"""Jadval + samarali qiyinlik: Arsenal — Aston Villa holati.

Haqiqiy voqea (GW3): rasmiy FDR Arsenal uchun bu o'yinni 4 ("qiyin") deb
belgilagan edi. Lekin Aston Villa mavsumni Brighton dan 0:4 yutqazib
boshlagan va jadval oxirida turardi. Arsenal o'yinni 1:0 yutdi, Raya 6,
Calafiori 11 ochko oldi — model esa ikkalasini ham zaxiraga tushirgandi.

Bu yerdagi sinovlar aynan shu xatoning qaytmasligini tekshiradi.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fplbrain import ratings as ratings_mod
from fplbrain import table as table_mod
from fplbrain.config import Config
from fplbrain.ev import EVEngine, build_profile
from fplbrain.squad import SquadPlayer, best_eleven
from tests.fake import make_bootstrap

ARS, AVL, MID_TABLE = 1, 2, 10        # fake.TEAM_NAMES: Arsenal, Aston Villa, Fulham

# (GW, uy, mehmon, uy gollari, mehmon gollari)
RESULTS = [
    # GW1 — Villa Brighton dan 0:4 yutqazadi, Arsenal 3:0 yutadi
    (1, ARS, 3, 3, 0), (1, 5, AVL, 4, 0), (1, 4, 6, 1, 1), (1, 7, 8, 1, 1),
    (1, 9, 10, 0, 1), (1, 11, 12, 1, 1), (1, 13, 14, 1, 1), (1, 15, 16, 1, 1),
    (1, 17, 18, 1, 1), (1, 19, 20, 1, 1),
    # GW2
    (2, ARS, 4, 2, 1), (2, 6, AVL, 2, 1), (2, 3, 5, 1, 1), (2, 8, 9, 1, 1),
    (2, 10, 11, 1, 1), (2, 12, 13, 1, 1), (2, 14, 15, 1, 1), (2, 16, 17, 1, 1),
    (2, 18, 19, 1, 1), (2, 20, 7, 1, 1),
    # GW3
    (3, ARS, 5, 2, 0), (3, 7, AVL, 3, 0), (3, 3, 4, 1, 1), (3, 6, 8, 1, 1),
    (3, 9, 11, 1, 1), (3, 10, 12, 0, 1), (3, 13, 15, 1, 1), (3, 14, 16, 1, 1),
    (3, 17, 19, 1, 1), (3, 18, 20, 1, 1),
]

# GW4 — kelgusi tur. Arsenal uyda Villani qabul qiladi, rasmiy FDR 4.
NEXT = [
    (ARS, AVL, 4, 5),
    (MID_TABLE, 12, 3, 3),
    (3, 4, 3, 3), (5, 6, 3, 3), (7, 8, 3, 3), (9, 11, 3, 3),
    (13, 14, 3, 3), (15, 16, 3, 3), (17, 18, 3, 3), (19, 20, 3, 3),
]


def _bootstrap() -> dict:
    """Hamma jamoa bir xil prior bilan boshlaydi va bir xil xG ga ega.

    Shunda farqning yagona manbai **jadval** bo'ladi — sinov aynan shu
    mexanizmni tekshiradi, prior tasodifini emas.
    """
    bs = make_bootstrap(played=3)
    for team in bs["teams"]:
        team["played"] = 3
        for key in ("strength_attack_home", "strength_attack_away",
                    "strength_defence_home", "strength_defence_away"):
            team[key] = 1200
    for element in bs["elements"]:
        element["expected_goals"] = 0.30
        element["expected_assists"] = 0.20
        element["expected_goals_conceded_per_90"] = 1.40
    return bs


def _fixtures() -> list[dict]:
    out, fid = [], 0
    for gw, home, away, gh, ga in RESULTS:
        fid += 1
        out.append({
            "id": fid, "event": gw, "team_h": home, "team_a": away,
            "team_h_score": gh, "team_a_score": ga,
            "finished": True, "finished_provisional": True,
            "kickoff_time": f"2026-08-{gw + 10:02d}T14:00:00Z",
            "team_h_difficulty": 3, "team_a_difficulty": 3,
        })
    for home, away, dh, da in NEXT:
        fid += 1
        out.append({
            "id": fid, "event": 4, "team_h": home, "team_a": away,
            "team_h_score": None, "team_a_score": None,
            "finished": False, "finished_provisional": False,
            "kickoff_time": "2026-09-01T14:00:00Z",
            "team_h_difficulty": dh, "team_a_difficulty": da,
        })
    return out


def _world():
    cfg = Config()
    bs, fx = _bootstrap(), _fixtures()
    table = table_mod.build_table(bs, fx)
    rt = ratings_mod.build_team_ratings(bs, cfg, table)
    views = ratings_mod.build_fixture_views(fx, rt, cfg, 4, 4)
    return dict(cfg=cfg, bs=bs, fx=fx, table=table, rt=rt, views=views)


# ------------------------------------------------------------------- jadval
def test_jadval_tugagan_oyinlardan_quriladi():
    table = _world()["table"]
    assert table[ARS].position == 1
    assert (table[ARS].played, table[ARS].points, table[ARS].gf, table[ARS].ga) == (3, 9, 7, 1)
    assert table[AVL].position == 20
    assert (table[AVL].points, table[AVL].gf, table[AVL].ga) == (0, 1, 9)
    assert table[AVL].form_string == "M M M"       # uch mag'lubiyat
    assert table[ARS].form_string == "G G G"


def test_tugamagan_oyin_jadvalga_kirmaydi():
    """GW2 xatosi qaytmasin: yarim o'ynalgan tur natijaga qo'shilmaydi."""
    bs, fx = _bootstrap(), _fixtures()
    live = copy.deepcopy(fx)
    for f in live:
        if f["event"] == 3:
            f["finished"] = f["finished_provisional"] = False
    table = table_mod.build_table(bs, live)
    assert table[ARS].played == 2
    assert table[ARS].points == 6


# ------------------------------------------------------------- jamoa reytingi
def test_jadval_jamoa_reytingini_ozgartiradi():
    rt = _world()["rt"]
    # Prior hamma uchun bir xil edi, demak farq faqat natijalardan keldi
    assert rt[ARS].attack > rt[AVL].attack
    assert rt[ARS].defence < rt[AVL].defence
    assert rt[ARS].position == 1 and rt[AVL].position == 20
    assert rt[ARS].form_string == "G G G"


def test_strength_tarqalishi_kengaytirilgan():
    """FPL ning siqilgan strength qiymatlari real gol tarqalishiga yoyiladi."""
    cfg_flat, cfg_wide = Config(), Config()
    cfg_flat.strength_spread = 1.0
    cfg_wide.strength_spread = 2.3

    bs = make_bootstrap(played=0)         # jadvalsiz: faqat prior ishlaydi
    for t in bs["teams"]:
        t["played"] = 0
    for e in bs["elements"]:
        e["minutes"] = 0
        e["expected_goals"] = 0.0

    flat = ratings_mod.build_team_ratings(bs, cfg_flat)
    wide = ratings_mod.build_team_ratings(bs, cfg_wide)

    def spread(rt):
        values = [r.attack for r in rt.values()]
        return max(values) / min(values)

    # Tekis holatda eng kuchli/eng zaif hujum nisbati ~1.3 — bu haqiqatga
    # to'g'ri kelmaydi. Daraja ko'tarilgach nisbat ~1.9 ga chiqadi.
    assert spread(flat) < 1.4
    assert spread(wide) > 1.7
    assert spread(wide) >= spread(flat) ** 2.3 * 0.95


# ------------------------------------------------------- samarali qiyinlik
def test_rasmiy_fdr_jadval_bilan_tuzatiladi():
    """Arsenal — Villa: rasmiy FDR 4, lekin jadvalda 1-o'rin 20-o'rinni qabul qiladi."""
    views = _world()["views"]
    arsenal = views[ARS][4][0]
    villa = views[AVL][4][0]

    assert arsenal.fdr == 4                    # FPL ning rasmiy bahosi
    assert arsenal.opp_position == 20
    assert arsenal.eff_fdr < 3.0               # model buni oson deb ko'radi
    assert arsenal.eff_fdr < arsenal.fdr - 1.0

    assert villa.eff_fdr > 4.0                 # teskari tomondan — haqiqatan qiyin
    assert villa.eff_fdr > arsenal.eff_fdr


def test_jadval_vazni_oyin_soni_bilan_osadi():
    """2 o'yinlik jadvalga kam, 20 o'yinlikka ko'proq ishoniladi."""
    early = ratings_mod.effective_difficulty(1.8, 0.6, opp_position=20, opp_played=2,
                                             official_fdr=4)
    late = ratings_mod.effective_difficulty(1.8, 0.6, opp_position=20, opp_played=20,
                                            official_fdr=4)
    assert late < early                        # jadval tasdiqlagani sari osonlashadi

    no_table = ratings_mod.effective_difficulty(1.8, 0.6, opp_position=0, opp_played=0,
                                                official_fdr=4)
    assert no_table > late                     # jadval yo'q — rasmiy FDR ustun


# ----------------------------------------------------------- asosiy 11 lik
def _clone(element: dict, new_id: int, team: int, name: str) -> dict:
    copy_ = dict(element)
    copy_.update({"id": new_id, "team": team, "web_name": name})
    return copy_


def _squad_players(world, elements: list[dict], events: list[int]) -> list[SquadPlayer]:
    engine = EVEngine(world["cfg"], world["rt"], world["views"])
    players = []
    for e in elements:
        profile = build_profile(e, None, world["cfg"], team_matches=3)
        players.append(SquadPlayer(
            ev=engine.evaluate(profile, events),
            purchase_price=e["now_cost"] / 10.0,
            selling_price=e["now_cost"] / 10.0,
        ))
    return players


def test_kuchli_jamoa_oyinchisi_zaxirada_qolmaydi():
    """Bir xil o'yinchi Arsenalda va o'rta jamoada — 11 likka Arsenalniki kiradi.

    Bu aynan Raya/Calafiori holati: ikkala o'yinchi ham mustahkam asosiy
    tarkib, farqi faqat jamoasi va raqibi.
    """
    world = _world()
    by_pos: dict[int, list[dict]] = {1: [], 2: [], 3: [], 4: []}
    for e in world["bs"]["elements"]:
        by_pos[e["element_type"]].append(e)

    # Namuna o'yinchilar — mustahkam asosiy tarkib (minutes/starts to'liq)
    def nailed(source: dict, eid: int, team: int, name: str) -> dict:
        e = _clone(source, eid, team, name)
        e.update({
            "minutes": 270, "starts": 3, "status": "a",
            "chance_of_playing_next_round": None, "news": "",
            "selected_by_percent": "25.0", "now_cost": 55,
        })
        return e

    gk_src = by_pos[1][0]
    def_src = by_pos[2][0]
    pairs = [
        nailed(gk_src, 9001, ARS, "ArsGK"),
        nailed(gk_src, 9002, MID_TABLE, "MidGK"),
        nailed(def_src, 9003, ARS, "ArsDEF"),
        nailed(def_src, 9004, MID_TABLE, "MidDEF"),
    ]
    # Qolgan 11 o'rinni boshqa jamoalardan to'ldiramiz (4 HIM, 5 YAR, 3 HUJ)
    filler = (
        [e for e in by_pos[2] if e["team"] not in (ARS, MID_TABLE)][:4]
        + [e for e in by_pos[3] if e["team"] not in (ARS, MID_TABLE)][:5]
        + [e for e in by_pos[4] if e["team"] not in (ARS, MID_TABLE)][:3]
    )
    players = _squad_players(world, pairs + filler, [4])
    xi, bench, _, _ = best_eleven(players, 4)
    xi_names = {p.name for p in xi}

    assert "ArsGK" in xi_names, "kuchli jamoaning darvozaboni 11 likda bo'lishi kerak"
    assert "MidGK" not in xi_names
    assert "ArsDEF" in xi_names, "kuchli jamoaning himoyachisi 11 likda bo'lishi kerak"

    ars_gk = next(p for p in players if p.name == "ArsGK")
    mid_gk = next(p for p in players if p.name == "MidGK")
    assert ars_gk.ev.per_event[4] > mid_gk.ev.per_event[4]


def test_mustahkam_oyinchi_shubhalidan_ustun():
    """Arzimas EV ustunligi shubhali o'yinchini 11 likka kiritmaydi."""
    world = _world()
    by_pos: dict[int, list[dict]] = {1: [], 2: [], 3: [], 4: []}
    for e in world["bs"]["elements"]:
        by_pos[e["element_type"]].append(e)

    src = by_pos[3][0]
    nailed = _clone(src, 9101, MID_TABLE, "Mustahkam")
    nailed.update({"minutes": 270, "starts": 3, "status": "a", "news": "",
                   "chance_of_playing_next_round": None,
                   "selected_by_percent": "20.0", "now_cost": 60})
    # Bir xil, lekin oxirgi turlarda kam o'ynagan — tarkibga kirishi shubhali
    shaky = dict(nailed)
    shaky.update({"id": 9102, "web_name": "Shubhali", "minutes": 70, "starts": 1,
                  "expected_goals": 0.9, "expected_assists": 0.6})

    squad = [nailed, shaky] + (
        [e for e in by_pos[1] if e["team"] not in (MID_TABLE,)][:2]
        + [e for e in by_pos[2] if e["team"] not in (MID_TABLE,)][:5]
        + [e for e in by_pos[3] if e["team"] not in (MID_TABLE,)][:3]
        + [e for e in by_pos[4] if e["team"] not in (MID_TABLE,)][:3]
    )
    players = _squad_players(world, squad, [4])
    firm = next(p for p in players if p.name == "Mustahkam")
    risky = next(p for p in players if p.name == "Shubhali")

    assert firm.ev.profile.p_start > 0.75
    assert risky.ev.profile.p_start < 0.55
    from fplbrain.squad import selection_score
    assert selection_score(firm, 4) > selection_score(risky, 4) or \
        risky.ev.per_event[4] - firm.ev.per_event[4] > 1.2
