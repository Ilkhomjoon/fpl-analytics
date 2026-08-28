#!/usr/bin/env python3
"""Kalibrovka — model chiqargan EV real FPL kutilmalariga mos kelishini tekshiradi.

Ishga tushirish:  python tools/calibrate.py
Kutilgan oraliqlar quyida yozilgan; ular FPL da tanish o'yinchi arxetiplariga asoslangan.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fplbrain.config import Config
from fplbrain.ev import DEF, FWD, GK, MID, build_profile, fixture_ev
from fplbrain.ratings import FixtureView, TeamRating

cfg = Config()

RATINGS = {
    1: TeamRating(1, "Mening jamoam", "MEN", attack=1.35, defence=0.80),
    2: TeamRating(2, "Kuchsiz raqib", "ZAI", attack=0.75, defence=1.30),
    3: TeamRating(3, "Kuchli raqib", "KUC", attack=1.40, defence=0.75),
}

# neytral holat (o'rtacha raqib bilan)
NEUTRAL_FOR, NEUTRAL_AGAINST = 1.55, 1.10


def element(pos: int, price: float, *, mins90: float, xg90: float, xa90: float,
            dc90: float = 0.0, bonus90: float = 0.4, saves90: float = 0.0,
            starts: int = 5, played: int = 5) -> dict:
    """Mavsum yig'indilarini 90 daqiqalik tezliklardan yasaydi."""
    minutes = int(mins90 * 90)
    return {
        "id": 1, "web_name": "Test", "team": 1, "element_type": pos,
        "now_cost": int(price * 10), "status": "a",
        "chance_of_playing_next_round": None, "news": "",
        "minutes": minutes, "starts": starts,
        "expected_goals": xg90 * mins90, "expected_assists": xa90 * mins90,
        "clearances_blocks_interceptions": dc90 * 0.6 * mins90,
        "tackles": dc90 * 0.4 * mins90, "recoveries": 0.0,
        "bonus": bonus90 * mins90, "saves": saves90 * mins90,
        "yellow_cards": 0.12 * mins90, "selected_by_percent": "20.0",
        "penalties_order": None, "cost_change_start": 0,
    }


def ev_for(el: dict, opponent: int, is_home: bool, played: int = 5) -> float:
    profile = build_profile(el, None, cfg, played)
    lam_for = (cfg.home_base_goals if is_home else cfg.away_base_goals) * \
        RATINGS[1].attack * RATINGS[opponent].defence
    lam_against = (cfg.away_base_goals if is_home else cfg.home_base_goals) * \
        RATINGS[opponent].attack * RATINGS[1].defence
    fx = FixtureView(3, 1, opponent, is_home, lam_for, lam_against)
    return fixture_ev(profile, fx, RATINGS, NEUTRAL_FOR, NEUTRAL_AGAINST)


CASES = [
    # (nomi, element, raqib, uyda?, kutilgan min, kutilgan max)
    ("Premium hujumchi (uyda, kuchsiz raqib)",
     element(FWD, 14.5, mins90=5.0, xg90=0.85, xa90=0.18, bonus90=0.9), 2, True, 6.0, 9.5),
    ("Premium hujumchi (mehmonda, kuchli raqib)",
     element(FWD, 14.5, mins90=5.0, xg90=0.85, xa90=0.18, bonus90=0.9), 3, False, 4.0, 7.0),
    ("Premium yarim himoyachi (uyda, kuchsiz)",
     element(MID, 12.5, mins90=5.0, xg90=0.55, xa90=0.35, bonus90=0.9), 2, True, 5.5, 9.0),
    ("O'rtacha yarim himoyachi",
     element(MID, 7.0, mins90=5.0, xg90=0.22, xa90=0.20, dc90=5.0, bonus90=0.4), 2, True, 3.0, 5.5),
    ("Hujumkor himoyachi (uyda, kuchsiz)",
     element(DEF, 6.0, mins90=5.0, xg90=0.10, xa90=0.18, dc90=7.5, bonus90=0.5), 2, True, 3.5, 6.5),
    ("Oddiy himoyachi (mehmonda, kuchli raqib)",
     element(DEF, 4.5, mins90=5.0, xg90=0.03, xa90=0.05, dc90=6.0, bonus90=0.2), 3, False, 1.5, 4.0),
    ("Yaxshi darvozabon (uyda, kuchsiz)",
     element(GK, 5.5, mins90=5.0, xg90=0.0, xa90=0.01, saves90=3.0, bonus90=0.4), 2, True, 3.5, 6.0),
    ("Rotatsiyadagi yarim himoyachi",
     element(MID, 5.5, mins90=1.6, xg90=0.10, xa90=0.10, dc90=4.0, starts=1), 2, True, 0.8, 3.2),
]


def main() -> int:
    print(f"{'Arxetip':46} {'EV':>6}  {'kutilgan':>12}  holat")
    print("-" * 82)
    failures = 0
    for name, el, opp, home, lo, hi in CASES:
        result = ev_for(el, opp, home)
        ok = lo <= result.ev <= hi
        failures += 0 if ok else 1
        print(f"{name:46} {result.ev:6.2f}  {lo:5.1f}–{hi:<5.1f}  {'✓' if ok else '✗ CHEGARADAN TASHQARI'}")

    print("\nTarkibiy qismlar (premium hujumchi, uyda):")
    detail = ev_for(CASES[0][1], 2, True)
    for key, value in detail.parts.items():
        print(f"  {key:14} {value:6.2f}")
    print(f"  {'p(hissa)':14} {detail.p_return:6.2f}")
    print(f"  {'p(haul)':14} {detail.p_haul:6.2f}")

    print("\nTarkibiy qismlar (hujumkor himoyachi, uyda):")
    detail = ev_for(CASES[4][1], 2, True)
    for key, value in detail.parts.items():
        print(f"  {key:14} {value:6.2f}")

    if failures:
        print(f"\n{failures} ta arxetip kutilgan oraliqdan chiqdi.")
    else:
        print("\nHamma arxetip kutilgan oraliqda.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
