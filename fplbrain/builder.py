"""Noldan jamoa tuzish — byudjet va FPL qoidalari ichida eng yaxshi 15 lik.

NEGA KERAK? Ikki holatda: **wildcard** ishlatganda va **H2H sinov** uchun —
algoritm tuzgan jamoani haqiqiy ekspertlar tuzgan jamoaga qarshi qo'yish.
Ikkinchisi modelning eng halol tekshiruvi: bir xil byudjet, bir xil qoidalar,
bir xil tur — kim ko'proq ochko oladi.

QOIDALAR (qattiq, buzilmaydi):

* 2 darvozabon, 5 himoyachi, 5 yarim himoyachi, 3 hujumchi — jami 15;
* bitta klubdan **eng ko'pi 3** o'yinchi;
* byudjet (odatda 100.0m) oshib ketmasligi shart.

MAQSAD FUNKSIYASI. "15 o'yinchining EV yig'indisi" **noto'g'ri** o'lchov
bo'lardi: zaxiradagi 4 kishi deyarli ochko keltirmaydi, lekin yig'indida
xuddi asosiy o'yinchidek turadi. Shuning uchun har tur uchun **asosiy 11
tanlanadi**, kapitan ikkilanadi, zaxira esa kichik vazn oladi — ya'ni
maqsad haqiqiy ochko hisobiga mos keladi.

USUL. Ochko maksimallashtirish — butun sonli optimallashtirish masalasi
(knapsack). Tashqi kutubxonasiz ikki bosqichda yechiladi:

1. **Ochko'z boshlang'ich** — har pozitsiyada narx birligiga to'g'ri
   keladigan EV bo'yicha saralab, byudjetga sig'adigan 15 lik yig'iladi;
2. **Mahalliy qidiruv** — bitta va ikkita almashtirishni sinab, maqsad
   funksiyasini oshiradigan har qanday o'zgarish qabul qilinadi. Yaxshilanish
   qolmaganda to'xtaydi.

Bu global optimumni **kafolatlamaydi**, lekin amalda unga juda yaqin keladi
va bir necha soniyada ishlaydi. Kafolat kerak bo'lsa MILP (PuLP + CBC)
kerak — u qo'shimcha o'rnatma talab qiladi.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .ev import DEF, FWD, GK, MID, PlayerEV
from .squad import Squad, SquadPlayer, best_eleven

# FPL qoidalari
SQUAD_SHAPE = {GK: 2, DEF: 5, MID: 5, FWD: 3}
MAX_PER_TEAM = 3
DEFAULT_BUDGET = 100.0

# Qidiruv chegaralari — tezlik uchun
POOL_PER_POSITION = 30      # har pozitsiyada nechta nomzod ko'riladi
MAX_PASSES = 12             # mahalliy qidiruvning eng ko'p aylanishi


@dataclass
class BuiltSquad:
    players: list[SquadPlayer]
    cost: float
    bank: float
    objective: float
    xi: list[SquadPlayer] = field(default_factory=list)
    bench: list[SquadPlayer] = field(default_factory=list)
    formation: tuple = (1, 4, 4, 2)
    captain: SquadPlayer | None = None
    xi_ev: float = 0.0
    passes: int = 0
    considered: int = 0

    @property
    def team_counts(self) -> dict[int, int]:
        counts: dict[int, int] = {}
        for p in self.players:
            counts[p.ev.profile.team] = counts.get(p.ev.profile.team, 0) + 1
        return counts

    def legal(self, budget: float = DEFAULT_BUDGET) -> bool:
        """Qoidalarga to'liq mosligini tekshiradi — hisobotda ham ko'rsatiladi."""
        shape: dict[int, int] = {}
        for p in self.players:
            shape[p.position] = shape.get(p.position, 0) + 1
        return (
            shape == SQUAD_SHAPE
            and max(self.team_counts.values(), default=0) <= MAX_PER_TEAM
            and self.cost <= budget + 1e-6
        )


def _as_squad_player(pev: PlayerEV) -> SquadPlayer:
    """Yangi olinadigan o'yinchi: sotish narxi = joriy narx."""
    return SquadPlayer(ev=pev, purchase_price=pev.profile.price,
                       selling_price=pev.profile.price)


def objective(players: list[SquadPlayer], events: list[int], cfg) -> float:
    """Gorizont bo'yicha kutilayotgan ochko — **kapitan bilan**.

    `squad_ev` dan farqi shuki, bu yerda kapitan ham hisobga olinadi.
    Kapitansiz maqsad funksiyasi premium o'yinchini past baholardi: uning
    asosiy qiymati aynan ikkilanishida.
    """
    total = 0.0
    for i, ev_id in enumerate(events):
        xi, bench, _, xi_ev = best_eleven(players, ev_id)
        cap = max((p.ev.per_event.get(ev_id, 0.0) for p in xi), default=0.0)
        bench_ev = sum(p.ev.per_event.get(ev_id, 0.0) for p in bench)
        total += (xi_ev + cap + cfg.bench_weight * bench_ev) * (
            cfg.horizon_decay ** i)
    return total


def candidate_pool(
    all_ev: list[PlayerEV],
    cfg,
    per_position: int = POOL_PER_POSITION,
    min_start: float = 0.45,
) -> dict[int, list[PlayerEV]]:
    """Har pozitsiya uchun nomzodlar: EV va **narx samarasi** bo'yicha.

    Ikki xil saralash ataylab: faqat EV bo'yicha olsak ro'yxat qimmat
    o'yinchilar bilan to'lib ketadi va byudjetga sig'maydi; faqat samara
    bo'yicha olsak arzon, lekin kuchsiz o'yinchilar bosib ketadi.
    Ikkalasidan ham olinadi.

    Zaxira o'rinlar uchun eng arzon "o'ynaydigan" o'yinchilar ham qo'shiladi:
    15 likning 4 tasi baribir o'tirmaydi, ularga pul sarflash isrof.
    """
    by_pos: dict[int, list[PlayerEV]] = {GK: [], DEF: [], MID: [], FWD: []}
    for pev in all_ev:
        pr = pev.profile
        if pr.position not in by_pos or pr.price <= 0:
            continue
        if pr.availability < 0.7 or pr.p_start < min_start:
            continue
        by_pos[pr.position].append(pev)

    out: dict[int, list[PlayerEV]] = {}
    for pos, items in by_pos.items():
        by_ev = sorted(items, key=lambda p: -p.horizon_ev)[:per_position]
        by_value = sorted(items, key=lambda p: -(p.horizon_ev / p.profile.price)
                          )[:per_position]
        # eng arzonlari — zaxira o'rinlari uchun
        by_price = sorted(items, key=lambda p: p.profile.price)[:8]
        seen, merged = set(), []
        for pev in by_ev + by_value + by_price:
            if pev.element not in seen:
                seen.add(pev.element)
                merged.append(pev)
        out[pos] = merged
    return out


def _greedy_seed(pool: dict[int, list[PlayerEV]], budget: float,
                 events: list[int], cfg) -> list[SquadPlayer] | None:
    """Byudjetga sig'adigan boshlang'ich 15 lik.

    Avval har pozitsiyaga eng yaxshi o'yinchilar olinadi; byudjet oshsa,
    eng "qimmat, lekin kam foydali" o'yinchi arzonrog'i bilan almashtiriladi.
    """
    first_event = events[0]

    def ev_of(pev: PlayerEV) -> float:
        return pev.per_event.get(first_event, 0.0)

    chosen: list[PlayerEV] = []
    counts: dict[int, int] = {}
    for pos, need in SQUAD_SHAPE.items():
        ranked = sorted(pool.get(pos, []), key=lambda p: -p.horizon_ev)
        taken = 0
        for pev in ranked:
            if taken >= need:
                break
            team = pev.profile.team
            if counts.get(team, 0) >= MAX_PER_TEAM:
                continue
            chosen.append(pev)
            counts[team] = counts.get(team, 0) + 1
            taken += 1
        if taken < need:
            return None                     # nomzod yetmadi

    # Byudjetga tushirish: eng past "EV / narx" li o'yinchini arzonrog'iga
    for _ in range(200):
        cost = sum(p.profile.price for p in chosen)
        if cost <= budget + 1e-9:
            break
        worst, replacement = None, None
        best_loss = None
        for pev in chosen:
            for alt in sorted(pool.get(pev.profile.position, []),
                              key=lambda p: p.profile.price):
                if alt.element in {c.element for c in chosen}:
                    continue
                if alt.profile.price >= pev.profile.price:
                    continue
                team_ok = (alt.profile.team == pev.profile.team
                           or counts.get(alt.profile.team, 0) < MAX_PER_TEAM)
                if not team_ok:
                    continue
                saved = pev.profile.price - alt.profile.price
                lost = max(0.0, ev_of(pev) - ev_of(alt))
                loss_rate = lost / saved if saved > 0 else float("inf")
                if best_loss is None or loss_rate < best_loss:
                    best_loss, worst, replacement = loss_rate, pev, alt
                break                        # har o'yinchi uchun eng arzoni yetadi
        if worst is None or replacement is None:
            return None
        counts[worst.profile.team] -= 1
        counts[replacement.profile.team] = counts.get(replacement.profile.team, 0) + 1
        chosen[chosen.index(worst)] = replacement

    if sum(p.profile.price for p in chosen) > budget + 1e-9:
        return None
    return [_as_squad_player(p) for p in chosen]


def _counts_of(players: list[SquadPlayer]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for p in players:
        counts[p.ev.profile.team] = counts.get(p.ev.profile.team, 0) + 1
    return counts


def _feasible(players: list[SquadPlayer], budget: float) -> bool:
    if sum(p.selling_price for p in players) > budget + 1e-9:
        return False
    return max(_counts_of(players).values(), default=0) <= MAX_PER_TEAM


def _pair_search(
    players: list[SquadPlayer],
    pool: dict[int, list[PlayerEV]],
    budget: float,
    events: list[int],
    cfg,
    best_score: float,
    fund_sources: int = 6,
    upgrades: int = 10,
    rounds: int = 3,
) -> tuple[list[SquadPlayer], float, int]:
    """Bir o'yinchini arzonlashtirib, ikkinchisini kuchaytirish.

    Qidiruv chegaralangan: pul manbai sifatida faqat eng past EV li bir
    nechta o'yinchi, kuchaytirish uchun esa har pozitsiyaning eng yaxshi
    nomzodlari ko'riladi. To'liq juftlik qidiruvi 15x15x30x30 bo'lardi va
    sahifani sekinlashtirardi.
    """
    first = events[0]
    considered = 0
    for _ in range(rounds):
        improved = False
        # eng kam foyda keltirayotganlar — pul manbai
        donors = sorted(players, key=lambda p: p.ev.per_event.get(first, 0.0)
                        )[:fund_sources]
        for donor in donors:
            cheaper = [a for a in pool.get(donor.position, [])
                       if a.profile.price < donor.selling_price
                       and a.element not in {p.element for p in players}]
            cheaper.sort(key=lambda p: -p.horizon_ev)
            for alt in cheaper[:6]:
                mid = list(players)
                mid[mid.index(donor)] = _as_squad_player(alt)
                bosh = sum(p.selling_price for p in mid)
                for idx, target in enumerate(mid):
                    if target.element == alt.element:
                        continue
                    better = [b for b in pool.get(target.position, [])
                              if b.profile.price > target.selling_price
                              and b.element not in {p.element for p in mid}]
                    better.sort(key=lambda p: -p.horizon_ev)
                    for up in better[:upgrades]:
                        narx = bosh - target.selling_price + up.profile.price
                        if narx > budget + 1e-9:
                            continue
                        trial = list(mid)
                        trial[idx] = _as_squad_player(up)
                        if not _feasible(trial, budget):
                            continue
                        considered += 1
                        score = objective(trial, events, cfg)
                        if score > best_score + 1e-9:
                            players, best_score, improved = trial, score, True
                            break
                    if improved:
                        break
                if improved:
                    break
            if improved:
                break
        if not improved:
            break
    return players, best_score, considered


def build_squad(
    all_ev: list[PlayerEV],
    events: list[int],
    cfg,
    budget: float = DEFAULT_BUDGET,
    max_passes: int = MAX_PASSES,
) -> BuiltSquad | None:
    """Byudjet ichida eng yaxshi 15 lik. Topilmasa `None`."""
    if not events:
        return None
    pool = candidate_pool(all_ev, cfg)
    players = _greedy_seed(pool, budget, events, cfg)
    if players is None:
        return None

    best_score = objective(players, events, cfg)
    considered = 0
    passes = 0

    for passes in range(1, max_passes + 1):
        improved = False
        for index, current in enumerate(players):
            others = {p.element for p in players}
            counts = _counts_of(players)
            spent = sum(p.selling_price for p in players)
            for alt in pool.get(current.position, []):
                if alt.element in others:
                    continue
                narx = spent - current.selling_price + alt.profile.price
                if narx > budget + 1e-9:
                    continue
                # klub chegarasi: chiqib ketayotgan o'yinchi hisobdan olinadi
                team_now = counts.get(alt.profile.team, 0)
                if alt.profile.team == current.ev.profile.team:
                    team_now -= 1
                if team_now >= MAX_PER_TEAM:
                    continue

                considered += 1
                trial = list(players)
                trial[index] = _as_squad_player(alt)
                score = objective(trial, events, cfg)
                if score > best_score + 1e-9:
                    players, best_score, improved = trial, score, True
                    break                    # birinchi yaxshilanish qabul qilinadi
        if not improved:
            break

    # Ikkitalik almashtirish. Bitta almashtirish ko'pincha yetmaydi: qimmat
    # o'yinchini olish uchun pul boshqa joydan chiqishi kerak. "Bir o'yinchini
    # arzonlashtirib, ikkinchisini kuchaytirish" — FPL da eng ko'p ishlatiladigan
    # harakat va u faqat juftlikda ko'rinadi.
    players, best_score, pair_considered = _pair_search(
        players, pool, budget, events, cfg, best_score)
    considered += pair_considered

    xi, bench, formation, xi_ev = best_eleven(players, events[0])
    captain = max(xi, key=lambda p: p.ev.per_event.get(events[0], 0.0),
                  default=None)
    cost = round(sum(p.selling_price for p in players), 1)
    return BuiltSquad(
        players=players,
        cost=cost,
        bank=round(budget - cost, 1),
        objective=round(best_score, 2),
        xi=xi,
        bench=bench,
        formation=formation,
        captain=captain,
        xi_ev=round(xi_ev, 2),
        passes=passes,
        considered=considered,
    )


def as_squad(built: BuiltSquad, event: int) -> Squad:
    """Tuzilgan jamoani oddiy `Squad` ga aylantiradi (boshqa modullar uchun)."""
    return Squad(players=built.players, bank=built.bank, event=event,
                 free_transfers=0, authenticated=False)
