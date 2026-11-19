"""H2H — model Free Hit tarkibi ekspertlar tarkibiga qarshi.

    python tools/h2h.py freeze                 # deadline oldidan: model tarkibini muzlatadi
    python tools/h2h.py experts "Raya, Gabriel, … Haaland (c), … | Dubravka, Konsa, …"
    python tools/h2h.py score                  # tur tugagach: ikkala tarkibni hisoblaydi
    python tools/h2h.py table                  # barcha turlar bo'yicha jadval
    python tools/h2h.py backfill               # o'tgan turlar: model orqaga qarab sinaladi

`experts` matni: 11 ism, keyin `|` va 4 zaxira (avtoalmashtirish tartibida).
Kapitan — `(c)`, vitse — `(v)`. `--gw N` berilmasa kelgusi tur olinadi.

`backfill` — backtest: har o'tgan tur uchun faqat o'sha paytgacha bo'lgan
ma'lumotdan tarkib tuziladi. Cheklov: jarohat bayroqlari tarixda yo'q, shuning
uchun model ba'zan o'sha turda jarohatli bo'lgan o'yinchini tanlaydi — jonli
natijadan biroz **yomonroq** chiqishi kutiladi.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from fplbrain import builder, h2h                                    # noqa: E402
from fplbrain.api import FplClient                                   # noqa: E402
from fplbrain.config import Config                                   # noqa: E402
from fplbrain.ev import build_profile                                # noqa: E402

EXPERT_ENTRY = 715763            # FPLUzbekistan — ekspertlarning haqiqiy jamoasi
POS = {1: "DRV", 2: "HIM", 3: "YAR", 4: "HUJ"}


def _client(cfg: Config) -> FplClient:
    return FplClient(cfg.cache_dir, cfg.cache_ttl_seconds, cfg.request_delay,
                     cfg.max_workers)


def _next_event(bootstrap: dict) -> int:
    nxt = next((e for e in bootstrap["events"] if e.get("is_next")), None)
    return nxt["id"] if nxt else max(e["id"] for e in bootstrap["events"])


def _show(title: str, lineup: h2h.Lineup, positions: dict[int, int],
          result: dict | None = None) -> None:
    def label(i: int) -> str:
        mark = " (c)" if i == lineup.captain else (" (v)" if i == lineup.vice else "")
        pts = f" {result['per_player'].get(i, 0)}" if result else ""
        return f"{lineup.names.get(i, i)}{mark}{pts}"

    print(f"  {title}")
    for pos in (1, 2, 3, 4):
        row = [label(i) for i in lineup.xi if positions.get(i) == pos]
        print(f"    {POS[pos]}: " + ", ".join(row))
    print("    zaxira: " + ", ".join(label(i) for i in lineup.bench))


# ------------------------------------------------------------------ freeze
def freeze(cfg: Config) -> None:
    from web import draftview, squadview
    client = _client(cfg)
    world = squadview.World(client, cfg, cfg.entry_id or 1)
    world.deepen(draftview._deepen_candidates(world))
    gw = world.next_event
    # Free Hit — faqat SHU tur uchun: gorizont bitta tur
    built = builder.build_squad(list(world.ev.values()), [gw], cfg)
    if built is None:
        sys.exit("Qonuniy 15 lik topilmadi.")
    lineup = h2h.model_lineup(built, gw)
    path = h2h.save(cfg.store_dir, gw, "model", lineup,
                    note=f"narx {built.cost:.1f}m")
    positions = {p.element: p.position for p in built.players}
    print(f"GW{gw} model tarkibi muzlatildi → {path}")
    _show(f"kutilmoqda {lineup.expected:.1f} ochko · narx {built.cost:.1f}m", lineup, positions)


# ----------------------------------------------------------------- experts
def experts(cfg: Config, text: str, gw: int) -> None:
    client = _client(cfg)
    bootstrap = client.bootstrap()
    gw = gw or _next_event(bootstrap)
    lineup, errors = h2h.parse_lineup(text, bootstrap["elements"])
    positions = {e["id"]: e["element_type"] for e in bootstrap["elements"]}
    _show(f"GW{gw} ekspertlar tarkibi (o'qilgani)", lineup, positions)
    if errors:
        print("\n  XATOLAR — saqlanmadi:")
        for e in errors:
            print(f"    • {e}")
        sys.exit(1)
    cost = sum(e["now_cost"] for e in bootstrap["elements"]
               if e["id"] in set(lineup.xi + lineup.bench)) / 10
    path = h2h.save(cfg.store_dir, gw, "experts", lineup, note=f"narx {cost:.1f}m")
    print(f"\n  saqlandi → {path}  (narx {cost:.1f}m)")


# ------------------------------------------------------------------- score
def _live(client: FplClient, gw: int) -> dict[int, tuple[int, int]]:
    return {e["id"]: (int(e["stats"].get("minutes") or 0),
                      int(e["stats"].get("total_points") or 0))
            for e in client.event_live(gw).get("elements", [])}


def _entry_points(client: FplClient, entry: int) -> dict[int, int]:
    try:
        history = client.entry_history(entry).get("current", [])
    except Exception:
        return {}
    return {h["event"]: h["points"] - h.get("event_transfers_cost", 0) for h in history}


def score(cfg: Config, gw: int) -> None:
    client = _client(cfg)
    bootstrap = client.bootstrap()
    records = h2h.all_records(cfg.store_dir)
    if not gw:
        gw = max((r["gw"] for r in records), default=0)
    record = h2h.load(cfg.store_dir, gw)
    if not record.get("model") and not record.get("experts"):
        sys.exit(f"GW{gw} uchun saqlangan tarkib yo'q.")
    stats = _live(client, gw)
    positions = {e["id"]: e["element_type"] for e in bootstrap["elements"]}
    event = next((e for e in bootstrap["events"] if e["id"] == gw), {})
    if not event.get("finished"):
        print(f"DIQQAT: GW{gw} hali tugamagan — raqamlar to'liq emas.")
    print(f"=== GW{gw} ===")
    for side, title in (("model", "MODEL"), ("experts", "EKSPERTLAR")):
        lineup = h2h.Lineup.from_dict(record.get(side))
        if not lineup:
            print(f"  {title}: tarkib kiritilmagan")
            continue
        result = h2h.score_lineup(lineup, stats, positions)
        _show(f"{title}: {result['points']} ochko"
              + (f" (kutilgan {lineup.expected:.1f})" if lineup.expected else ""),
              lineup, positions, result)
        for out, into in result["subs"]:
            print(f"    avtoalmashtirish: {lineup.names.get(out)} → {lineup.names.get(into)}")
    real = _entry_points(client, EXPERT_ENTRY).get(gw)
    mine = _entry_points(client, cfg.entry_id).get(gw) if cfg.entry_id else None
    print(f"  haqiqiy jamoalar: FPLUzbekistan {real}, siz {mine},"
          f" FPL o'rtachasi {event.get('average_entry_score')}")


def table(cfg: Config) -> None:
    client = _client(cfg)
    bootstrap = client.bootstrap()
    positions = {e["id"]: e["element_type"] for e in bootstrap["elements"]}
    events = {e["id"]: e for e in bootstrap["events"]}
    real = _entry_points(client, EXPERT_ENTRY)
    print("  GW   model  ekspert   farq   FPLUzb  FPL o'rt")
    wins = total_m = total_e = n = 0
    for record in h2h.all_records(cfg.store_dir):
        gw = record["gw"]
        if not events.get(gw, {}).get("finished"):
            continue
        stats = _live(client, gw)
        got = {}
        for side in ("model", "experts"):
            lineup = h2h.Lineup.from_dict(record.get(side))
            got[side] = h2h.score_lineup(lineup, stats, positions)["points"] if lineup else None
        m, e = got["model"], got["experts"]
        diff = f"{m - e:+5d}" if (m is not None and e is not None) else "    —"
        print(f"  {gw:2d}   {m if m is not None else '—':>5}  {e if e is not None else '—':>7}"
              f"  {diff}   {real.get(gw, '—'):>6}  {events[gw].get('average_entry_score', '—'):>8}")
        if m is not None and e is not None:
            n += 1; total_m += m; total_e += e; wins += m > e
    if n:
        print(f"  jami {n} tur: model {total_m}, ekspertlar {total_e},"
              f" model yutgan turlar {wins}/{n}")
        if n < 8:
            print(f"  ({n} tur — xulosa uchun kam: kamida 8-10 tur kerak.)")


# ---------------------------------------------------------------- backfill
def backfill(cfg: Config, first: int) -> None:
    import backtest as bt
    raw = bt.load_raw(cfg)
    bootstrap = raw["bootstrap"]
    histories = {int(i): h for i, h in raw["history"].items()}
    events = {e["id"]: e for e in bootstrap["events"]}
    finished = [e["id"] for e in bootstrap["events"] if e.get("finished")]
    client = _client(cfg)
    real = _entry_points(client, EXPERT_ENTRY)
    mine = _entry_points(client, cfg.entry_id) if cfg.entry_id else {}

    print("  GW  model FH (kutilgan)   FPLUzb    siz   FPL o'rt   kapitan")
    total = {"model": 0, "real": 0, "mine": 0, "avg": 0, "exp": 0.0}
    for k in range(first, max(finished) + 1):
        elements, engine, played, form_base = bt.asof_state(cfg, raw, k, histories)
        evs = []
        for e in elements:
            history = histories[e["id"]]
            if not any(h.get("round") == k for h in history):
                continue
            profile = build_profile(
                e, {"history": [h for h in history if (h.get("round") or 0) < k]},
                cfg, played.get(e["team"], 0), form_base=form_base)
            evs.append(engine.evaluate(profile, [k]))
        built = builder.build_squad(evs, [k], cfg)
        if built is None:
            continue
        lineup = h2h.model_lineup(built, k)
        stats = {i: (sum(h.get("minutes") or 0 for h in rows if h.get("round") == k),
                     sum(h.get("total_points") or 0 for h in rows if h.get("round") == k))
                 for i, rows in histories.items()}
        positions = {e["id"]: e["element_type"] for e in elements}
        result = h2h.score_lineup(lineup, stats, positions)
        avg = events[k].get("average_entry_score") or 0
        cap = lineup.names.get(result["armband"], "—")
        print(f"  {k:2d}   {result['points']:4d}    ({lineup.expected:5.1f})      "
              f"{real.get(k, 0):4d}   {mine.get(k, 0):4d}   {avg:6d}     "
              f"{cap} {result['captain_points']}")
        total["model"] += result["points"]; total["exp"] += lineup.expected
        total["real"] += real.get(k, 0); total["mine"] += mine.get(k, 0); total["avg"] += avg
    print(f"  jami {total['model']:4d}    ({total['exp']:5.0f})      {total['real']:4d}"
          f"   {total['mine']:4d}   {total['avg']:6d}")
    print("\n  Eslatma: model har tur Free Hit o'ynaydi (transfer cheklovi yo'q), "
          "haqiqiy jamoalar esa yo'q —\n  shuning uchun bu ustunlar to'g'ridan-to'g'ri "
          "raqobat emas, miqyos uchun. Halol taqqoslash — ekspertlarning\n  Free Hit "
          "tarkibi bilan (`score` / `table`).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("freeze", "experts", "score", "table", "backfill"))
    parser.add_argument("text", nargs="?", default="")
    parser.add_argument("--gw", type=int, default=0)
    parser.add_argument("--from", dest="first", type=int, default=3)
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    cfg = Config.load(args.config)
    if args.command == "freeze":
        freeze(cfg)
    elif args.command == "experts":
        if not args.text:
            sys.exit('Tarkib matni kerak: python tools/h2h.py experts "… | …"')
        experts(cfg, args.text, args.gw)
    elif args.command == "score":
        score(cfg, args.gw)
    elif args.command == "table":
        table(cfg)
    else:
        backfill(cfg, args.first)


if __name__ == "__main__":
    main()
