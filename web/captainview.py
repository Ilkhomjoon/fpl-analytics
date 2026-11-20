"""«Kapitan» — kimga bandaj, va nima uchun.

Kapitanlikda o'rtacha EV emas, **taqsimotning tepasi** hal qiladi: ochko
ikkilanadi, shuning uchun 10+ ochko ehtimoli muhim. Ikkinchi o'lchov —
raqiblar kimni qo'ygani: hamma qo'ygan kapitan o'rinni saqlaydi, lekin
ko'tarmaydi. Qaysi biri to'g'riligi menejerning o'rniga bog'liq
(`captain.rank_strategy`).

Raqiblarning kapitan tanlovi menejerning **o'z o'rin oralig'idan** olinadi
(`bands`), **o'tgan tur** holatida: kelgusi tur tanlovi deadline'gacha yopiq.
Bu taxminiy mo'ljal.
"""

from __future__ import annotations

import logging

from fplbrain import bands
from fplbrain import captain as captain_mod
from fplbrain import rivals

from . import squadview

log = logging.getLogger(__name__)

TOP_SAMPLE = 50
STRATEGY_NAMES = {"safe": "xavfsiz", "balanced": "muvozanatli", "aggressive": "tavakkal"}


def _band_captaincy(client, cfg, rank, total, event: int, next_event: int):
    """Menejerning o'rin oralig'idagi kapitan tanlovi: (ulushlar, oraliq nomi, namuna)."""
    if not rank or not total:
        return {}, "", 0
    try:
        sample = bands.load_band(client, cfg, bands.band_for(rank, total), event, next_event)
    except Exception as exc:
        log.warning("oraliq namunasi olinmadi: %s", exc)
        return {}, "", 0
    return ({int(k): v for k, v in sample.get("captaincy", {}).items()},
            sample["band"]["label"], sample.get("size", 0))


def _field_captaincy(client, cfg, event: int) -> dict[int, float]:
    try:
        stats, _ = rivals.top_managers(client, cfg, event, top_n=TOP_SAMPLE)
        return stats.captaincy
    except Exception as exc:                       # raqiblarsiz ham ishlayveradi
        log.warning("top menejerlar olinmadi: %s", exc)
        return {}


def build(client, cfg, entry_id: int, world=None) -> dict:
    world = world or squadview.World(client, cfg, entry_id)
    squad = world.squad()
    event = world.next_event

    rank = total = None
    try:
        rank = client.entry(entry_id).get("summary_overall_rank")
        total = world.bootstrap.get("total_players")
    except Exception as exc:
        log.warning("o'rin olinmadi: %s", exc)
    strategy, reason = captain_mod.rank_strategy(rank, total)

    # Raqiblar — avvalo menejerning O'Z oralig'idan: 1.8 mln-o'rindagi odamga
    # eng yuqori 50 talikning tanlovi emas, atrofidagilarniki muhim. Namuna
    # olinmasa — eski yo'l (top-50).
    captain_eo, field_label, field_size = _band_captaincy(
        client, cfg, rank, total, world.picks_event, event)
    if not captain_eo:
        captain_eo = _field_captaincy(client, cfg, world.picks_event)
        field_label = f"eng yuqori {TOP_SAMPLE}" if captain_eo else ""
        field_size = TOP_SAMPLE if captain_eo else 0
    teams = world.team_ratings

    def rows(mode: str, limit: int = 6) -> list[dict]:
        out = []
        for o in captain_mod.rank_captains(squad, event, captain_eo, mode, limit=limit,
                                           ev_by_element=world.ev):
            profile = o.player.ev.profile
            note = squadview.fixture_note(o.player, event, world.views)
            out.append({
                "element": o.player.element, "name": o.name,
                "pos": profile.position,
                "pos_short": squadview.POS_SHORT.get(profile.position, "?"),
                "team": teams[profile.team].short,
                "opponent": note["opponent"], "eff_fdr": note["eff_fdr"],
                "ev": o.ev, "p10": round(o.p10 * 100, 0), "p15": round(o.p15 * 100, 0),
                "ceiling": o.ceiling, "eo": o.eo, "score": o.score, "verdict": o.verdict,
                "p_start": round(profile.p_start * 100, 0),
            })
        return out

    options = rows(strategy)
    # Ikki chekka: xavfsiz va tavakkal tanlov — yonma-yon ko'rsatish uchun
    safe, bold = rows("safe", 1), rows("aggressive", 1)
    return {
        "entry_id": entry_id, "event": event,
        "rank": rank, "total_players": total,
        "strategy": strategy, "strategy_name": STRATEGY_NAMES[strategy], "reason": reason,
        "options": options,
        "safe": safe[0] if safe else None,
        "bold": bold[0] if bold else None,
        "field_sample": field_size, "field_label": field_label,
        "field_event": world.picks_event,
    }
