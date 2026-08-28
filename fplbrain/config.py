"""Sozlamalar: config.yaml + muhit o'zgaruvchilari (.env / GitHub Secrets)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.yaml"
DEFAULT_ENV = ROOT / ".env"


def load_env_file(path: Path = DEFAULT_ENV) -> int:
    """`.env` faylini o'qib, muhit o'zgaruvchilariga qo'yadi.

    Qoidalar:
      - `KEY=qiymat` — birinchi `=` bo'yicha ajratiladi, shuning uchun qiymat
        ichidagi `=` (cookie da ko'p uchraydi) buzilmaydi;
      - qiymatdagi `;` va bo'sh joylar saqlanadi — cookie aynan shunday;
      - satr boshidagi `#` izoh, `export KEY=...` ham qabul qilinadi;
      - allaqachon o'rnatilgan muhit o'zgaruvchisi ustunroq (CI ni buzmaslik uchun).

    Qaytaradi: nechta o'zgaruvchi qo'yilgani.
    """
    if not path.exists():
        return 0
    applied = 0
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        # Faqat butun qiymatni o'rab turgan qo'shtirnoqni olib tashlaymiz
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key in os.environ:            # $env: bilan berilgani ustun turadi
            continue
        os.environ[key] = value
        applied += 1
    return applied


@dataclass
class Config:
    # --- shaxsiy ma'lumotlar ---
    entry_id: int = 0                      # FPL jamoa ID (URL dagi raqam)
    mini_league_ids: list[int] = field(default_factory=list)
    fpl_cookie: str = ""                   # brauzerdan olingan sessiya cookie (ixtiyoriy)
    free_transfers_override: int = 0       # 0 = avtomatik aniqlansin

    # --- telegram ---
    telegram_token: str = ""
    telegram_chat_id: str = ""             # shaxsiy kanal: -100... yoki @username

    # --- model parametrlari ---
    horizon: int = 5                       # necha GW oldinga qaraymiz
    horizon_decay: float = 0.90            # har GW uchun ishonch koeffitsiyenti
    bench_weight: float = 0.14             # zaxiradagi o'yinchi EV ning qanchasi hisobga olinadi
    hit_cost: float = 4.0                  # qo'shimcha transfer narxi
    min_gain_to_suggest: float = 1.5       # shundan kam foyda bersa, transfer taklif qilinmaydi

    # shrinkage (kam o'yin o'ynagan o'yinchini prior tomon tortish), 90 daqiqalik birlikda
    shrink_attack_90s: float = 6.0
    shrink_defcon_90s: float = 5.0
    shrink_bonus_90s: float = 8.0
    prior_season_weight: float = 0.55      # o'tgan mavsum ma'lumotining boshlang'ich vazni
    minutes_prior_matches: float = 2.0     # daqiqalar priori necha o'yinga teng dalil sanaladi
    detail_players: int = 130              # nechta o'yinchi uchun batafsil tarix yuklanadi

    # jamoa kuchi
    home_base_goals: float = 1.55
    away_base_goals: float = 1.22
    team_form_shrink_matches: float = 6.0  # joriy mavsum xG ma'lumotiga ishonch

    # --- raqiblar tahlili ---
    overall_league_id: int = 314           # "Overall" klassik liga
    rank_window_pct: float = 1.0           # mendan necha % tepa/pastdagi jamoalar
    rank_window_sample: int = 25           # har tomondan nechta jamoa olinadi
    top_n_managers: int = 100              # top-N tahlili
    max_entry_fetch: int = 220             # bir ishga tushishda maks. jamoa yuklash

    # --- hisobot ---
    timezone: str = "Asia/Tashkent"
    language: str = "uz"
    deadline_report_hours: float = 30.0    # deadline'gacha shuncha soat qolganda to'liq hisobot
    max_transfer_suggestions: int = 4
    max_captain_options: int = 4

    # --- texnik ---
    cache_dir: Path = ROOT / "data" / "cache"
    store_dir: Path = ROOT / "data" / "store"
    cache_ttl_seconds: int = 1800
    request_delay: float = 0.35            # so'rovlar orasidagi pauza (FPL ni bezovta qilmaslik)
    max_workers: int = 4

    @classmethod
    def load(cls, path: str | Path | None = None, env_file: Path | None = None) -> "Config":
        load_env_file(env_file or DEFAULT_ENV)
        cfg = cls()
        p = Path(path) if path else DEFAULT_CONFIG
        data: dict[str, Any] = {}
        if p.exists():
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        for key, value in data.items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)

        # Maxfiy ma'lumotlar faqat muhitdan olinadi (repo ichiga tushmaydi)
        cfg.telegram_token = os.getenv("TELEGRAM_TOKEN", cfg.telegram_token)
        cfg.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", cfg.telegram_chat_id)
        cfg.fpl_cookie = os.getenv("FPL_COOKIE", cfg.fpl_cookie)
        if os.getenv("FPL_ENTRY_ID"):
            cfg.entry_id = int(os.environ["FPL_ENTRY_ID"])
        if os.getenv("FPL_LEAGUE_IDS"):
            cfg.mini_league_ids = [
                int(x) for x in os.environ["FPL_LEAGUE_IDS"].replace(" ", "").split(",") if x
            ]

        cfg.cache_dir = Path(cfg.cache_dir)
        cfg.store_dir = Path(cfg.store_dir)
        cfg.cache_dir.mkdir(parents=True, exist_ok=True)
        cfg.store_dir.mkdir(parents=True, exist_ok=True)
        return cfg
