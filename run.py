#!/usr/bin/env python3
"""FPL tahlil dvigateli — kunlik brifing va deadline hisobotini Telegramga jo'natadi.

Ishlatish:
    python run.py --dry-run            # Telegramga JO'NATMAYDI, ekranga chiqaradi
    python run.py --dry-run --out      # hisobot.html ga yozadi (brauzerda o'qish uchun)
    python run.py                      # jadvalga qarab rejimni o'zi tanlaydi
    python run.py --mode deadline      # to'liq hisobotni majburan yasaydi
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


from fplbrain import captain as captain_mod
from fplbrain import chips as chips_mod
from fplbrain import market, ratings, report, rivals, transfers
from fplbrain.api import FplClient
from fplbrain.config import Config
from fplbrain.ev import EVEngine, PlayerEV, build_profile
from fplbrain.squad import load_squad, squad_ev
from fplbrain.store import Store
from fplbrain.telegram import Telegram

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("fplbrain")


# ----------------------------------------------------------------- yordamchi
def pick_events(bootstrap: dict, horizon: int) -> tuple[int, int, dict]:
    """(joriy tugagan GW, keyingi GW, keyingi GW obyekti)."""
    events = bootstrap["events"]
    nxt = next((e for e in events if e.get("is_next")), None)
    cur = next((e for e in events if e.get("is_current")), None)
    if nxt is None:
        nxt = next((e for e in events if not e.get("finished")), events[-1])
    finished = cur["id"] if cur else max([e["id"] for e in events if e.get("finished")] or [1])
    return finished, nxt["id"], nxt


def team_matches_played(bootstrap: dict, fixtures: list[dict]) -> dict[int, int]:
    """Har jamoa nechta o'yin o'ynagani (teams.played ishonchsiz bo'lsa fixtures dan)."""
    played = {t["id"]: t.get("played", 0) or 0 for t in bootstrap["teams"]}
    if any(played.values()):
        return played
    for f in fixtures:
        if f.get("finished"):
            played[f["team_h"]] = played.get(f["team_h"], 0) + 1
            played[f["team_a"]] = played.get(f["team_a"], 0) + 1
    return played


def build_all_ev(cfg, client, bootstrap, engine, events, focus_ids: set[int],
                 played: dict[int, int]) -> dict[int, PlayerEV]:
    """Ikki bosqichli EV: avval bootstrap ma'lumoti, keyin muhim o'yinchilar uchun batafsil tarix."""
    elements = bootstrap["elements"]
    ev_by_element: dict[int, PlayerEV] = {}

    for e in elements:
        if e.get("status") == "u":                  # klubdan ketgan
            continue
        profile = build_profile(e, None, cfg, played.get(e["team"], 0))
        ev_by_element[e["id"]] = engine.evaluate(profile, events)

    # kimlar uchun batafsil tarix kerak: mening tarkibim + eng istiqbolli o'yinchilar
    ranked = sorted(ev_by_element.values(), key=lambda p: -p.horizon_ev)
    detail_ids = set(focus_ids)
    for pev in ranked:
        if len(detail_ids) >= cfg.detail_players:
            break
        detail_ids.add(pev.element)

    log.info("Batafsil tarix yuklanmoqda: %d o'yinchi", len(detail_ids))
    summaries = client.gather(sorted(detail_ids), client.element_summary)
    by_id = {e["id"]: e for e in elements}
    for el, summary in summaries.items():
        if not summary or el not in by_id:
            continue
        profile = build_profile(by_id[el], summary, cfg, played.get(by_id[el]["team"], 0))
        ev_by_element[el] = engine.evaluate(profile, events)
    return ev_by_element


def collect_rivals(client, cfg, event: int, squad, my_captain, ev_by_element, entry_info,
                   total_players: int = 0):
    """Mini-liga(lar), top-N va ±1% guruhlarini yig'adi."""
    comparisons, stats_list, captain_eo = [], [], {}

    for league_id in cfg.mini_league_ids:
        try:
            stats, _, _ = rivals.mini_league(client, cfg, league_id, event)
            comparisons.append(rivals.compare(squad, stats, my_captain))
            stats_list.append(stats)
        except Exception as exc:
            log.warning("Mini-liga %s yuklanmadi: %s", league_id, exc)

    try:
        top_stats, _ = rivals.top_managers(client, cfg, event, cfg.top_n_managers)
        comparisons.append(rivals.compare(squad, top_stats, my_captain))
        stats_list.append(top_stats)
        captain_eo = dict(top_stats.captaincy)
    except Exception as exc:
        log.warning("Top-%s yuklanmadi: %s", cfg.top_n_managers, exc)

    my_rank = (entry_info or {}).get("summary_overall_rank")
    total = total_players or 0
    if my_rank and total:
        try:
            above, below = rivals.rank_neighbours(client, cfg, my_rank, total, event)
            for st in (above, below):
                if st:
                    comparisons.append(rivals.compare(squad, st, my_captain))
                    stats_list.append(st)
        except Exception as exc:
            log.warning("±%s%% guruhlari yuklanmadi: %s", cfg.rank_window_pct, exc)

    return comparisons, stats_list, captain_eo


# ------------------------------------------------------------ sessiya tekshiruvi
# Bu tokenlar brauzer/IP ga bog'langan — boshqa mashinada (GitHub Actions) ishlamaydi
BROWSER_BOUND_COOKIES = ("cf_clearance", "datadome")
# Sessiyani tasdiqlaydiganlari. FPL PingOne SSO ga o'tgan: asosiylari
# access_token va global_sso_id; eski Django nomlari hamon uchrashi mumkin.
NEEDED_COOKIES = ("access_token", "global_sso_id", "pl_profile", "sessionid")


def check_auth(cfg: Config) -> int:
    """Cookie ishlayaptimi — my-team endpointiga bitta so'rov bilan tekshiradi."""
    if not cfg.fpl_cookie:
        print("FPL_COOKIE berilmagan. Ochiq ma'lumot bilan ishlaydi, "
              "lekin sotish narxi va FT taxminiy bo'ladi.")
        return 1
    if not cfg.entry_id:
        print("entry_id ko'rsatilmagan.")
        return 2

    present = [c for c in NEEDED_COOKIES if f"{c}=" in cfg.fpl_cookie]
    if not present:
        print(f"Ogohlantirish: cookie da {', '.join(NEEDED_COOKIES)} dan birortasi ham yo'q — "
              "noto'g'ri qatorni nusxalagan bo'lishingiz mumkin.")

    client = FplClient(cfg.cache_dir, cfg.cache_ttl_seconds, cfg.request_delay,
                       cfg.max_workers, cookie=cfg.fpl_cookie)
    data = client.my_team(cfg.entry_id)
    if not data or not data.get("picks"):
        err = client.last_auth_error
        print("\nSessiya ISHLAMADI.")
        if err:
            print(f"  Sabab: {err.explain()}")
        print("\nBrauzerda tekshiring — shu manzilni logindagi tabda oching:")
        print(f"  https://fantasy.premierleague.com/api/my-team/{cfg.entry_id}/")
        print("  • JSON ko'rinsa  -> cookie noto'g'ri nusxalangan. F12 -> Network ->")
        print("    my-team/ so'rovi -> Request Headers -> `cookie:` qatorini")
        print("    BOSHIDAN OXIRIGACHA nusxalang (Copy value).")
        print("  • 403 ko'rinsa   -> brauzerdagi sessiyaning o'zi tugagan. Chiqib,")
        print("    qayta kiring, keyin yangi cookie oling.")
        return 1

    transfers = data.get("transfers") or {}
    chips = [c["name"] for c in (data.get("chips") or [])
             if c.get("status_for_entry") == "available"]
    print("Sessiya ISHLAYAPTI.")
    print(f"  Erkin transfer : {transfers.get('limit')}")
    print(f"  Bank           : {(transfers.get('bank') or 0) / 10:.1f}m")
    print(f"  Tarkib qiymati : {(transfers.get('value') or 0) / 10:.1f}m")
    print(f"  Mavjud chiplar : {', '.join(chips) or 'yo`q'}")

    bound = [c for c in BROWSER_BOUND_COOKIES if f"{c}=" in cfg.fpl_cookie]
    if bound:
        print(f"\nEslatma: cookie da {', '.join(bound)} bor — bular brauzer va IP ga "
              "bog'langan bot himoyasi tokenlari.\nGitHub Actions da (boshqa IP) "
              "ishlamaydi, shuning uchun cookie ni faqat shu kompyuterda ishlating.")
    return 0


# --------------------------------------------------------------------- asosiy
def main() -> int:
    parser = argparse.ArgumentParser(description="FPL tahlil va Telegram hisoboti")
    parser.add_argument("--config", default=None)
    parser.add_argument("--mode", choices=["auto", "daily", "deadline"], default="auto")
    parser.add_argument("--dry-run", action="store_true",
                        help="Telegramga JO'NATMAYDI, faqat ekranga chiqaradi")
    parser.add_argument("--out", metavar="FAYL", nargs="?", const="hisobot.html",
                        help="hisobotni HTML faylga yozadi (default: hisobot.html)")
    parser.add_argument("--offline", action="store_true", help="faqat keshdan o'qiydi")
    parser.add_argument("--no-rivals", action="store_true", help="raqiblar tahlilini o'tkazib yuboradi")
    parser.add_argument("--strategy", choices=["safe", "balanced", "aggressive"], default="balanced")
    parser.add_argument("--demo", action="store_true", help="soxta ma'lumot bilan namuna hisobot")
    parser.add_argument("--check-auth", action="store_true",
                        help="FPL sessiyasi ishlayaptimi — faqat shuni tekshiradi")
    args = parser.parse_args()

    cfg = Config.load(args.config)
    log.info(
        "Sozlamalar: entry_id=%s · liga=%s · telegram=%s · cookie=%s",
        cfg.entry_id or "yo'q",
        len(cfg.mini_league_ids),
        "bor" if (cfg.telegram_token and cfg.telegram_chat_id) else "yo'q",
        "bor" if cfg.fpl_cookie else "yo'q",     # qiymatning o'zi hech qachon chiqarilmaydi
    )

    if args.check_auth:
        return check_auth(cfg)

    if args.demo:
        from fplbrain.demo import FakeClient

        cfg.entry_id = 999_999
        cfg.mini_league_ids = cfg.mini_league_ids or [12345]
        cfg.detail_players = 60
        # demo soxta ma'lumoti haqiqiy snapshotlarni buzmasligi uchun alohida papka
        cfg.store_dir = cfg.store_dir.parent / "demo_store"
        cfg.store_dir.mkdir(parents=True, exist_ok=True)
        client = FakeClient()
    else:
        if not cfg.entry_id:
            log.error("entry_id ko'rsatilmagan (config.yaml yoki FPL_ENTRY_ID)")
            return 2
        client = FplClient(cfg.cache_dir, cfg.cache_ttl_seconds, cfg.request_delay,
                           cfg.max_workers, offline=args.offline, cookie=cfg.fpl_cookie)
        if client.authenticated:
            log.info("FPL sessiyasi bilan ishlanmoqda (aniq narx va FT)")
    store = Store(cfg.store_dir)

    bootstrap = client.bootstrap()
    fixtures = client.fixtures()
    elements = bootstrap["elements"]
    by_id = {e["id"]: e for e in elements}
    team_short = {t["id"]: t["short_name"] for t in bootstrap["teams"]}
    names = {e["id"]: e["web_name"] for e in elements}

    last_finished, next_event, next_event_obj = pick_events(bootstrap, cfg.horizon)
    events = list(range(next_event, min(38, next_event + cfg.horizon - 1) + 1))
    now = report.now_in(cfg.timezone)
    deadline = report.parse_deadline(next_event_obj["deadline_time"], cfg.timezone)
    hours_left = (deadline - now).total_seconds() / 3600

    mode = args.mode
    if mode == "auto":
        mode = "deadline" if 0 < hours_left <= cfg.deadline_report_hours else "daily"
    log.info("Rejim: %s · GW%s · deadline'gacha %.1f soat", mode, next_event, hours_left)

    # ---- model ----
    team_ratings = ratings.build_team_ratings(bootstrap, cfg)
    views = ratings.build_fixture_views(fixtures, team_ratings, cfg, events[0], events[-1])
    engine = EVEngine(cfg, team_ratings, views)

    played = team_matches_played(bootstrap, fixtures)
    my_picks = client.entry_picks(cfg.entry_id, last_finished).get("picks", [])
    focus_ids = {p["element"] for p in my_picks}
    ev_by_element = build_all_ev(cfg, client, bootstrap, engine, events, focus_ids, played)
    all_ev = list(ev_by_element.values())

    squad = load_squad(client, cfg, cfg.entry_id, last_finished, ev_by_element, by_id)
    entry_info = client.entry(cfg.entry_id)
    owned = {p.element for p in squad.players}
    my_captain = next((p.element for p in squad.players if p.is_captain), None)

    horizon_ev = squad_ev(squad, events, cfg)
    moves = transfers.evaluate_moves(squad, all_ev, events, cfg, max_transfers=2)
    weak = transfers.weak_links(squad, events, cfg, all_ev)

    # ---- raqiblar ----
    comparisons, stats_list, captain_eo = ([], [], {})
    if not args.no_rivals:
        comparisons, stats_list, captain_eo = collect_rivals(
            client, cfg, last_finished, squad, my_captain, ev_by_element, entry_info,
            total_players=bootstrap.get("total_players", 0),
        )

    captains = captain_mod.rank_captains(
        squad, events[0], captain_eo, strategy=args.strategy, limit=cfg.max_captain_options
    )
    # my-team bo'lsa aniq ro'yxat, aks holda transfer tarixidan hisoblaymiz
    chips_left = squad.chips_available or chips_mod.available_chips(
        squad.chips_history, events[0]
    )
    if len(chips_left) < 4:
        log.info("Bu yarim yillikda qolgan chiplar: %s", ", ".join(chips_left) or "yo'q")
    chip_advice = chips_mod.advise(squad, all_ev, events, views, cfg,
                                   available_chips=chips_left)

    # ---- bozor ----
    prev_snapshot = store.snapshot_players(elements)
    price_pred = market.price_signals(elements, team_short, owned)
    rises, falls = market.actual_price_changes(elements, prev_snapshot, team_short, owned)
    news = market.news_signals(elements, prev_snapshot, team_short, owned)
    trend_up, trend_down = market.ownership_trends(elements, prev_snapshot, team_short)

    # ---- hisobot ----
    sections = [
        report.header(next_event, deadline, now, cfg.timezone, mode),
        report.news_section(news),
        report.price_section(rises, falls, price_pred),
        report.squad_section(squad, events, horizon_ev, weak),
    ]
    if mode == "deadline":
        sections += [
            report.xi_section(squad, events[0]),
            report.transfers_section(moves, cfg, squad),
            report.captain_section(captains, events[0]),
            report.rivals_section(comparisons, stats_list, names),
            report.chips_section(chip_advice, events[0]),
        ]
    else:
        sections += [
            report.transfers_section(moves, cfg, squad, limit=2),
            report.captain_section(captains[:3], events[0]),
            report.rivals_section(comparisons, stats_list, names, limit=4),
            report.chips_section(chip_advice, events[0], threshold=10.0),
        ]

    rank_txt = ""
    if entry_info.get("summary_overall_rank"):
        total_players = bootstrap.get("total_players", 0)
        pct = (
            f" — yuqori {entry_info['summary_overall_rank'] / total_players * 100:.1f}%"
            if total_players else ""
        )
        rank_txt = (
            f"<i>Umumiy o'rin: {entry_info['summary_overall_rank']:,} / "
            f"{total_players:,}{pct}</i>"
        )
    if not squad.authenticated:
        rank_txt += "\n<i>Sotish narxi va FT taxminiy — aniq bo'lishi uchun FPL_COOKIE qo'shing.</i>"
    sections.append(report.footer(rank_txt))

    text = report.build_report(sections)

    if args.out:
        out_path = Path(args.out).resolve()
        report.write_html(out_path, text, next_event,
                          f"{report.uz_date(now)} · {now.strftime('%H:%M')} · GW{next_event}")
        log.info("Hisobot yozildi: %s", out_path)

    tg = Telegram(cfg.telegram_token, cfg.telegram_chat_id, dry_run=args.dry_run)
    tg.send(text)

    if args.dry_run:
        log.info("--dry-run yoqilgan: Telegramga JO'NATILMADI. "
                 "Jo'natish uchun shu bayroqsiz ishga tushiring: python run.py")
    elif tg.dry_run:
        log.warning("TELEGRAM_TOKEN/TELEGRAM_CHAT_ID yo'q — jo'natilmadi.")

    store.log_run(mode, {
        "at": now.isoformat(),
        "event": next_event,
        "horizon_ev": horizon_ev,
        "best_move": moves[0].describe() if moves else None,
        "captain": captains[0].name if captains else None,
    })
    log.info("Tayyor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
