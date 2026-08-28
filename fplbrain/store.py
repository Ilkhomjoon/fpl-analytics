"""Kunlik snapshotlar: narx, ownership va injury xabarlarining o'zgarishini ko'rish uchun."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


class Store:
    def __init__(self, directory: Path) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ umumiy
    def _path(self, name: str) -> Path:
        return self.dir / f"{name}.json"

    def read(self, name: str, default: Any = None) -> Any:
        p = self._path(name)
        if not p.exists():
            return default
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default

    def write(self, name: str, data: Any) -> None:
        self._path(name).write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    # ------------------------------------------------------- o'yinchi snapshoti
    def snapshot_players(self, elements: list[dict]) -> dict[str, dict]:
        """Bugungi holatni saqlaydi va oldingi snapshotni qaytaradi."""
        prev = self.read("players_snapshot", default={}) or {}
        current = {
            str(e["id"]): {
                "now_cost": e["now_cost"],
                "selected_by_percent": float(e.get("selected_by_percent") or 0),
                "status": e.get("status"),
                "news": e.get("news") or "",
                "chance": e.get("chance_of_playing_next_round"),
                "transfers_in_event": e.get("transfers_in_event", 0),
                "transfers_out_event": e.get("transfers_out_event", 0),
                "price_change_percent": float(e.get("price_change_percent") or 0),
            }
            for e in elements
        }
        self.write("players_snapshot", current)
        history = self.read("snapshot_dates", default=[]) or []
        today = date.today().isoformat()
        if today not in history:
            history.append(today)
            self.write("snapshot_dates", history[-60:])
        return prev

    # ------------------------------------------------------------ hisobot logi
    def log_run(self, mode: str, summary: dict) -> None:
        runs = self.read("runs", default=[]) or []
        runs.append({"mode": mode, **summary})
        self.write("runs", runs[-120:])
