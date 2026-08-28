"""Bozor signallari: narx o'zgarishi bashorati, yangi jarohat xabarlari, egalik trendlari."""

from __future__ import annotations

from dataclasses import dataclass




@dataclass
class PriceSignal:
    element: int
    name: str
    team: str
    price: float
    percent: float           # 100 ga yetganda narx ko'tariladi, -100 da tushadi
    hourly: float            # soatiga o'zgarish tezligi (foizda)
    eta_hours: float | None
    direction: str           # "rise" | "fall"
    likelihood: str          # "juda yuqori" | "yuqori" | "o'rtacha"
    owned: bool = False


@dataclass
class NewsSignal:
    element: int
    name: str
    team: str
    text: str
    chance: int | None
    status: str
    owned: bool
    kind: str                # "yangi" | "o'zgargan" | "tuzaldi"


def _likelihood(percent: float, hourly: float) -> str:
    remaining = (100 - abs(percent))
    if abs(percent) >= 99:
        return "juda yuqori"
    if hourly and remaining / max(hourly, 1e-6) <= 6:
        return "yuqori"
    if hourly and remaining / max(hourly, 1e-6) <= 18:
        return "o'rtacha"
    return "past"


def price_signals(
    elements: list[dict], teams: dict[int, str], owned: set[int], min_abs_percent: float = 70.0
) -> list[PriceSignal]:
    """FPL ning yangi price_change_percent / hourly_rate maydonlari asosida bashorat."""
    out: list[PriceSignal] = []
    for e in elements:
        try:
            pct = float(e.get("price_change_percent") or 0)
        except (TypeError, ValueError):
            pct = 0.0
        hourly = float(e.get("price_change_hourly_rate") or 0) / 100.0
        if abs(pct) < min_abs_percent and e["id"] not in owned:
            continue
        if abs(pct) < 45:
            continue
        remaining = max(0.0, 100 - abs(pct))
        eta = round(remaining / hourly, 1) if hourly > 0 else None
        out.append(
            PriceSignal(
                element=e["id"],
                name=e.get("web_name", "?"),
                team=teams.get(e["team"], "?"),
                price=e["now_cost"] / 10.0,
                percent=round(pct, 1),
                hourly=round(hourly, 2),
                eta_hours=eta,
                direction="rise" if pct > 0 else "fall",
                likelihood=_likelihood(pct, hourly),
                owned=e["id"] in owned,
            )
        )
    out.sort(key=lambda s: (-abs(s.percent), not s.owned))
    return out


def actual_price_changes(elements: list[dict], prev: dict[str, dict], teams: dict[int, str], owned: set[int]):
    """Kecha snapshotdan beri haqiqatda o'zgargan narxlar."""
    rises, falls = [], []
    for e in elements:
        old = prev.get(str(e["id"]))
        if not old:
            continue
        delta = e["now_cost"] - old["now_cost"]
        if delta == 0:
            continue
        row = {
            "name": e.get("web_name", "?"),
            "team": teams.get(e["team"], "?"),
            "price": e["now_cost"] / 10.0,
            "delta": delta / 10.0,
            "owned": e["id"] in owned,
        }
        (rises if delta > 0 else falls).append(row)
    rises.sort(key=lambda r: -r["price"])
    falls.sort(key=lambda r: -r["price"])
    return rises, falls


def news_signals(elements: list[dict], prev: dict[str, dict], teams: dict[int, str], owned: set[int]) -> list[NewsSignal]:
    out: list[NewsSignal] = []
    for e in elements:
        old = prev.get(str(e["id"]))
        news = (e.get("news") or "").strip()
        status = e.get("status", "a")
        if old is None:
            continue
        old_news = (old.get("news") or "").strip()
        if news == old_news and status == old.get("status"):
            continue

        is_owned = e["id"] in owned
        popular = float(e.get("selected_by_percent") or 0) >= 3.0
        if not (is_owned or popular):
            continue

        if not news and old_news:
            kind = "tuzaldi"
            text = "xabar olib tashlandi — o'ynashi mumkin"
        elif news and not old_news:
            kind = "yangi"
            text = news
        else:
            kind = "o'zgargan"
            text = news or "holat o'zgardi"

        out.append(
            NewsSignal(
                element=e["id"],
                name=e.get("web_name", "?"),
                team=teams.get(e["team"], "?"),
                text=text,
                chance=e.get("chance_of_playing_next_round"),
                status=status,
                owned=is_owned,
                kind=kind,
            )
        )
    out.sort(key=lambda n: (not n.owned, n.kind != "yangi"))
    return out


def ownership_trends(elements: list[dict], prev: dict[str, dict], teams: dict[int, str], top: int = 6):
    """Bir kunda egalik eng ko'p oshgan/tushgan o'yinchilar."""
    rows = []
    for e in elements:
        old = prev.get(str(e["id"]))
        if not old:
            continue
        now = float(e.get("selected_by_percent") or 0)
        delta = now - float(old.get("selected_by_percent") or 0)
        if abs(delta) < 0.3:
            continue
        rows.append({
            "name": e.get("web_name", "?"),
            "team": teams.get(e["team"], "?"),
            "own": round(now, 1),
            "delta": round(delta, 1),
            "net": e.get("transfers_in_event", 0) - e.get("transfers_out_event", 0),
        })
    rows.sort(key=lambda r: -r["delta"])
    return rows[:top], rows[-top:][::-1]
