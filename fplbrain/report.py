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


def _diverse(moves: list[TransferMove], limit: int) -> list[TransferMove]:
    """Bir xil o'yinchini sotadigan variantlarni takrorlamaslik uchun xilma-xillik."""
    chosen, used_out, used_in = [], set(), set()
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
    if len(chosen) < limit:                       # yetmasa — qolganlaridan to'ldiramiz
        for m in moves:
            if m not in chosen:
                chosen.append(m)
            if len(chosen) >= limit:
                break
    return chosen


def transfers_section(moves: list[TransferMove], cfg, squad: Squad, limit: int | None = None) -> str:
    good = _diverse(
        [m for m in moves if m.gain >= cfg.min_gain_to_suggest],
        limit if limit is not None else cfg.max_transfer_suggestions,
    )
    lines = ["<b>🔁 TRANSFER TAHLILI</b>"]
    if not good:
        best = moves[0] if moves else None
        lines.append(
            "Bu hafta majburiy transfer yo'q — FT ni saqlab qo'yish foydaliroq."
        )
        if best:
            lines.append(
                f"<i>Eng yaxshi variant baribir zaif:</i> {escape(best.describe())} — {best.gain:+.1f} EV"
            )
        return "\n".join(lines)

    for i, m in enumerate(good, 1):
        hit_txt = f" · <b>-{m.hit} hit</b>" if m.hit else " · hit yo'q"
        money = f" · {m.cost:+.1f}m, bank {m.bank_after:.1f}m"
        lines.append(
            f"<b>{i}.</b> {escape(m.describe())}\n"
            f"    sof foyda <b>{m.gain:+.1f} EV</b> (xom {m.raw_gain:+.1f}){hit_txt}{money}"
        )
    if any(m.hit for m in good):
        lines.append("<i>Eslatma: hit faqat foyda +4 dan oshsa oqlanadi.</i>")
    return "\n".join(lines)


def captain_section(options: list[CaptainOption], event: int) -> str:
    if not options:
        return ""
    lines = [f"<b>🅲 KAPITAN — GW{event}</b>"]
    for i, o in enumerate(options, 1):
        eo = f" · raqiblarda {o.eo:.0f}% kapitan" if o.eo else ""
        lines.append(
            f"<b>{i}.</b> {_p(o.name)} — {o.ev:.1f} EV · haul {o.p_haul*100:.0f}%"
            f" · hissa {o.p_return*100:.0f}%{eo}\n    <i>{o.verdict}</i>"
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
