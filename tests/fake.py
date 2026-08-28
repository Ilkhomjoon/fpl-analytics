"""Sinov uchun soxta FPL olami — tarmoqsiz ishlaydi."""

from __future__ import annotations

import random

TEAM_NAMES = [
    ("Arsenal", "ARS"), ("Aston Villa", "AVL"), ("Bournemouth", "BOU"), ("Brentford", "BRE"),
    ("Brighton", "BHA"), ("Burnley", "BUR"), ("Chelsea", "CHE"), ("Crystal Palace", "CRY"),
    ("Everton", "EVE"), ("Fulham", "FUL"), ("Leeds", "LEE"), ("Liverpool", "LIV"),
    ("Man City", "MCI"), ("Man Utd", "MUN"), ("Newcastle", "NEW"), ("Nott'm Forest", "NFO"),
    ("Sunderland", "SUN"), ("Spurs", "TOT"), ("West Ham", "WHU"), ("Wolves", "WOL"),
]

POS_COUNT = {1: 3, 2: 8, 3: 9, 4: 4}     # har jamoada


def make_bootstrap(seed: int = 7, played: int = 2) -> dict:
    rng = random.Random(seed)
    teams = []
    for i, (name, short) in enumerate(TEAM_NAMES, start=1):
        base = rng.randint(1050, 1400)
        teams.append({
            "id": i, "name": name, "short_name": short, "played": played,
            "strength": 3,
            "strength_attack_home": base + rng.randint(-60, 60),
            "strength_attack_away": base + rng.randint(-60, 60),
            "strength_defence_home": base + rng.randint(-60, 60),
            "strength_defence_away": base + rng.randint(-60, 60),
        })

    elements, eid = [], 0
    for t in teams:
        for pos, count in POS_COUNT.items():
            for j in range(count):
                eid += 1
                starter = j < {1: 1, 2: 4, 3: 4, 4: 2}[pos]
                minutes = (played * rng.randint(70, 90)) if starter else rng.randint(0, 40)
                nineties = max(minutes / 90.0, 0.01)
                xg_rate = {1: 0.0, 2: 0.06, 3: 0.18, 4: 0.40}[pos] * rng.uniform(0.3, 2.4)
                xa_rate = {1: 0.01, 2: 0.09, 3: 0.18, 4: 0.14}[pos] * rng.uniform(0.3, 2.2)
                dc_rate = {1: 0.0, 2: 7.0, 3: 6.0, 4: 3.0}[pos] * rng.uniform(0.6, 1.5)
                price = {1: 45, 2: 45, 3: 50, 4: 55}[pos] + rng.randint(0, 65)
                elements.append({
                    "id": eid,
                    "web_name": f"{t['short_name']}{pos}{j+1}",
                    "first_name": "Test", "second_name": f"Player{eid}",
                    "team": t["id"], "element_type": pos, "now_cost": price,
                    "cost_change_start": rng.choice([-1, 0, 0, 0, 1, 2]),
                    "status": "a" if rng.random() > 0.05 else "d",
                    "chance_of_playing_next_round": None if rng.random() > 0.08 else rng.choice([25, 50, 75]),
                    "news": "" if rng.random() > 0.06 else "Tizza jarohati - 75% ehtimol",
                    "minutes": minutes,
                    "starts": played if starter else 0,
                    "expected_goals": round(xg_rate * nineties, 2),
                    "expected_assists": round(xa_rate * nineties, 2),
                    "expected_goals_conceded_per_90": round(rng.uniform(0.8, 2.0), 2),
                    "clearances_blocks_interceptions": round(dc_rate * 0.55 * nineties),
                    "tackles": round(dc_rate * 0.25 * nineties),
                    "recoveries": round(dc_rate * 0.6 * nineties),
                    "defensive_contribution": 0,
                    "bonus": rng.randint(0, 3),
                    "bps": rng.randint(0, 60),
                    "saves": rng.randint(0, 10) if pos == 1 else 0,
                    "yellow_cards": rng.randint(0, 1),
                    "selected_by_percent": str(round(rng.uniform(0.1, 45.0), 1)),
                    "penalties_order": 1 if (pos == 4 and j == 0) else None,
                    "corners_and_indirect_freekicks_order": 1 if (pos == 3 and j == 0) else None,
                    "direct_freekicks_order": None,
                    "transfers_in_event": rng.randint(0, 90000),
                    "transfers_out_event": rng.randint(0, 90000),
                    "price_change_percent": str(round(rng.uniform(-105, 105), 1)),
                    "price_change_hourly_rate": rng.randint(0, 900),
                    "total_points": rng.randint(0, 25),
                    "element_type_name": pos,
                })

    events = []
    for gw in range(1, 39):
        events.append({
            "id": gw, "name": f"Gameweek {gw}",
            "deadline_time": f"2026-{8 + (gw // 5):02d}-{(gw % 28) + 1:02d}T17:30:00Z",
            "finished": gw <= played,
            "is_current": gw == played,
            "is_next": gw == played + 1,
            "is_previous": gw == played - 1,
            "average_entry_score": 50,
        })
    events[played]["deadline_time"] = "2026-08-28T17:30:00Z"

    return {"teams": teams, "elements": elements, "events": events,
            "element_types": [{"id": i} for i in range(1, 5)],
            "total_players": 9_730_161}


def make_fixtures(bootstrap: dict, seed: int = 11, from_gw: int = 3, to_gw: int = 12) -> list[dict]:
    rng = random.Random(seed)
    team_ids = [t["id"] for t in bootstrap["teams"]]
    fixtures, fid = [], 0
    for gw in range(from_gw, to_gw + 1):
        pool = team_ids[:]
        rng.shuffle(pool)
        for i in range(0, len(pool) - 1, 2):
            fid += 1
            fixtures.append({
                "id": fid, "event": gw, "team_h": pool[i], "team_a": pool[i + 1],
                "finished": False, "finished_provisional": False,
                "kickoff_time": f"2026-09-{(gw % 28) + 1:02d}T14:00:00Z",
                "team_h_difficulty": rng.randint(2, 5),
                "team_a_difficulty": rng.randint(2, 5),
            })
    return fixtures


def make_picks(bootstrap: dict, seed: int = 3) -> list[dict]:
    """Qoidalarga mos 15 kishilik tarkib (2 DRV, 5 HIM, 5 YAR, 3 HUJ, jamoadan maks 3)."""
    rng = random.Random(seed)
    need = {1: 2, 2: 5, 3: 5, 4: 3}
    per_team: dict[int, int] = {}
    picks, position = [], 0
    for pos, count in need.items():
        pool = [e for e in bootstrap["elements"] if e["element_type"] == pos]
        rng.shuffle(pool)
        taken = 0
        for e in pool:
            if taken >= count:
                break
            if per_team.get(e["team"], 0) >= 3:
                continue
            per_team[e["team"]] = per_team.get(e["team"], 0) + 1
            position += 1
            picks.append({
                "element": e["id"], "position": position, "multiplier": 1,
                "is_captain": False, "is_vice_captain": False,
            })
            taken += 1
    picks[0]["is_captain"] = True
    picks[1]["is_vice_captain"] = True
    return picks
