"""Walk-forward backtest — EV modeli haqiqiy ochkoga qanchalik mos.

Har o'tgan tur `k` uchun: **faqat k-turgacha bo'lgan** ma'lumotdan o'yinchi
profili va jamoa reytinglari qayta quriladi, model k-turni bashorat qiladi,
natija haqiqiy ochko bilan solishtiriladi. Kelajak ma'lumoti ishlatilmaydi.

    python tools/backtest.py                 # 3-turdan oxirgi tugagan turgacha
    python tools/backtest.py --refresh       # FPL dan qayta yuklash
    python tools/backtest.py --from 5 --json data/cache/backtest.json

Nimani o'lchaydi:
  * umumiy xato (bias, MAE, RMSE) va pozitsiya bo'yicha;
  * **qismlar** bo'yicha: ishtirok, gol, uzatma, toza darvoza, DefCon, bonus…
    — qaysi qism oshirib yoki kamaytirib ko'rsatilayotgani shu yerda ko'rinadi;
  * daqiqalar modeli: `p_start` va `p60` haqiqiy ulushlarga mosmi;
  * tartiblash: eng yuqori baholangan o'yinchilar haqiqatan ko'p ochko oldimi.

Cheklovlar (halol bo'lish uchun):
  * Jarohat bayroqlari (`status`, `chance_of_playing`) tarixda YO'Q. Shuning
    uchun asosiy tanlanma — "safdagi" o'yinchilar: oldingi ikki turning
    (k-1, k-2) kamida birida maydonga tushganlar. Uzoq jarohatdagilar shu
    bilan chiqib ketadi; endigina jarohatlanganlar esa qoladi — jonli model
    ularni bayroq orqali ko'radi, backtest ko'rmaydi (daqiqalar biroz oshadi).
  * Jamoalarning FPL `strength` qiymatlari — bugungi (tarixi yo'q).
  * Penaltichi/standart belgilari — bugungi.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fplbrain import congestion                                    # noqa: E402
from fplbrain import ratings as ratings_mod                        # noqa: E402
from fplbrain import table as table_mod                            # noqa: E402
from fplbrain.api import FplClient                                 # noqa: E402
from fplbrain.config import Config                                 # noqa: E402
from fplbrain.ev import (CS_POINTS, DEFCON_THRESHOLD, GOAL_POINTS,  # noqa: E402
                         EVEngine, build_profile, form_baseline)

RAW_PATH = ROOT / "data" / "cache" / "backtest_raw.json"
POS = {1: "DRV", 2: "HIM", 3: "YAR", 4: "HUJ"}
PARTS = ["ishtirok", "gol", "uzatma", "toza_darvoza", "kiritilgan",
         "to'xtatish", "defcon", "bonus", "kartochka", "boshqa"]

# Tarix qatoridan yig'iladigan maydonlar (bootstrap dagi nomlari bilan bir xil)
SUM_INT = ["minutes", "starts", "goals_scored", "assists", "clean_sheets",
           "goals_conceded", "own_goals", "penalties_saved", "penalties_missed",
           "yellow_cards", "red_cards", "saves", "bonus", "bps", "total_points",
           "clearances_blocks_interceptions", "recoveries", "tackles",
           "defensive_contribution"]
SUM_FLOAT = ["expected_goals", "expected_assists", "expected_goal_involvements",
             "expected_goals_conceded"]


def _f(value, default: float = 0.0) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _when(text: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat((text or "").replace("Z", "+00:00"))
    except ValueError:
        return None


# ------------------------------------------------------------------ yuklash
def load_raw(cfg: Config, refresh: bool = False) -> dict:
    """Bootstrap, uchrashuvlar va o'ynagan har bir o'yinchining tarixi."""
    if RAW_PATH.exists() and not refresh:
        return json.loads(RAW_PATH.read_text(encoding="utf-8"))
    client = FplClient(cfg.cache_dir, cfg.cache_ttl_seconds, cfg.request_delay,
                       cfg.max_workers)
    bootstrap, fixtures = client.bootstrap(), client.fixtures()
    ids = [e["id"] for e in bootstrap["elements"] if (e.get("minutes") or 0) > 0]
    print(f"{len(ids)} o'yinchi tarixi yuklanmoqda…", file=sys.stderr)
    summaries = client.gather(ids, client.element_summary)
    raw = {
        "saved_at": time.time(),
        "bootstrap": bootstrap,
        "fixtures": fixtures,
        "history": {str(i): (s or {}).get("history", []) for i, s in summaries.items()},
    }
    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    RAW_PATH.write_text(json.dumps(raw), encoding="utf-8")
    return raw


# ------------------------------------------------------- o'sha paytdagi holat
def asof_element(element: dict, history: list[dict], k: int,
                 total_players: int, deadline: datetime | None) -> dict:
    """O'yinchining `k`-tur deadline'idagi bootstrap ko'rinishi."""
    past = [h for h in history if (h.get("round") or 0) < k]
    now = [h for h in history if h.get("round") == k]
    e = dict(element)
    for key in SUM_INT:
        e[key] = sum(int(h.get(key) or 0) for h in past)
    for key in SUM_FLOAT:
        e[key] = round(sum(_f(h.get(key)) for h in past), 2)

    minutes = e["minutes"]
    e["expected_goals_conceded_per_90"] = (
        round(e["expected_goals_conceded"] / minutes * 90, 2) if minutes else 0.0)

    # Narx va egalik — tur qatorida deadline holatida turadi (o'yindan oldin ma'lum)
    ref = now[0] if now else (past[-1] if past else None)
    if ref:
        e["now_cost"] = ref.get("value") or element["now_cost"]
        if total_players:
            e["selected_by_percent"] = round(
                100.0 * (ref.get("selected") or 0) / total_players, 1)

    # Forma: so'nggi 30 kundagi o'yinlar bo'yicha o'rtacha ochko
    if deadline:
        since = deadline - timedelta(days=30)
        window = [h for h in past if (_when(h.get("kickoff_time")) or since) >= since]
        e["form"] = round(sum(h.get("total_points") or 0 for h in window)
                          / len(window), 1) if window else 0.0

    # Bootstrapdagi `event_points` — oxirgi tugagan turdagi ochko
    e["event_points"] = sum(h.get("total_points") or 0
                            for h in past if h.get("round") == k - 1)

    # Jarohat bayroqlari tarixda yo'q — hammani sog'lom deb olamiz (cheklov)
    e["status"], e["news"] = "a", ""
    e["chance_of_playing_next_round"] = None
    return e


def asof_fixtures(fixtures: list[dict], k: int) -> list[dict]:
    """`k` va undan keyingi turlar hali o'ynalmagan ko'rinishda."""
    out = []
    for f in fixtures:
        if (f.get("event") or 99) >= k:
            f = dict(f, finished=False, finished_provisional=False,
                     team_h_score=None, team_a_score=None)
        out.append(f)
    return out


def actual_parts(pos: int, rows: list[dict]) -> dict[str, float]:
    """Haqiqiy ochkoning model qismlari bilan bir xil bo'linishi."""
    parts = dict.fromkeys(PARTS, 0.0)
    for h in rows:
        minutes = h.get("minutes") or 0
        if minutes <= 0:
            continue
        parts["ishtirok"] += 2 if minutes >= 60 else 1
        parts["gol"] += (h.get("goals_scored") or 0) * GOAL_POINTS[pos]
        parts["uzatma"] += (h.get("assists") or 0) * 3
        if minutes >= 60 and (h.get("clean_sheets") or 0):
            parts["toza_darvoza"] += CS_POINTS[pos]
        if pos in (1, 2):
            parts["kiritilgan"] -= (h.get("goals_conceded") or 0) // 2
        if pos == 1:
            parts["to'xtatish"] += (h.get("saves") or 0) // 3
            parts["to'xtatish"] += (h.get("penalties_saved") or 0) * 5
        if pos in DEFCON_THRESHOLD and \
                (h.get("defensive_contribution") or 0) >= DEFCON_THRESHOLD[pos]:
            parts["defcon"] += 2
        parts["bonus"] += h.get("bonus") or 0
        parts["kartochka"] -= (h.get("yellow_cards") or 0) + 3 * (h.get("red_cards") or 0)
        parts["boshqa"] -= 2 * ((h.get("own_goals") or 0) + (h.get("penalties_missed") or 0))
    return parts


# ------------------------------------------------------------------- yurish
def asof_state(cfg: Config, raw: dict, k: int, histories: dict[int, list] | None = None):
    """`k`-tur deadline'idagi dunyo: (o'yinchilar, EV dvigateli, o'ynalgan o'yinlar, forma bazasi)."""
    bootstrap, fixtures = raw["bootstrap"], raw["fixtures"]
    if histories is None:
        histories = {int(i): h for i, h in raw["history"].items()}
    deadline = next((_when(e.get("deadline_time")) for e in bootstrap["events"]
                     if e["id"] == k), None)
    total_players = bootstrap.get("total_players") or 0
    elements = [
        asof_element(e, histories[e["id"]], k, total_players, deadline)
        for e in bootstrap["elements"] if e["id"] in histories
    ]
    boot = dict(bootstrap, elements=elements)
    fx = asof_fixtures(fixtures, k)
    table = table_mod.build_table(boot, fx)
    team_ratings = ratings_mod.build_team_ratings(boot, cfg, table)
    views = ratings_mod.build_fixture_views(
        fx, team_ratings, cfg, k, k,
        schedules=congestion.build_schedules(fx),
        european=congestion.european_team_ids(cfg, bootstrap.get("teams", [])),
        table=table)
    engine = EVEngine(cfg, team_ratings, views)
    played = {tid: row.played for tid, row in table.items()}
    return elements, engine, played, form_baseline(elements)


def run(cfg: Config, raw: dict, first: int, last: int, use_history: bool) -> list[dict]:
    """Har (o'yinchi, tur) uchun bashorat va haqiqat. `use_history` — batafsil
    tarix bilan (jamoangizdagi o'yinchilar shunday baholanadi) yoki faqat
    mavsum yig'indisi bilan (qolgan hamma shunday baholanadi)."""
    histories = {int(i): h for i, h in raw["history"].items()}
    records: list[dict] = []

    for k in range(first, last + 1):
        elements, engine, played, form_base = asof_state(cfg, raw, k, histories)

        for e in elements:
            history = histories[e["id"]]
            rows = [h for h in history if h.get("round") == k]
            if not rows:                                   # bo'sh tur yoki hali kelmagan
                continue
            summary = ({"history": [h for h in history if (h.get("round") or 0) < k]}
                       if use_history else None)
            profile = build_profile(
                e, summary, cfg, played.get(e["team"], 0), form_base=form_base,
                last_event_played=any(h.get("round") == k - 1 for h in history))
            pev = engine.evaluate(profile, [k])
            fxs = pev.fixtures.get(k, [])
            if not fxs:
                continue
            pred = dict.fromkeys(PARTS, 0.0)
            for f in fxs:
                for key, value in f.parts.items():
                    pred[key] += value
            minutes = sum(h.get("minutes") or 0 for h in rows)
            # Faqat O'TMISH: k-turning o'zi kirsa, tanlanma natijaga qarab
            # saralangan bo'lardi va past ehtimolli o'yinchilar sun'iy ravishda
            # "kam baholangan" ko'rinardi.
            near = [h for h in history if 1 <= k - (h.get("round") or 0) <= 2]
            records.append({
                "gw": k, "element": e["id"], "name": e.get("web_name", "?"),
                "pos": e["element_type"], "price": e["now_cost"] / 10.0,
                "ev": pev.per_event.get(k, 0.0), "pred": pred,
                "p_start": profile.p_start, "p60": profile.p60,
                "p_appear": profile.p_appear,
                "p_cs": fxs[0].inputs.p_cs, "p_dc": fxs[0].inputs.p_dc,
                "pts": sum(h.get("total_points") or 0 for h in rows),
                "act": actual_parts(e["element_type"], rows),
                "minutes": minutes,
                "started": any((h.get("starts") or 0) > 0 for h in rows),
                "sixty": any((h.get("minutes") or 0) >= 60 for h in rows),
                "cs": any((h.get("clean_sheets") or 0) for h in rows),
                "team_cs": any((h.get("goals_conceded") or 0) == 0
                               and (h.get("minutes") or 0) >= 60 for h in rows),
                # "safda": oldingi ikki turning birida o'ynagan — uzoq jarohat emas
                "active": any((h.get("minutes") or 0) > 0 for h in near),
                "ppg": (e["total_points"] / played[e["team"]]
                        if played.get(e["team"]) else 0.0),
                "n_fix": len(rows),
            })
    return records


# ------------------------------------------------------------------ hisobot
def _stats(rows: list[dict], key: str = "ev") -> dict:
    n = len(rows)
    if not n:
        return {"n": 0, "pred": 0.0, "act": 0.0, "bias": 0.0, "mae": 0.0, "rmse": 0.0}
    err = [r[key] - r["pts"] for r in rows]
    return {
        "n": n,
        "pred": sum(r[key] for r in rows) / n,
        "act": sum(r["pts"] for r in rows) / n,
        "bias": sum(err) / n,
        "mae": sum(abs(x) for x in err) / n,
        "rmse": math.sqrt(sum(x * x for x in err) / n),
    }


def _spearman(xs: list[float], ys: list[float]) -> float:
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        out = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for t in range(i, j + 1):
                out[order[t]] = (i + j) / 2.0
            i = j + 1
        return out
    if len(xs) < 3:
        return 0.0
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else 0.0


def summarise(records: list[dict]) -> dict:
    """Hisobotning mashina o'qiydigan ko'rinishi (testlar va taqqoslash uchun)."""
    active = [r for r in records if r["active"]]
    out: dict = {"all": _stats(records), "active": _stats(active),
                 "naive_ppg": _stats(active, "ppg")}
    out["by_pos"] = {POS[p]: _stats([r for r in active if r["pos"] == p]) for p in POS}

    parts: dict = {}
    for p in POS:
        rows = [r for r in active if r["pos"] == p]
        n = len(rows) or 1
        parts[POS[p]] = {
            key: (sum(r["pred"][key] for r in rows) / n,
                  sum(r["act"][key] for r in rows) / n) for key in PARTS}
    out["parts"] = parts

    buckets = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 99)]
    out["ev_buckets"] = [
        dict(_stats([r for r in active if lo <= r["ev"] < hi]), lo=lo, hi=hi)
        for lo, hi in buckets]

    mins = []
    for lo, hi in [(0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, .9), (.9, 1.01)]:
        rows = [r for r in active if lo <= r["p_start"] < hi]
        n = len(rows) or 1
        mins.append({"lo": lo, "hi": hi, "n": len(rows),
                     "p_start": sum(r["p_start"] for r in rows) / n,
                     "started": sum(r["started"] for r in rows) / n,
                     "p60": sum(r["p60"] for r in rows) / n,
                     "sixty": sum(r["sixty"] for r in rows) / n})
    out["minutes"] = mins

    # Tartiblash: har turda eng yuqori baholangan 20 o'yinchining haqiqiy ochkosi
    by_gw = defaultdict(list)
    for r in active:
        by_gw[r["gw"]].append(r)
    top_model, top_naive, rho = [], [], []
    for rows in by_gw.values():
        top_model += sorted(rows, key=lambda r: -r["ev"])[:20]
        top_naive += sorted(rows, key=lambda r: -r["ppg"])[:20]
        cand = [r for r in rows if r["ev"] >= 2.0]
        rho.append(_spearman([r["ev"] for r in cand], [r["pts"] for r in cand]))
    out["top20_model"] = sum(r["pts"] for r in top_model) / (len(top_model) or 1)
    out["top20_naive"] = sum(r["pts"] for r in top_naive) / (len(top_naive) or 1)
    out["top20_pred"] = sum(r["ev"] for r in top_model) / (len(top_model) or 1)
    out["spearman"] = sum(rho) / (len(rho) or 1)

    # Toza darvoza: bashorat qilingan ehtimol va haqiqiy ulush (60+ o'ynaganlar)
    cs_rows = [r for r in active if r["pos"] in (1, 2) and r["sixty"] and r["n_fix"] == 1]
    out["cs"] = {"n": len(cs_rows),
                 "pred": sum(r["p_cs"] for r in cs_rows) / (len(cs_rows) or 1),
                 "act": sum(r["cs"] for r in cs_rows) / (len(cs_rows) or 1)}
    dc_rows = [r for r in active if r["pos"] in (2, 3, 4) and r["sixty"] and r["n_fix"] == 1]
    out["dc"] = {POS[p]: {
        "n": len([r for r in dc_rows if r["pos"] == p]),
        "pred": sum(r["p_dc"] for r in dc_rows if r["pos"] == p)
                / (len([r for r in dc_rows if r["pos"] == p]) or 1),
        "act": sum(r["act"]["defcon"] / 2 for r in dc_rows if r["pos"] == p)
               / (len([r for r in dc_rows if r["pos"] == p]) or 1)} for p in (2, 3, 4)}
    return out


def report(label: str, s: dict) -> None:
    def line(name, st):
        print(f"  {name:14s} n={st['n']:5d}  bashorat {st['pred']:5.2f}  haqiqat {st['act']:5.2f}"
              f"  bias {st['bias']:+5.2f}  MAE {st['mae']:4.2f}  RMSE {st['rmse']:4.2f}")
    print(f"\n=== {label} ===")
    line("hamma", s["all"])
    line("safdagilar", s["active"])
    line("sodda (PPG)", s["naive_ppg"])
    for name, st in s["by_pos"].items():
        line(name, st)

    print("\n  Qismlar (bashorat / haqiqat, o'yinchi-turga o'rtacha):")
    print("  " + " " * 14 + "".join(f"{POS[p]:>15s}" for p in POS))
    for key in PARTS:
        print(f"  {key:14s}" + "".join(
            f"{s['parts'][POS[p]][key][0]:7.2f}/{s['parts'][POS[p]][key][1]:5.2f}  "
            for p in POS))

    print("\n  EV oralig'i bo'yicha kalibrovka:")
    for b in s["ev_buckets"]:
        if b["n"]:
            print(f"    EV {b['lo']}-{b['hi'] if b['hi'] < 99 else '+':<2}  n={b['n']:5d}"
                  f"  bashorat {b['pred']:5.2f}  haqiqat {b['act']:5.2f}  bias {b['bias']:+5.2f}")

    print("\n  Daqiqalar (p_start oralig'i → haqiqiy ulush):")
    for m in s["minutes"]:
        if m["n"]:
            print(f"    {m['lo']:.1f}-{min(m['hi'], 1.0):.1f}  n={m['n']:5d}"
                  f"  p_start {m['p_start']:.2f} → boshladi {m['started']:.2f}"
                  f"   p60 {m['p60']:.2f} → 60+ {m['sixty']:.2f}")

    print(f"\n  Toza darvoza (60+ o'ynagan DRV/HIM): bashorat {s['cs']['pred']:.3f}"
          f" / haqiqat {s['cs']['act']:.3f}  (n={s['cs']['n']})")
    for name, d in s["dc"].items():
        print(f"  DefCon {name} (60+): bashorat {d['pred']:.3f} / haqiqat {d['act']:.3f}"
              f"  (n={d['n']})")
    print(f"\n  Top-20 (har turda): model tanlagani o'rtacha {s['top20_model']:.2f} ochko oldi"
          f" (bashorat {s['top20_pred']:.2f}); sodda PPG tanlagani {s['top20_naive']:.2f}")
    print(f"  Spearman (EV ≥ 2): {s['spearman']:.3f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="first", type=int, default=3)
    parser.add_argument("--to", dest="last", type=int, default=0)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--json", default="")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    cfg = Config.load(args.config)
    raw = load_raw(cfg, args.refresh)
    finished = [e["id"] for e in raw["bootstrap"]["events"] if e.get("finished")]
    last = args.last or (max(finished) if finished else 0)
    if last < args.first:
        sys.exit("Backtest uchun tugagan turlar yetarli emas.")

    result = {}
    for label, use_history in (("faqat mavsum yig'indisi (ro'yxatdagi hamma)", False),
                               ("batafsil tarix bilan (jamoangizdagilar)", True)):
        records = run(cfg, copy.deepcopy(raw), args.first, last, use_history)
        s = summarise(records)
        report(f"GW{args.first}-{last} · {label}", s)
        result["history" if use_history else "bootstrap"] = s
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
