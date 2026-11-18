"""PingOne DaVinci oqimi — tarmoqsiz sinovlar.

Soxta server haqiqiy javoblarning shaklini takrorlaydi (`sso_probe` bergan
ma'lumot asosida):

  authorize → skProps + `/as/resume` formasi va `state`
  start     → PingOne **Protect** qadami (yagona maydoni `protectsdk`)
  qadam 1   → login qadami (username/password)
  qadam 2   → `dvResponse`
  resume    → 302, `Location` ichida `code`
  token     → `access_token`

Diqqat: birinchi qadam login formasi EMAS — model shuni to'g'ri o'tishi kerak.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fplbrain import pl_sso

CLIENT_ID = "11111111-2222-3333-4444-555555555555"
REDIRECT = "https://fantasy.premierleague.com/"
API_ROOT = "https://account.premierleague.com"
COMPANY = "company-abc"
POLICY = "policy-xyz"
SDK_TOKEN = "sdk-token-123456"
STATE = "0e61704b-10db-4634-8569-5e29d230b8a3"
CODE = "authcode-abc"
TOKEN = "eyJhbGciOiJIUzI1NiJ9.payload.signature"
DV_RESPONSE = "dv-response-blob"

AUTHORIZE_LINK = (
    f"https://account.premierleague.com/as/authorize?client_id={CLIENT_ID}"
    f"&redirect_uri={REDIRECT}&response_type=code&scope=openid+profile"
)
HOME_HTML = f'<html><body><a href="{AUTHORIZE_LINK}">Sign In</a></body></html>'

AUTHORIZE_HTML = """
<html><body>
<form id="pingOneDaVinciResponseForm" method="POST" action="%s/as/resume">
  <input type="hidden" id="dvResponse" name="dvResponse" value="">
  <input type="hidden" id="state" name="state" value="%s">
</form>
<script>var skProps = {"method":"runFlow","apiRoot":"%s","accessToken":"%s",
"companyId":"%s","policyId":"%s","passCredentialsToCapabilities":false}</script>
</body></html>
""" % (API_ROOT, STATE, API_ROOT, SDK_TOKEN, COMPANY, POLICY)


def _node(node_id: str, capability: str, fields: list, extra: dict | None = None) -> dict:
    """DaVinci qadami — haqiqiy javob shaklida."""
    payload = {
        "id": node_id,
        "flowId": "flow-1",
        "interactionId": "int-1",
        "connectionId": f"conn-{node_id}",
        "capabilityName": capability,
        "resetCookie": True,
        "_links": {"self": {"href": f"{API_ROOT}/davinci/policy/{POLICY}/start"}},
        "screen": {
            "name": "HTTP",
            "properties": {
                "formFieldsList": {
                    "type": "array",
                    "constructType": "formFieldsList",
                    "value": fields,
                },
                "button": {
                    "constructType": "button",
                    "onClick": {"constructType": "skEvent", "eventName": "continue",
                                "params": [], "eventType": "post", "postProcess": {}},
                },
            },
        },
    }
    payload.update(extra or {})
    return payload


PROTECT_NODE = _node("node-protect", "customHTMLTemplate", [
    {"propertyName": "protectsdk", "displayName": "Protect Payload",
     "preferredControlType": "textField", "preferredDataType": "string", "value": ""},
])
# Haqiqiy shablon: "Register" tugmasi "Sign in" dan OLDIN turadi
LOGIN_HTML = (
    '<div><a data-skcomponent="skbutton" data-skbuttonvalue="REGISTER" '
    'data-skbuttontype="next">Register</a>'
    '<input name="username"><input type="password" name="password">'
    '<button data-skcomponent="skbutton" data-skbuttonvalue="SIGNON" '
    'data-skbuttontype="form-submit">Sign in</button>'
    '<a data-skcomponent="skbutton" data-skbuttonvalue="FORGOTTEN_PASSWORD" '
    'data-skbuttontype="next">Forgot password?</a></div>'
)
# Haqiqiy javobda uchta maydon bor: `buttonValue` ham maydon
LOGIN_FIELDS = [
    {"propertyName": "username", "displayName": "Email",
     "preferredControlType": "textField", "preferredDataType": "string"},
    {"propertyName": "buttonValue", "displayName": "Button",
     "preferredControlType": "button", "preferredDataType": "string"},
    {"propertyName": "password", "displayName": "Password",
     "preferredControlType": "passwordField", "preferredDataType": "string"},
]
LOGIN_NODE = _node("node-login", "customHTMLTemplate", LOGIN_FIELDS,
                   {"customHTML": LOGIN_HTML})
# HTML siz variant: qiymat faqat zaxira ro'yxatidan topilishi kerak
LOGIN_NODE_NO_HTML = _node("node-login", "customHTMLTemplate", LOGIN_FIELDS)
# Serverning haqiqiy xatosi — bo'sh `buttonValue` yuborilganda shu keladi
BUTTON_ERROR = {
    "message": "An unexpected error has occurred",
    "description": "Could not determine what button was selected by the user",
    "code": "Unexpected value received",
    "httpResponseCode": 400,
}
# "Register" bosilsa server 200 qaytaradi, lekin ro'yxatdan o'tish ekraniga
# olib boradi — haqiqiy oqimda aynan shunday bo'lgan
REGISTER_NODE = _node("node-register", "customHTMLTemplate", [
    {"propertyName": "email", "displayName": "Email",
     "preferredControlType": "textField", "preferredDataType": "string"},
    {"propertyName": "buttonValue", "displayName": "Button",
     "preferredControlType": "button", "preferredDataType": "string"},
])
# Paroldan keyingi oraliq ekran: faqat tugma so'raydi
INTERSTITIAL_HTML = (
    '<p>Keep me signed in</p>'
    '<a data-skcomponent="skbutton" data-skbuttonvalue="REGISTER" '
    'data-skbuttontype="next-event">Register</a>'
    '<button data-skcomponent="skbutton" data-skbuttonvalue="CONTINUE" '
    'data-skbuttontype="form-submit">Continue</button>'
)
INTERSTITIAL_NODE = _node("node-mid", "customHTMLTemplate", [
    {"propertyName": "buttonValue", "displayName": "Button",
     "preferredControlType": "button", "preferredDataType": "string"},
], {"customHTML": INTERSTITIAL_HTML})
DONE_NODE = {"id": "node-done", "dvResponse": DV_RESPONSE, "status": "COMPLETED"}


class FakeResponse:
    def __init__(self, status=200, body="", payload=None, headers=None):
        self.status_code = status
        self._payload = payload
        self.text = body if payload is None else json.dumps(payload)
        self.headers = headers or {}
        self.cookies: dict = {}

    def json(self):
        if self._payload is None:
            raise ValueError("JSON emas")
        return self._payload


class FakeSession:
    """Haqiqiy oqim shaklini takrorlaydigan soxta sessiya."""

    def __init__(self, start_reject=(), fail_login=False, resume_status=302,
                 authorize_body=AUTHORIZE_HTML, accepts_button="SIGNON",
                 login_node=LOGIN_NODE, interstitial=False):
        self.headers: dict = {}
        # Haqiqiy holat: interactionToken cookie si YO'Q
        self.cookies: dict = {"__cf_bm": "x", "interactionId": "int-1"}
        self.calls: list[tuple[str, str]] = []
        self.bodies: list[dict] = []
        self.start_reject = start_reject
        self.fail_login = fail_login
        self.resume_status = resume_status
        self.authorize_body = authorize_body
        # Server faqat shu tugma qiymatini qabul qiladi
        self.accepts_button = accepts_button
        self.login_node = login_node
        self.interstitial = interstitial
        self.buttons: list[str] = []

    # -------------------------------------------------------------- GET
    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append(("GET", url))
        if url == pl_sso.FPL_HOME:
            return FakeResponse(body=HOME_HTML)
        if url.endswith("/as/authorize"):
            self.last_authorize_params = params or {}
            return FakeResponse(body=self.authorize_body)
        return FakeResponse(status=404, body="")

    # ------------------------------------------------------------- POST
    def post(self, url, json=None, data=None, headers=None, timeout=None,
             allow_redirects=True):
        self.calls.append(("POST", url))
        if url.endswith("/start"):
            self.last_start_headers = headers
            if any(bit in url for bit in self.start_reject):
                return FakeResponse(status=403, payload={"message": "Forbidden"})
            return FakeResponse(payload=PROTECT_NODE)

        if "/connections/" in url:
            self.bodies.append(json or {})
            self.last_headers = headers
            params = (json or {}).get("parameters", {})
            if "protectsdk" in params:
                return FakeResponse(payload=self.login_node)
            if "password" in params:
                pressed = params.get("buttonValue", "")
                self.buttons.append(pressed)
                # "Register" bosilsa — xato emas, boshqa shoxobcha
                if pressed in ("REGISTER", "FORGOTTEN_PASSWORD"):
                    return FakeResponse(payload=REGISTER_NODE)
                # Bo'sh yoki notanish qiymat — serverning haqiqiy 400 xatosi
                if pressed != self.accepts_button:
                    return FakeResponse(status=400, payload=BUTTON_ERROR)
                if self.fail_login:
                    return FakeResponse(
                        status=400,
                        payload={"message": "Invalid username or password"})
                return FakeResponse(
                    payload=INTERSTITIAL_NODE if self.interstitial else DONE_NODE)

            # Faqat tugma so'raydigan oraliq ekran
            if set(params) <= {"buttonValue", "buttonType"}:
                pressed = params.get("buttonValue", "")
                self.buttons.append(pressed)
                if pressed == "CONTINUE":
                    return FakeResponse(payload=DONE_NODE)
                return FakeResponse(status=400, payload=BUTTON_ERROR)
            return FakeResponse(status=400, payload={"message": "kutilmagan qadam"})

        if url.endswith("/as/resume"):
            self.last_resume = data
            if self.resume_status == 302:
                return FakeResponse(status=302, headers={
                    "Location": f"{REDIRECT}?code={CODE}&state={STATE}"})
            return FakeResponse(status=self.resume_status,
                                payload={"message": "kod yo'q"})

        if url.endswith("/as/token"):
            self.last_token_data = data
            return FakeResponse(payload={"access_token": TOKEN, "token_type": "Bearer"})
        return FakeResponse(status=404, body="")


# ------------------------------------------------------------------- PKCE
def test_pkce_juftligi_standartga_mos():
    verifier, challenge = pl_sso.pkce_pair()
    assert 43 <= len(verifier) <= 128
    assert "=" not in verifier and "=" not in challenge
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    assert challenge == expected
    assert pl_sso.pkce_pair()[0] != verifier


# ------------------------------------------------------------- authorize
def test_authorize_widget_va_resume_formasini_beradi():
    widget = pl_sso.extract_widget(AUTHORIZE_HTML)
    assert widget.ok
    assert widget.api_root == API_ROOT
    assert widget.policy_id == POLICY
    assert widget.resume_url == f"{API_ROOT}/as/resume"
    # `state` ni PingOne beradi — biz yuborgan qiymat emas
    assert widget.state == STATE


def test_widget_tashxisida_maxfiy_qiymat_chiqmaydi():
    widget = pl_sso.extract_widget(AUTHORIZE_HTML)
    dumped = json.dumps(widget.as_dict(), ensure_ascii=False)
    assert SDK_TOKEN not in dumped and STATE not in dumped
    assert widget.as_dict()["accessToken_bormi"] is True
    assert widget.as_dict()["state_bormi"] is True


def test_authorize_pkce_bilan_chaqiriladi():
    session = FakeSession()
    params, _ = pl_sso.discover_authorize(session)
    _, challenge = pl_sso.pkce_pair()
    widget, step = pl_sso.start_authorize(session, params, challenge, "state1")
    assert step.ok and widget.ok
    sent = session.last_authorize_params
    assert sent["code_challenge"] == challenge
    assert sent["code_challenge_method"] == "S256"
    assert sent["client_id"] == CLIENT_ID


# ------------------------------------------------ discovery: yangi bundle
# 2026-11 dagi haqiqiy sahifa shakli. Uch tuzoq:
#   1. bosh sahifada BOSHQA ilovalarning `clientId` lari bor (premierleague.com)
#   2. FPL ning o'z bundle'i uchinchi tomon skriptlaridan KEYIN turadi
#   3. bundle satrlarni backtick bilan yozadi: client_id:`…`
WWW_CLIENT_ID = "1f243d70-a140-4035-8c41-341f5af5aa12"
U13_CLIENT_ID = "c2906aae-cb6e-44d1-838f-0d3565380c06"
BUNDLE_HOME_HTML = """<!doctype html><html><head>
<script charset="UTF-8" src="https://cdn.example.com/a.js" type="text/javascript"></script>
<script src="https://cdn.example.com/b.js"></script>
<script defer="" src="https://cdn.example.com/c.js"></script>
<script>window.PULSE.envPaths = {sso: {authUrl: "https://account.premierleague.com",
  clientId: "%s", u13AppId: "%s"}};</script>
<script src="//translations.example.com/en.js"></script>
<script type="module" crossorigin src="/assets/index-CMoSnM_-.js"></script>
</head><body></body></html>""" % (WWW_CLIENT_ID, U13_CLIENT_ID)
BUNDLE_JS = (
    "gz=new _I({authority:`https://account.premierleague.com/as`,"
    "client_id:`%s`,redirect_uri:`${window.location.origin}/`,"
    "scope:`openid profile email offline_access`}),"
    "Rpe=new _I({authority:`https://account.premierleague.com/as`,"
    "client_id:`%s`,redirect_uri:`${window.location.origin}/`})"
) % (CLIENT_ID, U13_CLIENT_ID)


class BundleSession(FakeSession):
    def __init__(self, noise_scripts=0):
        super().__init__()
        noise = "".join(f'<script src="https://cdn.example.com/n{i}.js"></script>'
                        for i in range(noise_scripts))
        self.home = BUNDLE_HOME_HTML.replace("<head>", "<head>" + noise)

    def get(self, url, params=None, timeout=None, headers=None):
        if url == pl_sso.FPL_HOME:
            self.calls.append(("GET", url))
            return FakeResponse(body=self.home)
        if url == "https://fantasy.premierleague.com/assets/index-CMoSnM_-.js":
            self.calls.append(("GET", url))
            return FakeResponse(body=BUNDLE_JS)
        return super().get(url, params=params, timeout=timeout, headers=headers)


def test_discovery_backtickli_bundledan_client_id_topadi():
    params, step = pl_sso.discover_authorize(BundleSession())
    assert step.ok, step.detail
    # Aynan FPL ilovasining ID si — bosh sahifadagi yoki U13 niki emas
    assert params["client_id"] == CLIENT_ID


def test_discovery_begona_skriptlar_bundleni_surib_chiqarmaydi():
    # Oldinda 10 ta uchinchi tomon skripti: o'z bundle'imiz baribir o'qiladi
    params, step = pl_sso.discover_authorize(BundleSession(noise_scripts=10))
    assert step.ok, step.detail
    assert params["client_id"] == CLIENT_ID


# ---------------------------------------------------------- qadam tahlili
def test_qadam_maydonlari_json_dan_oqiladi():
    """`screen` HTML emas — maydonlar `formFieldsList` da."""
    node = pl_sso.parse_node(PROTECT_NODE)
    assert node.ok
    assert node.field_names == ["protectsdk"]
    assert node.kind() == "protect"
    assert node.wants_credentials is False
    assert node.next_event["eventName"] == "continue"


def test_login_qadami_tanib_olinadi():
    node = pl_sso.parse_node(LOGIN_NODE)
    assert node.wants_credentials is True
    assert node.password_field == "password"
    assert node.user_field == "username"
    assert node.kind() == "login"


def test_parol_faqat_parol_qadamiga_qoyiladi():
    """Protect qadamiga parol yuborilmasligi SHART."""
    protect = pl_sso.parse_node(PROTECT_NODE)
    params = pl_sso.node_parameters(protect, "a@b.uz", "MAXFIY")
    assert params["protectsdk"] == ""
    assert "MAXFIY" not in json.dumps(params)

    login = pl_sso.parse_node(LOGIN_NODE)
    params = pl_sso.node_parameters(login, "a@b.uz", "MAXFIY")
    assert params["username"] == "a@b.uz"
    assert params["password"] == "MAXFIY"


def test_tugma_qiymati_bosh_ketmaydi():
    """Bo'sh `buttonValue` — server rad etgan haqiqiy xato edi."""
    login = pl_sso.parse_node(LOGIN_NODE)
    params = pl_sso.node_parameters(login, "a@b.uz", "MAXFIY")
    assert params["buttonValue"] == "SIGNON"      # HTML shablonidan olindi
    assert params["buttonType"] == "form-submit"


def test_register_tugmasi_hech_qachon_bosilmaydi():
    """Parol yuborilayotgan qadamda "Register" tanlanmasligi SHART."""
    login = pl_sso.parse_node(LOGIN_NODE)
    assert [b["value"] for b in login.buttons] == [
        "REGISTER", "SIGNON", "FORGOTTEN_PASSWORD"]     # hammasi topildi
    candidates = login.button_candidates()
    assert candidates[0] == "SIGNON"                    # birinchisi emas, mosi
    assert "REGISTER" not in candidates
    assert "FORGOTTEN_PASSWORD" not in candidates


def test_tugma_turi_qiymati_bilan_juft_olinadi():
    """"Register" ning turi "Sign in" ning qiymatiga yopishib qolmasin."""
    login = pl_sso.parse_node(LOGIN_NODE)
    params = pl_sso.node_parameters(login, "a@b.uz", "MAXFIY")
    assert params["buttonValue"] == "SIGNON"
    assert params["buttonType"] == "form-submit"        # "next" emas


def test_notogri_shoxobchaga_ketsa_aniq_aytiladi():
    """200 kelgani oqim to'g'ri ketdi degani emas."""
    session = FakeSession(accepts_button="__hech_qachon__")

    class Register(FakeSession):
        def post(self, url, json=None, data=None, headers=None, timeout=None,
                 allow_redirects=True):
            if "/connections/" in url and "password" in (json or {}).get(
                    "parameters", {}):
                self.buttons.append((json or {})["parameters"]["buttonValue"])
                return FakeResponse(payload=REGISTER_NODE)
            return super().post(url, json=json, data=data, headers=headers,
                                timeout=timeout, allow_redirects=allow_redirects)

    session = Register()
    result = pl_sso.login("a@b.uz", "MAXFIY", session=session)
    assert result.ok is False
    assert "shoxobcha" in result.hint
    detail = " ".join(s.detail for s in result.steps)
    assert "email" in detail                 # nima so'ralgani aytiladi
    assert "MAXFIY" not in json.dumps(result.as_dict())


def test_paroldan_keyingi_oraliq_ekran_otiladi():
    """Parol o'tgani bilan oqim tugamasligi mumkin."""
    session = FakeSession(interstitial=True)
    result = pl_sso.login("a@b.uz", "MAXFIY", session=session)
    assert result.ok is True and result.token == TOKEN
    assert session.buttons == ["SIGNON", "CONTINUE"]   # Register bosilmadi


def test_oraliq_ekranda_ham_register_bosilmaydi():
    node = pl_sso.parse_node(INTERSTITIAL_NODE)
    assert node.wants_credentials is False             # parol maydoni yo'q
    assert node.button_candidates()[0] == "CONTINUE"
    assert "REGISTER" not in node.button_candidates()


def test_ekran_matni_oqiladi():
    """Oraliq ekran nima deyayotgani ko'rinishi kerak."""
    assert "Keep me signed in" in pl_sso.screen_text(INTERSTITIAL_NODE)


def test_tugma_qiymati_html_dan_oqiladi_taxmin_qilinmaydi():
    node = pl_sso.parse_node(
        _node("n", "customHTMLTemplate", LOGIN_FIELDS,
              {"customHTML": '<button data-skbuttonvalue="LOGIN_BTN" '
                             'data-skbuttontype="next">Kirish</button>'}))
    assert node.buttons == [{"value": "LOGIN_BTN", "type": "next"}]
    params = pl_sso.node_parameters(node, "a@b.uz", "MAXFIY")
    assert params["buttonValue"] == "LOGIN_BTN"   # zaxira ro'yxati emas
    assert params["buttonType"] == "next"


def test_tugma_rad_etilsa_boshqa_qiymat_sinaladi():
    """HTML jim bo'lsa ham oqim to'xtamaydi — nomzodlar ketma-ket sinaladi."""
    session = FakeSession(accepts_button="submit", login_node=LOGIN_NODE_NO_HTML)
    result = pl_sso.login("a@b.uz", "MAXFIY", session=session)
    assert result.ok is True
    assert session.buttons[0] == "SIGNON" and session.buttons[-1] == "submit"
    step = next(s for s in result.steps if s.name == "qadam:login")
    assert step.ok is True and len(step.attempts) >= 2


def test_tugma_urinishlari_hisobotda_parolsiz_koinadi():
    session = FakeSession(accepts_button="submit", login_node=LOGIN_NODE_NO_HTML)
    result = pl_sso.login("a@b.uz", "MAXFIY", session=session)
    assert "MAXFIY" not in json.dumps(result.as_dict())


def test_interaction_token_yoq_deb_belgilanadi():
    """`interactionId` cookie si token deb olinmasligi kerak."""
    session = FakeSession()
    value, source = pl_sso.interaction_token(FakeResponse(payload={}), session, {})
    assert value == "" and source == ""


def test_nomida_token_bor_cookie_olinadi():
    session = FakeSession()
    session.cookies = {"interactionToken": "haqiqiy"}
    value, source = pl_sso.interaction_token(FakeResponse(payload={}), session, {})
    assert value == "haqiqiy"
    assert "interactionToken" in source


# ------------------------------------------------------------ start qadami
def test_start_protect_qadamini_qaytaradi():
    session = FakeSession()
    widget = pl_sso.extract_widget(AUTHORIZE_HTML)
    node, step = pl_sso.start_policy(session, widget)
    assert step.ok
    assert ("POST", f"{API_ROOT}/davinci/policy/{POLICY}/start") in session.calls
    assert node.kind() == "protect"
    assert widget.flow_base == f"{API_ROOT}/davinci"
    assert session.last_start_headers["Authorization"] == f"Bearer {SDK_TOKEN}"


def test_birinchi_shakl_otmasa_ikkinchisi_sinaladi():
    session = FakeSession(start_reject=("/davinci/",))
    widget = pl_sso.extract_widget(AUTHORIZE_HTML)
    node, step = pl_sso.start_policy(session, widget)
    assert step.ok and node.ok
    assert widget.flow_base == f"{API_ROOT}/v1/company/{COMPANY}"


def test_hech_bir_shakl_otmasa_xabar_saqlanadi():
    session = FakeSession(start_reject=("/davinci/", "/v1/company/"))
    widget = pl_sso.extract_widget(AUTHORIZE_HTML)
    _, step = pl_sso.start_policy(session, widget)
    assert step.ok is False
    assert "Forbidden" in step.detail
    assert len(step.attempts) == 2


# ---------------------------------------------------------- to'liq oqim
def test_toliq_oqim_token_bilan_tugaydi():
    session = FakeSession()
    result = pl_sso.login("a@b.uz", "parol", session=session)
    assert result.ok is True, result.hint
    assert result.token == TOKEN
    assert [s.name for s in result.steps] == [
        "discovery", "authorize", "start",
        "qadam:protect", "qadam:login", "resume", "token",
    ]
    assert all(s.ok for s in result.steps)


def test_protect_qadami_avtomatik_otiladi():
    """Zanjir: protect → login. Parol birinchi qadamga ketmasligi kerak."""
    session = FakeSession()
    pl_sso.login("a@b.uz", "MAXFIY", session=session)
    first, second = session.bodies[0], session.bodies[1]
    assert "MAXFIY" not in json.dumps(first)
    assert second["parameters"]["password"] == "MAXFIY"


def test_resume_dvresponse_va_state_bilan_ketadi():
    session = FakeSession()
    pl_sso.login("a@b.uz", "parol", session=session)
    assert session.last_resume == {"dvResponse": DV_RESPONSE, "state": STATE}
    assert session.last_token_data["code"] == CODE
    assert session.last_token_data["code_verifier"]


def test_notogri_parol_aniq_aytiladi():
    session = FakeSession(fail_login=True)
    result = pl_sso.login("a@b.uz", "notogri", session=session)
    assert result.ok is False
    failed = result.failed_step
    assert failed.name == "qadam:login"
    assert "Invalid username or password" in failed.detail
    assert "parol" in result.hint.lower()


def test_parol_xato_hisobotiga_tushmaydi():
    session = FakeSession(fail_login=True)
    result = pl_sso.login("a@b.uz", "JUDA-MAXFIY", session=session)
    assert "JUDA-MAXFIY" not in json.dumps(result.as_dict(), ensure_ascii=False)


def test_resume_kod_bermasa_qayerda_toxtagani_aytiladi():
    session = FakeSession(resume_status=400)
    result = pl_sso.login("a@b.uz", "parol", session=session)
    assert result.ok is False
    assert result.failed_step.name == "resume"
    assert result.failed_step.status == 400


def test_state_topilmasa_resume_urinmaydi():
    html = AUTHORIZE_HTML.replace(f'value="{STATE}"', 'value=""')
    session = FakeSession(authorize_body=html)
    result = pl_sso.login("a@b.uz", "parol", session=session)
    assert result.ok is False
    assert "state" in result.failed_step.detail.lower()


def test_zanjir_cheksiz_ketmaydi():
    """Har qadam yana protect qaytarsa — model to'xtashi kerak."""
    class Loop(FakeSession):
        def post(self, url, json=None, data=None, headers=None, timeout=None,
                 allow_redirects=True):
            if "/connections/" in url:
                self.bodies.append(json or {})
                return FakeResponse(payload=PROTECT_NODE)
            return super().post(url, json=json, data=data, headers=headers,
                                timeout=timeout, allow_redirects=allow_redirects)

    result = pl_sso.login("a@b.uz", "parol", session=Loop(), max_nodes=3)
    assert result.ok is False
    assert "uzun" in result.hint.lower()


def test_natija_lugatida_token_sukut_boyicha_yoq():
    session = FakeSession()
    result = pl_sso.login("a@b.uz", "parol", session=session)
    assert "token" not in result.as_dict()
    assert result.as_dict(include_token=True)["token"] == TOKEN


# --------------------------------------------------------------- tashxis
def test_server_xatosi_matni_saqlanadi():
    assert pl_sso.error_text({"message": "Forbidden"}) == "message=Forbidden"
    assert "error=invalid_grant" in pl_sso.error_text(
        {"error": "invalid_grant", "error_description": "redirect_uri mismatch"})
    text = pl_sso.error_text({"someSecret": "juda-maxfiy"})
    assert "juda-maxfiy" not in text and "someSecret" in text


def test_oqim_tuzilishi_screensiz_yigiladi():
    debug = pl_sso.flow_debug(PROTECT_NODE)
    assert "screen" not in debug
    assert "resetCookie" in debug
    full = pl_sso.flow_debug(PROTECT_NODE, include_screen=True)
    assert "protectsdk" in full["screen"]
