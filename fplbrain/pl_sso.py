"""FPL ga login/parol bilan kirish — PingOne **DaVinci** oqimi.

Oqim `sso_probe` bergan haqiqiy javoblar asosida qurilgan. Muhim jihati:
u **bitta so'rov emas, qadamlar zanjiri**. Har bir qadam ("node") o'zi nima
so'rayotganini aytadi, biz esa shunga qarab javob beramiz.

    discovery   FPL sahifasidan client_id
                ↓
    authorize   /as/authorize → widget sozlamasi (apiRoot, policyId,
                accessToken) + `/as/resume` formasi va uning `state` qiymati
                ↓
    start       /davinci/policy/{policyId}/start → BIRINCHI qadam.
                Bu login formasi EMAS: FPL da u PingOne Protect qadami,
                yagona maydoni `protectsdk`
                ↓
    qadamlar    har bir qadam `connections/{id}/capabilities/{name}` ga
                yuboriladi. Qaysi maydonlar kerakligi `screen` ichidagi
                `formFieldsList` da yozilgan — o'qiymiz, taxmin qilmaymiz.
                Parol faqat parol maydoni bor qadamda beriladi
                ↓
    dvResponse  oqim tugagach shu qiymat keladi
                ↓
    resume      dvResponse + state → /as/resume → redirect ichida `code`
                ↓
    token       code + PKCE verifier → access_token

Nima uchun oldingi urinishlar to'xtagani (hammasi probe da ko'rindi):

* `interactionToken` umuman berilmaydi — cookie faqat `interactionId`;
* `screen` HTML emas, JSON tuzilma, shuning uchun `<input>` izlash befoyda;
* birinchi qadam login formasi deb o'ylangan edi, aslida u Protect qadami;
* oqim `/as/resume` orqali tugaydi, kod to'g'ridan-to'g'ri JSON da kelmaydi.

Maxfiylik: parol faqat kerakli qadamning so'rov tanasiga qo'yiladi; hisobotga
ham, jurnalga ham tushmaydi. Tashxisda javob **kalitlari** va serverning
**xato xabari** saqlanadi — notanish javobning qiymatlari emas.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

import requests

log = logging.getLogger(__name__)

ACCOUNT = "https://account.premierleague.com"
FPL_HOME = "https://fantasy.premierleague.com/"

AUTHORIZE_RE = re.compile(
    r"https://account\.premierleague\.com/as/authorize\?[^\"'\s\\<>]+"
)
REDIRECT_RE = re.compile(r"redirect_uri[\"'=:\s]+(https?://[^\"'\s,&]+)", re.IGNORECASE)
CLIENT_ID_RE = re.compile(r"client_id[\"'=:\s]+([0-9a-fA-F-]{20,40})")
# `/as/resume` formasi va uning yashirin `state` qiymati
RESUME_FORM_RE = re.compile(r'<form[^>]+action="([^"]*?/as/resume)"', re.IGNORECASE)
STATE_INPUT_RE = re.compile(
    r'<input[^>]+name="state"[^>]+value="([^"]*)"', re.IGNORECASE
)

WIDGET_KEYS = ("apiRoot", "companyId", "policyId", "accessToken")
WIDGET_ATTR = {
    "apiRoot": "api_root", "companyId": "company_id",
    "policyId": "policy_id", "accessToken": "access_token",
}
# Qadam javobida bo'lishi shart bo'lgan kalitlar
NODE_KEYS = ("interactionId", "connectionId", "capabilityName")
# `interactionToken` ixtiyoriy: FPL uni bermaydi, boshqa o'rnatmalar berishi
# mumkin. Faqat nomida `token` bor cookie ko'riladi — `interactionId` ni token
# deb olish xato edi va noto'g'ri sarlavha yuborilardi.
TOKEN_HEADERS = ("interactionToken", "X-Interaction-Token")
TOKEN_COOKIE_RE = re.compile(r"token", re.IGNORECASE)

PASS_RE = re.compile(r"pass", re.IGNORECASE)
USER_RE = re.compile(r"user|email|login|account", re.IGNORECASE)
# Tugma maydonlari. Ular bo'sh ketolmaydi: server "qaysi tugma bosilgani
# aniqlanmadi" deb 400 qaytaradi — bu haqiqiy xato bo'lgan.
BUTTON_RE = re.compile(r"^button(value|type)$", re.IGNORECASE)
# DaVinci HTML shablonidagi tugma: qiymat shu yerda yozilgan, taxmin qilinmaydi.
# Shablonda tugma BITTA emas — login sahifasida "Register" ham turadi, shuning
# uchun hammasi yig'iladi va tanlanadi (birinchisini olish xato bo'lgan).
SKBUTTON_TAG_RE = re.compile(r"<[^>]*data-skbuttonvalue=[^>]*>", re.IGNORECASE)
SKBUTTON_VALUE_RE = re.compile(r'data-skbuttonvalue="([^"]+)"', re.IGNORECASE)
SKBUTTON_TYPE_RE = re.compile(r'data-skbuttontype="([^"]+)"', re.IGNORECASE)
# Formani yuboradigan tugma turi
SUBMIT_TYPE_RE = re.compile(r"submit", re.IGNORECASE)
# "Kirish" ma'nosidagi qiymatlar
SIGNIN_RE = re.compile(r"sign.?on|sign.?in|log.?in|submit|continue|next",
                       re.IGNORECASE)
# Parol yuborilayotgan qadamda BOSILMAYDIGAN tugmalar
AVOID_RE = re.compile(
    r"register|sign.?up|create|forgot|reset|cancel|back|help|"
    r"apple|google|facebook|social",
    re.IGNORECASE,
)
# HTML ham, maydon ham jim qolsa — shu tartibda sinaladi
BUTTON_FALLBACKS = ("SIGNON", "submit", "continue")
HTML_KEYS = ("customHTML", "customHtml", "html", "template", "content")
# Tugma tanlanmagani haqidagi xato: boshqa qiymat bilan qayta urinsa bo'ladi
BUTTON_ERROR_RE = re.compile(r"button", re.IGNORECASE)
ERROR_KEYS = (
    "message", "error_description", "error", "errorMessage", "detail",
    "description", "code", "httpResponseCode",
)
DEBUG_KEYS = ("_links", "startUiSubFlow", "subFlowSettings", "eventName",
              "nextEvent", "passCredentialsToCapabilities", "resetCookie")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


# ------------------------------------------------------------------ natijalar
@dataclass
class Step:
    """Bitta bosqich hisoboti. Maxfiy qiymat saqlanmaydi."""
    name: str
    url: str = ""
    status: int = 0
    ok: bool = False
    detail: str = ""
    shape: list[str] = field(default_factory=list)
    attempts: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        out = {
            "name": self.name, "url": self.url, "status": self.status,
            "ok": self.ok, "detail": self.detail[:600], "shape": self.shape[:40],
        }
        if self.attempts:
            out["urinishlar"] = self.attempts[:10]
        return out


@dataclass
class WidgetConfig:
    """`/as/authorize` javobidan olingan hamma narsa."""
    api_root: str = ""
    company_id: str = ""
    policy_id: str = ""
    access_token: str = ""
    method: str = ""
    flow_base: str = ""      # `start` da ishlagan prefiks
    resume_url: str = ""     # oqim oxirida `dvResponse` shu yerga boradi
    state: str = ""          # `/as/resume` kutadigan qiymat (PingOne beradi)

    @property
    def ok(self) -> bool:
        return bool(self.api_root and self.company_id and self.policy_id
                    and self.access_token)

    def base(self) -> str:
        return self.flow_base or start_bases(self)[0][1]

    def as_dict(self) -> dict:
        """Tashxis uchun — `accessToken` va `state` QIYMATI chiqmaydi."""
        return {
            "apiRoot": self.api_root, "companyId": self.company_id,
            "policyId": self.policy_id, "method": self.method,
            "accessToken_bormi": bool(self.access_token),
            "flow_base": self.flow_base,
            "resume_url": self.resume_url,
            "state_bormi": bool(self.state),
        }


@dataclass
class Node:
    """DaVinci oqimining bitta qadami."""
    node_id: str = ""
    interaction_id: str = ""
    interaction_token: str = ""
    connection_id: str = ""
    capability: str = ""
    fields: list[dict] = field(default_factory=list)   # [{name, control, type}]
    next_event: dict = field(default_factory=dict)
    # Shablondagi HAMMA tugma: [{value, type}]. Tanlash `button_candidates` da
    buttons: list[dict] = field(default_factory=list)
    # Maydonning o'zida yozilgan qiymat (agar bo'lsa)
    button_value: str = ""
    button_type: str = ""
    # Xom javob — faqat tashxis uchun (`flow_debug`). Hisobotga chiqmaydi.
    raw: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.connection_id and self.capability)

    @property
    def field_names(self) -> list[str]:
        return [f["name"] for f in self.fields]

    @property
    def password_field(self) -> str:
        for item in self.fields:
            control = (item.get("control") or "").lower()
            if "password" in control or PASS_RE.search(item["name"]):
                return item["name"]
        return ""

    @property
    def user_field(self) -> str:
        password = self.password_field
        for item in self.fields:
            if item["name"] != password and USER_RE.search(item["name"]):
                return item["name"]
        return ""

    @property
    def button_fields(self) -> list[str]:
        return [f["name"] for f in self.fields if BUTTON_RE.match(f["name"])]

    @property
    def wants_credentials(self) -> bool:
        return bool(self.password_field)

    def button_score(self, button: dict) -> int:
        """Tugma qanchalik mos. Katta son — oldinroq sinaladi.

        Login sahifasida bir nechta tugma bor: "Sign in" bilan bir qatorda
        "Register" ham. Birinchisini olish parolni ro'yxatdan o'tish
        shoxobchasiga yuborib qo'ygan edi — server 200 qaytaradi, lekin oqim
        noto'g'ri tomonga ketadi. Shuning uchun tanlanadi, olinmaydi.
        """
        value, btype = button.get("value", ""), button.get("type", "")
        score = 0
        if SUBMIT_TYPE_RE.search(btype):
            score += 3
        if SIGNIN_RE.search(value):
            score += 2
        if AVOID_RE.search(value):
            score -= 10
        return score

    def button_candidates(self) -> list[str]:
        """Tugma qiymati uchun nomzodlar — mosligi bo'yicha tartiblangan."""
        ranked = sorted(
            self.buttons,
            key=lambda b: -self.button_score(b),
        )
        out: list[str] = []
        for button in ranked:
            value = button.get("value", "")
            # "Register", "Forgot password", ijtimoiy tarmoqlar — oqimning
            # HECH BIR qadamida bosilmaydi. Biz parol bilan kiryapmiz.
            if not value or AVOID_RE.search(value) or value in out:
                continue
            out.append(value)
        for value in (self.button_value, *BUTTON_FALLBACKS):
            if value and value not in out and not AVOID_RE.search(value):
                out.append(value)
        return out

    def button_type_for(self, value: str) -> str:
        """Tanlangan qiymatga juft keladigan tugma turi."""
        for button in self.buttons:
            if button.get("value") == value and button.get("type"):
                return button["type"]
        return self.button_type or "form-submit"

    def kind(self) -> str:
        if self.wants_credentials:
            return "login"
        if any("protect" in name.lower() for name in self.field_names):
            return "protect"
        return "oraliq"

    def describe(self) -> str:
        return (f"{self.kind()}[{self.capability}] "
                f"maydonlar: {', '.join(self.field_names) or '—'}")


@dataclass
class SsoResult:
    ok: bool = False
    token: str = ""
    steps: list[Step] = field(default_factory=list)
    hint: str = ""

    @property
    def failed_step(self) -> Step | None:
        return next((s for s in self.steps if not s.ok), None)

    def as_dict(self, include_token: bool = False) -> dict:
        out = {"ok": self.ok, "hint": self.hint,
               "steps": [s.as_dict() for s in self.steps]}
        if include_token:
            out["token"] = self.token
        return out


# -------------------------------------------------------------------- PKCE
def pkce_pair() -> tuple[str, str]:
    """(verifier, challenge) — RFC 7636, S256."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode().rstrip("=")
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


# ------------------------------------------------------------ javob tahlili
def _iter_json_objects(text: str):
    """Matn ichidagi JSON obyektlarini topib beradi (HTML ichidagi ham)."""
    depth, start = 0, -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start >= 0:
                chunk = text[start:i + 1]
                if len(chunk) <= 200_000:
                    try:
                        yield json.loads(chunk)
                    except ValueError:
                        pass


def _walk(node, found: dict, keys: tuple[str, ...]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in keys and isinstance(value, str) and value and key not in found:
                found[key] = value
            _walk(value, found, keys)
    elif isinstance(node, list):
        for item in node:
            _walk(item, found, keys)


def _collect(payload: str | dict, keys: tuple[str, ...]) -> dict:
    found: dict = {}
    if isinstance(payload, dict):
        _walk(payload, found, keys)
        return found
    try:
        _walk(json.loads(payload), found, keys)
    except ValueError:
        for obj in _iter_json_objects(payload):
            _walk(obj, found, keys)
            if all(k in found for k in keys):
                break
    return found


def _collect_raw(node, key: str):
    """Ichma-ich JSON dan bitta kalitning xom qiymatini topadi."""
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            if key in current:
                return current[key]
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return None


def _shape(payload) -> list[str]:
    """Javobning kalitlari. Qiymatlar OLINMAYDI."""
    if isinstance(payload, dict):
        return sorted(payload.keys())
    if isinstance(payload, str):
        keys: set[str] = set()
        for obj in _iter_json_objects(payload):
            if isinstance(obj, dict):
                keys |= set(obj.keys())
            if len(keys) > 60:
                break
        return sorted(keys)[:60]
    return []


def error_text(payload, limit: int = 300) -> str:
    """Server **xatosining** matni — tashxisning eng qimmatli qismi.

    Xato xabari maxfiy emas. Tanish kalit topilmasa faqat kalitlar qaytadi.
    """
    if isinstance(payload, dict):
        parts = [
            f"{key}={payload[key]}"
            for key in ERROR_KEYS
            if isinstance(payload.get(key), (str, int)) and str(payload[key])
        ]
        if parts:
            return "; ".join(parts)[:limit]
        return "kalitlar: " + ", ".join(_shape(payload)[:15])
    if isinstance(payload, str):
        return re.sub(r"\s+", " ", payload).strip()[:limit]
    return ""


def flow_debug(payload, include_screen: bool = False, limit: int = 1500) -> dict:
    """Oqim tuzilishi — maxfiy bo'lmagan kalitlar. `screen` faqat so'ralganda."""
    out: dict = {}
    for key in DEBUG_KEYS + (("screen",) if include_screen else ()):
        value = _collect_raw(payload, key)
        if value is None:
            continue
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        out[key] = text[:limit]
    return out


def _body(response) -> tuple[object, list[str]]:
    try:
        data = response.json()
        return data, _shape(data)
    except ValueError:
        return response.text, _shape(response.text)


def cookie_names(session) -> list[str]:
    """Cookie NOMLARI — tashxis uchun. Qiymatlar olinmaydi."""
    try:
        return sorted({c.name for c in session.cookies})
    except Exception:
        try:
            return sorted(session.cookies.keys())
        except Exception:
            return []


def _jar_names(jar) -> list[str]:
    try:
        return [c.name for c in jar]
    except Exception:
        try:
            return list(jar.keys())
        except Exception:
            return []


def interaction_token(response, session, payload) -> tuple[str, str]:
    """`interactionToken`: (qiymat, manba). Topilmasa ("", "").

    FPL uni bermaydi — bu normal, oqim usiz ham ketadi.
    """
    if isinstance(payload, dict):
        value = _collect(payload, ("interactionToken",)).get("interactionToken")
        if value:
            return value, "tana"
    for name in TOKEN_HEADERS:
        value = response.headers.get(name)
        if value:
            return value, f"sarlavha:{name}"
    for jar in (getattr(response, "cookies", None), getattr(session, "cookies", None)):
        if jar is None:
            continue
        for name in _jar_names(jar):
            if not TOKEN_COOKIE_RE.search(name):
                continue
            try:
                value = jar.get(name)
            except Exception:
                value = None
            if value:
                return value, f"cookie:{name}"
    return "", ""


def screen_html(payload) -> str:
    """Qadamning HTML shabloni. Tugma qiymati aynan shu yerda yozilgan.

    Bir nechta kalit nomi sinaladi (`customHTML`, `html`, ...) — qaysi biri
    ishlatilishi o'rnatmaga bog'liq, shuning uchun qattiq yozilmagan.
    """
    for key in HTML_KEYS:
        value = _collect_raw(payload, key)
        if isinstance(value, dict):          # {"value": "<html…>"} ko'rinishi
            value = value.get("value")
        if isinstance(value, str) and "<" in value:
            return value
    return ""


TAG_RE = re.compile(r"<[^>]+>")


def screen_text(payload, limit: int = 300) -> str:
    """Ekrandagi o'qiladigan matn — "parol noto'g'ri" kabi xabarlar shu yerda.

    Oraliq ekran nima deyayotganini bilmasdan turib oqimni davom ettirish
    ko'r-ko'rona bo'lardi. Matn qisqartiriladi va maxfiy qiymat qidirilmaydi.
    """
    html = screen_html(payload)
    if not html:
        return ""
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", html)).strip()[:limit]


def buttons_in_html(html: str) -> list[dict]:
    """Shablondagi HAMMA tugma: [{value, type}].

    Har bir tugmaning qiymati va turi **birga** olinadi. Avval qiymat va tur
    alohida-alohida qidirilardi — natijada "Register" tugmasining qiymati
    "Sign in" tugmasining turi bilan qo'shilib ketishi mumkin edi.
    """
    out: list[dict] = []
    for tag in SKBUTTON_TAG_RE.findall(html or ""):
        value = SKBUTTON_VALUE_RE.search(tag)
        if not value:
            continue
        btype = SKBUTTON_TYPE_RE.search(tag)
        out.append({"value": value.group(1),
                    "type": btype.group(1) if btype else ""})
    return out


# --------------------------------------------------------------- qadam tahlili
def parse_node(payload, session=None, response=None) -> Node:
    """Javobni DaVinci qadamiga aylantiradi.

    Maydonlar `screen.properties.formFieldsList.value` dan olinadi — u yerda
    har bir maydonning `propertyName` i yozilgan. Bu HTML dan `<input>`
    izlashdan ishonchliroq: FPL da `screen` umuman HTML emas.
    """
    node = Node()
    if not isinstance(payload, dict):
        return node

    node.raw = payload
    ids = _collect(payload, NODE_KEYS + ("interactionToken",))
    node.interaction_id = ids.get("interactionId", "")
    node.interaction_token = ids.get("interactionToken", "")
    node.connection_id = ids.get("connectionId", "")
    node.capability = ids.get("capabilityName", "")
    node_id = payload.get("id")
    node.node_id = node_id if isinstance(node_id, str) else ""

    fields = _collect_raw(payload, "formFieldsList")
    values = fields.get("value") if isinstance(fields, dict) else None
    for item in values or []:
        if not isinstance(item, dict):
            continue
        name = item.get("propertyName") or item.get("key") or item.get("name")
        if not isinstance(name, str) or not name:
            continue
        node.fields.append({
            "name": name,
            "control": item.get("preferredControlType", ""),
            "type": item.get("preferredDataType", ""),
        })
        # Tugma maydonining o'z qiymati bo'lsa — eng ishonchli manba
        if BUTTON_RE.match(name):
            own = item.get("value") or item.get("defaultValue") or ""
            if isinstance(own, str) and own:
                if name.lower() == "buttonvalue":
                    node.button_value = node.button_value or own
                else:
                    node.button_type = node.button_type or own

    node.buttons = buttons_in_html(screen_html(payload))

    button = _collect_raw(payload, "button")
    if isinstance(button, dict) and isinstance(button.get("onClick"), dict):
        node.next_event = button["onClick"]

    if session is not None and response is not None and not node.interaction_token:
        node.interaction_token = interaction_token(response, session, payload)[0]
    return node


def find_dv_response(payload) -> str:
    """Oqim tugagach keladigan `dvResponse` — u `/as/resume` ga yuboriladi."""
    if not isinstance(payload, dict):
        return ""
    value = _collect_raw(payload, "dvResponse")
    return value if isinstance(value, str) and value else ""


def find_code(payload) -> str:
    """Javobning istalgan joyidan avtorizatsiya kodini topadi."""
    stack = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "code" and isinstance(value, str) and value:
                    return value
                if isinstance(value, str) and key in (
                    "callbackUrl", "redirectUrl", "location", "authorizeResponse"
                ):
                    query = parse_qs(urlparse(value).query)
                    if query.get("code"):
                        return query["code"][0]
                stack.append(value)
        elif isinstance(node, list):
            stack.extend(node)
    return ""


def new_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": UA,
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "en-GB,en;q=0.9",
    })
    return session


# ---------------------------------------------------------------- 1. topish
def discover_authorize(
    session: requests.Session, redirect_uri: str = ""
) -> tuple[dict, Step]:
    """FPL sahifasidan `client_id` va (imkon bo'lsa) `redirect_uri` ni topadi."""
    step = Step(name="discovery", url=FPL_HOME)
    texts: list[str] = []
    try:
        home = session.get(FPL_HOME, timeout=25)
        step.status = home.status_code
        texts.append(home.text)
        for src in re.findall(r'src="([^"]+\.js)"', home.text)[:8]:
            url = src if src.startswith("http") else FPL_HOME.rstrip("/") + src
            try:
                texts.append(session.get(url, timeout=25).text)
            except Exception:
                continue
    except Exception as exc:
        step.detail = f"{type(exc).__name__}: {exc}"
        return {}, step

    for text in texts:
        match = AUTHORIZE_RE.search(text)
        if match:
            params = {k: v[0] for k, v in parse_qs(urlparse(match.group(0)).query).items()}
            if params.get("client_id"):
                if redirect_uri:
                    params["redirect_uri"] = redirect_uri
                step.ok, step.shape = True, sorted(params)
                step.detail = "authorize havolasi topildi"
                return params, step

    params: dict = {}
    for text in texts:
        if "client_id" not in params:
            found = CLIENT_ID_RE.search(text)
            if found:
                params["client_id"] = found.group(1)
        if "redirect_uri" not in params:
            found = REDIRECT_RE.search(text)
            if found and "premierleague.com" in found.group(1):
                params["redirect_uri"] = found.group(1)
        if len(params) == 2:
            break
    if redirect_uri:
        params["redirect_uri"] = redirect_uri
    if params.get("client_id"):
        step.ok, step.shape = True, sorted(params)
        step.detail = ("client_id va redirect_uri topildi" if params.get("redirect_uri")
                       else "faqat client_id topildi; redirect_uri standart qiymatda")
        return params, step

    step.detail = "authorize havolasi ham, client_id ham topilmadi"
    return {}, step


# ------------------------------------------------------------- 2. authorize
def extract_widget(payload: str | dict) -> WidgetConfig:
    """`/as/authorize` javobidan widget sozlamasi va resume formasi."""
    found = _collect(payload, WIDGET_KEYS + ("method",))
    widget = WidgetConfig(
        api_root=found.get("apiRoot", ""),
        company_id=found.get("companyId", ""),
        policy_id=found.get("policyId", ""),
        access_token=found.get("accessToken", ""),
        method=found.get("method", ""),
    )
    if isinstance(payload, str):
        form = RESUME_FORM_RE.search(payload)
        if form:
            widget.resume_url = form.group(1)
        state = STATE_INPUT_RE.search(payload)
        if state:
            # Diqqat: bu qiymatni PingOne beradi — biz authorize ga yuborgan
            # `state` emas. `/as/resume` aynan shuni kutadi.
            widget.state = state.group(1)
    return widget


def start_authorize(
    session: requests.Session, params: dict, challenge: str, state: str
) -> tuple[WidgetConfig, Step]:
    """`/as/authorize` — widget sozlamasi va `/as/resume` formasi shu yerda."""
    query = {
        "client_id": params.get("client_id", ""),
        "redirect_uri": params.get("redirect_uri") or FPL_HOME,
        "response_type": params.get("response_type", "code"),
        "scope": params.get("scope", "openid profile email offline_access"),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    if params.get("response_mode"):
        query["response_mode"] = params["response_mode"]

    step = Step(name="authorize", url=f"{ACCOUNT}/as/authorize")
    try:
        response = session.get(step.url, params=query, timeout=25,
                               headers={"Referer": FPL_HOME})
    except Exception as exc:
        step.detail = f"{type(exc).__name__}: {exc}"
        return WidgetConfig(), step

    step.status = response.status_code
    payload, step.shape = _body(response)
    widget = extract_widget(payload)
    if widget.ok:
        step.ok = True
        step.detail = (
            f"apiRoot={widget.api_root}, policyId={widget.policy_id}"
            f" · resume: {widget.resume_url or 'topilmadi'}"
            f" · state: {'bor' if widget.state else 'yo`q'}"
        )
        return widget, step

    missing = [k for k in WIDGET_KEYS if not getattr(widget, WIDGET_ATTR[k])]
    step.detail = (
        f"widget sozlamasi to'liq emas (yetishmaydi: {', '.join(missing)}). "
        + (f"Server: {error_text(payload)}" if response.status_code != 200
           else "Kalitlar: " + (", ".join(step.shape[:20]) or "(JSON emas)"))
    )
    return widget, step


# ------------------------------------------------------------ 3. oqim boshi
def start_bases(widget: WidgetConfig) -> list[tuple[str, str]]:
    """DaVinci ning ikki joylashuvi: mijoz domeni ortida yoki o'z hostida."""
    root = widget.api_root.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    return [
        ("davinci", f"{root}/davinci"),
        ("v1/company", f"{root}/v1/company/{widget.company_id}"),
    ]


def _flow_headers(widget: WidgetConfig, node: Node | None = None) -> dict:
    headers = {
        "Authorization": f"Bearer {widget.access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": ACCOUNT,
        "Referer": f"{ACCOUNT}/",
        "X-Requested-With": "XMLHttpRequest",
    }
    if node is not None:
        if node.interaction_id:
            headers["interactionId"] = node.interaction_id
        # Bo'sh qiymat yubormaymiz — u yo'qdan yomonroq
        if node.interaction_token:
            headers["interactionToken"] = node.interaction_token
    return headers


def start_policy(session: requests.Session, widget: WidgetConfig) -> tuple[Node, Step]:
    """Oqimning birinchi qadamini oladi.

    Bu qadam **login formasi emas**: FPL da u PingOne Protect qadami.
    """
    step = Step(name="start")
    for base_name, base in start_bases(widget):
        url = f"{base}/policy/{widget.policy_id}/start"
        attempt: dict = {"shakl": base_name, "url": url}
        try:
            response = session.post(url, json={}, headers=_flow_headers(widget),
                                    timeout=30)
        except Exception as exc:
            attempt.update(status=0, xato=f"{type(exc).__name__}: {exc}"[:200])
            step.attempts.append(attempt)
            continue

        payload, shape = _body(response)
        attempt["status"] = response.status_code
        node = parse_node(payload, session, response)
        if node.ok and node.interaction_id:
            widget.flow_base = base
            attempt.update(natija="OK", qadam=node.describe(),
                           cookielar=cookie_names(session))
            step.attempts.append(attempt)
            step.url, step.status, step.ok = url, response.status_code, True
            step.shape = shape
            step.detail = f"birinchi qadam ({base_name}): {node.describe()}"
            return node, step

        attempt["javob"] = error_text(payload)
        step.attempts.append(attempt)

    step.url = step.attempts[0]["url"] if step.attempts else ""
    step.status = next((a.get("status", 0) for a in step.attempts if a.get("status")), 0)
    step.detail = "oqim boshlanmadi — " + " ; ".join(
        f"{a['shakl']}: HTTP {a.get('status')} "
        f"{a.get('javob') or a.get('xato') or ''}".strip()
        for a in step.attempts
    )
    return Node(), step


# --------------------------------------------------------- 4. qadamlar zanjiri
DEFAULT_EVENT = {
    "constructType": "skEvent", "eventName": "continue",
    "params": [], "eventType": "post", "postProcess": {},
}


def node_parameters(
    node: Node, email: str, password: str, button_value: str = ""
) -> dict:
    """Qadam so'ragan maydonlarni to'ldiradi.

    Parol faqat parol maydoni bor qadamga qo'yiladi. `protectsdk` kabi
    maydonlar bo'sh ketadi: ular brauzer SDK si to'ldiradigan qiymatlar va
    ularni soxtalashtirish noto'g'ri bo'lardi.

    **Tugma maydoni bo'sh ketolmaydi.** Login qadamida `buttonValue` bo'sh
    yuborilganda server 400 bilan «qaysi tugma bosilgani aniqlanmadi» degan
    edi: DaVinci uchun tugma ham maydon, foydalanuvchi nimani bosgani shu
    orqali bilinadi.
    """
    chosen = button_value or (node.button_candidates() or [""])[0]
    btype = node.button_type_for(chosen)
    params: dict = {"buttonType": btype, "buttonValue": chosen}
    pass_field, user_field = node.password_field, node.user_field
    for item in node.fields:
        name = item["name"]
        if name == pass_field:
            params[name] = password
        elif name == user_field:
            params[name] = email
        elif BUTTON_RE.match(name):
            params[name] = btype if name.lower() == "buttontype" else chosen
        else:
            params[name] = ""
    if pass_field and not user_field:
        params.setdefault("username", email)
    return params


def advance(
    session: requests.Session,
    widget: WidgetConfig,
    node: Node,
    email: str,
    password: str,
) -> tuple[object, Node, Step]:
    """Bitta qadamni oldinga suradi: (javob, keyingi qadam, hisobot).

    Qadamda tugma maydoni bo'lsa va server tugma haqida shikoyat qilsa,
    boshqa nomzod qiymat bilan qayta yuboriladi — bu bir marta yo'l qo'yilgan
    xato edi va endi o'zi tuzaladi.
    """
    url = (f"{widget.base()}/connections/{node.connection_id}"
           f"/capabilities/{node.capability}")
    step = Step(name=f"qadam:{node.kind()}", url=url)
    candidates = node.button_candidates() if node.button_fields else [""]

    response = payload = None
    for index, candidate in enumerate(candidates):
        body = {
            "id": node.node_id,
            "eventName": (node.next_event or DEFAULT_EVENT).get(
                "eventName", "continue"),
            "nextEvent": node.next_event or DEFAULT_EVENT,
            "parameters": node_parameters(node, email, password, candidate),
        }
        try:
            response = session.post(
                url, json=body, headers=_flow_headers(widget, node), timeout=30)
        except Exception as exc:
            step.detail = f"{type(exc).__name__}: {exc}"
            return None, Node(), step

        step.status = response.status_code
        payload, step.shape = _body(response)
        if response.status_code == 200:
            if candidate and index:      # birinchisi o'tmagan bo'lsa — yozib qo'yamiz
                step.attempts.append({
                    "buttonValue": candidate, "status": 200, "natija": "OK"})
            break

        # Parol hech qachon hisobotga tushmaydi — faqat serverning xatosi
        message = error_text(payload)
        if candidate:
            step.attempts.append({
                "buttonValue": candidate, "status": response.status_code,
                "natija": "OK" if response.status_code == 200 else message[:200],
            })
        last = index == len(candidates) - 1
        if last or not BUTTON_ERROR_RE.search(message):
            step.detail = f"HTTP {response.status_code} — {message}"
            return payload, Node(), step

    step.ok = True
    nxt = parse_node(payload, session, response)
    # Interaction ma'lumoti keyingi qadamga o'tadi
    nxt.interaction_id = nxt.interaction_id or node.interaction_id
    nxt.interaction_token = nxt.interaction_token or node.interaction_token
    step.detail = (
        f"yuborildi ({', '.join(node.field_names) or 'maydonsiz'}) → "
        + (nxt.describe() if nxt.ok else "oqim tugadi")
    )
    return payload, nxt, step


# ------------------------------------------------------------------ 5. resume
def resume(
    session: requests.Session, widget: WidgetConfig, dv_response: str
) -> tuple[str, Step]:
    """`dvResponse` ni `/as/resume` ga yuborib, avtorizatsiya kodini oladi."""
    url = widget.resume_url or f"{ACCOUNT}/as/resume"
    step = Step(name="resume", url=url)
    if not widget.state:
        step.detail = "state topilmadi — authorize sahifasida forma yo'q edi"
        return "", step
    try:
        response = session.post(
            url,
            data={"dvResponse": dv_response, "state": widget.state},
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Referer": f"{ACCOUNT}/"},
            allow_redirects=False, timeout=30,
        )
    except Exception as exc:
        step.detail = f"{type(exc).__name__}: {exc}"
        return "", step

    step.status = response.status_code
    location = response.headers.get("Location", "")
    code = ""
    if location:
        parsed = urlparse(location)
        code = (parse_qs(parsed.query).get("code") or [""])[0]
        if not code:
            code = (parse_qs(parsed.fragment).get("code") or [""])[0]
    if not code:
        payload, step.shape = _body(response)
        code = find_code(payload) if isinstance(payload, dict) else ""
    if code:
        step.ok = True
        step.detail = "kod olindi"
    else:
        step.detail = (
            f"HTTP {response.status_code}; kod topilmadi"
            + (f"; Location: {urlparse(location).path}" if location
               else "; Location yo'q")
        )
    return code, step


# ------------------------------------------------------------------ 6. token
def exchange_code(
    session: requests.Session, params: dict, code: str, verifier: str
) -> tuple[str, Step]:
    step = Step(name="token", url=f"{ACCOUNT}/as/token")
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": verifier,
        "client_id": params.get("client_id", ""),
        "redirect_uri": params.get("redirect_uri") or FPL_HOME,
    }
    try:
        response = session.post(
            step.url, data=data, timeout=25,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    except Exception as exc:
        step.detail = f"{type(exc).__name__}: {exc}"
        return "", step

    step.status = response.status_code
    payload, step.shape = _body(response)
    token = payload.get("access_token", "") if isinstance(payload, dict) else ""
    if token:
        step.ok = True
        step.detail = "access_token olindi"
    else:
        step.detail = f"HTTP {response.status_code} — {error_text(payload)}"
    return token, step


# ------------------------------------------------------------------ umumiy
MAX_NODES = 8


def login(
    email: str,
    password: str,
    session: requests.Session | None = None,
    redirect_uri: str = "",
    max_nodes: int = MAX_NODES,
) -> SsoResult:
    """To'liq oqim. Parol faqat parol maydoni bor qadamga beriladi."""
    session = session or new_session()
    result = SsoResult()

    params, step = discover_authorize(session, redirect_uri)
    result.steps.append(step)
    if not step.ok:
        result.hint = "FPL sahifasidan login parametrlari topilmadi."
        return result

    verifier, challenge = pkce_pair()
    widget, step = start_authorize(session, params, challenge, secrets.token_urlsafe(16))
    result.steps.append(step)
    if not step.ok:
        result.hint = "PingOne widget sozlamasi kelmadi."
        return result

    node, step = start_policy(session, widget)
    result.steps.append(step)
    if not step.ok:
        result.hint = "DaVinci oqimi boshlanmadi."
        return result

    # Qadamlar zanjiri: har biri nima so'rasa, shuni beramiz
    dv_response, sent_password = "", False
    for _ in range(max_nodes):
        if node.wants_credentials:
            sent_password = True
        payload, nxt, step = advance(session, widget, node, email, password)
        result.steps.append(step)
        if not step.ok:
            result.hint = ("Parol qabul qilinmadi." if sent_password
                           else "Oqim qadamida to'xtadi.")
            return result
        dv_response = find_dv_response(payload)
        if dv_response:
            break
        if not nxt.ok:
            result.steps.append(Step(
                name="oqim",
                detail="Qadam tugadi, lekin dvResponse kelmadi. Kalitlar: "
                       + ", ".join(_shape(payload)[:20])))
            result.hint = "Oqim kutilmaganda tugadi."
            return result
        # Parolni yuborgandan keyin yana email so'ralsa — oqim boshqa
        # shoxobchaga (ro'yxatdan o'tish / parolni tiklash) ketgan
        if sent_password and nxt.user_field and not nxt.password_field:
            result.steps.append(Step(
                name="oqim",
                detail=(f"Paroldan keyin yana '{nxt.user_field}' so'ralmoqda — "
                        f"oqim kirish shoxobchasidan chiqib ketdi. "
                        f"Tugmalar: {', '.join(node.button_candidates()) or '—'}")))
            result.hint = ("Login o'rniga boshqa shoxobcha ochildi "
                           "(tugma tanlovi yoki hisob holati).")
            return result
        node = nxt
    else:
        result.steps.append(Step(
            name="oqim", detail=f"{max_nodes} qadamdan keyin ham tugamadi"))
        result.hint = "Oqim juda uzun — qo'shimcha tasdiqlash bo'lishi mumkin."
        return result

    if not sent_password:
        result.steps.append(Step(
            name="oqim", detail="Parol so'raladigan qadam umuman uchramadi"))
        result.hint = "Login formasi topilmadi."
        return result

    code, step = resume(session, widget, dv_response)
    result.steps.append(step)
    if not code:
        result.hint = "dvResponse kodga almashmadi."
        return result

    token, step = exchange_code(session, params, code, verifier)
    result.steps.append(step)
    if not token:
        result.hint = "Kod tokenga almashmadi."
        return result

    result.ok, result.token = True, token
    return result
