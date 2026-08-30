"""Sinovlar uchun umumiy fixture'lar — soxta FPL olami."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fplbrain import ratings
from fplbrain.config import Config
from fplbrain.ev import EVEngine, build_profile
from fplbrain.squad import Squad, SquadPlayer
from tests.fake import make_bootstrap, make_fixtures, make_picks


@pytest.fixture(scope="module")
def world():
    """To'liq soxta olam: jamoalar, o'yinchilar, uchrashuvlar va EV lar."""
    cfg = Config()
    cfg.horizon = 5
    bs = make_bootstrap()
    fx = make_fixtures(bs)
    rt = ratings.build_team_ratings(bs, cfg)
    events = [3, 4, 5, 6, 7]
    views = ratings.build_fixture_views(fx, rt, cfg, events[0], events[-1])
    engine = EVEngine(cfg, rt, views)
    ev_by_element = {}
    for e in bs["elements"]:
        p = build_profile(e, None, cfg, 2)
        ev_by_element[e["id"]] = engine.evaluate(p, events)
    return dict(cfg=cfg, bs=bs, fx=fx, rt=rt, views=views, engine=engine,
                events=events, ev=ev_by_element)


def make_squad(world) -> Squad:
    """Qoidalarga mos 15 kishilik tarkib (soxta olamdan)."""
    bs, ev = world["bs"], world["ev"]
    picks = make_picks(bs)
    by_id = {e["id"]: e for e in bs["elements"]}
    players = [
        SquadPlayer(
            ev=ev[p["element"]],
            purchase_price=by_id[p["element"]]["now_cost"] / 10.0,
            selling_price=by_id[p["element"]]["now_cost"] / 10.0,
            is_captain=p["is_captain"],
            is_vice=p["is_vice_captain"],
        )
        for p in picks
    ]
    return Squad(players=players, bank=1.5, event=3, free_transfers=1)
