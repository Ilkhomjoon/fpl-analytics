"""Raqiblar tahlili: mini-liga, top-N menejerlar va mendan ±1% masofadagi jamoalar."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .config import Config
from .squad import Squad


@dataclass
class ManagerEntry:
    entry: int
    name: str
    player_name: str
    rank: int | None
    total: int | None
    picks: list[dict] = field(default_factory=list)
    captain: int | None = None
    chip: str | None = None


@dataclass
class GroupStats:
    label: str
    size: int
    ownership: dict[int, float]        # element -> egalik %
    captaincy: dict[int, float]        # element -> kapitanlik %
    eo: dict[int, float]               # effective ownership % (kapitan 2x hisoblanadi)
    chips: dict[str, int] = field(default_factory=dict)
    avg_total: float = 0.0


# ------------------------------------------------------------------ yuklash
def fetch_group(
    client, cfg: Config, entries: list[ManagerEntry], event: int, label: str
) -> tuple[GroupStats, list[ManagerEntry]]:
    entries = entries[: cfg.max_entry_fetch]
    results = client.gather([e.entry for e in entries], lambda eid: client.entry_picks(eid, event))

    filled: list[ManagerEntry] = []
    for e in entries:
        data = results.get(e.entry)
        if not data:
            continue
        e.picks = data.get("picks", [])
        e.chip = data.get("active_chip")
        cap = next((p for p in e.picks if p.get("is_captain")), None)
        e.captain = cap["element"] if cap else None
        filled.append(e)

    n = len(filled) or 1
    own: dict[int, int] = {}
    cap_count: dict[int, int] = {}
    chips: dict[str, int] = {}
    for e in filled:
        for p in e.picks:
            if p.get("position", 16) <= 11 or True:      # 15 lik tarkibning hammasi
                own[p["element"]] = own.get(p["element"], 0) + 1
        if e.captain:
            cap_count[e.captain] = cap_count.get(e.captain, 0) + 1
        if e.chip:
            chips[e.chip] = chips.get(e.chip, 0) + 1

    ownership = {el: 100.0 * c / n for el, c in own.items()}
    captaincy = {el: 100.0 * c / n for el, c in cap_count.items()}
    eo = {el: ownership.get(el, 0.0) + captaincy.get(el, 0.0) for el in ownership}
    totals = [e.total for e in filled if e.total is not None]

    stats = GroupStats(
        label=label,
        size=len(filled),
        ownership=ownership,
        captaincy=captaincy,
        eo=eo,
        chips=chips,
        avg_total=round(sum(totals) / len(totals), 1) if totals else 0.0,
    )
    return stats, filled


def _entries_from_standings(results: list[dict]) -> list[ManagerEntry]:
    return [
        ManagerEntry(
            entry=r["entry"],
            name=r.get("entry_name", "?"),
            player_name=r.get("player_name", "?"),
            rank=r.get("rank"),
            total=r.get("total"),
        )
        for r in results
        if r.get("entry")
    ]


def mini_league(client, cfg: Config, league_id: int, event: int) -> tuple[GroupStats, list[ManagerEntry], str]:
    data = client.league_standings(league_id, page=1)
    name = (data.get("league") or {}).get("name", f"Liga {league_id}")
    entries = _entries_from_standings((data.get("standings") or {}).get("results", []))
    stats, filled = fetch_group(client, cfg, entries, event, f"Mini-liga: {name}")
    return stats, filled, name


def top_managers(client, cfg: Config, event: int, top_n: int = 100) -> tuple[GroupStats, list[ManagerEntry]]:
    entries: list[ManagerEntry] = []
    pages = math.ceil(top_n / 50)
    for page in range(1, pages + 1):
        data = client.league_standings(cfg.overall_league_id, page=page)
        entries += _entries_from_standings((data.get("standings") or {}).get("results", []))
    entries = entries[:top_n]
    return fetch_group(client, cfg, entries, event, f"Top-{top_n}")


def rank_neighbours(
    client, cfg: Config, my_rank: int, total_players: int, event: int
) -> tuple[GroupStats | None, GroupStats | None]:
    """Mendan ~1% tepa va ~1% pastdagi jamoalar guruhlari."""
    step = max(1, int(total_players * cfg.rank_window_pct / 100.0))
    above_rank = max(1, my_rank - step)
    below_rank = min(total_players, my_rank + step)

    def _group(target: int, label: str) -> GroupStats | None:
        try:
            data = client.league_page_for_rank(cfg.overall_league_id, target)
        except Exception:
            return None
        rows = (data.get("standings") or {}).get("results", [])
        if not rows:
            return None
        # sahifadagi kerakli o'ringa eng yaqin jamoalarni olamiz
        rows.sort(key=lambda r: abs((r.get("rank") or 0) - target))
        entries = _entries_from_standings(rows[: cfg.rank_window_sample])
        stats, _ = fetch_group(client, cfg, entries, event, label)
        return stats

    above = _group(above_rank, f"Mendan ~{cfg.rank_window_pct:g}% tepada (≈{above_rank:,})")
    below = _group(below_rank, f"Mendan ~{cfg.rank_window_pct:g}% pastda (≈{below_rank:,})")
    return above, below


# ----------------------------------------------------------------- solishtirish
@dataclass
class Comparison:
    group: str
    differentials: list[tuple[int, float]]   # menda bor, ularda kam — (element, eo)
    threats: list[tuple[int, float]]         # ularda bor, menda yo'q — (element, eo)
    shared: int
    captain_split: list[tuple[int, float]]
    my_captain_eo: float


def compare(squad: Squad, stats: GroupStats, my_captain: int | None, top: int = 6) -> Comparison:
    mine = {p.element for p in squad.players}
    diffs = sorted(
        [(el, stats.eo.get(el, 0.0)) for el in mine],
        key=lambda x: x[1],
    )[:top]
    threats = sorted(
        [(el, eo) for el, eo in stats.eo.items() if el not in mine],
        key=lambda x: -x[1],
    )[:top]
    caps = sorted(stats.captaincy.items(), key=lambda x: -x[1])[:5]
    return Comparison(
        group=stats.label,
        differentials=diffs,
        threats=threats,
        shared=len(mine & set(stats.ownership.keys())),
        captain_split=caps,
        my_captain_eo=stats.captaincy.get(my_captain, 0.0) if my_captain else 0.0,
    )


def swing_estimate(
    comparison: Comparison, ev_by_element: dict[int, "object"], event: int
) -> tuple[float, float]:
    """Differensiallar va tahdidlar bo'yicha kutilayotgan ochko farqi (taxminiy)."""
    gain = 0.0
    for el, eo in comparison.differentials:
        pev = ev_by_element.get(el)
        if pev:
            gain += pev.per_event.get(event, 0.0) * (1 - eo / 100.0)
    loss = 0.0
    for el, eo in comparison.threats:
        pev = ev_by_element.get(el)
        if pev:
            loss += pev.per_event.get(event, 0.0) * (eo / 100.0)
    return round(gain, 2), round(loss, 2)
