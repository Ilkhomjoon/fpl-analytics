"""FPL hisobiga kirish — email va parol orqali.

MUHIM HAQIQAT, bir marta va aniq aytilsin:

* **O'yinchilar ro'yxati login TALAB QILMAYDI.** `bootstrap-static/` ochiq
  endpoint — narx, egalik, daqiqa, xG, transfer oqimi, hammasi loginsiz keladi.
  Shuning uchun web sahifaning asosiy qismi login ishlamasa ham to'liq ishlaydi.
* Login faqat **shaxsiy** ma'lumot uchun kerak: `my-team/{id}` (aniq sotish
  narxlari, erkin transferlar soni, chip holati).
* FPL 2024/25 dan beri oddiy login formasidan **PingOne SSO** ga o'tgan.
  Ya'ni "email + parol → sessiya" endi bitta so'rov emas. Ustiga
  Cloudflare/DataDome bot himoyasi turadi va u serverdan (ayniqsa bulutdan)
  kelgan so'rovni odam brauzeridan ajratadi.

TEKSHIRILGAN HOLAT:

* `users.premierleague.com` — eski login formasi turgan manzil — **butunlay
  yo'q qilingan**. DNS da mavjud emas: `getaddrinfo failed`. Koddan olib
  tashlandi.
* `grant_type=password` (ROPC) — **noto'g'ri usul**. Server uni rad etadi,
  chunki FPL uni umuman ishlatmaydi. Uning rad javobi "kirib bo'lmaydi"
  degani emas edi.
* FPL ning **haqiqiy** oqimi — PingOne **DaVinci** (`pl_sso.py`). Brauzeringiz
  ham, uchinchi tomon ilovalari (FFM va boshqalar) ham shuni bajaradi. Bu
  oddiy HTTP so'rovlar ketma-ketligi, demak koddan ham bajariladi.

Yo'llar, tartib bilan:

  1. **DaVinci SSO** (`pl_sso.py`) — login va parol bilan, brauzersiz.
  2. **Brauzer** (`browser_login.py`) — haqiqiy Chromium ochiladi, parol o'zi
     yoziladi, token FPL ning so'rovlaridan tutiladi. Kafolatli, lekin sekinroq.
  3. Qo'lda token/cookie — zaxira yo'l.

Har bir urinish qayerda to'xtaganini (bosqich, HTTP kodi, javob tuzilishi)
alohida yozadi. Batafsil tashxis uchun: `python tools/sso_probe.py`.

Parol hech qayerga saqlanmaydi: u faqat urinish paytida ishlatiladi va
javobga ham, jurnalga ham tushmaydi.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import requests

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# PingOne odatda shu manzillarning birida discovery hujjatini beradi.
# Discovery — standart: token endpointini taxmin qilmasdan, aytilganini olamiz.
DISCOVERY_URLS = (
    "https://account.premierleague.com/.well-known/openid-configuration",
    "https://account.premierleague.com/as/.well-known/openid-configuration",
)
ME_URL = "https://fantasy.premierleague.com/api/me/"
FPL_HOME = "https://fantasy.premierleague.com/"

CLIENT_ID_RE = re.compile(r"client_id[\"'=:\s]+([0-9a-fA-F-]{20,40})")
UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")


# --------------------------------------------------------------------- natija
@dataclass
class Credentials:
    """Kirish natijasi — FplClient shu bilan shaxsiy endpointga boradi."""
    token: str = ""            # Bearer access_token (SSO yo'li)
    cookie: str = ""           # brauzerdan olingan sessiya cookie (zaxira yo'l)
    entry_id: int = 0
    name: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.token or self.cookie)

    def headers(self) -> dict[str, str]:
        out: dict[str, str] = {}
        if self.token:
            # FPL shaxsiy endpointi aynan shu sarlavhani kutadi
            out["X-Api-Authorization"] = f"Bearer {self.token}"
            out["Authorization"] = f"Bearer {self.token}"
        if self.cookie:
            out["Cookie"] = self.cookie
        if out:
            out["Referer"] = FPL_HOME
            out["X-Requested-With"] = "XMLHttpRequest"
        return out


@dataclass
class LoginResult:
    ok: bool = False
    credentials: Credentials = field(default_factory=Credentials)
    stage: str = ""            # qaysi bosqichda to'xtadi
    status: int = 0
    detail: str = ""           # server javobining qisqartmasi
    hint: str = ""             # foydalanuvchiga aniq ko'rsatma
    tried: list[dict] = field(default_factory=list)   # HAR BIR urinish hisoboti

    def summary(self) -> dict:
        return {
            "stage": self.stage,
            "status": self.status,
            "detail": self.detail[:400],
            "hint": self.hint,
        }

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "entry_id": self.credentials.entry_id,
            "name": self.credentials.name,
            "method": "token" if self.credentials.token else (
                "cookie" if self.credentials.cookie else ""
            ),
            "stage": self.stage,
            "status": self.status,
            "detail": self.detail[:400],
            "hint": self.hint,
            "tried": self.tried,
        }


def _blocked(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in (
        "datadome", "captcha", "cf-ray", "attention required", "just a moment",
        "access denied",
    ))


def new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-GB,en;q=0.9",
        "Origin": "https://fantasy.premierleague.com",
        "Referer": FPL_HOME,
    })
    return s


# ------------------------------------------------------------- topib olish
def discover_token_endpoint(session: requests.Session) -> tuple[str, str]:
    """OIDC discovery: (token_endpoint, xato matni).

    Taxmin qilmaymiz — provayderning o'zi aytgan manzilni olamiz.
    """
    last = ""
    for url in DISCOVERY_URLS:
        try:
            r = session.get(url, timeout=20)
            if r.status_code == 200:
                data = r.json()
                endpoint = data.get("token_endpoint") or ""
                if endpoint:
                    return endpoint, ""
                last = f"{url}: token_endpoint yo'q"
            else:
                last = f"{url}: HTTP {r.status_code}"
        except Exception as exc:
            last = f"{url}: {exc}"
    return "", last


def discover_client_id(session: requests.Session) -> tuple[str, str]:
    """FPL web ilovasining OAuth client_id sini sahifadan topadi."""
    try:
        r = session.get(FPL_HOME, timeout=20)
        if r.status_code != 200:
            return "", f"bosh sahifa HTTP {r.status_code}"
        named = CLIENT_ID_RE.search(r.text)
        if named:
            return named.group(1), ""
        loose = UUID_RE.search(r.text)
        if loose:
            return loose.group(0), ""
        # asosiy JS to'plamida bo'lishi mumkin
        for script in re.findall(r'src="([^"]+\.js)"', r.text)[:6]:
            src = script if script.startswith("http") else FPL_HOME.rstrip("/") + script
            try:
                js = session.get(src, timeout=20)
            except Exception:
                continue
            found = CLIENT_ID_RE.search(js.text)
            if found:
                return found.group(1), ""
        return "", "client_id sahifadan topilmadi"
    except Exception as exc:
        return "", str(exc)


def whoami(session: requests.Session, creds: Credentials) -> tuple[int, str, str]:
    """`/api/me/` orqali kim kirganini aniqlaydi: (entry_id, ism, xato)."""
    try:
        r = session.get(ME_URL, headers=creds.headers(), timeout=20)
    except Exception as exc:
        return 0, "", str(exc)
    if r.status_code != 200:
        return 0, "", f"HTTP {r.status_code}: {r.text[:200]}"
    try:
        player = (r.json() or {}).get("player") or {}
    except ValueError:
        return 0, "", "javob JSON emas"
    entry = player.get("entry") or 0
    name = " ".join(x for x in (player.get("first_name"), player.get("last_name")) if x)
    return int(entry or 0), name.strip(), ""


# --------------------------------------------------------- yo'l 1: DaVinci SSO
def _login_sso(email: str, password: str, redirect_uri: str = "") -> LoginResult:
    """FPL ning haqiqiy login oqimi — PingOne DaVinci (`pl_sso` moduli).

    Oldin bu yerda `grant_type=password` (ROPC) turardi. U noto'g'ri edi:
    server uni rad etadi, chunki FPL bu usulni umuman ishlatmaydi. Uchinchi
    tomon ilovalari (FFM va boshqalar) aynan DaVinci oqimini bajaradi.
    """
    from . import pl_sso

    result = LoginResult(stage="sso")
    session = pl_sso.new_session()
    flow = pl_sso.login(email, password, session=session, redirect_uri=redirect_uri)

    # Har bir bosqichni ko'rinadigan qilamiz — qayerda to'xtagani yo'qolmasin
    result.detail = " | ".join(
        f"{s.name}:{s.status or '-'}{'' if s.ok else ' ✗'}" for s in flow.steps
    )
    failed = flow.failed_step
    if not flow.ok:
        result.hint = flow.hint or "SSO oqimi tugamadi."
        if failed:
            result.status = failed.status
            result.detail += f" || {failed.name}: {failed.detail}"
        return result

    creds = Credentials(token=flow.token)
    # `/api/me/` AYNAN shu sessiya bilan so'raladi: u Cloudflare tekshiruvidan
    # o'tgan (`__cf_bm`) va login davomida qo'yilgan cookie'lar ham shunda.
    # Toza sessiya ishlayotgan tokenni "qabul qilinmadi" ko'rsatishi mumkin.
    entry_id, name, err = whoami(session, creds)
    if not entry_id:
        result.detail += f" || /api/me/: {err}"
        result.hint = "Token olindi, lekin /api/me/ uni qabul qilmadi."
        return result
    creds.entry_id, creds.name = entry_id, name
    return LoginResult(ok=True, credentials=creds, stage="sso", status=200,
                       detail=result.detail)


# ------------------------------------------------- yo'l 3: qo'lda token
def login_with_token(token_or_cookie: str) -> LoginResult:
    """Brauzerdan nusxalangan token yoki cookie bilan kirish.

    Bu yo'l **doim ishlaydi**, chunki tekshiruvdan sizning brauzeringiz o'tgan.
    """
    raw = re.sub(r"\s+", " ", (token_or_cookie or "").strip())
    if not raw:
        return LoginResult(stage="token", hint="Bo'sh qiymat.")

    # `Bearer xxx`, `access_token=xxx` yoki to'liq cookie satri bo'lishi mumkin
    if raw.lower().startswith("bearer "):
        creds = Credentials(token=raw[7:].strip())
    elif "=" in raw and ";" in raw:
        creds = Credentials(cookie=raw)
    elif raw.count(".") == 2 and " " not in raw:      # JWT ko'rinishi
        creds = Credentials(token=raw)
    else:
        creds = Credentials(cookie=raw)

    session = new_session()
    entry_id, name, err = whoami(session, creds)
    if not entry_id:
        return LoginResult(
            stage="token", detail=err,
            hint="FPL bu qiymatni qabul qilmadi — eskirgan yoki chala nusxalangan.",
        )
    creds.entry_id, creds.name = entry_id, name
    return LoginResult(ok=True, credentials=creds, stage="token", status=200)


# ----------------------------------------------------- yo'l 1: brauzer orqali
def login_with_browser(
    email: str = "",
    password: str = "",
    data_dir=None,
    timeout: float = 180.0,
    allow_visible: bool = True,
    profile_key: str = "",
) -> LoginResult:
    """Chromium orqali token oladi.

    Ikki bosqich: avval **ko'rinmas** urinish (profil saqlangan bo'lsa —
    oyna ochilmaydi, siz kutmaysiz), o'tmasa ochiq oyna. Shu tartib sizning
    vaqtingizni tejaydi: birinchi kirishdan keyin qayta kirish jimgina bo'ladi.
    """
    from . import browser_login, session_store

    result = LoginResult(stage="brauzer")
    # Profil kalit bo'yicha ajratiladi: boshqa email — boshqa profil, ya'ni
    # oldingi hisobning cookie si aralashib ketmaydi.
    key = profile_key or session_store.account_key(email)
    root = data_dir or (browser_login.Path(__file__).resolve().parent.parent / "data")
    silent_first = browser_login.profile_ready(root, key)
    modes = [True] if silent_first else []
    if allow_visible:
        modes.append(False)
    if not modes:                      # profil yo'q va oyna ochish taqiqlangan
        result.hint = "Saqlangan profil yo'q — bir marta ochiq oynada kirish kerak."
        return result

    tried: list[str] = []
    for headless in modes:
        label = "ko'rinmas" if headless else "ochiq oyna"
        try:
            captured = browser_login.capture_credentials(
                email=email, password=password, data_dir=data_dir,
                timeout=(30.0 if headless else timeout), headless=headless,
                profile_key=key,
            )
        except browser_login.BrowserLoginError as exc:
            result.detail = str(exc)
            result.hint = "Brauzer yo'li ishga tushmadi."
            return result
        except Exception as exc:
            tried.append(f"{label}: {type(exc).__name__}")
            continue

        if captured.get("ok"):
            creds = Credentials(
                token=captured.get("token", ""),
                cookie=captured.get("cookie", ""),
                entry_id=int(captured.get("entry_id") or 0),
            )
            entry_id, name, err = whoami(new_session(), creds)
            if entry_id:
                creds.entry_id, creds.name = entry_id, name
                return LoginResult(ok=True, credentials=creds, stage="brauzer",
                                   status=200, detail=f"{label}: token tutildi")
            if creds.entry_id:
                return LoginResult(
                    ok=True, credentials=creds, stage="brauzer", status=200,
                    detail=f"{label}: token tutildi",
                    hint=f"Tekshiruv so'rovi o'tmadi ({err}), lekin token bor.")
            tried.append(f"{label}: jamoa ID aniqlanmadi")
            continue

        tried.append(f"{label}: {captured.get('detail', 'token tutilmadi')}")

    result.detail = " | ".join(tried)
    result.hint = "Token tutilmadi."
    return result


# ------------------------------------------------------------------ umumiy
def login(
    email: str,
    password: str,
    client_id: str = "",
    use_browser: bool = True,
    data_dir=None,
    redirect_uri: str = "",
    profile_key: str = "",
) -> LoginResult:
    """Email va parol bilan kirishga urinadi. Parol hech qayerga saqlanmaydi.

    Tartib: **DaVinci SSO** (haqiqiy oqim, uchinchi tomon ilovalari ham shuni
    ishlatadi) → brauzer (kafolatli, lekin sekinroq).
    """
    if not email or not password:
        return LoginResult(hint="Email va parol kerak.")

    attempts = [lambda: _login_sso(email, password, redirect_uri)]
    if use_browser:
        attempts.append(lambda: login_with_browser(
            email, password, data_dir, profile_key=profile_key))

    tried: list[dict] = []
    last = LoginResult(stage="sso")
    for attempt in attempts:
        last = attempt()
        tried.append(last.summary())
        if last.ok:
            last.tried = tried
            return last

    last.tried = tried
    last.hint = (
        (last.hint + " ") if last.hint else ""
    ) + (
        "SSO oqimi qayerda to'xtaganini yozib olish uchun: "
        "python tools/sso_probe.py"
    )
    return last
