"""Web bo'limlari javobini (payload) Telegram matniga aylantiradi.

Hisob-kitob bu yerda YO'Q: har funksiya `web/*view.py` qaytargan lug'atni oladi
va matn qaytaradi. Shunday qilib bot va sahifa **bir xil raqamni** ko'rsatadi —
ikkita joyda ikki xil hisob yuritilmaydi.

Telegram HTML ning kichik to'plami ishlatiladi: <b>, <i>, <code>. Foydalanuvchi
yoki FPL dan kelgan har qanday matn `esc()` dan o'tadi.

Kutilayotgan ochko yaxlit ko'rsatiladi (sahifadagi kabi); foyda va farqlar —
bitta kasr bilan, chunki ular kichik sonlar va ishorasi muhim.
"""

from __future__ import annotations

import html

LIMIT = 3900                      # Telegram xabari 4096 belgi; zaxira bilan
POS = {1: "DRV", 2: "HIM", 3: "YAR", 4: "HUJ"}
CHIP_SHORT = {"bboost": "BB", "3xc": "TC", "freehit": "FH", "wildcard": "WC"}


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=False)


def ev0(value) -> str:
    return str(round(value or 0))


def signed(value, digits: int = 1) -> str:
    value = value or 0
    return f"{value:+.{digits}f}"


def big(value) -> str:
    return f"{value:,}".replace(",", " ") if value else "—"


def clip(text: str, limit: int = LIMIT) -> str:
    """Juda uzun matnni satr chegarasida kesadi (HTML tegini yarmida qoldirmasdan)."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit("\n", 1)[0] + "\n\n<i>…davomi sahifada</i>"


def error(payload: dict, title: str) -> str | None:
    """Bo'lim xato qaytargan bo'lsa — foydalanuvchiga tushunarli matn."""
    if not payload or not payload.get("error"):
        return None
    hint = f"\n{esc(payload['hint'])}" if payload.get("hint") else ""
    return f"<b>{esc(title)}</b>\n\n{esc(payload['error'])}{hint}"


# ------------------------------------------------------------------ jamoam
def squad(p: dict) -> str:
    if (bad := error(p, "Jamoam")):
        return bad
    xi = [r for r in p["players"] if r["in_xi"]]
    bench = [r for r in p["players"] if not r["in_xi"]]
    ft = "∞" if p.get("unlimited_transfers") else str(p.get("free_transfers", "?"))
    lines = [
        f"<b>Jamoam · GW{p['event']}</b>",
        f"Kutilayotgan ochko: <b>{ev0(p.get('xi_ev_captain') or p['xi_ev'])}</b>"
        f" (kapitan {esc(p.get('captain'))})",
        f"Sxema {esc(p['formation'])} · butun tarkib {ev0(p.get('squad_ev'))}"
        f" · bank {p['bank']:.1f}m · transfer {ft}",
        "",
        "<b>Tavsiya etilgan 11 lik</b>",
    ]
    for r in xi:
        mark = " ©" if r["name"] == p.get("captain") else ""
        flag = " ⚠️" if r.get("status") not in (None, "a") else ""
        fixture = (r.get("fixture") or {}).get("opponent", "—")
        six = (r.get("outlook") or {}).get("p6")
        odds = f" · 6+ {six}%" if six is not None else ""
        lines.append(f"{POS.get(r['pos'], '?')} <b>{esc(r['name'])}</b>{mark}{flag} — "
                     f"{ev0(r['ev'])} · {esc(fixture)}{odds}")
    lines += ["", "<b>Zaxira</b>"]
    for r in bench:
        reason = f" — <i>{esc(r['reason'])}</i>" if r.get("reason") else ""
        lines.append(f"{POS.get(r['pos'], '?')} {esc(r['name'])} — {ev0(r['ev'])}{reason}")
    if not p.get("authenticated"):
        lines += ["", "<i>Tarkib oxirgi deadline holatida; transferlar soni taxminiy.</i>"]
    return clip("\n".join(lines))


# ------------------------------------------------------------------ o'rnim
def rank(p: dict) -> str:
    if (bad := error(p, "O'rnim")):
        return bad
    pr, risk = p["projection"], p["risk"]
    change = pr["rank_change"]
    if not pr.get("density"):
        move = "hisoblab bo'lmadi"
    elif abs(change) < 500:
        move = "o'zgarishsiz"
    else:
        move = f"{'↑' if change > 0 else '↓'} {big(abs(change))} (taxminan {big(pr['rank_after'])})"
    lines = [
        f"<b>O'rnim · GW{p['event']}</b>",
        f"Umumiy o'rin: <b>{big(p['rank'])}</b> (yuqori {p['percentile']}%)"
        f" · {p.get('points') or '—'} ochko",
        f"Oraliq: {esc(p['band']['label'])} · {p['band']['size']} ta jamoa namunasi",
        f"Raqiblarga nisbatan: <b>{signed(pr['edge'])}</b> ochko"
        f" (siz {ev0(pr['mine'])}, ular {ev0(pr['field'])})",
        f"Turdan keyin o'rin: {move}",
    ]
    if p.get("climb"):
        lines.append(f"Top {big(p['climb']['rank'])} gacha: {p['climb']['points']} ochko"
                     f" (turiga +{p['climb']['per_event']})")
    lines += ["", f"<b>Rejim: {esc(risk['name'])}.</b> {esc(risk['text'])}",
              f"<i>{esc(risk['stage'])}</i>", "", "<b>Xavf</b> — raqiblarda bor, sizda yo'q"]
    for t in p["threats"][:6]:
        lines.append(f"• <b>{esc(t['name'])}</b> — raqiblarda {t['eo']}%, {signed(t['swing'])}")
        how = t.get("how")
        if how and how.get("short"):
            lines.append(f"   ↳ pul yetmaydi: yana {how['short']:.1f}m")
        elif how:
            verdict = "" if how["worth_it"] else " — olmagan ma'qul"
            lines.append(f"   ↳ {esc(how['out'])} o'rniga: {signed(how['gain'])}"
                         f" ({p.get('horizon', 5)} tur){verdict}")
    if not p["threats"]:
        lines.append("• yo'q — raqiblardagi asosiy o'yinchilar sizda bor")
    lines += ["", "<b>Imkoniyat</b> — sizda bor, raqiblarda kam"]
    for c in p["chances"][:6]:
        lines.append(f"• <b>{esc(c['name'])}</b> — raqiblarda {c['eo']}%, {signed(c['swing'])}")
    cap = p["captain"]
    if cap.get("pick"):
        lines += ["", f"<b>Kapitan: {esc(cap['pick']['name'])}</b> — {esc(cap['why'])}"]
    used = [c for c in p["chips"] if not c["mine_used"]]
    lines += ["", "<b>Chiplar</b> (raqiblarning nechtasi ishlatgan)"]
    for c in p["chips"]:
        mine = "ishlatgansiz" if c["mine_used"] else "sizda bor"
        lines.append(f"• {esc(c['name'])}: {mine} · raqiblar {c['field_used']}%")
    if not used:
        lines.append("<i>Bu yarim yillik chiplaringiz tugagan.</i>")
    lines += ["", "<i>Raqiblar tarkibi o'tgan deadline holatida. O'rin prognozi — o'rtacha "
              "kutilma: bitta turda tasodif ±15–20 ochko.</i>"]
    return clip("\n".join(lines))


# ----------------------------------------------------------------- kapitan
def captain(p: dict) -> str:
    if (bad := error(p, "Kapitan")):
        return bad
    lines = [f"<b>Kapitan · GW{p['event']}</b>",
             f"Strategiya: <b>{esc(p['strategy_name'])}</b> — {esc(p['reason'])}", ""]
    safe, bold = p.get("safe"), p.get("bold")
    if safe and bold and safe["element"] == bold["element"]:
        lines.append(f"Ikkala yondashuvda ham: <b>{esc(safe['name'])}</b>")
    else:
        if safe:
            lines.append(f"Xavfsiz tanlov: <b>{esc(safe['name'])}</b>")
        if bold:
            lines.append(f"Tavakkal tanlov: <b>{esc(bold['name'])}</b>")
    lines += ["", "<b>Variantlar</b> (EV · 10+ ehtimoli · raqiblarda)"]
    for o in p["options"]:
        lines.append(f"• <b>{esc(o['name'])}</b> {esc(o['opponent'])} — {ev0(o['ev'])} · "
                     f"{o['p10']:.0f}% · {o['eo']:.0f}%\n   <i>{esc(o['verdict'])}</i>")
    if p.get("field_sample"):
        lines += ["", f"<i>Raqiblar — o'rningiz oralig'idagi ({esc(p.get('field_label'))}) "
                  f"{p['field_sample']} ta jamoa, o'tgan tur tanlovi.</i>"]
    return clip("\n".join(lines))


# ------------------------------------------------------------- transferlar
def _names(players: list[dict], selling: bool) -> str:
    return " + ".join(
        f"{esc(x['name'])} ({(x['selling'] if selling else x['price']):.1f})" for x in players)


def transfers(p: dict) -> str:
    if (bad := error(p, "Transferlar")):
        return bad
    ft = "∞" if p.get("unlimited_transfers") else str(p.get("free_transfers", "?"))
    lines = [f"<b>Transferlar · GW{p['event']}</b>",
             f"Tekin transfer {ft} · bank {p['bank']:.1f}m · hit −{p['hit_cost']}", ""]
    if p.get("recommendation") == "hold":
        lines += ["<b>Hozircha ushlab turing.</b> Hech bir variant hit va xavfni oqlamayapti.", ""]
    lines.append(f"<b>Takliflar</b> (foyda — {p['horizon']} tur bo'yicha, hit ayirilgan)")
    for m in p["moves"][:6]:
        tag = (m.get("rank") or {}).get("label")
        extra = f" · <i>{esc(tag)}</i>" if tag else ""
        hit = f" (−{m['hit']} hit)" if m.get("hit") else ""
        lines.append(f"• <b>{signed(m['gain'])}</b>{hit} — {_names(m['out'], True)} → "
                     f"{_names(m['in'], False)}{extra}")
    if not p["moves"]:
        lines.append("• byudjetga sig'adigan yaxshiroq variant topilmadi")
    if p.get("weak"):
        lines += ["", "<b>Zaif bo'g'inlar</b>"]
        for w in p["weak"][:4]:
            lines.append(f"• {esc(w['name'])} — <i>{esc(w['reason'])}</i>")
    if not p.get("authenticated"):
        lines += ["", "<i>Sotish narxlari va transferlar soni taxminiy (loginsiz).</i>"]
    return clip("\n".join(lines))


# ----------------------------------------------------------------- chiplar
def chips(p: dict) -> str:
    if (bad := error(p, "Chiplar")):
        return bad
    lines = [f"<b>Chiplar · GW{p['event']}</b>"]
    special = [f"GW{d['event']} — ikki o'yin: {esc(', '.join(d['teams']))}" for d in p["doubles"]]
    special += [f"GW{b['event']} — o'yin yo'q: {esc(', '.join(b['teams']))}" for b in p["blanks"]]
    lines.append("; ".join(special) if special
                 else f"Yaqin {len(p['events'])} turda ikki o'yinli yoki bo'sh tur yo'q.")
    lines.append("")
    for c in p["chips"]:
        if not c["available"]:
            lines.append(f"• <b>{esc(c['name'])}</b> — ishlatilgan")
            continue
        values = " ".join(f"GW{e['event']}:{e['value']:+.0f}" for e in c["by_event"])
        lines.append(f"• <b>{esc(c['name'])}</b> — {esc(c['verdict'])}\n   <code>{values}</code>")
    if all(not c["available"] for c in p["chips"]):
        lines += ["", f"<i>Bu yarim yillik chiplaringiz tugagan. Yangilari "
                  f"GW{p['refresh_event']} da beriladi.</i>"]
    else:
        lines += ["", f"<i>Raqam — chipni o'sha turda ishlatsangiz qo'shiladigan taxminiy ochko. "
                  f"Chegara +{p['threshold']:.0f}.</i>"]
    return clip("\n".join(lines))


# ---------------------------------------------------------------- raqiblar
def rivals(p: dict) -> str:
    if (bad := error(p, "Raqiblar")):
        return bad
    me = p["me"]
    lines = [f"<b>Raqiblar · {esc(p['league']['name'])}</b>"]
    if me.get("in_league"):
        gap = p.get("leader_gap")
        lines.append(f"O'rningiz: <b>{big(me['rank'])}</b> · {me['total']} ochko"
                     + (f" · yetakchidan {gap} ochko ortda" if gap and gap > 0 else ""))
        lines.append(f"Kelgusi turda kutilmoqda: {ev0(me.get('projected'))}")
    else:
        lines.append("<i>Bu ligada jamoangiz topilmadi.</i>")
    lines += ["", "<b>Xavf</b> — raqiblarda ko'p, sizda yo'q"]
    for t in p["threats"][:5]:
        lines.append(f"• {esc(t['name'])} — {t['eo']:.0f}% · EV {ev0(t['ev'])}")
    lines += ["", "<b>Imkoniyat</b> — sizda bor, raqiblarda kam"]
    for d in p["differentials"][:5]:
        lines.append(f"• {esc(d['name'])} — {d['eo']:.0f}% · EV {ev0(d['ev'])}")
    lines += ["", "<b>Jadval</b> (ochko · sizdan farq · kelgusi turda)"]
    last = 0
    for m in duel_candidates(p, limit=12, include_me=True):
        if last and m["rank"] and m["rank"] - last > 1:
            lines.append("  …")
        last = m["rank"] or last
        gap = "" if m["is_me"] or m.get("gap") is None else f" · {m['gap']:+d}"
        chip = f" [{CHIP_SHORT.get(m['chip'], m['chip'])}]" if m.get("chip") else ""
        name = f"<b>{esc(m['name'])}</b> ← siz" if m["is_me"] else esc(m["name"])
        lines.append(f"{m['rank'] or '—'}. {name}{chip} — {m['total']}{gap}"
                     f" · {ev0(m['projected'])}")
    lines += ["", "<i>Raqibni tanlang — u bilan yakkama-yakka tahlil. Tarkiblar o'tgan "
              "deadline holatida.</i>"]
    return clip("\n".join(lines))


def duel_candidates(p: dict, limit: int = 8, include_me: bool = False) -> list[dict]:
    """Yakkama-yakka uchun ko'rsatiladigan raqiblar: yetakchilar va o'rningiz atrofidagilar."""
    rows = p.get("managers", [])
    mine = next((i for i, m in enumerate(rows) if m["is_me"]), None)
    keep: list[int] = list(range(min(3, len(rows))))
    if mine is not None:
        half = max(2, (limit - 3) // 2)
        keep += list(range(max(0, mine - half), min(len(rows), mine + half + 1)))
    else:
        keep += list(range(3, min(len(rows), limit)))
    out = [rows[i] for i in sorted(set(keep))]
    return out if include_me else [m for m in out if not m["is_me"]][:limit]


def duel(p: dict) -> str:
    if (bad := error(p, "Yakkama-yakka")):
        return bad

    def pct(value) -> str:
        if value is None:
            return "—"
        return "&lt;1%" if value <= 0 else ("&gt;99%" if value >= 100 else f"{value}%")

    def share(value) -> str:
        return "kapitan" if value >= 2 else ("11 likda" if value >= 1 else "zaxirada")

    gap = p.get("gap")
    gap_text = "—" if gap is None else (f"{gap} ochko ortdasiz" if gap > 0
                                        else (f"{-gap} ochko oldindasiz" if gap < 0 else "teng"))
    lines = [
        f"<b>Siz va {esc(p['rival']['name'])}</b>",
        f"{p['me'].get('total', '—')} : {p['rival'].get('total', '—')} — {gap_text}"
        f" · {p['shared']}/15 umumiy",
        "",
        esc(p["verdict"]),
        "",
        f"GW{p['event']} da kutilma: <b>{signed(p['edge_next'])}</b>"
        f" (yutish ehtimoli {pct(p.get('win_next'))})",
        f"Turiga o'rtacha: {signed(p['edge_avg'])}",
        f"{p['ahead']['horizon_events']} turdan keyin oldinda: {pct(p['ahead'].get('horizon'))}"
        f" · mavsum oxirida: {pct(p['ahead'].get('season'))}",
        "",
        "<code>" + "  ".join(f"GW{e['event']}:{e['edge']:+.0f}" for e in p["per_event"]) + "</code>",
        "",
        "<b>Faqat sizda</b>",
    ]
    lines += [f"• {esc(r['name'])} — {share(r['share'])}, {ev0(r['ev_horizon'])}"
              for r in p["only_mine"][:7]] or ["• yo'q"]
    lines += ["", "<b>Faqat unda</b>"]
    lines += [f"• {esc(r['name'])} — {share(r['share'])}, {ev0(r['ev_horizon'])}"
              for r in p["only_his"][:7]] or ["• yo'q"]
    chase = p["plan"]["mode"] == "chase"
    first, second = (("differ", "Farq yaratish (unda yo'q)"), ("cover", "Farqni yopish (undagilar)"))
    if not chase:
        first, second = second, first
    for key, title in (first, second):
        lines += ["", f"<b>{title}</b>" + (" — sizga mos" if (key, title) == first else "")]
        moves = p["plan"][key]
        lines += [f"• {esc(m['out'])} → {esc(m['in'])}: {signed(m['gain'])}" for m in moves] \
            or ["• foydali variant topilmadi"]
    lines += ["", "<i>Ehtimollar taxminiy: raqib tarkibini o'zgartirmaydi deb olingan.</i>"]
    return clip("\n".join(lines))


# ------------------------------------------------------------ jamoa tuzish
def draft(p: dict) -> str:
    if (bad := error(p, "Jamoa tuzish")):
        return bad
    xi = [r for r in p["players"] if r["in_xi"]]
    bench = [r for r in p["players"] if not r["in_xi"]]
    lines = [
        f"<b>Noldan tuzilgan jamoa · GW{p['event']}</b>",
        f"Kutilayotgan ochko: <b>{ev0(p['expected_points'])}</b> (kapitan {esc(p['captain'])})",
        f"Sxema {esc(p['formation'])} · sarflandi {p['cost']:.1f}m · qoldi {p['bank']:.1f}m",
        "",
    ]
    for pos in (1, 2, 3, 4):
        row = [f"{esc(r['name'])}{' ©' if r.get('is_captain') else ''} ({ev0(r['ev'])})"
               for r in xi if r["pos"] == pos]
        lines.append(f"<b>{POS[pos]}</b> " + ", ".join(row))
    lines.append("<b>Zaxira</b> " + ", ".join(esc(r["name"]) for r in bench))
    lines += ["", "<i>Mavjud tarkibingizdan mustaqil — wildcard yoki Free Hit uchun. "
              "100m, 2/5/5/3, bitta klubdan ko'pi 3 ta.</i>"]
    return clip("\n".join(lines))


# --------------------------------------------------------------------- H2H
def h2h(p: dict) -> str:
    if (bad := error(p, "H2H")):
        return bad
    t = p["totals"]
    lines = ["<b>H2H — model ekspertlarga qarshi</b>"]
    if t["live_n"]:
        lines.append(f"Jonli hisob: <b>{t['live_model']} : {t['live_experts']}</b>"
                     f" ({t['live_n']} tur)")
    else:
        lines.append("Jonli hisob hali boshlanmagan.")
    if t["n"]:
        lines.append(f"Orqaga qarab bilan birga: {t['model']} : {t['experts']}"
                     f" · model yutgan turlar {t['wins']}/{t['n']}")
    up = p.get("upcoming")
    if up:
        for side, title in (("model", "Model"), ("experts", "Ekspertlar")):
            data = up.get(side)
            lines += ["", f"<b>{title} · GW{up['gw']}</b>"]
            if not data:
                lines.append("tarkib hali kiritilmagan")
                continue
            for pos in (1, 2, 3, 4):
                row = [f"{esc(x['name'])}{' ©' if x['captain'] else ''}"
                       for x in data["players"] if x["pos"] == pos]
                if row:
                    lines.append(f"{POS[pos]}: " + ", ".join(row))
            if data.get("expected"):
                lines.append(f"kutilmoqda {ev0(data['expected'])}")
    done = [r for r in p["rows"] if r["finished"] and r.get("diff") is not None]
    if done:
        lines += ["", "<b>Turlar</b> (model : ekspertlar)"]
        for r in reversed(done[-10:]):
            tag = "" if r["live"] else " <i>orqaga qarab</i>"
            lines.append(f"GW{r['gw']}: {r['model']['points']} : {r['experts']['points']}"
                         f" ({r['diff']:+d}){tag}")
    lines += ["", f"<i>Qoida: {esc(p['rule'])}. Xulosa uchun kamida 8 jonli tur kerak.</i>"]
    return clip("\n".join(lines))


# ------------------------------------------------------------------ sur'at
def pace(p: dict) -> str:
    if (bad := error(p, "Sur'at")):
        return bad
    lines = [
        f"<b>Mavsum sur'ati</b> · maqsad {p['target']}",
        f"<b>{p['points']}</b> / {p['target']} ochko · GW{p['played']}/{p['total_events']}",
        f"Holat: <b>{esc(p['grade'])}</b> — rejadan {signed(round(p['delta']), 0)} ochko",
        "",
        f"Turiga o'rtacha: {p['average']:.1f} (norma {p['per_event_needed']:.1f})",
    ]
    if p.get("needed_per_event") is not None:
        lines.append(f"Qolgan {p['remaining_events']} turda kerak: {p['needed_per_event']:.1f}")
    lines.append(f"Shu sur'atda yakun: {round(p['projected'])}")
    if p.get("rank"):
        lines.append(f"Umumiy o'rin: {big(p['rank'])}")
    lines += [
        "",
        f"O'rtacha menejerdan: {signed(p.get('vs_average_total', 0), 0)}"
        f" ({p.get('beat_average', 0)}/{p['played']} turda ustun)",
        f"Minusga ketdi: −{p.get('hits_paid', 0)} · zaxirada qoldi: {p.get('bench_lost', 0)}",
    ]
    if p.get("best") and p.get("worst"):
        lines.append(f"Eng yaxshi tur: {p['best']['net']} (GW{p['best']['event']})"
                     f" · eng yomon: {p['worst']['net']} (GW{p['worst']['event']})")
    return clip("\n".join(lines))
