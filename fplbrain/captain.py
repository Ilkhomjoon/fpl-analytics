"""Kapitan tanlash — EV, "haul" ehtimoli va raqiblar egaligini (EO) hisobga oladi."""

from __future__ import annotations

from dataclasses import dataclass

from .ev import GK
from .squad import Squad, SquadPlayer, best_eleven


@dataclass
class CaptainOption:
    player: SquadPlayer
    ev: float
    p_haul: float
    p_return: float
    eo: float                 # raqiblar orasida kapitanlik ulushi (%)
    score: float
    verdict: str

    @property
    def name(self) -> str:
        return self.player.name


def rank_captains(
    squad: Squad,
    event: int,
    captain_eo: dict[int, float] | None = None,
    strategy: str = "balanced",
    limit: int = 5,
) -> list[CaptainOption]:
    """strategy: 'safe' (o'rinni himoya qilish), 'balanced', 'aggressive' (o'rinni ko'tarish)."""
    captain_eo = captain_eo or {}
    xi, _, _, _ = best_eleven(squad.players, event)
    options: list[CaptainOption] = []

    # Darvozabon kapitan bo'lmaydi: uning ochkosi tepasi past (maks ~10),
    # kapitanlikdan kutilayotgan foyda esa aynan "tepasi" dan keladi.
    candidates = [p for p in xi if p.position != GK] or xi

    for p in candidates:
        ev = p.ev.per_event.get(event, 0.0)
        fxs = p.ev.fixtures.get(event, [])
        p_haul = 1 - _prod(1 - f.p_haul for f in fxs) if fxs else 0.0
        p_return = 1 - _prod(1 - f.p_return for f in fxs) if fxs else 0.0
        eo = captain_eo.get(p.element, 0.0)

        # differensial bonus/jarima: ommaviy kapitan xavfsiz, lekin o'rin ko'tarmaydi
        if strategy == "safe":
            adj = 0.020 * eo
        elif strategy == "aggressive":
            adj = -0.018 * eo + 3.0 * p_haul
        else:
            adj = 0.006 * eo + 1.2 * p_haul
        score = ev + adj

        if eo >= 40 and ev >= 4.5:
            verdict = "xavfsiz — raqiblarning ko'pchiligida bor"
        elif eo <= 12 and p_haul >= 0.18:
            verdict = "differensial — yutsa katta o'rin beradi"
        elif ev < 4.0:
            verdict = "zaif variant"
        else:
            verdict = "muvozanatli"

        options.append(
            CaptainOption(p, round(ev, 2), round(p_haul, 3), round(p_return, 3),
                          round(eo, 1), round(score, 2), verdict)
        )

    options.sort(key=lambda o: -o.score)
    return options[:limit]


def _prod(values) -> float:
    out = 1.0
    for v in values:
        out *= v
    return out
