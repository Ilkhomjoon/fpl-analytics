"""Bitta o'yinchi bo'yicha model qanday qaror chiqargani — to'liq izoh.

Maqsad: har bir raqamni qo'lda tekshirish mumkin bo'lsin. Model "shunday deb
o'ylayman" demaydi — qaysi ma'lumotdan, qanday og'irlik bilan chiqqanini
ko'rsatadi.
"""

from __future__ import annotations

from .ev import (
    DEFCON_THRESHOLD, GK, PRIOR_XA90, PRIOR_XG90, PlayerProfile,
    points_distribution,
)

POS_NAME = {1: "Darvozabon", 2: "Himoyachi", 3: "Yarim himoyachi", 4: "Hujumchi"}


def _row(label: str, value: str, note: str = "") -> str:
    return f"  {label:<26} {value:>12}   {note}"


def explain_player(
    profile: PlayerProfile,
    player_ev,
    element: dict,
    summary: dict | None,
    events: list[int],
    team_name: str = "",
) -> str:
    """O'yinchi bo'yicha to'liq hisob-kitobni matn ko'rinishida qaytaradi."""
    lines: list[str] = []
    add = lines.append

    add("=" * 72)
    add(f"{profile.name} ({team_name}) · {POS_NAME.get(profile.position, '?')} · "
        f"{profile.price:.1f}m")
    add("=" * 72)

    # ---------------------------------------------------- kirish ma'lumotlari
    past = (summary or {}).get("history_past") or []
    history = (summary or {}).get("history") or []

    add("\nO'TGAN MAVSUM (prior manbasi)")
    if past:
        last = past[-1]
        pm = last.get("minutes", 0) or 0
        ps = last.get("starts", 0) or 0
        past_90s = pm / 90.0
        add(_row("daqiqa", f"{pm}", f"38 o'yindan {pm / (38 * 90) * 100:.0f}%"))
        add(_row("asosiy tarkibda", f"{ps}", f"38 dan {ps / 38 * 100:.0f}%"))
        if past_90s >= 5:
            add(_row("xG / 90", f"{(last.get('expected_goals') or 0) / past_90s:.3f}"))
            add(_row("xA / 90", f"{(last.get('expected_assists') or 0) / past_90s:.3f}"))
    else:
        add("  (ma'lumot yo'q — prior narxdan olinadi)")

    add("\nJORIY MAVSUM")
    add(_row("daqiqa", f"{profile.minutes}", f"{profile.nineties:.2f} ta 90 daqiqa"))
    add(_row("asosiy tarkibda", f"{element.get('starts', 0)}"))
    if history:
        recent = history[-5:]
        detail = ", ".join(
            f"GW{h.get('round')}: {h.get('minutes', 0)}'"
            f"{'(A)' if (h.get('starts') or 0) else '(Z)'}"
            for h in recent
        )
        add(f"  so'nggi turlar             {detail}")
    add(_row("xG (jami)", f"{element.get('expected_goals', 0)}"))
    add(_row("xA (jami)", f"{element.get('expected_assists', 0)}"))

    # ---------------------------------------------------- daqiqalar modeli
    add("\nDAQIQALAR MODELI")
    add(_row("mavjudlik", f"{profile.availability:.2f}",
             element.get("news") or "xabar yo'q"))
    add(_row("p(asosiy tarkib)", f"{profile.p_start:.2f}"))
    add(_row("p(o'ynaydi)", f"{profile.p_appear:.2f}"))
    add(_row("p(60+ daqiqa)", f"{profile.p60:.2f}"))
    add(_row("kutilayotgan daqiqa", f"{profile.xmins:.1f}"))
    if history:
        last_h = history[-1]
        started = (last_h.get("starts") or 0) > 0
        mins = last_h.get("minutes", 0) or 0
        if started and mins >= 60:
            add("  → so'nggi turda asosiy tarkibda 60+ daqiqa: p_start ≥ 0.75 qilindi")
        elif mins == 0:
            add("  → so'nggi turda o'ynamadi: p_start ≤ 0.45 bilan cheklandi")

    # ---------------------------------------------------- hujum tezliklari
    add("\nHUJUM TEZLIKLARI (shrinkage bilan)")
    add(_row("xG90 (model)", f"{profile.xg90:.3f}",
             f"pozitsiya priori {PRIOR_XG90[profile.position]:.2f}"))
    add(_row("xA90 (model)", f"{profile.xa90:.3f}",
             f"pozitsiya priori {PRIOR_XA90[profile.position]:.2f}"))
    if profile.position in DEFCON_THRESHOLD:
        add(_row("himoya harakati / 90", f"{profile.dc90:.1f}",
                 f"chegara {DEFCON_THRESHOLD[profile.position]}"))
        if profile.dc_hit_rate is not None:
            add(_row("chegaradan o'tish", f"{profile.dc_hit_rate * 100:.0f}%",
                     "haqiqiy statistika"))
    add(_row("bonus / 90", f"{profile.bonus90:.2f}"))
    if profile.position == GK:
        add(_row("to'xtatish / 90", f"{profile.saves90:.1f}"))
    if profile.is_pen_taker:
        add("  → penalti ijrochisi (1-navbat)")
    if profile.is_set_piece:
        add("  → standart holatlar ijrochisi")

    # ---------------------------------------------------- turlar bo'yicha EV
    add("\nTURLAR BO'YICHA EV")
    for ev_id in events:
        fixtures = player_ev.fixtures.get(ev_id, [])
        if not fixtures:
            add(f"  GW{ev_id:<3} —  o'yin yo'q (bo'sh tur)")
            continue
        for fx in fixtures:
            add(f"  GW{ev_id:<3} {fx.opponent}{'(u)' if fx.is_home else '(m)'}  "
                f"EV {fx.ev:5.2f}")
            parts = ", ".join(
                f"{k}={v:+.2f}" for k, v in fx.parts.items() if abs(v) >= 0.01
            )
            add(f"        {parts}")

    # ---------------------------------------------------- taqsimot
    first = events[0]
    fixtures = player_ev.fixtures.get(first, [])
    if fixtures:
        dist = points_distribution(fixtures[0].inputs)
        add(f"\nGW{first} OCHKO TAQSIMOTI")
        add(_row("o'rtacha", f"{dist.mean():.2f}"))
        add(_row("P(0 ochko)", f"{dist.pmf.get(0, 0) * 100:.0f}%"))
        add(_row("P(2+ ochko)", f"{dist.tail(2) * 100:.0f}%"))
        add(_row("P(6+ ochko)", f"{dist.tail(6) * 100:.0f}%"))
        add(_row("P(10+ ochko)", f"{dist.tail(10) * 100:.0f}%"))
        add(_row("P(15+ ochko)", f"{dist.tail(15) * 100:.0f}%"))
        add(_row("90-foizli natija", f"{dist.percentile(0.90)}"))

    add(f"\nJAMI: kelgusi {len(events)} tur uchun {player_ev.horizon_ev:.1f} EV "
        f"(vaznlangan), keyingi tur {player_ev.next_ev:.1f} EV")
    add("=" * 72)
    return "\n".join(lines)


def find_players(elements: list[dict], query: str) -> list[dict]:
    """Nomi bo'yicha o'yinchi qidiradi (qismiy moslik, katta-kichik harf farqsiz)."""
    q = query.strip().lower()
    exact = [
        e for e in elements
        if q == (e.get("web_name") or "").lower()
    ]
    if exact:
        return exact
    return [
        e for e in elements
        if q in (e.get("web_name") or "").lower()
        or q in f"{e.get('first_name', '')} {e.get('second_name', '')}".lower()
    ][:10]
