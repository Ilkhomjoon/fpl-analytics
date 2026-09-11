"""Haqiqiy brauzer orqali FPL ga kirish — eng ishonchli yo'l.

NEGA SHUNDAY?

Serverdan parol bilan kirish ikki sababdan o'tmaydi:

* `users.premierleague.com` — eski login formasi turgan manzil — **umuman
  yo'q bo'lib ketgan** (DNS da mavjud emas, `getaddrinfo failed`);
* `account.premierleague.com` esa PingOne SSO: u `password` grantini qabul
  qilmaydi, ustiga DataDome bot himoyasi so'rovni odam brauzeridan ajratadi.

Demak parolni HTTP so'rovga solib yuborishning iloji yo'q. Lekin **haqiqiy
brauzerda** kirish oddiy ish — siz buni har kuni qilasiz. Shuning uchun bu
modul kompyuteringizda chinakam Chromium oynasini ochadi, email/parolni
o'zi yozadi, DataDome/captcha bo'lsa siz bir marta bosasiz — va FPL o'z
so'rovlarida yuboradigan `X-Api-Authorization` tokenini tutib oladi.

Natijada foydalanuvchi uchun bu baribir "login va parol bilan kirish", faqat
tokenni DevTools dan qo'lda ko'chirish kerak emas.

Profil `data/browser/` da saqlanadi, shuning uchun **ikkinchi martadan boshlab
hech narsa yozish shart emas** — oyna ochiladi va token o'zi tutiladi.

Playwright ixtiyoriy paket. O'rnatilmagan bo'lsa modul aniq ko'rsatma beradi.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

MY_TEAM_URL = "https://fantasy.premierleague.com/my-team"
AUTH_HEADER = "x-api-authorization"
ENTRY_URL_RE = re.compile(r"/api/(?:my-team|entry)/(\d+)")

INSTALL_HINT = (
    "Playwright o'rnatilmagan. Bir marta shu ikki buyruqni bering:\n"
    "    pip install playwright\n"
    "    python -m playwright install chromium"
)


class BrowserLoginError(RuntimeError):
    pass


def profile_dir(root: Path, key: str = "default") -> Path:
    """Har akkaunt uchun ALOHIDA profil.

    Nega alohida? Bitta umumiy profil jiddiy xatoga olib keladi: unda oldingi
    foydalanuvchining sessiya cookie si qoladi va brauzer `/my-team` ga
    to'g'ridan-to'g'ri **o'sha** hisob bilan kiradi. Natijada boshqa email/parol
    yozgan odam birovning jamoasini ko'radi. Profil kalit bo'yicha ajratilsa,
    bunday aralashish umuman mumkin emas.
    """
    path = Path(root) / "profiles" / (key or "default")
    path.mkdir(parents=True, exist_ok=True)
    return path


def profile_ready(root: Path, key: str = "default") -> bool:
    """Shu akkaunt profilida oldingi sessiya bormi.

    Bor bo'lsa **ko'rinmas** (headless) rejimda ishlash mumkin: login formasi
    chiqmaydi, DataDome ham o'sha profilni allaqachon ko'rgan.
    """
    path = Path(root) / "profiles" / (key or "default")
    try:
        return path.exists() and any(path.iterdir())
    except Exception:
        return False


EMAIL_SELECTORS = (
    "input[type=email]", "input[name=email]", "input[name=username]",
    "input#email", "input#username", "input[autocomplete=username]",
    "input[type=text][name*=user i]",
)
PASSWORD_SELECTORS = (
    "input[type=password]", "input[name=password]", "input#password",
)
# `/my-team` sahifasi tizimga kirmagan holatda login formasini KO'RSATMAYDI —
# u faqat «Log in» tugmasini beradi. Shuning uchun avval shu tugmani bosamiz.
LOGIN_ENTRY_SELECTORS = (
    'a[href*="account.premierleague.com"]',
    'a[href*="users.premierleague.com"]',
    'a[href*="/login"]',
    'a:has-text("Log in")',
    'button:has-text("Log in")',
    'a:has-text("Sign in")',
    'button:has-text("Sign in")',
)


def _first_visible(scope, selectors):
    """Ko'rinib turgan birinchi elementni qaytaradi (yoki None)."""
    for selector in selectors:
        try:
            found = scope.locator(selector).first
            if found.count() and found.is_visible(timeout=1200):
                return found
        except Exception:
            continue
    return None


def _scopes(page):
    """Sahifaning o'zi va uning barcha freymlari.

    DaVinci widget login formasini iframe ichida ko'rsatishi mumkin, shuning
    uchun faqat asosiy sahifaga qarash yetarli emas.
    """
    yield page
    try:
        for frame in page.frames:
            if frame is not page.main_frame:
                yield frame
    except Exception:
        return


def _find_login_scope(page):
    """Parol maydoni turgan sahifa yoki freym."""
    for scope in _scopes(page):
        if _first_visible(scope, PASSWORD_SELECTORS) is not None:
            return scope
    return None


def _open_login_page(page, timeout_ms: int = 20000) -> str:
    """Login formasiga o'tadi. Qaytaradi: nima qilingani (tashxis uchun)."""
    if _find_login_scope(page) is not None:
        return "forma allaqachon ochiq"
    entry = _first_visible(page, LOGIN_ENTRY_SELECTORS)
    if entry is None:
        return "«Log in» tugmasi topilmadi"
    try:
        entry.click(timeout=5000)
    except Exception as exc:
        return f"«Log in» bosilmadi: {exc}"
    # SSO sahifasi ochilishini kutamiz
    deadline, waited = timeout_ms, 0
    while waited < deadline:
        page.wait_for_timeout(500)
        waited += 500
        if _find_login_scope(page) is not None:
            return "«Log in» bosildi, forma ochildi"
    return "«Log in» bosildi, lekin forma chiqmadi"


def _fill_login_form(page, email: str, password: str) -> bool:
    """Login formasini to'ldiradi. Forma topilmasa False."""
    scope = _find_login_scope(page)
    if scope is None:
        return False
    user = _first_visible(scope, EMAIL_SELECTORS)
    pw = _first_visible(scope, PASSWORD_SELECTORS)
    if pw is None:
        return False
    try:
        if user is not None:
            user.fill(email, timeout=5000)
        pw.fill(password, timeout=5000)
        pw.press("Enter")
        return True
    except Exception as exc:
        log.warning("formani to'ldirib bo'lmadi: %s", exc)
        return False


def capture_credentials(
    email: str = "",
    password: str = "",
    data_dir: Path | None = None,
    timeout: float = 180.0,
    headless: bool | None = None,
    start_url: str = MY_TEAM_URL,
    cookie_domain: str = "premierleague.com",
    profile_key: str = "default",
) -> dict:
    """Brauzerni ochib, FPL tokenini tutadi.

    Qaytaradi: {"ok", "token", "cookie", "entry_id", "detail"}.

    `headless=None` — avtomatik: saqlangan profil bo'lsa **ko'rinmas** rejim
    (oyna ochilmaydi, siz kutmaysiz), bo'lmasa ochiq oyna. Sabab: birinchi
    kirishda captcha chiqishi mumkin va uni siz bosasiz; keyingi safar esa
    profil tayyor va hech narsa talab qilinmaydi.
    """
    try:
        from playwright.sync_api import TimeoutError as PwTimeout  # noqa: F401
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserLoginError(INSTALL_HINT) from exc

    data_dir = Path(data_dir or (Path(__file__).resolve().parent.parent / "data"))
    if headless is None:
        headless = profile_ready(data_dir, profile_key)
    found: dict = {"token": "", "entry_id": 0}
    cookie, typed, entry_note = "", False, "urinilmadi"

    def on_request(request) -> None:
        if found["token"]:
            return
        try:
            headers = {k.lower(): v for k, v in request.headers.items()}
        except Exception:
            return
        value = headers.get(AUTH_HEADER) or ""
        if value.lower().startswith("bearer "):
            found["token"] = value[7:].strip()
            log.info("token tutildi (%s)", request.url.split("?")[0])
        match = ENTRY_URL_RE.search(request.url)
        if match and not found["entry_id"]:
            found["entry_id"] = int(match.group(1))

    def on_response(response) -> None:
        if found["entry_id"] or "/api/me/" not in response.url:
            return
        try:
            player = (response.json() or {}).get("player") or {}
            if player.get("entry"):
                found["entry_id"] = int(player["entry"])
        except Exception:
            pass

    with sync_playwright() as pw:
        try:
            context = pw.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir(data_dir, profile_key)),
                headless=headless,
                viewport={"width": 1280, "height": 900},
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception as exc:
            raise BrowserLoginError(
                f"Chromium ochilmadi: {exc}\n\n{INSTALL_HINT}"
            ) from exc

        try:
            context.on("request", on_request)
            context.on("response", on_response)
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(start_url, wait_until="domcontentloaded", timeout=60000)

            if email and password:
                page.wait_for_timeout(2500)
                entry_note = _open_login_page(page)
                log.info("login sahifasi: %s", entry_note)
                typed = _fill_login_form(page, email, password)
                if typed:
                    # Kirgandan keyin `/my-team` ni qayta ochamiz — token
                    # aynan o'sha sahifaning API so'rovida keladi
                    page.wait_for_timeout(4000)
                    try:
                        page.goto(start_url, wait_until="domcontentloaded",
                                  timeout=30000)
                    except Exception:
                        pass

            # Token FPL ning o'z so'rovlarida keladi. Ba'zan captcha yoki 2FA
            # chiqadi — shuning uchun uzoq kutamiz, foydalanuvchi oynada
            # ishini tugatsin.
            deadline = timeout * 1000
            waited = 0.0
            token_at: float | None = None
            # Token kelgandan keyin jamoa ID sini cheksiz kutmaymiz: FPL uni
            # odatda darrov beradi, bermasa keyin ochiq API dan aniqlanadi.
            grace = 12000.0

            while waited < deadline:
                if found["token"] and found["entry_id"]:
                    break
                if found["token"]:
                    if token_at is None:
                        token_at = waited
                    elif waited - token_at >= grace:
                        break
                try:
                    page.wait_for_timeout(500)
                except Exception:
                    break                      # foydalanuvchi oynani yopdi
                waited += 500
                if waited % 15000 == 0 and not found["token"]:
                    # sahifani turtib qo'yamiz — API so'rovi qayta ketsin
                    try:
                        page.goto(start_url, wait_until="domcontentloaded",
                                  timeout=30000)
                    except Exception:
                        break

            cookie = "; ".join(
                f"{c['name']}={c['value']}" for c in context.cookies()
                if cookie_domain in (c.get("domain") or "")
            )
        finally:
            try:
                context.close()
            except Exception:
                pass

    if not found["token"] and not cookie:
        return {
            "ok": False, "headless": headless, "token": "", "cookie": "", "entry_id": 0,
            "detail": (
                "Brauzer ochildi, lekin token tutilmadi. "
                + ("Login formasi to'ldirildi. " if typed else
                   f"Login formasi topilmadi ({entry_note}). ")
                + "Oynada tizimga kirib, «Pick Team» sahifasini oching va qaytadan urinib ko'ring."
            ),
        }

    return {
        "ok": True,
        "headless": headless,
        "token": found["token"],
        "cookie": cookie,
        "entry_id": found["entry_id"],
        "detail": "Brauzerdan token tutildi." if found["token"]
                  else "Token topilmadi, cookie olindi.",
    }
