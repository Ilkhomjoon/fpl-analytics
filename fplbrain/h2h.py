"""H2H — model tuzgan Free Hit tarkibi ekspertlar tarkibiga qarshi.

Eng halol taqqoslash shu: ikkala tomon ham **har tur noldan**, 100m ichida,
faqat shu tur uchun 15 lik tuzadi. Transferlar, hit va jamoa qiymati aralashmaydi
— faqat "kim yaxshiroq tanladi" degan savol qoladi.

Uch qism:

* `parse_lineup` / `resolve_names` — ekspertlar tarkibini matndan o'qish
  (ism xatolariga chidamli: «De Cupyer», «Grob», «Dewsburry-hall»);
* `score_lineup` — FPL qoidalari bo'yicha hisob: kapitan ikkilanadi, o'ynamasa
  vitse-kapitan; maydonga tushmagan o'yinchi zaxiradagi bilan almashadi
  (sxema qonuniy qolsa);
* `load` / `save` — har tur uchun bitta fayl: `data/store/h2h/gwNN.json`.

Tarkiblar **deadline'dan oldin** yoziladi va keyin o'zgartirilmaydi — aks holda
natijani bilib turib "tuzatish" vasvasasi paydo bo'ladi.
"""

from __future__ import annotations

import difflib
import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

GK, DEF, MID, FWD = 1, 2, 3, 4
# Avtoalmashtirishdan keyin ham saqlanishi shart bo'lgan eng kam sonlar
MIN_FORMATION = {GK: 1, DEF: 3, MID: 2, FWD: 1}


# ------------------------------------------------------------- ism moslash
def normalise(name: str) -> str:
    """«Groß» → «gross», «Dewsbury-Hall» → «dewsburyhall», «Gyökeres» → «gyokeres»."""
    text = (name or "").replace("ß", "ss").replace("ø", "o").replace("Ø", "o")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _keys(element: dict) -> set[str]:
    web, second = element.get("web_name") or "", element.get("second_name") or ""
    first = element.get("first_name") or ""
    keys = {normalise(web), normalise(second), normalise(f"{first} {second}")}
    # «ß» ni ko'pincha «b» deb yozishadi (Groß → Grob)
    for raw in (web, second):
        if "ß" in raw:
            keys.add(normalise(raw.replace("ß", "b")))
    keys.discard("")
    return keys


def resolve_names(names: list[str], elements: list[dict]) -> tuple[list[int], list[str]]:
    """Ismlarni o'yinchi ID lariga aylantiradi: (ID lar, topilmagan ismlar).

    Bir ismga bir nechta o'yinchi to'g'ri kelsa (masalan «Gabriel») — egaligi
    eng yuqorisi olinadi: ekspert tarkibida mashhuri nazarda tutiladi.
    Topilmagan ism uchun ID o'rnida 0 turadi.
    """
    active = [e for e in elements if e.get("status") != "u"]
    index: dict[str, list[dict]] = {}
    for e in active:
        for key in _keys(e):
            index.setdefault(key, []).append(e)

    def best(candidates: list[dict]) -> int:
        return max(candidates, key=lambda e: float(e.get("selected_by_percent") or 0))["id"]

    ids: list[int] = []
    missing: list[str] = []
    for name in names:
        key = normalise(name)
        found = index.get(key)
        if not found and key:
            prefixed = [e for k, v in index.items() for e in v
                        if len(key) >= 4 and (k.startswith(key) or key.startswith(k))
                        and len(k) >= 4]
            found = prefixed or None
        if not found and key:
            close = difflib.get_close_matches(key, list(index), n=1, cutoff=0.75)
            found = index.get(close[0]) if close else None
        if found:
            ids.append(best(found))
        else:
            ids.append(0)
            missing.append(name)
    return ids, missing


@dataclass
class Lineup:
    xi: list[int] = field(default_factory=list)
    bench: list[int] = field(default_factory=list)       # avtoalmashtirish tartibida
    captain: int = 0
    vice: int = 0
    names: dict[int, str] = field(default_factory=dict)
    expected: float = 0.0                                # model bahosi (kapitan bilan)

    def as_dict(self) -> dict:
        return {"xi": self.xi, "bench": self.bench, "captain": self.captain,
                "vice": self.vice, "expected": round(self.expected, 2),
                "names": {str(k): v for k, v in self.names.items()}}

    @classmethod
    def from_dict(cls, data: dict | None) -> "Lineup | None":
        if not data or not data.get("xi"):
            return None
        return cls(xi=list(data["xi"]), bench=list(data.get("bench") or []),
                   captain=int(data.get("captain") or 0), vice=int(data.get("vice") or 0),
                   names={int(k): v for k, v in (data.get("names") or {}).items()},
                   expected=float(data.get("expected") or 0.0))


_MARK = re.compile(r"\(\s*([cv])\s*\)", re.IGNORECASE)


def parse_lineup(text: str, elements: list[dict]) -> tuple[Lineup, list[str]]:
    """Matndan tarkib: `11 ism | 4 zaxira`, kapitan `(c)`, vitse `(v)`.

        Raya, Gabriel, Tarkowski, De Cuyper, Rogers, Tavernier (v),
        Dewsbury-Hall, Groß, Haaland (c), Barry, Evanilson
        | Dubravka, Konsa, Van Hecke, Gomez

    Ismlar vergul, nuqtali vergul yoki yangi qator bilan ajratiladi. Zaxira
    `|` dan keyin, avtoalmashtirish tartibida. Qaytaradi: (tarkib, xatolar).
    """
    errors: list[str] = []
    main, _, rest = text.partition("|")

    def split(part: str) -> list[str]:
        return [x.strip() for x in re.split(r"[,;\n]+", part) if x.strip()]

    raw_xi, raw_bench = split(main), split(rest)
    captain_name = vice_name = ""
    clean: list[str] = []
    for raw in raw_xi + raw_bench:
        mark = _MARK.search(raw)
        name = _MARK.sub("", raw).strip()
        if mark and mark.group(1).lower() == "c":
            captain_name = name
        elif mark:
            vice_name = name
        clean.append(name)

    ids, missing = resolve_names(clean, elements)
    errors += [f"topilmadi: {name}" for name in missing]
    by_id = {e["id"]: e for e in elements}
    lineup = Lineup(xi=ids[:len(raw_xi)], bench=ids[len(raw_xi):],
                    names={i: by_id[i].get("web_name", "?") for i in ids if i})
    lookup = dict(zip(clean, ids))
    lineup.captain = lookup.get(captain_name, 0)
    lineup.vice = lookup.get(vice_name, 0)

    if len(raw_xi) != 11:
        errors.append(f"asosiy tarkibda 11 emas, {len(raw_xi)} ta ism")
    if len(raw_bench) != 4:
        errors.append(f"zaxirada 4 emas, {len(raw_bench)} ta ism (`|` dan keyin)")
    chosen = [i for i in ids if i]
    if len(set(chosen)) != len(chosen):
        errors.append("bir o'yinchi ikki marta yozilgan")
    if not lineup.captain:
        errors.append("kapitan belgilanmagan — ism yoniga (c) qo'ying")
    counts = {p: 0 for p in MIN_FORMATION}
    for i in lineup.xi:
        if i:
            counts[by_id[i]["element_type"]] += 1
    if not missing and len(raw_xi) == 11 and (
            counts[GK] != 1 or any(counts[p] < MIN_FORMATION[p] for p in counts)):
        errors.append(f"sxema noto'g'ri: DRV {counts[GK]}, HIM {counts[DEF]}, "
                      f"YAR {counts[MID]}, HUJ {counts[FWD]}")
    return lineup, errors


# --------------------------------------------------------------- hisoblash
def score_lineup(lineup: Lineup, stats: dict[int, tuple[int, int]],
                 positions: dict[int, int]) -> dict:
    """FPL qoidalari bo'yicha tur ochkosi.

    `stats` — o'yinchi → (daqiqa, ochko); `positions` — o'yinchi → pozitsiya.

    * Maydonga tushmagan (0 daqiqa) asosiy o'yinchi zaxiradagi bilan, zaxira
      tartibida almashadi — faqat sxema qonuniy qolsa (kamida 3 HIM, 2 YAR,
      1 HUJ). Darvozabon faqat darvozabon bilan almashadi.
    * Kapitan ochkosi ikkilanadi; u o'ynamagan bo'lsa — vitse-kapitanniki.
    """
    def minutes(i: int) -> int:
        return stats.get(i, (0, 0))[0]

    def points(i: int) -> int:
        return stats.get(i, (0, 0))[1]

    field_ = list(lineup.xi)
    free = list(lineup.bench)
    subs: list[tuple[int, int]] = []
    for out in list(lineup.xi):
        if minutes(out) > 0:
            continue
        for candidate in free:
            if minutes(candidate) <= 0:
                continue
            is_gk = positions.get(out) == GK
            if (positions.get(candidate) == GK) != is_gk:
                continue
            trial = [candidate if x == out else x for x in field_]
            counts = {p: 0 for p in MIN_FORMATION}
            for x in trial:
                counts[positions.get(x, MID)] += 1
            if any(counts[p] < MIN_FORMATION[p] for p in counts):
                continue
            field_ = trial
            free.remove(candidate)
            subs.append((out, candidate))
            break

    armband = 0
    if lineup.captain in field_ and minutes(lineup.captain) > 0:
        armband = lineup.captain
    elif lineup.vice in field_ and minutes(lineup.vice) > 0:
        armband = lineup.vice
    total = sum(points(i) for i in field_) + (points(armband) if armband else 0)
    return {
        "points": total,
        "field": field_,
        "subs": subs,
        "armband": armband,
        "captain_points": points(armband) if armband else 0,
        "bench_points": sum(points(i) for i in free),
        "per_player": {i: points(i) for i in lineup.xi + lineup.bench},
    }


# ------------------------------------------------------------------ saqlash
def path_for(store_dir, gw: int) -> Path:
    return Path(store_dir) / "h2h" / f"gw{gw:02d}.json"


def load(store_dir, gw: int) -> dict:
    path = path_for(store_dir, gw)
    if not path.exists():
        return {"gw": gw}
    return json.loads(path.read_text(encoding="utf-8"))


def save(store_dir, gw: int, side: str, lineup: Lineup, note: str = "") -> Path:
    """`side` — "model" yoki "experts". Fayldagi boshqa tomon saqlanib qoladi."""
    record = load(store_dir, gw)
    record["gw"] = gw
    record[side] = dict(lineup.as_dict(), saved_at=time.time(), note=note)
    path = path_for(store_dir, gw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def all_records(store_dir) -> list[dict]:
    folder = Path(store_dir) / "h2h"
    if not folder.exists():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("gw*.json"))]


def model_lineup(built, event: int) -> Lineup:
    """`builder.build_squad` natijasidan tarkib. Vitse — 11 likdagi ikkinchi eng yuqori EV."""
    def ev(p) -> float:
        return p.ev.per_event.get(event, 0.0)

    ranked = sorted(built.xi, key=ev, reverse=True)
    captain = built.captain or (ranked[0] if ranked else None)
    vice = next((p for p in ranked if captain is None or p.element != captain.element), None)
    bench = sorted(built.bench, key=lambda p: (p.position == GK, -ev(p)))
    return Lineup(
        xi=[p.element for p in built.xi],
        bench=[p.element for p in bench],
        captain=captain.element if captain else 0,
        vice=vice.element if vice else 0,
        names={p.element: p.name for p in built.players},
        expected=sum(ev(p) for p in built.xi) + (ev(captain) if captain else 0.0),
    )
