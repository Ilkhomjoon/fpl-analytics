"""Jonli EV sinovi — bashoratni deadline'dan OLDIN muzlatib, keyin haqiqat bilan solishtiradi.

    python tools/ev_check.py save      # deadline oldidan: kelgusi tur bashoratini saqlaydi
    python tools/ev_check.py check     # tur tugagach: saqlangan bashorat vs haqiqiy ochko
    python tools/ev_check.py check --gw 11

Backtestdan farqi: bu yerda bashorat **haqiqatan oldindan** yozib qo'yiladi —
jarohat bayroqlari, narx va egalik o'sha paytdagi holatda. Backtest bularni
tiklay olmaydi. `save` ni deadline'ga iloji boricha yaqin ishga tushiring
(qayta ishga tushirsangiz, eski nusxa ustidan yoziladi).

Bir tur — juda kichik namuna: bitta o'yinchida ±5 ochko farq oddiy hol.
Qarash kerak bo'lgani — yig'indilar: 11 lik, eng yuqori 20 talik, bias.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fplbrain.api import FplClient                                  # noqa: E402
from fplbrain.config import Config                                  # noqa: E402
from web import squadview                                           # noqa: E402

DEEPEN_TOP = 80          # eng yuqori EV li shuncha o'yinchi batafsil tarix bilan baholanadi


def _path(cfg: Config, gw: int) -> Path:
    return Path(cfg.store_dir) / "ev" / f"gw{gw:02d}.json"


def _client(cfg: Config) -> FplClient:
    # Cookie ataylab berilmaydi: bu vosita faqat ochiq ma'lumot bilan ishlaydi.
    # `.env` dagi eskirgan cookie har safar "my-team olinmadi (403)" degan
    # qo'rqinchli, lekin zararsiz xabar chiqarardi.
    return FplClient(cfg.cache_dir, cfg.cache_ttl_seconds, cfg.request_delay,
                     cfg.max_workers)


def save(cfg: Config) -> None:
    client = _client(cfg)
    world = squadview.World(client, cfg, cfg.entry_id)
    gw = world.next_event
    top = sorted(world.ev.values(), key=lambda p: -p.next_ev)[:DEEPEN_TOP]
    world.deepen([p.element for p in top])
    squad = squadview.build(client, cfg, cfg.entry_id, world=world)

    players = {}
    for element_id, pev in world.ev.items():
        pr = pev.profile
        players[str(element_id)] = {
            "name": pr.name, "pos": pr.position, "team": pr.team,
            "ev": round(pev.per_event.get(gw, 0.0), 3),
            "p_start": round(pr.p_start, 3),
            "detailed": element_id in world.detailed,
        }
    payload = {
        "gw": gw, "saved_at": time.time(),
        "deadline": next((e.get("deadline_time") for e in world.bootstrap["events"]
                          if e["id"] == gw), ""),
        "squad": {
            "entry_id": cfg.entry_id, "authenticated": squad["authenticated"],
            "xi_ev": squad["xi_ev"], "xi_ev_captain": squad["xi_ev_captain"],
            "squad_ev": squad["squad_ev"], "captain": squad["captain"],
            "players": [{"element": r["element"], "name": r["name"],
                         "pos_short": r["pos_short"], "in_xi": r["in_xi"],
                         "ev": r["ev"], "parts": r["detail"]["parts"]}
                        for r in squad["players"]],
        },
        "players": players,
    }
    path = _path(cfg, gw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"GW{gw} bashorati saqlandi: {path}")
    print(f"  deadline: {payload['deadline']}")
    print(f"  11 lik + kapitan ({squad['captain']}): {squad['xi_ev_captain']:.1f}"
          f"   butun tarkib: {squad['squad_ev']:.1f}")
    if not squad["authenticated"]:
        print("  Diqqat: tarkib ochiq ma'lumotdan — oxirgi deadline holatida. Shu "
              "turda transfer qilsangiz, jamoa qismi eskiradi; butun liga bo'yicha "
              "tekshiruvga bu ta'sir qilmaydi.")


def check(cfg: Config, gw: int) -> None:
    store = Path(cfg.store_dir) / "ev"
    if not gw:
        saved = sorted(store.glob("gw*.json"))
        if not saved:
            sys.exit("Saqlangan bashorat yo'q. Avval: python tools/ev_check.py save")
        gw = int(saved[-1].stem[2:])
    path = _path(cfg, gw)
    if not path.exists():
        sys.exit(f"GW{gw} uchun saqlangan bashorat yo'q: {path}")
    snap = json.loads(path.read_text(encoding="utf-8"))

    client = _client(cfg)
    event = next((e for e in client.bootstrap()["events"] if e["id"] == gw), {})
    live = {e["id"]: e["stats"] for e in client.event_live(gw).get("elements", [])}
    if not live:
        sys.exit(f"GW{gw} natijalari hali yo'q.")
    if not event.get("finished"):
        print(f"DIQQAT: GW{gw} hali tugamagan — raqamlar to'liq emas.\n")

    def pts(element) -> int:
        return int((live.get(int(element)) or {}).get("total_points") or 0)

    # --- sizning tarkibingiz ---
    sq = snap["squad"]
    print(f"=== GW{gw} · jamoa {sq['entry_id']} ===")
    xi_pred = xi_act = 0.0
    for p in sq["players"]:
        actual = pts(p["element"])
        mark = "XI " if p["in_xi"] else "zax"
        print(f"  {mark} {p['pos_short']} {p['name']:18s} bashorat {p['ev']:5.1f}"
              f"  haqiqat {actual:3d}  farq {actual - p['ev']:+5.1f}")
        if p["in_xi"]:
            xi_pred += p["ev"]
            xi_act += actual
    captain = next((p for p in sq["players"] if p["name"] == sq["captain"]), None)
    cap_act = pts(captain["element"]) if captain else 0
    print(f"  11 lik: bashorat {xi_pred:.1f} / haqiqat {xi_act:.0f}"
          f"   kapitan bilan ({sq['captain']}): {sq['xi_ev_captain']:.1f} / {xi_act + cap_act:.0f}")
    print("  (Bu — model tavsiya etgan 11 lik va kapitan; FPL dagi haqiqiy "
          "tanlovingiz boshqacha bo'lishi mumkin.)")

    # --- butun liga ---
    rows = [(p["ev"], pts(i), p) for i, p in snap["players"].items() if int(i) in live]
    played = [r for r in rows if r[0] >= 1.0]
    n = len(played) or 1
    bias = sum(e - a for e, a, _ in played) / n
    rmse = math.sqrt(sum((e - a) ** 2 for e, a, _ in played) / n)
    top = sorted(rows, key=lambda r: -r[0])[:20]
    print(f"\n=== butun liga (EV ≥ 1, n={len(played)}) ===")
    print(f"  bias {bias:+.2f}   RMSE {rmse:.2f}   (backtest: bias ~0, RMSE ~2.7)")
    print(f"  model tanlagan top-20: bashorat {sum(r[0] for r in top) / 20:.2f}"
          f" / haqiqat {sum(r[1] for r in top) / 20:.2f}   (backtest: ~5.1 / ~5.1)")
    for lo, hi in ((1, 2), (2, 3), (3, 4), (4, 5), (5, 99)):
        b = [r for r in rows if lo <= r[0] < hi]
        if b:
            print(f"    EV {lo}-{hi if hi < 99 else '+':<2} n={len(b):4d}"
                  f"  bashorat {sum(r[0] for r in b) / len(b):.2f}"
                  f"  haqiqat {sum(r[1] for r in b) / len(b):.2f}")
    print("\n  Eng katta xatolar (top-20 ichida):")
    for e, a, p in sorted(top, key=lambda r: -abs(r[0] - r[1]))[:6]:
        print(f"    {p['name']:18s} bashorat {e:4.1f}  haqiqat {a:3d}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("save", "check"))
    parser.add_argument("--gw", type=int, default=0)
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    cfg = Config.load(args.config)
    if args.command == "save":
        save(cfg)
    else:
        check(cfg, args.gw)


if __name__ == "__main__":
    main()
