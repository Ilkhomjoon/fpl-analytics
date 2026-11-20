"""O'rin oraliqlari — "mening o'rnimdagi raqiblar" namunasi.

O'rin ochkoga emas, **raqiblardan farqqa** bog'liq: hamma olgan o'yinchi gol
ursa, o'rin deyarli o'zgarmaydi. Shuning uchun har menejerga "eng ko'p ochko"
emas, "sening o'rningdagi raqiblarga nisbatan eng foydali qaror" kerak. Buning
uchun o'sha raqiblarda **kim borligini** bilish kerak.

NEGA ORALIQLAR? Har menejer uchun atrofidagi 40 ta jamoani yuklash bitta odam
uchun muammo emas, lekin kanalning yuzlab a'zosi uchun so'rovlar soni
ko'payadi. Shuning uchun umumiy jadval oraliqlarga bo'linadi (top 1k, 10k,
50k … 4 mln) va har oraliqdan namuna **bir marta** olinib, diskda saqlanadi:
bitta oraliqdagi hamma foydalanuvchi shuni ishlatadi.

Namuna — **o'tgan deadline** holati: kelgusi tur tarkiblari FPL da
deadline'gacha yopiq. Tur tugagach namuna yangi tur uchun qayta olinadi.

Bu modul faqat ma'lumot va sodda hisob beradi; sahifaga `web/rankview.py` chiqaradi.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from . import chips as chips_mod

log = logging.getLogger(__name__)

OVERALL_LEAGUE = 314
# Oraliq chegaralari (umumiy o'rin). Tepada zichroq: u yerda bir necha ming
# o'rin farq bitta turda yopiladi, pastda esa yuz minglab jamoa bir xil ochkoda.
EDGES = [1_000, 10_000, 50_000, 100_000, 250_000, 500_000,
         1_000_000, 2_000_000, 4_000_000]
PAGES = 8                 # har oraliqdan nechta sahifa
PER_PAGE = 5              # har sahifadan nechta jamoa → jami 40
SEASON_EVENTS = 38
# O'ringa moslash mavsum oxiriga qarab kuchayadi. 20-turgacha deyarli hamma
# uchun to'g'ri yo'l — shunchaki EV ni maksimal qilish; xavfni ataylab oshirish
# yoki kamaytirish faqat oxirgi turlarda haqiqatan foyda beradi.
ADAPT_FROM, ADAPT_FULL = 19, 34
MIN_INTENSITY = 0.15


@dataclass(frozen=True)
class Band:
    index: int
    low: int              # oraliqning yaxshi cheti (kichik raqam), shu kiradi
    high: int             # yomon cheti

    @property
    def label(self) -> str:
        def short(n: int) -> str:
            if n >= 1_000_000:
                return f"{n / 1_000_000:g} mln"
            return f"{n // 1000}k" if n >= 1000 else str(n)
        if self.low <= 1:
            return f"top {short(self.high)}"
        return f"{short(self.low)} – {short(self.high)}"


def band_for(rank: int, total_players: int) -> Band:
    """Menejerning oralig'i. Oxirgi oraliq — 4 mln dan pastdagi hamma."""
    bounds = [1] + [e for e in EDGES if e < total_players] + [max(total_players, 2)]
    for i in range(len(bounds) - 1):
        if rank <= bounds[i + 1]:
            return Band(i, bounds[i], bounds[i + 1])
    return Band(len(bounds) - 2, bounds[-2], bounds[-1])


def sample_ranks(band: Band, pages: int = PAGES) -> list[int]:
    """Oraliq bo'ylab teng tarqalgan o'rinlar — har biridan bitta sahifa olinadi."""
    span = band.high - band.low
    return [int(band.low + span * (i + 0.5) / pages) for i in range(pages)]


# ------------------------------------------------------------------- namuna
def _cache_path(client, band: Band, event: int) -> Path | None:
    """Kesh fayli — **klientning** kesh papkasida.

    Soxta (demo/test) klientda kesh papkasi yo'q: uning uydirma tarkiblari
    haqiqiy namuna o'rniga diskka yozilib qolmasligi kerak.
    """
    root = getattr(client, "cache_dir", None)
    if not root:
        return None
    return Path(root) / "bands" / f"gw{event:02d}_b{band.index}_{band.low}.json"


def load_band(client, cfg, band: Band, event: int, next_event: int,
              refresh: bool = False) -> dict:
    """Oraliq namunasi: egalik, kapitanlik, ishlatilgan chiplar, tarkiblar.

    `event` — tarkiblar olinadigan (deadline'i o'tgan) tur; `next_event` —
    chiplarning qaysi yarim yillikka tegishliligini aniqlash uchun.
    Natija diskda saqlanadi va shu tur uchun qayta yuklanmaydi.
    """
    path = _cache_path(client, band, event)
    if path and path.exists() and not refresh:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass

    entries: list[dict] = []
    anchors: list[tuple[int, int]] = []
    for rank in sample_ranks(band):
        try:
            data = client.league_page_for_rank(OVERALL_LEAGUE, rank)
        except Exception as exc:
            log.warning("oraliq sahifasi olinmadi (%s): %s", rank, exc)
            continue
        rows = (data.get("standings") or {}).get("results", [])
        if not rows:
            continue
        anchors.append((rows[0].get("rank") or rank, rows[0].get("total") or 0))
        # Sahifa bo'ylab teng qadam bilan — qo'shni (ko'pincha bir xil) jamoalar emas
        step = max(1, len(rows) // PER_PAGE)
        entries += [r for r in rows[::step][:PER_PAGE] if r.get("entry")]

    ids = [r["entry"] for r in entries]
    picks = client.gather(ids, lambda eid: client.entry_picks(eid, event)) if ids else {}
    histories = client.gather(ids, client.entry_history) if ids else {}

    squads: list[list[dict]] = []
    own: dict[int, int] = {}
    caps: dict[int, int] = {}
    used: dict[str, int] = {}
    active: dict[str, int] = {}
    for eid in ids:
        data = picks.get(eid) or {}
        rows = data.get("picks") or []
        if not rows:
            continue
        squads.append([{"e": p["element"], "p": p.get("position", 16),
                        "m": p.get("multiplier", 1)} for p in rows])
        for p in rows:
            own[p["element"]] = own.get(p["element"], 0) + 1
            if p.get("is_captain"):
                caps[p["element"]] = caps.get(p["element"], 0) + 1
        if data.get("active_chip"):
            active[data["active_chip"]] = active.get(data["active_chip"], 0) + 1
        history = (histories.get(eid) or {}).get("chips") or []
        left = set(chips_mod.available_chips(history, next_event))
        for chip in chips_mod.ALL_CHIPS:
            if chip not in left:
                used[chip] = used.get(chip, 0) + 1

    n = len(squads) or 1
    result = {
        "band": {"index": band.index, "low": band.low, "high": band.high, "label": band.label},
        "event": event, "size": len(squads), "saved_at": time.time(),
        "ownership": {str(el): round(100.0 * c / n, 1) for el, c in own.items()},
        "captaincy": {str(el): round(100.0 * c / n, 1) for el, c in caps.items()},
        "chips_used": {chip: round(100.0 * c / n) for chip, c in used.items()},
        "chips_active": {chip: round(100.0 * c / n) for chip, c in active.items()},
        "anchors": sorted(anchors),
        "squads": squads,
    }
    if squads and path:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result), encoding="utf-8")
        except OSError as exc:
            log.warning("oraliq keshi yozilmadi: %s", exc)
    return result


def effective_ownership(sample: dict) -> dict[int, float]:
    """O'yinchi → ta'sirli egalik ulushi (0..2): egalik + kapitanlik.

    Kapitan ikki marta sanaladi, shuning uchun 1.0 dan oshishi mumkin: o'yinchi
    gol ursa, raqiblar o'rtacha shuncha "nusxa" ochko oladi.
    """
    own = {int(k): v / 100.0 for k, v in sample.get("ownership", {}).items()}
    cap = {int(k): v / 100.0 for k, v in sample.get("captaincy", {}).items()}
    return {el: own.get(el, 0.0) + cap.get(el, 0.0) for el in set(own) | set(cap)}


# Transferni raqiblarga nisbatan belgilash chegaralari (ta'sirli egalik, %)
COVER_EO = 30.0          # shundan ko'p — "ommaviy": olsangiz farq yopiladi
DIFFER_EO = 12.0         # shundan kam — "kam uchraydi": olsangiz farq yaratiladi


def move_profile(in_eo: list[float], out_eo: list[float]) -> dict:
    """Transfer raqiblarga nisbatan nima qiladi: farqni yopadimi yoki yaratadimi.

    MUHIM: transferning raqiblarga nisbatan **kutilayotgan** foydasi uning EV
    foydasiga teng — raqiblar ochkosi mening transferimdan o'zgarmaydi. Egalik
    faqat **xavfni** o'zgartiradi: ommaviy o'yinchini olish natijamni
    raqiblarnikiga yaqinlashtiradi (o'rin kam tebranadi), kam uchraydiganini
    olish uzoqlashtiradi (ko'p tebranadi — ikki tomonga ham).

    `cover` — raqiblar bilan umumiylik qanchaga ortadi (foiz punktlarida).
    """
    cover = sum(in_eo) - sum(out_eo)
    if in_eo and min(in_eo) >= COVER_EO and cover > 0:
        kind, label = "cover", "xavfni yopadi"
    elif in_eo and max(in_eo) <= DIFFER_EO:
        kind, label = "differ", "farq yaratadi"
    else:
        kind, label = "neutral", ""
    return {"kind": kind, "label": label, "cover": round(cover)}


def order_moves(rows: list[dict], risk: dict, horizon_weight: float) -> list[dict]:
    """Takliflarni xavf rejimiga qarab tartiblaydi — faqat **deyarli teng** variantlar orasida.

    Eng yaxshi EV foydasidan `sacrifice × horizon_weight` ochkodan ko'p orqada
    qolmagan, foydali variantlar "teng" sanaladi. Ular orasida himoya rejimi
    farqni yopadiganini, quvish rejimi farq yaratadiganini oldinga chiqaradi.
    Chegara mavsum boshida juda kichik (bir ochkodan kam) — ya'ni tartibni
    deyarli har doim EV belgilaydi. Qolganlari EV bo'yicha qoladi.
    """
    if not rows:
        return rows
    tolerance = risk.get("sacrifice", 0.0) * horizon_weight
    best = max(r["gain"] for r in rows)
    mode = risk.get("mode", "balanced")
    sign = {"protect": -1, "chase": 1}.get(mode, 0)
    if not sign or tolerance <= 0:
        return rows
    close = [r for r in rows if r["worth_it"] and best - r["gain"] <= tolerance]
    rest = [r for r in rows if r not in close]
    ordered = sorted(close, key=lambda r: (sign * r["rank"]["cover"], -r["gain"]))
    if ordered and ordered[0] is not close[0]:
        ordered[0]["rank"]["promoted"] = True
    return ordered + rest


# ------------------------------------------------------------- o'rin hisobi
def rank_density(anchors: list[tuple[int, int]], rank: int) -> float:
    """Shu o'rin atrofida **bir ochkoga** nechta menejer to'g'ri keladi.

    `anchors` — (o'rin, ochko) juftliklari. Menejer o'rnini o'rab turgan ikki
    nuqtadan olinadi; chetda bo'lsa — eng yaqin ikkitasidan.
    """
    # Pastki oraliqlarda yuz minglab jamoa bir xil ochkoda turadi. Shuning uchun
    # har ochko uchun **boshlanish o'rni** olinadi (o'sha ochkodagi eng yaxshi
    # o'rin): aks holda bir xil ochkoli ikki nuqta orasida farq 0 chiqib,
    # zichlik hisoblanmay qoladi.
    start: dict[int, int] = {}
    for r, t in anchors:
        if r and t:
            start[t] = min(r, start.get(t, r))
    points = sorted((r, t) for t, r in start.items())
    if len(points) < 2:
        return 0.0
    pair = None
    for a, b in zip(points, points[1:]):
        if a[0] <= rank <= b[0]:
            pair = (a, b)
            break
    if pair is None:
        pair = (points[0], points[1]) if rank < points[0][0] else (points[-2], points[-1])
    (r1, t1), (r2, t2) = pair
    gap = t1 - t2
    return (r2 - r1) / gap if gap > 0 else 0.0


def projected_rank(rank: int, edge: float, density: float, total_players: int) -> int:
    """Tur ichida raqiblardan `edge` ochko ko'p olinsa, taxminiy yangi o'rin."""
    return int(max(1, min(total_players, round(rank - edge * density))))


# ------------------------------------------------------------ xavf darajasi
def adapt_intensity(next_event: int) -> float:
    """O'ringa moslash kuchi: 0.15 (mavsum boshi) → 1.0 (oxirgi turlar)."""
    if next_event <= ADAPT_FROM:
        return MIN_INTENSITY
    share = (next_event - ADAPT_FROM) / (ADAPT_FULL - ADAPT_FROM)
    return round(max(MIN_INTENSITY, min(1.0, MIN_INTENSITY + (1 - MIN_INTENSITY) * share)), 2)


# Farq qiluvchi tanlov uchun kutilayotgan ochkodan voz kechish chegarasi
# (to'liq kuchda). "Himoya"da — nol: o'rinni saqlayotgan odam EV yo'qotmaydi.
SACRIFICE = {"protect": 0.0, "balanced": 0.5, "chase": 1.2}
MODE_NAMES = {"protect": "himoya", "balanced": "muvozanat", "chase": "quvish"}


def risk_advice(rank: int | None, total_players: int | None, next_event: int) -> dict:
    """O'rin va mavsum bosqichiga qarab xavf darajasi.

    Uch rejim: **himoya** (yuqori 1%) — ommaviy tanlovdan chetlashmaslik;
    **muvozanat** (yuqori 10%) — tanlab tavakkal; **quvish** — farq kerak.
    `sacrifice` — farq qiluvchi tanlov uchun necha ochko EV dan voz kechsa
    bo'ladi; mavsum boshida deyarli nol.
    """
    intensity = adapt_intensity(next_event)
    if not rank or not total_players:
        mode, pct = "balanced", None
    else:
        pct = rank / total_players * 100
        mode = "protect" if pct <= 1 else ("balanced" if pct <= 10 else "chase")
    sacrifice = round(SACRIFICE[mode] * intensity, 2)

    where = f"yuqori {pct:.1f}% dasiz" if pct is not None else "o'rin noma'lum"
    if mode == "protect":
        text = (f"{where} — vazifa o'rinni saqlash. Raqiblarda ko'p uchraydigan "
                "o'yinchilarni qamrab oling, kapitanni ommaviy tanlang.")
    elif mode == "balanced":
        text = (f"{where} — asos mustahkam bo'lsin, bir-ikki joyda farq qiling.")
    else:
        text = (f"{where} — hamma olgan o'yinchi sizni yuqoriga ko'tarmaydi; "
                "o'rin ko'tarish uchun raqiblarda yo'q kuchli o'yinchilar kerak.")
    if intensity < 0.5:
        stage = (f"Mavsumning hozirgi bosqichida (GW{next_event}) bu maslahat yumshoq: "
                 "hali ko'p tur bor, eng to'g'ri yo'l — shunchaki kutilayotgan ochkoni "
                 "maksimal qilish. O'ringa moslash oxirgi turlarga qarab kuchayadi.")
    else:
        stage = (f"Mavsum oxiriga {SEASON_EVENTS - next_event + 1} tur qoldi — "
                 "o'ringa moslash endi haqiqatan ahamiyatli.")
    return {
        "mode": mode, "name": MODE_NAMES[mode], "percentile": round(pct, 1) if pct is not None else None,
        "intensity": intensity, "sacrifice": sacrifice, "text": text, "stage": stage,
    }
