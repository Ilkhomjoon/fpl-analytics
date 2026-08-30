"""Telegram hisobotini o'zbek tilida yig'ish."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

from .captain import CaptainOption
from .chips import CHIP_NAMES, ChipAdvice
from .ev import DEF, FWD, GK, MID
from .market import NewsSignal, PriceSignal
from .rivals import Comparison, GroupStats
from .squad import Squad, best_eleven
from .telegram import escape
from .transfers import TransferMove

POS_SHORT = {GK: "DRV", DEF: "HIM", MID: "YAR", FWD: "HUJ"}
MONTHS_UZ = [
    "yanvar", "fevral", "mart", "aprel", "may", "iyun",
    "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr",
]
WEEKDAYS_UZ = ["dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"]

log = logging.getLogger(__name__)

# tzdata o'rnatilmagan tizimlar uchun zaxira siljishlar (yozgi vaqti yo'q zonalar)
FALLBACK_OFFSETS = {"Asia/Tashkent": 5, "Asia/Almaty": 5, "Asia/Bishkek": 6, "UTC": 0}


def uz_date(dt: datetime) -> str:
    return f"{dt.day}-{MONTHS_UZ[dt.month - 1]}, {WEEKDAYS_UZ[dt.weekday()]}"


def countdown(deadline: datetime, now: datetime) -> str:
    delta = deadline - now
    if delta.total_seconds() <= 0:
        return "deadline o'tdi"
    hours, rem = divmod(int(delta.total_seconds()), 3600)
    days, hours = divmod(hours, 24)
    minutes = rem // 60
    if days:
        return f"{days} kun {hours} soat qoldi"
    return f"{hours} soat {minutes} daqiqa qoldi"


def _p(name: str) -> str:
    return escape(name)


# ------------------------------------------------------------------ bo'limlar
def header(event: int, deadline: datetime, now: datetime, tz: str, mode: str) -> str:
    title = "KUNLIK BRIFING" if mode == "daily" else "DEADLINE HISOBOTI"
    return (
        f"<b>📊 FPL {title}</b>\n"
        f"{uz_date(now)} · {now.strftime('%H:%M')}\n"
        f"GW{event} deadline: {deadline.strftime('%d.%m %H:%M')} — <b>{countdown(deadline, now)}</b>"
    )


def news_section(signals: list[NewsSignal], limit: int = 8) -> str:
    if not signals:
        return ""
    lines = ["<b>🩺 YANGI XABARLAR</b>"]
    for s in signals[:limit]:
        mark = "⚠️ <b>sizda bor</b>" if s.owned else ""
        chance = f" · {s.chance}%" if s.chance is not None else ""
        icon = {"yangi": "🔴", "o'zgargan": "🟡", "tuzaldi": "🟢"}.get(s.kind, "•")
        lines.append(f"{icon} <b>{_p(s.name)}</b> ({s.team}){chance} — {_p(s.text)} {mark}".rstrip())
    return "\n".join(lines)


def price_section(
    rises: list[dict], falls: list[dict], predicted: list[PriceSignal], limit: int = 6
) -> str:
    lines = ["<b>💷 NARXLAR</b>"]
    if rises or falls:
        changed = []
        for r in rises[:limit]:
            changed.append(f"↑ {_p(r['name'])} ({r['team']}) {r['price']:.1f}" + (" · sizda" if r["owned"] else ""))
        for f in falls[:limit]:
            changed.append(f"↓ {_p(f['name'])} ({f['team']}) {f['price']:.1f}" + (" · sizda" if f["owned"] else ""))
        lines.append("<i>Kecha o'zgardi:</i>\n" + "\n".join(changed))
    upcoming = [s for s in predicted if s.likelihood in ("juda yuqori", "yuqori")][:limit]
    if upcoming:
        lines.append("<i>Bugun kechqurun kutilmoqda:</i>")
        for s in upcoming:
            arrow = "↑" if s.direction == "rise" else "↓"
            if abs(s.percent) >= 100:
                eta = " · <b>bugun</b>"
            elif s.eta_hours:
                eta = f" · ~{s.eta_hours:.0f} soat"
            else:
                eta = ""
            own = " · <b>sizda</b>" if s.owned else ""
            lines.append(
                f"{arrow} {_p(s.name)} ({s.team}) {s.price:.1f} — {abs(s.percent):.0f}%{eta}{own}"
            )
    return "\n".join(lines) if len(lines) > 1 else ""


def squad_section(squad: Squad, events: list[int], horizon_ev: float, weak: list) -> str:
    xi, bench, form, xi_ev = best_eleven(squad.players, events[0])
    form_txt = "-".join(str(x) for x in form[1:])
    lines = [
        "<b>🧠 MENING JAMOAM</b>",
        f"Qiymat <b>{squad.value:.1f}m</b> · bank {squad.bank:.1f}m · FT ≈ {squad.free_transfers}",
        f"GW{events[0]} eng yaxshi sxema: <b>{form_txt}</b> — {xi_ev:.1f} EV",
        f"Kelgusi {len(events)} tur (vaznlangan): <b>{horizon_ev:.1f} EV</b>",
    ]
    if weak:
        lines.append("<i>Eng zaif bo'g'inlar:</i>")
        for p, ev, reason in weak[:3]:
            lines.append(f"• {_p(p.name)} ({POS_SHORT[p.position]}) — {ev:.1f} EV · {reason}")
    return "\n".join(lines)


def xi_section(squad: Squad, event: int) -> str:
    xi, bench, form, xi_ev = best_eleven(squad.players, event)
    order = {GK: 0, DEF: 1, MID: 2, FWD: 3}
    xi = sorted(xi, key=lambda p: (order[p.position], -p.ev.per_event.get(event, 0)))
    lines = [f"<b>📋 GW{event} TAVSIYA ETILGAN 11 LIK</b>"]
    for p in xi:
        ev = p.ev.per_event.get(event, 0.0)
        fx = p.ev.fixtures.get(event, [])
        opp = ", ".join(f"{f.opponent}{'(u)' if f.is_home else '(m)'}" for f in fx) or "—"
        lines.append(f"{POS_SHORT[p.position]} {_p(p.name)} — {ev:.1f} · {opp}")
    lines.append("<i>Zaxira:</i> " + ", ".join(
        f"{_p(p.name)} ({p.ev.per_event.get(event, 0.0):.1f})" for p in bench
    ))
    return "\n".join(lines)


def _diverse(
    moves: list[TransferMove], limit: int, exclude: TransferMove | None = None
) -> list[TransferMove]:
    """Bir xil o'yinchini sotadigan variantlarni takrorlamaslik uchun xilma-xillik.

    `exclude` — allaqachon ko'rsatilgan variant; unda ishtirok etgan o'yinchilar
    muqobillarda qayta chiqmaydi.
    """
    chosen, used_out, used_in = [], set(), set()
    if exclude is not None:
        used_out |= {p.element for p in exclude.out_players}
        used_in |= {p.element for p in exclude.in_players}
    for m in moves:
        outs = frozenset(p.element for p in m.out_players)
        ins = frozenset(p.element for p in m.in_players)
        if outs & used_out or ins & used_in:
            continue
        chosen.append(m)
        used_out |= outs
        used_in |= ins
        if len(chosen) >= limit:
            break
    return chosen


def transfers_section(moves: list[TransferMove], cfg, squad: Squad, limit: int | None = None) -> str:
    """Reja ko'rinishida: FT soniga mos asosiy tavsiya + muqobillar."""
    good = [m for m in moves if m.gain >= cfg.min_gain_to_suggest]
    ft = squad.free_transfers
    lines = [
        f"<b>🔁 TRANSFER REJASI</b> · {ft} FT · bank {squad.bank:.1f}m"
    ]
    if not good:
        best = moves[0] if moves else None
        lines.append("Bu hafta arziydigan transfer yo'q — FT ni saqlab qo'ying.")
        if best:
            lines.append(
                f"<i>Eng yaxshisi ham yetarli emas:</i> {escape(best.describe())} "
                f"— {best.gain:+.1f} EV"
            )
        return "\n".join(lines)

    # FT soniga mos eng yaxshi variant — asosiy tavsiya
    fitting = [m for m in good if m.n <= max(1, ft)]
    primary = fitting[0] if fitting else good[0]

    lines.append(f"\n<b>▶ TAVSIYA</b> ({primary.n} ta transfer)")
    lines.append(f"  {escape(primary.describe())}")
    hit_txt = f"<b>-{primary.hit} hit</b>" if primary.hit else "hit yo'q"
    lines.append(
        f"  foyda <b>{primary.gain:+.1f} EV</b> ({len_events_note()}) · {hit_txt} · "
        f"{primary.cost:+.1f}m, bank {primary.bank_after:.1f}m"
    )

    # hit bilan qo'shimcha transfer arziydimi
    with_hit = [m for m in good if m.n > max(1, ft) and m.hit]
    if with_hit and with_hit[0].gain > primary.gain:
        extra = with_hit[0]
        lines.append(
            f"\n<b>▶ HIT BILAN</b> — {escape(extra.describe())}\n"
            f"  {extra.gain:+.1f} EV (hit hisobga olingan), ya'ni tavsiyadan "
            f"{extra.gain - primary.gain:+.1f} yaxshiroq"
        )
    elif any(m.hit for m in good):
        lines.append("\n<i>-4 hit olishga arziydigan variant yo'q.</i>")

    others = _diverse(
        [m for m in good if m is not primary],
        (limit if limit is not None else cfg.max_transfer_suggestions) - 1,
        exclude=primary,
    )
    if others:
        lines.append("\n<i>Muqobillar (bir vaqtda emas — har biri bankni o'zicha ishlatadi):</i>")
        for m in others:
            lines.append(
                f"  • {escape(m.describe())} — {m.gain:+.1f} EV, bank {m.bank_after:.1f}m"
            )
    return "\n".join(lines)


def len_events_note() -> str:
    return "kelgusi turlar bo'yicha"


def captain_section(options: list[CaptainOption], event: int) -> str:
    if not options:
        return ""
    lines = [
        f"<b>🅲 KAPITAN — GW{event}</b>",
        "<i>Kapitanlikda o'rtacha emas, tepasi hal qiladi — ochko ikkilanadi.</i>",
    ]
    for i, o in enumerate(options, 1):
        eo = f" · raqiblarda {o.eo:.0f}%" if o.eo else ""
        edge = f" · maydondan {o.edge:+.1f}" if o.edge else ""
        lines.append(
            f"<b>{i}.</b> {_p(o.name)} — {o.ev:.1f} EV · "
            f"10+: <b>{o.p10*100:.0f}%</b> · 15+: {o.p15*100:.0f}%{eo}{edge}\n"
            f"    <i>{o.verdict}</i>"
        )
    return "\n".join(lines)


def _eo(stats: GroupStats, element: int) -> str:
    """Egalik va kapitanlikni alohida ko'rsatadi — "108%" chalg'itmasligi uchun."""
    own = stats.ownership.get(element, 0.0)
    cap = stats.captaincy.get(element, 0.0)
    if cap >= 1.0:
        return f"{own:.0f}% (K {cap:.0f}%)"
    return f"{own:.0f}%"


def rivals_section(
    comparisons: list[Comparison],
    stats: list[GroupStats],
    names: dict[int, str],
    limit: int = 5,
) -> str:
    if not comparisons:
        return ""
    lines = [
        "<b>👥 RAQIBLAR TAHLILI</b>",
        "<i>EO = egalik % + kapitanlik %. Shuning uchun 100% dan oshishi mumkin: "
        "hamma egallagan va yarmi kapitan qilgan o'yinchi 150% beradi.</i>",
    ]
    for comp, st in zip(comparisons, stats):
        lines.append(f"<u>{escape(comp.group)}</u> ({st.size} jamoa · o'rtacha {st.avg_total:.0f} ochko)")
        if comp.threats:
            threats = ", ".join(
                f"{_p(names.get(el, '?'))} {_eo(st, el)}" for el, _ in comp.threats[:limit]
            )
            lines.append(f"⛔ Menda yo'q, ularda bor: {threats}")
        if comp.differentials:
            diffs = ", ".join(
                f"{_p(names.get(el, '?'))} {_eo(st, el)}" for el, _ in comp.differentials[:limit]
            )
            lines.append(f"💎 Mening differensiallarim: {diffs}")
        if comp.captain_split:
            caps = ", ".join(
                f"{_p(names.get(el, '?'))} {pct:.0f}%" for el, pct in comp.captain_split[:3]
            )
            lines.append(f"🅲 Ularning kapitani: {caps}")
        if st.chips:
            chips = ", ".join(f"{CHIP_NAMES.get(c, c)} {n}" for c, n in st.chips.items())
            lines.append(f"🎴 Chip ishlatganlar: {chips}")
        lines.append("")
    return "\n".join(lines).strip()


def strategy_section(strategy: str, reason: str, gap, benchmark) -> str:
    """Eng muhim bo'lim: maydonga nisbatan holat va undan kelib chiqadigan yo'l."""
    names = {"safe": "HIMOYA", "balanced": "MUVOZANAT", "aggressive": "HUJUM"}
    lines = [f"<b>🎯 STRATEGIYA — {names.get(strategy, strategy.upper())}</b>", f"<i>{escape(reason)}</i>"]

    if gap and benchmark:
        net = gap.net
        verdict = (
            "maydondan oldindasiz" if net > 1.0
            else "maydon bilan tengsiz" if net > -1.5
            else "har tur maydonga yutqazyapsiz"
        )
        lines.append(
            f"\n<b>{escape(gap.group)}</b> bilan 11 likka 11 lik: "
            f"meniki <b>{benchmark.my_xi_ev:.1f}</b> vs shablon "
            f"<b>{benchmark.template_ev:.1f}</b> = <b>{net:+.1f} ochko/tur</b> — {verdict}"
        )
        if gap.threats:
            lines.append(
                "<i>Menda yo'q, ular har tur shundan yutadi (EO × EV):</i>"
            )
            for e in gap.threats:
                lines.append(
                    f"  ▼ {_p(e.name)} — {e.eo:.0f}% EO · {e.ev:.1f} EV · "
                    f"<b>{e.swing:+.2f}</b>/tur"
                )
        if gap.edges:
            lines.append("<i>Mening 11 ligimdagi ustunliklarim:</i>")
            for e in gap.edges[:3]:
                lines.append(
                    f"  ▲ {_p(e.name)} — {e.eo:.0f}% EO · {e.ev:.1f} EV · "
                    f"<b>{e.swing:+.2f}</b>/tur"
                )
        lines.append(
            "<i>Yuqoridagi qatorlar farqning izohi — ular qo'shilib umumiy "
            "songa aylanmaydi.</i>"
        )
    return "\n".join(lines)


def fixtures_section(best, worst, events: list[int]) -> str:
    if not best:
        return ""
    span = f"GW{events[0]}–{events[-1]}"
    lines = [f"<b>📅 KELGUSI TURLAR ({span})</b>", "<i>Eng qulay jadval:</i>"]
    for row in best[:4]:
        mine = f" ← {', '.join(_p(n) for n in row.my_players)}" if row.my_players else ""
        lines.append(f"  {row.short} {row.score:+.2f} · {' '.join(row.marks[:5])}{mine}")
    lines.append("<i>Eng og'ir jadval:</i>")
    for row in worst[:3]:
        mine = f" ← <b>{', '.join(_p(n) for n in row.my_players)}</b>" if row.my_players else ""
        lines.append(f"  {row.short} {row.score:+.2f} · {' '.join(row.marks[:5])}{mine}")
    return "\n".join(lines)


def chips_section(advice: list[ChipAdvice], current_event: int, threshold: float = 8.0) -> str:
    # har chip uchun faqat eng foydali tur ko'rsatiladi
    best_per_chip: dict[str, ChipAdvice] = {}
    for a in advice:
        if a.value < threshold:
            continue
        if a.chip not in best_per_chip or a.value > best_per_chip[a.chip].value:
            best_per_chip[a.chip] = a
    strong = sorted(best_per_chip.values(), key=lambda a: -a.value)[:3]
    if not strong:
        return ""
    lines = ["<b>🎴 CHIP SIGNALI</b>"]
    for a in strong:
        when = "shu tur" if a.event == current_event else f"GW{a.event}"
        lines.append(f"• <b>{CHIP_NAMES.get(a.chip, a.chip)}</b> — {when}: +{a.value:.1f} EV ({a.reason})")
    return "\n".join(lines)


def rank_line(entry_info: dict, bootstrap: dict, squad) -> str:
    """Hisobot oxiridagi o'rin qatori."""
    rank = (entry_info or {}).get("summary_overall_rank")
    if not rank:
        return ""
    total = (bootstrap or {}).get("total_players", 0)
    pct = f" — yuqori {rank / total * 100:.1f}%" if total else ""
    line = f"<i>Umumiy o'rin: {rank:,} / {total:,}{pct}</i>"
    if squad is not None and not squad.authenticated:
        line += ("\n<i>Sotish narxi va FT taxminiy — aniq bo'lishi uchun "
                 "FPL_COOKIE qo'shing.</i>")
    return line


def menu_summary(
    event: int, deadline: datetime, now: datetime, mode: str, squad,
    entry_info: dict, total_players: int, moves, captains, cfg, risk=None,
) -> str:
    """Menyu xabarining tepasidagi qisqa xulosa — eng muhim uch narsa."""
    lines = [
        f"<b>📊 FPL — GW{event}</b>",
        f"{uz_date(now)} · deadline {deadline.strftime('%d.%m %H:%M')} "
        f"(<b>{countdown(deadline, now)}</b>)",
    ]

    rank = (entry_info or {}).get("summary_overall_rank")
    if rank:
        pct = f" ({rank / total_players * 100:.1f}%)" if total_players else ""
        lines.append(f"O'rin: <b>{rank:,}</b>{pct} · qiymat {squad.value:.1f}m · "
                     f"{squad.free_transfers} FT · bank {squad.bank:.1f}m")

    if risk is not None and risk.headline:
        lines.append(f"<b>{risk.headline}</b>")

    best = next((m for m in moves if m.gain >= cfg.min_gain_to_suggest), None)
    if best:
        lines.append(f"🔁 <b>{escape(best.describe())}</b> ({best.gain:+.1f} EV)")
    else:
        lines.append("🔁 Arziydigan transfer yo'q — FT ni saqlang")

    if captains:
        top = captains[0]
        lines.append(f"🅲 <b>{_p(top.name)}</b> — {top.ev:.1f} EV · "
                     f"10+: {top.p10 * 100:.0f}%")
    return "\n".join(lines)


def footer(model_note: str = "") -> str:
    base = "<i>Model: xG/xA + Poisson fixture, daqiqalar, DefCon, bonus. EV = kutilayotgan ochko.</i>"
    return f"{base}\n{model_note}".strip()


def build_report(sections: list[str]) -> str:
    return "\n\n".join(s for s in sections if s and s.strip())


HTML_PAGE = """<!doctype html>
<html lang="uz"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FPL hisoboti — GW{event}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    font: 16px/1.65 -apple-system, "Segoe UI", Roboto, sans-serif;
    max-width: 46rem; margin: 0 auto; padding: 2rem 1.25rem 4rem;
    background: Canvas; color: CanvasText;
  }}
  pre {{ white-space: pre-wrap; word-wrap: break-word; font: inherit; margin: 0; }}
  b {{ font-weight: 650; }}
  u {{ text-decoration: none; font-weight: 650; border-bottom: 2px solid currentColor;
       padding-bottom: 1px; }}
  i {{ opacity: .72; font-style: normal; font-size: .92em; }}
  .meta {{ opacity: .55; font-size: .85em; margin-bottom: 1.5rem; }}
</style></head>
<body><div class="meta">{generated}</div><pre>{body}</pre></body></html>
"""


def write_html(path, text: str, event: int, generated: str) -> None:
    """Telegram uchun yasalgan HTML ni brauzerda o'qish uchun sahifaga o'raydi."""
    from pathlib import Path

    Path(path).write_text(
        HTML_PAGE.format(event=event, body=text, generated=escape(generated)),
        encoding="utf-8",
    )


def _zone(tz: str) -> tzinfo:
    """Vaqt zonasini oladi; Windows da tzdata paketi bo'lmasa — qat'iy siljish bilan."""
    try:
        return ZoneInfo(tz)
    except Exception:
        offset = FALLBACK_OFFSETS.get(tz)
        if offset is None:
            log.warning("'%s' zonasi topilmadi — UTC ishlatilmoqda. `pip install tzdata`", tz)
            return timezone.utc
        log.warning(
            "'%s' zonasi topilmadi — UTC%+d bilan davom etilmoqda. "
            "Yozgi/qishki vaqt o'zgarsa xato bo'lishi mumkin: `pip install tzdata`",
            tz, offset,
        )
        return timezone(timedelta(hours=offset))


def now_in(tz: str) -> datetime:
    return datetime.now(_zone(tz))


def parse_deadline(iso: str, tz: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(_zone(tz))


def target_section(pace, leader_name: str = "") -> str:
    """Mavsum sur'ati — maqsadga nisbatan holat."""
    if not pace:
        return ""
    lines = [
        f"<b>🎯 MAVSUM SUR'ATI — maqsad {pace.target:,} ochko</b>",
        f"<i>{pace.target // 38} ochko/tur × 38 tur. O'tgan mavsum g'olibi shu darajada.</i>",
        "",
        f"O'ynalgan: <b>{pace.played}</b> tur · qolgan <b>{pace.remaining}</b>",
        f"Menda: <b>{pace.my_total}</b> ochko · o'rtacha <b>{pace.my_average:.1f}</b>/tur "
        f"(eng yaxshi {pace.my_best}, eng yomon {pace.my_worst})",
    ]
    if pace.partial_event is not None:
        lines.append(
            f"<i>GW{pace.partial_event} hali tugamagan "
            f"({pace.partial_points} ochko — oraliq natija), "
            f"hisobga olinmadi.</i>"
        )
    if pace.fpl_average_total:
        diff = pace.my_total - pace.fpl_average_total
        lines.append(f"FPL o'rtachasi: {pace.fpl_average_total} — siz "
                     f"<b>{diff:+d}</b> ochko {'oldinda' if diff >= 0 else 'orqada'}")

    if pace.leader_total is not None:
        who = f" ({escape(leader_name)})" if leader_name else ""
        note = " (ikkalasi ham jonli)" if pace.partial_event else ""
        lines.append(
            f"Yetakchi{who}: <b>{pace.leader_total}</b> ochko · "
            f"o'rtacha {pace.leader_average:.1f}/tur · "
            f"mendan <b>{pace.leader_gap:+d}</b> oldinda{note}"
        )

    lines += [
        "",
        f"<b>Maqsad uchun kerak: {pace.required_average:.1f} ochko/tur</b> "
        f"(hozir {pace.my_average:.1f})",
        f"Hozirgi sur'atda yakun: <b>{pace.realistic_target:,}</b> ochko",
    ]
    if pace.shortfall > 0:
        lines.append(f"Maqsaddan farq: <b>{pace.shortfall:.0f}</b> ochko kam")
    else:
        lines.append(f"Maqsaddan <b>{-pace.shortfall:.0f}</b> ochko ortiq")

    catch = pace.catch_leader_average
    if catch is not None:
        lines.append(f"Yetakchini quvib yetish uchun: <b>{catch:.1f}</b> ochko/tur")

    lines.append(f"\n<i>{pace.verdict}</i>")

    if pace.rows:
        recent = pace.rows[-6:]
        lines.append("\n<i>So'nggi turlar (siz / o'rtacha):</i>")
        lines.append("  " + " · ".join(
            f"GW{r.event}: <b>{r.points}</b>/{r.average}" for r in recent
        ))
    return "\n".join(lines)


def template_section(moves, bank: float, group: str = "Top-100") -> str:
    """Shablon asosidagi sotish/olish tavsiyalari."""
    if not moves:
        return ""
    lines = [
        f"<b>🔄 SHABLON BILAN TENGLASHISH — {escape(group)}</b>",
        "<i>Ommaviy o'yinchi ikki tomonlama foyda beradi: EV odatda yuqori, "
        "va u ochko olganda siz orqada qolmaysiz.</i>",
        f"<i>Bank: {bank:.1f}m</i>",
    ]
    for i, m in enumerate(moves, 1):
        mark = "" if m.affordable else " ⚠️"
        lines.append(
            f"\n<b>{i}.</b> {_p(m.out_name)} ({m.out_price:.1f}m, EO {m.out_eo:.0f}%) "
            f"➜ <b>{_p(m.in_name)}</b> ({m.in_price:.1f}m, EO {m.in_eo:.0f}%){mark}"
        )
        lines.append(
            f"    EV <b>{m.ev_gain:+.1f}</b> · EO <b>{m.eo_gain:+.0f}%</b> · {m.reason}"
        )
    return "\n".join(lines)


POS_FULL = {GK: "Darvozabon", DEF: "Himoyachi", MID: "Yarim himoyachi", FWD: "Hujumchi"}


def _rating_row(r) -> str:
    flag = " ⚠️" if r.is_enabler else ""
    return (
        f"  {_p(r.name)} ({r.team}, {r.price:.1f}m){flag}\n"
        f"    reyting <b>{r.score:.0f}</b> · rol {r.role*100:.0f}% · "
        f"chiqim {r.output90:.2f}/90 · egalik {r.ownership:.1f}%"
    )


def rating_section(ratings, positions=(4, 3, 2), top: int = 4) -> str:
    """Har pozitsiya bo'yicha eng yuqori reytingli o'yinchilar."""
    from .rating import best_by_position

    if not ratings:
        return ""
    lines = [
        "<b>⭐ O'YINCHI REYTINGI</b>",
        "<i>Reyting = rol × chiqim. Rol daqiqalar, asosiy tarkib va (narxga "
        "qarab chegirilgan) egalikdan; chiqim xG/xA va haqiqiy natijadan.</i>",
    ]
    for pos in positions:
        rows = best_by_position(ratings, pos, top=top)
        if not rows:
            continue
        lines.append(f"\n<u>{POS_FULL.get(pos, '?')}</u>")
        for r in rows:
            lines.append(_rating_row(r))
            if r.note:
                lines.append(f"    <i>{escape(r.note)}</i>")
    return "\n".join(lines)


def value_section(ratings, top: int = 8) -> str:
    """Narxiga nisbatan eng samarali o'yinchilar."""
    from .rating import best_value

    rows = best_value(ratings, top=top)
    if not rows:
        return ""
    lines = [
        "<b>💎 NARXIGA NISBATAN ENG SAMARALI</b>",
        "<i>1 million evaziga kutilayotgan haftalik chiqim. Byudjet "
        "to'ldiruvchilar (ommaviy, lekin o'ynamaydiganlar) chiqarib tashlangan.</i>",
    ]
    for i, r in enumerate(rows, 1):
        lines.append(
            f"{i}. {_p(r.name)} ({r.team}, {r.price:.1f}m) — "
            f"<b>{r.value:.2f}</b>/m · rol {r.role*100:.0f}% · "
            f"{r.goals}G {r.assists}A · xGI {r.xg + r.xa:.1f}"
        )
    return "\n".join(lines)


def momentum_section(ratings, top: int = 5) -> str:
    """Shu tur oldidan bozor harakati — kim olinmoqda, kim sotilmoqda."""
    from .rating import market_movers

    buying, selling = market_movers(ratings, top=top)
    buying = [r for r in buying if r.net_transfers > 0]
    selling = [r for r in selling if r.net_transfers < 0]
    if not buying and not selling:
        return ""

    lines = ["<b>📊 BOZOR HARAKATI (shu tur)</b>"]
    if buying:
        lines.append("<i>Eng ko'p olinmoqda:</i>")
        for r in buying:
            lines.append(
                f"  ↗ {_p(r.name)} ({r.team}, {r.price:.1f}m) "
                f"<b>+{r.net_transfers:,}</b> · egalik {r.ownership:.1f}% · "
                f"rol {r.role*100:.0f}%"
            )
    if selling:
        lines.append("<i>Eng ko'p sotilmoqda:</i>")
        for r in selling:
            lines.append(
                f"  ↘ {_p(r.name)} ({r.team}, {r.price:.1f}m) "
                f"<b>{r.net_transfers:,}</b> · egalik {r.ownership:.1f}%"
            )
    return "\n".join(lines)


def risk_section(risk, event: int) -> str:
    """Deadline oldidan eng muhim tekshiruv — hamma o'ynaydimi."""
    if not risk or not risk.players:
        return ("<b>✅ O'YIN VAQTI TEKSHIRUVI</b>\n"
                "11 likdagi hamma o'yinchi o'ynashi kutilmoqda.")

    icons = {3: "🔴", 2: "🟠", 1: "🟡"}
    lines = [
        f"<b>⚠️ O'YIN VAQTI XAVFI — GW{event}</b>",
        "<i>Maydonga chiqmagan o'yinchi 0 ochko beradi. Bu tekshiruv "
        "boshqa hamma narsadan muhimroq.</i>",
    ]
    for p in risk.players:
        lines.append(
            f"{icons.get(p.severity, '•')} <b>{_p(p.name)}</b> "
            f"({POS_SHORT.get(p.position, '?')}) — {escape(p.reason)}"
        )
    serious = len(risk.serious)
    if serious:
        lines.append(f"\n<b>{serious} ta o'yinchini almashtirish yoki "
                     f"zaxiraga tushirishni ko'rib chiqing.</b>")
    return "\n".join(lines)
