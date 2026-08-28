"""Demo rejimi — tarmoqsiz, soxta ma'lumot bilan to'liq hisobotni ko'rish uchun.

    python run.py --demo --dry-run
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.fake import make_bootstrap, make_fixtures, make_picks  # noqa: E402


class FakeClient:
    """FplClient bilan bir xil interfeys, lekin hammasi xotirada."""

    def __init__(self, seed: int = 7, played: int = 2) -> None:
        self.rng = random.Random(seed)
        self._bootstrap = make_bootstrap(seed=seed, played=played)
        self._fixtures = make_fixtures(self._bootstrap, from_gw=played + 1, to_gw=played + 12)
        self._my_picks = make_picks(self._bootstrap, seed=3)
        self.played = played

    # ------------------------------------------------------------ interfeys
    def bootstrap(self) -> dict:
        return self._bootstrap

    def fixtures(self) -> list[dict]:
        return self._fixtures

    def element_summary(self, element_id: int) -> dict:
        e = next(x for x in self._bootstrap["elements"] if x["id"] == element_id)
        rng = random.Random(element_id)
        history = []
        for gw in range(1, self.played + 1):
            starter = (e.get("starts", 0) or 0) > 0
            mins = rng.randint(65, 90) if starter else rng.randint(0, 30)
            history.append({
                "round": gw, "minutes": mins, "starts": 1 if starter else 0,
                "clearances_blocks_interceptions": rng.randint(0, 9),
                "tackles": rng.randint(0, 4), "recoveries": rng.randint(0, 9),
                "expected_goals": round(rng.uniform(0, 0.6), 2),
                "expected_assists": round(rng.uniform(0, 0.4), 2),
                "bonus": rng.choice([0, 0, 0, 1, 2, 3]), "bps": rng.randint(0, 45),
            })
        return {"history": history, "history_past": [], "fixtures": []}

    def entry(self, entry_id: int) -> dict:
        return {
            "id": entry_id, "name": "Demo Jamoa", "player_first_name": "Demo",
            "summary_overall_rank": 245_133, "player_count": 9_730_161,
            "summary_overall_points": 118,
        }

    def entry_history(self, entry_id: int) -> dict:
        return {
            "current": [
                {"event": gw, "event_transfers": 0 if gw == 1 else 1, "points": 55}
                for gw in range(1, self.played + 1)
            ],
            "chips": [],
        }

    def entry_transfers(self, entry_id: int) -> list[dict]:
        return []

    def entry_picks(self, entry_id: int, event: int) -> dict:
        if entry_id == 999_999 or entry_id == getattr(self, "_my_entry", None):
            picks = self._my_picks
        else:
            picks = make_picks(self._bootstrap, seed=entry_id % 5000)
        return {"picks": picks, "entry_history": {"bank": 12}, "active_chip": None}

    def league_standings(self, league_id: int, page: int = 1) -> dict:
        start = (page - 1) * 50 + 1
        return {
            "league": {"id": league_id, "name": f"Demo liga {league_id}"},
            "standings": {
                "results": [
                    {
                        "entry": 100_000 + start + i, "entry_name": f"Jamoa {start+i}",
                        "player_name": f"Menejer {start+i}", "rank": start + i,
                        "total": 130 - i // 3,
                    }
                    for i in range(50)
                ]
            },
        }

    def league_page_for_rank(self, league_id: int, rank: int) -> dict:
        page = max(1, rank // 50)
        return self.league_standings(league_id, page=page)

    def gather(self, items, fn):
        return {item: fn(item) for item in items}
