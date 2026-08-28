"""Mening jamoam: tarkib, eng yaxshi 11 lik, sotish narxi va erkin transferlar."""

from __future__ import annotations

from dataclasses import dataclass, field


from .ev import DEF, FWD, GK, MID, PlayerEV

# Ruxsat etilgan sxemalar (GK, DEF, MID, FWD)
FORMATIONS = [
    (1, 3, 4, 3), (1, 3, 5, 2), (1, 4, 4, 2), (1, 4, 3, 3),
    (1, 4, 5, 1), (1, 5, 3, 2), (1, 5, 4, 1), (1, 5, 2, 3),
    (1, 3, 3, 4),
]


@dataclass
class SquadPlayer:
    ev: PlayerEV
    purchase_price: float
    selling_price: float
    is_captain: bool = False
    is_vice: bool = False
    pick_position: int = 0

    @property
    def element(self) -> int:
        return self.ev.element

    @property
    def position(self) -> int:
        return self.ev.profile.position

    @property
    def name(self) -> str:
        return self.ev.profile.name


@dataclass
class Squad:
    players: list[SquadPlayer]
    bank: float
    event: int
    free_transfers: int = 1
    chips_used: list[str] = field(default_factory=list)
    chips_history: list[dict] = field(default_factory=list)   # [{"name":..., "event":...}]
    chips_available: list[str] = field(default_factory=list)
    authenticated: bool = False       # ma'lumot my-team dan olindimi (aniq) yoki taxminmi

    @property
    def value(self) -> float:
        return round(sum(p.selling_price for p in self.players) + self.bank, 1)

    def by_element(self, element: int) -> SquadPlayer | None:
        return next((p for p in self.players if p.element == element), None)


# --------------------------------------------------------------- eng yaxshi 11
def best_eleven(
    players: list[SquadPlayer], event: int, ev_of=None
) -> tuple[list[SquadPlayer], list[SquadPlayer], tuple[int, int, int, int], float]:
    """Sxemalar bo'yicha brute-force: (asosiy 11, zaxira, sxema, EV)."""
    if ev_of is None:
        ev_of = lambda p: p.ev.per_event.get(event, 0.0)  # noqa: E731

    by_pos: dict[int, list[SquadPlayer]] = {GK: [], DEF: [], MID: [], FWD: []}
    for p in players:
        by_pos[p.position].append(p)
    for pos in by_pos:
        by_pos[pos].sort(key=ev_of, reverse=True)

    best: tuple[list[SquadPlayer], tuple[int, int, int, int], float] | None = None
    for form in FORMATIONS:
        need = dict(zip((GK, DEF, MID, FWD), form))
        if any(len(by_pos[pos]) < n for pos, n in need.items()):
            continue
        xi = [p for pos, n in need.items() for p in by_pos[pos][:n]]
        total = sum(ev_of(p) for p in xi)
        if best is None or total > best[2]:
            best = (xi, form, total)

    if best is None:                      # to'liq bo'lmagan tarkib uchun zaxira yechim
        xi = sorted(players, key=ev_of, reverse=True)[:11]
        return xi, [p for p in players if p not in xi], (1, 4, 4, 2), sum(ev_of(p) for p in xi)

    xi, form, total = best
    xi_ids = {p.element for p in xi}
    bench = sorted(
        [p for p in players if p.element not in xi_ids],
        key=lambda p: (p.position == GK, -ev_of(p)),
    )
    return xi, bench, form, round(total, 3)


def squad_ev(squad: Squad, events: list[int], cfg) -> float:
    """Butun tarkifning gorizont bo'yicha EV si: asosiy 11 + zaxira (kichik vazn bilan)."""
    total = 0.0
    for i, ev_id in enumerate(events):
        xi, bench, _, xi_ev = best_eleven(squad.players, ev_id)
        bench_ev = sum(p.ev.per_event.get(ev_id, 0.0) for p in bench)
        total += (xi_ev + cfg.bench_weight * bench_ev) * (cfg.horizon_decay ** i)
    return round(total, 3)


# ----------------------------------------------------- xarid/sotish narxlari
def reconstruct_prices(
    client, entry_id: int, current_picks: list[dict], elements: dict[int, dict]
) -> dict[int, float]:
    """Transfer tarixidan har bir o'yinchining xarid narxini tiklaydi (0.1m aniqlikda)."""
    purchase: dict[int, float] = {}
    try:
        transfers = client.entry_transfers(entry_id) or []
    except Exception:
        transfers = []
    # eng oxirgi xarid narxi ustun (transferlar yangidan eskiga qarab keladi)
    for t in reversed(transfers):
        purchase[t["element_in"]] = t["element_in_cost"] / 10.0

    for pick in current_picks:
        el = pick["element"]
        if el not in purchase:
            # GW1 dan beri saqlanib qolgan: joriy narxdan mavsum o'zgarishini ayiramiz
            e = elements.get(el)
            if e:
                purchase[el] = (e["now_cost"] - e.get("cost_change_start", 0)) / 10.0
    return purchase


def selling_price(purchase: float, now_cost_tenths: int) -> float:
    """FPL qoidasi: o'sishning yarmi (0.1m ga yaxlitlangan, pastga) qaytariladi."""
    now = now_cost_tenths / 10.0
    if now <= purchase:
        return round(now, 1)
    rise_tenths = round((now - purchase) * 10)
    return round(purchase + (rise_tenths // 2) / 10.0, 1)


def estimate_free_transfers(history: dict, last_event: int) -> int:
    """FT ni tarixdan taxminlaydi (maks. 5). Aniq qiymatni config da qo'lda berish mumkin."""
    ft = 1
    for row in history.get("current", []):
        ev = row.get("event")
        if ev is None or ev > last_event:
            continue
        if ev == 1:
            ft = 1
            continue
        ft = min(5, ft + 1)
        made = row.get("event_transfers", 0) or 0
        # wildcard/free hit ishlatilgan bo'lsa FT sarflanmaydi
        chip = next(
            (c["name"] for c in history.get("chips", []) if c.get("event") == ev), None
        )
        if chip in ("wildcard", "freehit"):
            continue
        ft = max(0, ft - made)
    return max(1, min(5, ft + 1))


# ------------------------------------------------------------------- yuklash
def load_squad(
    client,
    cfg,
    entry_id: int,
    event: int,
    ev_by_element: dict[int, PlayerEV],
    elements: dict[int, dict],
) -> Squad:
    entry_history = client.entry_history(entry_id)
    my_team = client.my_team(entry_id) if hasattr(client, "my_team") else None

    if my_team and my_team.get("picks"):
        # --- aniq yo'l: shaxsiy endpoint sotish narxi va FT ni to'g'ridan-to'g'ri beradi
        picks = my_team["picks"]
        transfers_info = my_team.get("transfers") or {}
        bank = (transfers_info.get("bank") or 0) / 10.0
        limit = transfers_info.get("limit")
        free_transfers = 1 if limit is None else int(limit)
        chips_available = [
            c["name"] for c in (my_team.get("chips") or [])
            if c.get("status_for_entry") == "available"
        ]
        authenticated = True
        get_buy = lambda p: (p.get("purchase_price", 0) or 0) / 10.0        # noqa: E731
        get_sell = lambda p: (p.get("selling_price", 0) or 0) / 10.0        # noqa: E731
    else:
        # --- ochiq yo'l: narxlar transfer tarixidan tiklanadi, FT taxminlanadi
        picks_data = client.entry_picks(entry_id, event)
        picks = picks_data.get("picks", [])
        purchase = reconstruct_prices(client, entry_id, picks, elements)
        bank = (picks_data.get("entry_history", {}) or {}).get("bank", 0) / 10.0
        free_transfers = estimate_free_transfers(entry_history, event)
        chips_available = []
        authenticated = False

        def get_buy(p):
            return purchase.get(p["element"], elements[p["element"]]["now_cost"] / 10.0)

        def get_sell(p):
            return selling_price(get_buy(p), elements[p["element"]]["now_cost"])

    if cfg is not None and getattr(cfg, "free_transfers_override", 0):
        free_transfers = int(cfg.free_transfers_override)

    players: list[SquadPlayer] = []
    for pick in picks:
        el = pick["element"]
        pev = ev_by_element.get(el)
        if pev is None:
            continue
        buy = get_buy(pick) or elements[el]["now_cost"] / 10.0
        sell = get_sell(pick) or buy
        players.append(
            SquadPlayer(
                ev=pev,
                purchase_price=buy,
                selling_price=sell,
                is_captain=pick.get("is_captain", False),
                is_vice=pick.get("is_vice_captain", False),
                pick_position=pick.get("position", 0),
            )
        )

    return Squad(
        players=players,
        bank=bank,
        event=event,
        free_transfers=max(0, min(5, free_transfers)),
        chips_used=[c["name"] for c in entry_history.get("chips", [])],
        chips_history=entry_history.get("chips", []) or [],
        chips_available=chips_available,
        authenticated=authenticated,
    )
