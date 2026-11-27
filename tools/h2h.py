"""H2H — model Free Hit tarkibi ekspertlar tarkibiga qarshi.

    python tools/h2h.py freeze                 # deadline oldidan: model tarkibini muzlatadi
    python tools/h2h.py import                 # ekspertlar jadvalidan («2026-27 GW Team.xlsx»)
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
        # Jadval qoidasi: 11 lik + kapitan, zaxirasiz — ikkala tomon uchun bir xil
        result = h2h.score_lineup(lineup, stats, positions, autosubs=False)
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
        live_model = bool(record.get("model"))
        sides = {"model": record.get("model") or record.get("model_backtest"),
                 "experts": record.get("experts")}
        for side, data in sides.items():
            lineup = h2h.Lineup.from_dict(data)
            got[side] = (h2h.score_lineup(lineup, stats, positions, autosubs=False)["points"]
                         if lineup else None)
        m, e = got["model"], got["experts"]
        diff = f"{m - e:+5d}" if (m is not None and e is not None) else "    —"
        if m is not None and not live_model:
            diff += " *"                        # * — orqaga qarab tuzilgan (backtest)
        print(f"  {gw:2d}   {m if m is not None else '—':>5}  {e if e is not None else '—':>7}"
              f"  {diff}   {real.get(gw, '—'):>6}  {events[gw].get('average_entry_score', '—'):>8}")
        if m is not None and e is not None:
            n += 1; total_m += m; total_e += e; wins += m > e
    if n:
        print(f"  jami {n} tur: model {total_m}, ekspertlar {total_e},"
              f" model yutgan turlar {wins}/{n}")
        if n < 8:
            print(f"  ({n} tur — xulosa uchun kam: kamida 8-10 tur kerak.)")


# ------------------------------------------------------------------ import
def import_xlsx(cfg: Config, path: str) -> None:
    """Ekspertlar jadvalidan («GW Team» fayli) barcha turlarni yuklaydi."""
    import json
    client = _client(cfg)
    bootstrap = client.bootstrap()
    finished = [e["id"] for e in bootstrap["events"] if e.get("finished")]
    points = {gw: {i: s[1] for i, s in _live(client, gw).items()} for gw in finished}
    positions = {e["id"]: e["element_type"] for e in bootstrap["elements"]}
    for rec in h2h.read_workbook(path, bootstrap["elements"], points):
        gw, team = rec["gw"], rec["team"]
        if gw == _next_event(bootstrap) and len(team.xi) == 11:
            # Kelgusi tur: ekspertlar tarkibini model qanday baholashi ham saqlanadi —
            # deadline'dan keyin model keyingi turga o'tadi va buni qayta hisoblab bo'lmaydi
            try:
                from web import squadview
                world = squadview.World(client, cfg, cfg.entry_id or 1)
                world.deepen(team.xi)
                team.expected = h2h.expected_points(team, world.ev, gw)
            except Exception as exc:
                print(f"  (GW{gw} kutilmasi hisoblanmadi: {type(exc).__name__})")
        record = h2h.load(cfg.store_dir, gw)
        record["gw"] = gw
        record["experts"] = dict(team.as_dict(), note="GW Team (jadval)")
        record.pop("experts_all", None)
        managers = rec["managers"]
        # Shaxsiy tanlovlar — git'ga kirmaydigan papkaga (repo ochiq)
        h2h.save_private(cfg.store_dir, gw, [
            dict(lineup.as_dict(), manager=(managers[n] if n < len(managers) else f"{n + 1}-o'rin"))
            for n, lineup in enumerate(rec["experts"]) if lineup.xi])
        target = h2h.path_for(cfg.store_dir, gw)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")

        line = f"  GW{gw:2d}: {len(team.xi)} o'yinchi, kapitan {team.names.get(team.captain, '—')}"
        if gw in points:
            stats = {i: (90 if p else 0, p) for i, p in points[gw].items()}
            got = h2h.score_lineup(team, stats, positions, autosubs=False)["points"]
            sheet = rec["sheet_scores"][-1] if rec["sheet_scores"] else None
            line += f" — {got} ochko" + ("" if sheet in (None, got) else f"  (jadvalda {sheet} — FARQ!)")
        elif team.expected:
            line += f" — model bahosi {team.expected:.1f}"
        if len(team.xi) != 11:
            line += "  ← 11 ta emas!"
        if rec["missing"]:
            line += f"  TOPILMADI: {', '.join(rec['missing'])}"
        print(line)


# ---------------------------------------------------------------- backfill
def backfill(cfg: Config, first: int) -> None:
    """Model o'tgan turlarda nima tuzgan bo'lardi — ekspertlar jadvaliga qarshi.

    Hisob jadval qoidasi bilan: faqat 11 lik + kapitan (zaxira va
    avtoalmashtirishsiz) — ikkala tomon uchun bir xil.
    """
    import json
    import backtest as bt
    raw = bt.load_raw(cfg)
    bootstrap = raw["bootstrap"]
    histories = {int(i): h for i, h in raw["history"].items()}
    events = {e["id"]: e for e in bootstrap["events"]}
    finished = [e["id"] for e in bootstrap["events"] if e.get("finished")]

    print("  GW   model (kutilgan)  GW Team  eksp. o'rt  eng yaxshi  model o'rni   FPL o'rt   model kapitani")
    tot = {"model": 0, "team": 0, "avg": 0.0, "fpl": 0, "n": 0, "wins": 0, "exp": 0.0}
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
        positions = {e["id"]: e["element_type"] for e in bootstrap["elements"]}
        result = h2h.score_lineup(lineup, stats, positions, autosubs=False)
        model = result["points"]

        # Orqaga qarab tuzilgan tarkib alohida kalitda: jonli muzlatilgani bilan aralashmasin
        record = h2h.load(cfg.store_dir, k)
        record["gw"] = k
        record["model_backtest"] = dict(lineup.as_dict(), note="backtest (jarohat bayroqlarisiz)")
        target = h2h.path_for(cfg.store_dir, k)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")

        team = h2h.Lineup.from_dict(record.get("experts"))
        team_pts = h2h.score_lineup(team, stats, positions, autosubs=False)["points"] if team else None
        each = [h2h.score_lineup(h2h.Lineup.from_dict(x), stats, positions, autosubs=False)["points"]
                for x in h2h.load_private(cfg.store_dir, k)]
        avg = events[k].get("average_entry_score") or 0
        cap = f"{lineup.names.get(result['armband'], '—')} {result['captain_points']}"
        if team_pts is None:
            print(f"  {k:2d}   {model:4d}  ({lineup.expected:5.1f})        —  (ekspertlar tarkibi yo'q)"
                  f"{'':24s}{avg:6d}   {cap}")
            continue
        each = each or [team_pts]            # shaxsiy tanlovlar yuklanmagan bo'lsa
        rank = 1 + sum(1 for s in each if s > model)
        print(f"  {k:2d}   {model:4d}  ({lineup.expected:5.1f})     {team_pts:4d}      "
              f"{sum(each) / len(each):5.1f}       {max(each):4d}     {rank:2d}/{len(each) + 1}"
              f"      {avg:6d}   {cap}")
        tot["model"] += model; tot["team"] += team_pts; tot["avg"] += sum(each) / len(each)
        tot["fpl"] += avg; tot["n"] += 1; tot["wins"] += model > team_pts; tot["exp"] += lineup.expected
    if tot["n"]:
        print(f"  jami {tot['model']:4d}  ({tot['exp']:5.0f})     {tot['team']:4d}      {tot['avg']:5.0f}"
              f"{'':29s}{tot['fpl']:6d}")
        print(f"\n  {tot['n']} tur: model GW Team dan {tot['model'] - tot['team']:+d} ochko,"
              f" yutgan turlari {tot['wins']}/{tot['n']}.")
    print("  Cheklovlar: (1) backtestda jarohat bayroqlari yo'q — model ba'zan o'sha turda jarohatli\n"
          "  o'yinchini tanlaydi; (2) model koeffitsiyentlari shu turlar ma'lumotida tekshirilgan,\n"
          "  ya'ni natija biroz optimistik bo'lishi mumkin. Haqiqiy sinov — GW11 dan boshlab jonli.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("freeze", "experts", "import", "score",
                                            "table", "backfill"))
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
    elif args.command == "import":
        import_xlsx(cfg, args.text or str(ROOT / "2026-27 GW Team.xlsx"))
    elif args.command == "score":
        score(cfg, args.gw)
    elif args.command == "table":
        table(cfg)
    else:
        backfill(cfg, args.first)


if __name__ == "__main__":
    main()
