"""FPL ochiq API klienti — disk keshi, qayta urinish va oqilona so'rov tezligi bilan."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Iterable

import requests

log = logging.getLogger(__name__)

BASE = "https://fantasy.premierleague.com/api"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
# Windows fayl nomida ruxsat etilmagan belgilar
SAFE_NAME_RE = re.compile(r'[^A-Za-z0-9._-]+')


class FplApiError(RuntimeError):
    pass


class AuthError(FplApiError):
    """401/403 — sessiya yaroqsiz yoki bot himoyasi to'sdi."""

    def __init__(self, status: int, body: str, url: str) -> None:
        self.status = status
        self.body = body or ""
        self.url = url
        super().__init__(f"{status}: {url}")

    @property
    def blocked_by_bot_protection(self) -> bool:
        """Cloudflare/DataDome to'sganini javob matnidan aniqlaydi."""
        haystack = self.body.lower()
        return any(
            marker in haystack
            for marker in ("datadome", "cloudflare", "cf-ray", "captcha",
                           "attention required", "just a moment")
        )

    def explain(self) -> str:
        if self.blocked_by_bot_protection:
            return (
                "Bot himoyasi (Cloudflare/DataDome) to'sdi — sessiya emas, so'rovning "
                "o'zi rad etildi. Cookie boshqa qurilma yoki IP dan olingan bo'lsa "
                "shunday bo'ladi."
            )
        return (
            "Sessiya qabul qilinmadi — cookie eskirgan, chala nusxalangan yoki "
            "logout/parol almashtirishdan keyin bekor bo'lgan."
        )


class FplClient:
    """Ochiq (login talab qilmaydigan) FPL endpointlari uchun klient."""

    def __init__(
        self,
        cache_dir: Path,
        ttl: int = 1800,
        delay: float = 0.35,
        max_workers: int = 4,
        offline: bool = False,
        cookie: str = "",
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl
        self.delay = delay
        self.max_workers = max_workers
        self.offline = offline
        self._lock = threading.Lock()
        self._last_call = 0.0
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": UA, "Accept": "application/json"})
        self.last_auth_error: AuthError | None = None
        # Yopishtirishda kirib qolgan satr ko'chishi/ortiqcha bo'shliqni tozalaymiz —
        # HTTP sarlavhasida `\n` bo'lsa `requests` xato beradi
        self.cookie = re.sub(r"\s+", " ", (cookie or "").strip())
        if self.cookie:
            # Shaxsiy endpointlar (my-team) uchun brauzerdan olingan sessiya cookie si
            self._session.headers["Cookie"] = self.cookie
            self._session.headers["Referer"] = "https://fantasy.premierleague.com/"
            self._session.headers["X-Requested-With"] = "XMLHttpRequest"

    @property
    def authenticated(self) -> bool:
        return bool(self.cookie)

    # ------------------------------------------------------------------ kesh
    def _cache_path(self, url: str) -> Path:
        """Fayl nomi — URL dan; Windows ruxsat bermaydigan belgilar tozalanadi.

        Windows da `? : * " < > | \\` fayl nomida bo'lolmaydi, shuning uchun
        `?page_standings=1` kabi so'rov qismi to'g'ridan-to'g'ri nomga tushsa
        [Errno 22] chiqadi. To'liq URL hash da saqlanadi, nom faqat o'qish uchun.
        """
        key = hashlib.sha1(url.encode()).hexdigest()[:16]
        name = url.replace(BASE + "/", "").strip("/")
        name = SAFE_NAME_RE.sub("_", name).strip("_")[:60]
        return self.cache_dir / f"{name or 'req'}__{key}.json"

    def _read_cache(self, path: Path, ttl: int | None) -> Any | None:
        if not path.exists():
            return None
        ttl = self.ttl if ttl is None else ttl
        if not self.offline and ttl >= 0 and (time.time() - path.stat().st_mtime) > ttl:
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    # ------------------------------------------------------------------ so'rov
    def get(self, path: str, ttl: int | None = None) -> Any:
        url = path if path.startswith("http") else f"{BASE}/{path.lstrip('/')}"
        cache_file = self._cache_path(url)

        cached = self._read_cache(cache_file, ttl)
        if cached is not None:
            return cached
        if self.offline:
            raise FplApiError(f"offline rejim: kesh topilmadi — {url}")

        last_err: Exception | None = None
        for attempt in range(4):
            with self._lock:
                wait = self.delay - (time.time() - self._last_call)
                if wait > 0:
                    time.sleep(wait)
                self._last_call = time.time()
            try:
                resp = self._session.get(url, timeout=25)
                if resp.status_code == 404:
                    raise FplApiError(f"404: {url}")
                if resp.status_code in (401, 403):
                    # Qayta urinishning ma'nosi yo'q — sabab so'rovning o'zida.
                    # Javob matni ikki holatni ajratishga yordam beradi:
                    # sessiya yaroqsizmi yoki bot himoyasi to'sib qo'yganmi.
                    raise AuthError(resp.status_code, resp.text[:400], url)
                if resp.status_code == 429:
                    time.sleep(3 * (attempt + 1))
                    continue
                resp.raise_for_status()
                data = resp.json()
                cache_file.write_text(json.dumps(data), encoding="utf-8")
                return data
            except FplApiError:
                raise
            except Exception as exc:  # tarmoq xatosi — qayta urinamiz
                last_err = exc
                time.sleep(1.5 * (attempt + 1))
        # oxirgi chora: muddati o'tgan kesh ham yo'qdan yaxshi
        stale = self._read_cache(cache_file, ttl=-1)
        if stale is not None:
            log.warning("%s uchun eski kesh ishlatildi (%s)", url, last_err)
            return stale
        raise FplApiError(f"so'rov muvaffaqiyatsiz: {url} ({last_err})")

    def gather(self, items: Iterable[Any], fn: Callable[[Any], Any]) -> dict[Any, Any]:
        """Bir nechta so'rovni parallel bajaradi; xato bo'lsa None qaytaradi."""
        out: dict[Any, Any] = {}

        def _run(item: Any) -> tuple[Any, Any]:
            try:
                return item, fn(item)
            except Exception as exc:
                log.warning("yuklab bo'lmadi %s: %s", item, exc)
                return item, None

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            for key, value in pool.map(_run, items):
                out[key] = value
        return out

    # ------------------------------------------------------------- endpointlar
    def bootstrap(self) -> dict:
        return self.get("bootstrap-static/", ttl=900)

    def fixtures(self) -> list[dict]:
        return self.get("fixtures/", ttl=900)

    def element_summary(self, element_id: int) -> dict:
        return self.get(f"element-summary/{element_id}/", ttl=3600)

    def entry(self, entry_id: int) -> dict:
        return self.get(f"entry/{entry_id}/", ttl=1800)

    def entry_history(self, entry_id: int) -> dict:
        return self.get(f"entry/{entry_id}/history/", ttl=1800)

    def entry_transfers(self, entry_id: int) -> list[dict]:
        return self.get(f"entry/{entry_id}/transfers/", ttl=1800)

    def entry_picks(self, entry_id: int, event: int) -> dict:
        # tugagan GW o'zgarmaydi — uzoq kesh
        return self.get(f"entry/{entry_id}/event/{event}/picks/", ttl=6 * 3600)

    def my_team(self, entry_id: int) -> dict | None:
        """Shaxsiy endpoint: aniq sotish narxlari, erkin transferlar va chip holati.

        Cookie bo'lmasa yoki sessiya eskirgan bo'lsa None qaytaradi — dastur
        ochiq ma'lumot bilan davom etaveradi.
        """
        if not self.cookie:
            return None
        try:
            return self.get(f"my-team/{entry_id}/", ttl=300)
        except AuthError as exc:
            log.warning("my-team olinmadi (%s). %s", exc.status, exc.explain())
            self.last_auth_error = exc
            return None
        except Exception as exc:
            log.warning("my-team olinmadi: %s", exc)
            return None

    def event_live(self, event: int) -> dict:
        return self.get(f"event/{event}/live/", ttl=300)

    def league_standings(self, league_id: int, page: int = 1) -> dict:
        return self.get(
            f"leagues-classic/{league_id}/standings/?page_standings={page}", ttl=1800
        )

    def league_page_for_rank(self, league_id: int, rank: int) -> dict:
        """Berilgan o'ringa mos sahifani oladi (sahifada 50 ta jamoa)."""
        page = max(1, math.ceil(rank / 50))
        return self.league_standings(league_id, page=page)
