"""Transfer dvigateli — kimni sotib, kimni olish kerakligini EV farqi bilan hisoblaydi."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from .config import Config
from .ev import PlayerEV
from .squad import Squad, SquadPlayer, squad_ev

MAX_PER_TEAM = 3


@dataclass
class TransferMove:
    out_players: list[SquadPlayer]
    in_players: list[PlayerEV]
    gain: float                 # hit hisobga olingan sof foyda
    raw_gain: float             # hit siz foyda
    hit: int                    # ochkodagi jarima
    cost: float                 # pul farqi (+ = qimmatlashadi)
    bank_after: float
    note: str = ""

    @property
    def n(self) -> int:
        return len(self.out_players)

    def describe(self) -> str:
        outs = " + ".join(f"{p.name} ({p.selling_price:.1f})" for p in self.out_players)
        ins = " + ".join(f"{p.profile.name} ({p.profile.price:.1f})" for p in self.in_players)
        return f"{outs} ➜ {ins}"


def _team_counts(players: list[SquadPlayer]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for p in players:
        counts[p.ev.profile.team] = counts.get(p.ev.profile.team, 0) + 1
    return counts


def candidate_pool(
    all_ev: list[PlayerEV],
    squad: Squad,
    cfg: Config,
    per_position: int = 14,
) -> dict[int, list[PlayerEV]]:
    """Har pozitsiya uchun eng istiqbolli nomzodlar."""
    owned = {p.element for p in squad.players}
    pool: dict[int, list[PlayerEV]] = {1: [], 2: [], 3: [], 4: []}
    for pev in all_ev:
        pr = pev.profile
        if pev.element in owned:
            continue
        if pr.availability < 0.6 or pr.p_start < 0.35:
            continue
        pool[pr.position].append(pev)
    for pos in pool:
        pool[pos].sort(key=lambda p: -p.horizon_ev)
        pool[pos] = pool[pos][:per_position]
    return pool


def _swap(squad: Squad, outs: list[SquadPlayer], ins: list[PlayerEV]) -> list[SquadPlayer]:
    out_ids = {p.element for p in outs}
    kept = [p for p in squad.players if p.element not in out_ids]
    new = kept + [
        SquadPlayer(ev=pev, purchase_price=pev.profile.price, selling_price=pev.profile.price)
        for pev in ins
    ]
    return new


def _legal(new_players: list[SquadPlayer]) -> bool:
    counts = _team_counts(new_players)
    return all(c <= MAX_PER_TEAM for c in counts.values())


def evaluate_moves(
    squad: Squad,
    all_ev: list[PlayerEV],
    events: list[int],
    cfg: Config,
    max_transfers: int = 2,
) -> list[TransferMove]:
    """Bitta va ikkita transferli variantlarni baholaydi va saralaydi."""
    base = squad_ev(squad, events, cfg)
    pool = candidate_pool(all_ev, squad, cfg)
    singles: list[TransferMove] = []

    for out in squad.players:
        budget = squad.bank + out.selling_price
        for pev in pool.get(out.position, []):
            if pev.profile.price > budget + 1e-9:
                continue
            new_players = _swap(squad, [out], [pev])
            if not _legal(new_players):
                continue
            new_squad = Squad(
                players=new_players,
                bank=round(budget - pev.profile.price, 1),
                event=squad.event,
                free_transfers=squad.free_transfers,
                chips_used=squad.chips_used,
            )
            raw = squad_ev(new_squad, events, cfg) - base
            hit = 0 if squad.free_transfers >= 1 else int(cfg.hit_cost)
            singles.append(
                TransferMove(
                    out_players=[out],
                    in_players=[pev],
                    raw_gain=round(raw, 2),
                    gain=round(raw - hit, 2),
                    hit=hit,
                    cost=round(pev.profile.price - out.selling_price, 1),
                    bank_after=new_squad.bank,
                )
            )

    singles.sort(key=lambda m: -m.gain)
    moves = list(singles)

    if max_transfers >= 2 and len(singles) >= 2:
        top = singles[:8]
        seen: set[tuple[int, int]] = set()
        for a, b in combinations(top, 2):
            if a.out_players[0].element == b.out_players[0].element:
                continue
            if a.in_players[0].element == b.in_players[0].element:
                continue
            key = tuple(sorted((a.in_players[0].element, b.in_players[0].element)))
            if key in seen:
                continue
            seen.add(key)
            outs = [a.out_players[0], b.out_players[0]]
            ins = [a.in_players[0], b.in_players[0]]
            budget = squad.bank + sum(p.selling_price for p in outs)
            spend = sum(p.profile.price for p in ins)
            if spend > budget + 1e-9:
                continue
            new_players = _swap(squad, outs, ins)
            if not _legal(new_players):
                continue
            new_squad = Squad(
                players=new_players,
                bank=round(budget - spend, 1),
                event=squad.event,
                free_transfers=squad.free_transfers,
                chips_used=squad.chips_used,
            )
            raw = squad_ev(new_squad, events, cfg) - base
            hit = int(cfg.hit_cost) * max(0, 2 - squad.free_transfers)
            moves.append(
                TransferMove(
                    out_players=outs,
                    in_players=ins,
                    raw_gain=round(raw, 2),
                    gain=round(raw - hit, 2),
                    hit=hit,
                    cost=round(spend - sum(p.selling_price for p in outs), 1),
                    bank_after=new_squad.bank,
                )
            )

    moves.sort(key=lambda m: -m.gain)
    return moves


def weak_links(
    squad: Squad,
    events: list[int],
    cfg: Config,
    all_ev: list[PlayerEV] | None = None,
) -> list[tuple[SquadPlayer, float, str]]:
    """Tarkibdagi eng zaif bo'g'inlar — nima uchun zaif ekani izohi bilan.

    Izoh mutlaq EV ga emas, **shu narx darajasidagi alternativalarga** nisbatan
    beriladi: "10.5 EV" o'zi hech narsa demaydi, "6.0m himoyachilar orasida
    o'rtachadan 4.2 EV past" — deydi.
    """
    # narx darajasi bo'yicha taqqoslash bazasi
    benchmark: dict[int, list[tuple[float, float]]] = {1: [], 2: [], 3: [], 4: []}
    for pev in all_ev or []:
        if pev.profile.availability >= 0.6 and pev.profile.p_start >= 0.5:
            benchmark[pev.profile.position].append((pev.profile.price, pev.horizon_ev))

    def peer_gap(p: SquadPlayer) -> float | None:
        """Shu pozitsiya va ±0.5m narx oralig'idagi eng yaxshi variantdan farq."""
        peers = [
            ev for price, ev in benchmark.get(p.position, [])
            if abs(price - p.selling_price) <= 0.5
        ]
        if len(peers) < 3:
            return None
        return max(peers) - p.ev.horizon_ev

    rows = []
    for p in squad.players:
        pr = p.ev.profile
        reasons = []
        if pr.status in ("i", "s", "u", "n"):
            reasons.append("o'ynamaydi")
        elif pr.availability < 0.75:
            reasons.append(f"jarohat shubhasi ({pr.availability*100:.0f}%)")
        elif pr.availability < 1.0:
            reasons.append("yengil shubha")
        if pr.p_start < 0.55:
            reasons.append(f"asosiy tarkib ehtimoli {pr.p_start*100:.0f}%")

        gap = peer_gap(p)
        if gap is not None and gap >= 3.0:
            reasons.append(f"shu narxdagi eng yaxshisidan {gap:.1f} EV orqada")

        fixtures_ev = [p.ev.per_event.get(e, 0.0) for e in events]
        if fixtures_ev and max(fixtures_ev) < 3.0:
            reasons.append("kelgusi turlarning hammasi zaif")

        if not reasons:
            reasons.append("tarkibdagi eng past EV, lekin jiddiy muammo yo'q")
        rows.append((p, p.ev.horizon_ev, ", ".join(reasons)))
    rows.sort(key=lambda r: r[1])
    return rows
