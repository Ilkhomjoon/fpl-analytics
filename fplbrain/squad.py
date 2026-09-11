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
    transfers_made: int = 0           # shu turda ALLAQACHON qilingan transferlar
    unlimited_transfers: bool = False  # wildcard/free hit faol
    # FPL ning o'z javobidan olingan xom qiymatlar (login bo'lganda)
    transfers_status: str = ""        # "free" yoki "cost" — keyingi transfer tekinmi
    transfers_cost: int = 0           # shu turda allaqachon olingan jarima
    api_value: float = 0.0            # FPL ning o'zi hisoblagan jamoa qiymati
    override_used: bool = False       # FT config dan olindi (serverdan emas)

    @property
    def value(self) -> float:
        """Jamoa qiymati — FPL ning o'z raqami bilan bir xil bo'lishi kerak.

        FPL `value` maydonini beradi, lekin unga bank kiradimi-yo'qmi
        hujjatlashtirilmagan. Taxmin qilish o'rniga **tekshiramiz**: o'zimiz
        hisoblagan sotish narxlari yig'indisi bilan solishtirib, qaysi
        talqin to'g'ri kelishini aniqlaymiz.
        """
        sotish = sum(p.selling_price for p in self.players)
        hisob = round(sotish + self.bank, 1)
        if not self.api_value:
            return hisob
        # Bank kirmagan bo'lsa — qo'shamiz; kirgan bo'lsa — shundayligicha
        banksiz = abs(self.api_value - sotish)
        bank_bilan = abs(self.api_value - (sotish + self.bank))
        return round(self.api_value + (self.bank if banksiz <= bank_bilan else 0.0), 1)

    def by_element(self, element: int) -> SquadPlayer | None:
        return next((p for p in self.players if p.element == element), None)


# --------------------------------------------------------------- eng yaxshi 11
# Tanlash mezoni faqat EV emas. Sabab: EV o'rtacha qiymat, asosiy 11 lik esa
# BIR marta o'ynaladi. 4.0 EV beradigan mustahkam asosiy tarkib o'yinchisi bilan
# 4.2 EV beradigan, lekin tarkibga tushishi shubhali o'yinchi orasida
# birinchisi afzal — chunki ikkinchisi 0 ochko olib qolishi mumkin, zaxira esa
# uni to'liq qoplamaydi (avtoalmashtirish faqat o'ynamagan holda ishlaydi).
RISK_AVERSION = 0.35      # config.xi_risk_aversion bilan almashtirsa bo'ladi
NAILED_START = 0.75       # mustahkam o'rin
FRINGE_START = 0.55       # shubhali o'rin
SWAP_TOLERANCE = 1.2      # EV farqi shundan kichik bo'lsa, mustahkamlik ustun turadi


def _p_start(player: SquadPlayer) -> float:
    value = getattr(player.ev.profile, "p_start", 1.0)
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 1.0


def selection_score(
    player: SquadPlayer, event: int, ev_of=None, risk_aversion: float = RISK_AVERSION
) -> float:
    """EV ni "o'ynash aniqligi" bilan jazolangan tanlov bali.

    p_start = 0.95 -> EV ning 98% i; p_start = 0.50 -> 82% i.
    Bu ataylab ikki marta hisoblash: EV ichida ham p_appear bor. Farqi shundaki,
    EV o'rtachani, bu bal esa **xavfdan qochishni** ifodalaydi.
    """
    if ev_of is None:
        ev_of = lambda p: p.ev.per_event.get(event, 0.0)  # noqa: E731
    return ev_of(player) * (1.0 - risk_aversion * (1.0 - _p_start(player)))


def _nailed_swaps(
    xi: list[SquadPlayer],
    bench: list[SquadPlayer],
    ev_of,
    nailed: float = NAILED_START,
    fringe: float = FRINGE_START,
    tolerance: float = SWAP_TOLERANCE,
) -> list[tuple[SquadPlayer, SquadPlayer]]:
    """Zaxiradagi mustahkam o'yinchini 11 likdagi shubhali o'yinchi bilan almashtirish.

    Faqat bir xil pozitsiya ichida — shunda sxema buzilmaydi. Chegara: EV farqi
    `tolerance` dan kichik bo'lsa. Ya'ni sezilarli EV ustunligi bo'lsa,
    shubhali o'yinchi baribir 11 likda qoladi.
    """
    swaps: list[tuple[SquadPlayer, SquadPlayer]] = []
    xi_live = list(xi)
    for candidate in sorted(bench, key=ev_of, reverse=True):
        if _p_start(candidate) < nailed:
            continue
        weakest = None
        for member in xi_live:
            if member.position != candidate.position or _p_start(member) >= fringe:
                continue
            if ev_of(member) - ev_of(candidate) >= tolerance:
                continue
            if weakest is None or ev_of(member) < ev_of(weakest):
                weakest = member
        if weakest is not None:
            xi_live[xi_live.index(weakest)] = candidate
            swaps.append((weakest, candidate))
    return swaps


def best_eleven(
    players: list[SquadPlayer], event: int, ev_of=None, risk_aversion: float | None = None
) -> tuple[list[SquadPlayer], list[SquadPlayer], tuple[int, int, int, int], float]:
    """Sxemalar bo'yicha brute-force: (asosiy 11, zaxira, sxema, EV).

    Tanlov `selection_score` bo'yicha, qaytariladigan yig'indi esa **xom EV** —
    boshqa bo'limlar (shablon bilan solishtirish, chip hisobi) shu birlikda
    ishlaydi, shuning uchun uni o'zgartirmaymiz.
    """
    if ev_of is None:
        ev_of = lambda p: p.ev.per_event.get(event, 0.0)  # noqa: E731
    lam = RISK_AVERSION if risk_aversion is None else risk_aversion
    score_of = lambda p: selection_score(p, event, ev_of, lam)  # noqa: E731

    by_pos: dict[int, list[SquadPlayer]] = {GK: [], DEF: [], MID: [], FWD: []}
    for p in players:
        by_pos[p.position].append(p)
    for pos in by_pos:
        by_pos[pos].sort(key=score_of, reverse=True)

    best: tuple[list[SquadPlayer], tuple[int, int, int, int], float] | None = None
    for form in FORMATIONS:
        need = dict(zip((GK, DEF, MID, FWD), form))
        if any(len(by_pos[pos]) < n for pos, n in need.items()):
            continue
        xi = [p for pos, n in need.items() for p in by_pos[pos][:n]]
        total = sum(score_of(p) for p in xi)
        if best is None or total > best[2]:
            best = (xi, form, total)

    if best is None:                      # to'liq bo'lmagan tarkib uchun zaxira yechim
        xi = sorted(players, key=score_of, reverse=True)[:11]
        return xi, [p for p in players if p not in xi], (1, 4, 4, 2), sum(ev_of(p) for p in xi)

    xi, form, _ = best
    xi_ids = {p.element for p in xi}
    bench = [p for p in players if p.element not in xi_ids]

    # Mustahkam o'rin himoyasi: shubhali o'yinchi arzimas EV ustunligi bilan
    # 11 likka kirib qolmasin.
    for out_player, in_player in _nailed_swaps(xi, bench, ev_of):
        xi[xi.index(out_player)] = in_player
        bench[bench.index(in_player)] = out_player

    bench.sort(key=lambda p: (p.position == GK, -score_of(p)))
    return xi, bench, form, round(sum(ev_of(p) for p in xi), 3)


def bench_reason(player: SquadPlayer, event: int, xi_min_ev: float) -> str:
    """Nima uchun zaxirada — bir qatorli izoh.

    Bu mantiq tanlovga tegishli, matn yasashga emas: uni Telegram hisoboti ham,
    web sahifa ham bir xil ishlatadi.
    """
    profile = player.ev.profile
    if not player.ev.fixtures.get(event):
        return "jamoasi bu turda o'ynamaydi"
    if profile.availability <= 0.05:
        return profile.news or "o'ynamaydi"
    if profile.availability < 0.8:
        return profile.news or f"o'ynash ehtimoli {profile.availability * 100:.0f}%"
    if profile.p_start < FRINGE_START:
        return f"asosiy tarkib ehtimoli {profile.p_start * 100:.0f}%"
    gap = xi_min_ev - player.ev.per_event.get(event, 0.0)
    if gap > 0:
        return f"11 likdagi eng zaifdan {gap:.1f} ochko past"
    return "sxemaga sig'madi"


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


def estimate_free_transfers(history: dict, event: int) -> int:
    """FT ni tarixdan taxminlaydi (maks. 5).

    Muhim: **shu turda qilingan transferlar ham hisobga olinadi.** Avval
    oxirida yana bitta FT qo'shilardi — natijada transferlar allaqachon
    ishlatilgan bo'lsa ham "2 FT bor" deb ko'rsatardi.
    """
    rows = {r.get("event"): r for r in history.get("current", []) if r.get("event")}
    chips = {c.get("event"): c.get("name") for c in history.get("chips", [])}
    ft = 1
    for ev in range(1, max(1, int(event or 1)) + 1):
        if ev > 1:
            ft = min(5, ft + 1)             # har tur boshida bitta qo'shiladi
        # wildcard/free hit ishlatilgan turda FT sarflanmaydi
        if chips.get(ev) in ("wildcard", "freehit"):
            continue
        made = (rows.get(ev) or {}).get("event_transfers", 0) or 0
        ft = max(0, ft - int(made))
    return max(0, min(5, ft))


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
        api_value = (transfers_info.get("value") or 0) / 10.0
        # FT ni aniqlash. `limit` va `made` ning ma'nosi FPL hujjatlarida
        # yozilmagan va ular har doim ham kutilgandek to'ldirilmaydi.
        # `status` esa ANIQ: "cost" — keyingi transfer ochko turadi, ya'ni
        # tekin transfer QOLMAGAN. Shuning uchun u hal qiluvchi bo'ladi.
        limit = transfers_info.get("limit")
        made = int(transfers_info.get("made") or 0)
        status = str(transfers_info.get("status") or "").lower()
        cost_taken = int(transfers_info.get("cost") or 0)
        transfers_made = made
        if limit is None:                       # wildcard/free hit — cheksiz
            unlimited = True
            free_transfers = 15
        else:
            unlimited = False
            free_transfers = max(0, int(limit) - made)
            if status == "cost":
                free_transfers = 0              # server aniq aytdi: tekin yo'q
            elif status == "free" and free_transfers == 0:
                free_transfers = 1              # aksincha holat ham bo'lishi mumkin
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
        api_value = ((picks_data.get("entry_history", {}) or {}).get("value", 0) or 0) / 10.0
        free_transfers = estimate_free_transfers(entry_history, event)
        transfers_made = int(
            (picks_data.get("entry_history", {}) or {}).get("event_transfers", 0) or 0)
        unlimited = False
        status, cost_taken = "", 0
        chips_available = []
        authenticated = False

        def get_buy(p):
            return purchase.get(p["element"], elements[p["element"]]["now_cost"] / 10.0)

        def get_sell(p):
            return selling_price(get_buy(p), elements[p["element"]]["now_cost"])

    # Qo'lda berilgan FT — bu **bilmaganda ishlatiladigan zaxira**, serverning
    # javobini tuzatadigan qiymat emas. Avval u oxirida turardi va my-team dan
    # kelgan aniq raqamni bosib ketardi: `config.yaml` da bir marta yozilgan
    # eski qiymat login qilingandan keyin ham kuchda qolardi.
    override = int(getattr(cfg, "free_transfers_override", 0) or 0) if cfg else 0
    override_used = False
    if override and not authenticated:
        free_transfers = override
        override_used = True

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
        free_transfers=free_transfers if unlimited else max(0, min(5, free_transfers)),
        chips_used=[c["name"] for c in entry_history.get("chips", [])],
        chips_history=entry_history.get("chips", []) or [],
        chips_available=chips_available,
        authenticated=authenticated,
        transfers_made=transfers_made,
        unlimited_transfers=unlimited,
        transfers_status=status,
        transfers_cost=cost_taken,
        api_value=api_value,
        override_used=override_used,
    )
