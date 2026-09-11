"""Web qatlami: o'yinchilar ro'yxati API si va kirish mantiqi.

Hech bir sinov tarmoqqa chiqmaydi — tashqi so'rov qiladigan joylar
almashtiriladi.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fplbrain import auth as auth_mod
from fplbrain.config import Config
from web.app import create_app, team_matches_played
from tests.fake import make_bootstrap, make_fixtures


@pytest.fixture(scope="module")
def client():
    app = create_app(Config(), demo=True)
    return app.test_client()


# --------------------------------------------------------- o'yinchilar API
def test_royxat_loginsiz_keladi(client):
    """Asosiy vazifa: ro'yxat hech qanday kirishsiz ishlashi kerak."""
    r = client.get("/api/players")
    assert r.status_code == 200
    data = r.get_json()
    assert len(data["players"]) > 300
    assert len(data["teams"]) == 20
    assert len(data["positions"]) == 4


def test_royxatda_kerakli_metrikalar_bor(client):
    """Foydalanuvchi so'ragan formulaning har bir bo'lagi javobda bo'lsin."""
    row = client.get("/api/players").get_json()["players"][0]
    for key in (
        "ownership", "price", "starts", "minutes", "minutes_share",
        "goals", "assists", "ga", "xg", "xa", "xgi",
        "in_event", "out_event", "net", "momentum",
        "role", "output90", "value", "score", "enabler",
    ):
        assert key in row, f"«{key}» ko'rsatkichi yo'q"


def test_enabler_belgilanadi(client):
    players = client.get("/api/players").get_json()["players"]
    for p in players:
        if p["enabler"]:
            # arzon + ommaviy + kam o'ynagan
            assert p["price"] <= 4.6 and p["ownership"] >= 8.0
            assert p["minutes_share"] < 35.0


def test_kesh_ishlaydi_va_yangilanadi(client):
    first = client.get("/api/players").get_json()["generated"]
    assert client.get("/api/players").get_json()["generated"] == first
    assert client.get("/api/players?refresh=1").get_json()["generated"] >= first


# ------------------------------------------------------------------ holat
def test_holat_loginsiz(client):
    body = client.get("/api/status").get_json()
    assert body["logged_in"] is False
    assert body["demo"] is True


def test_me_loginsiz_401(client):
    assert client.get("/api/me").status_code == 401


def test_login_bosh_soro_400(client):
    r = client.post("/api/login", json={})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False


# ---------------------------------------------------- tugagan o'yinlar soni
def test_yarim_oynalgan_tur_sanalmaydi():
    """Jamoa nechta o'yin o'ynagani — faqat TUGAGAN uchrashuvlardan."""
    bs = make_bootstrap(played=2)
    fx = make_fixtures(bs, from_gw=1, to_gw=3)
    for f in fx:
        f["finished"] = f["finished_provisional"] = f["event"] <= 2
    played = team_matches_played(bs, fx)
    assert set(played.values()) == {2}


def test_tugagan_oyin_bolmasa_bootstrapga_qaytadi():
    bs = make_bootstrap(played=3)
    played = team_matches_played(bs, [])
    assert set(played.values()) == {3}


# --------------------------------------------------------------- kirish
def test_credentials_sarlavhalari():
    token = auth_mod.Credentials(token="abc")
    assert token.headers()["X-Api-Authorization"] == "Bearer abc"
    assert "Cookie" not in token.headers()

    cookie = auth_mod.Credentials(cookie="sessionid=xyz")
    assert cookie.headers()["Cookie"] == "sessionid=xyz"
    assert "X-Api-Authorization" not in cookie.headers()

    assert auth_mod.Credentials().headers() == {}
    assert auth_mod.Credentials().ok is False


@pytest.mark.parametrize("raw, expect_token", [
    ("Bearer eyJhbGciOi.payload.sig", True),
    ("eyJhbGciOi.payload.sig", True),
    ("pl_profile=abc; sessionid=xyz", False),
])
def test_token_yoki_cookie_ajratiladi(monkeypatch, raw, expect_token):
    """Yopishtirilgan qiymat token mi yoki cookie mi — shakliga qarab aniqlanadi."""
    seen: dict = {}

    def fake_whoami(session, creds):
        seen["creds"] = creds
        return 777, "Test", ""

    monkeypatch.setattr(auth_mod, "whoami", fake_whoami)
    result = auth_mod.login_with_token(raw)
    assert result.ok
    assert result.credentials.entry_id == 777
    assert bool(seen["creds"].token) is expect_token
    assert bool(seen["creds"].cookie) is not expect_token


def test_bosh_token_rad_etiladi():
    assert auth_mod.login_with_token("   ").ok is False


def test_parolsiz_login_rad_etiladi():
    result = auth_mod.login("kimdir@example.com", "")
    assert result.ok is False
    assert "parol" in result.hint.lower()


def test_login_muvaffaqiyatsiz_bosqichlarni_aytadi(monkeypatch):
    """Xato bo'lganda «ishlamadi» emas, HAR BIR urinish alohida aytilishi kerak."""
    monkeypatch.setattr(auth_mod, "_login_sso", lambda *a, **k:
                        auth_mod.LoginResult(stage="sso", status=400, hint="SSO yopiq",
                                             detail="authorize: DaVinci topilmadi"))
    monkeypatch.setattr(auth_mod, "login_with_browser", lambda *a, **k:
                        auth_mod.LoginResult(stage="brauzer", hint="Playwright yo'q"))
    result = auth_mod.login("a@b.uz", "parol")
    assert result.ok is False

    stages = {row["stage"]: row for row in result.tried}
    assert set(stages) == {"sso", "brauzer"}
    # birinchi urinishning tafsiloti oxirgi xatoga ko'milib ketmasligi kerak
    assert stages["sso"]["status"] == 400
    assert stages["sso"]["detail"] == "authorize: DaVinci topilmadi"
    assert stages["brauzer"]["hint"] == "Playwright yo'q"
    # oxirgi maslahat tashxis vositasiga yo'naltiradi
    assert "sso_probe" in result.hint


def test_olik_login_manzili_ishlatilmaydi():
    """users.premierleague.com DNS da yo'q — u yo'l koddan olib tashlangan."""
    source = (Path(auth_mod.__file__)).read_text(encoding="utf-8")
    assert "users.premierleague.com/accounts" not in source
    assert not hasattr(auth_mod, "_login_legacy_form")
    # ROPC ham noto'g'ri usul edi — u ham olib tashlangan
    assert not hasattr(auth_mod, "_login_password_grant")
    assert '"grant_type": "password"' not in source


def test_brauzer_yoli_ochirilishi_mumkin(monkeypatch):
    """use_browser=False bo'lsa brauzer umuman ochilmaydi (web sahifa shunday chaqiradi)."""
    called = []
    monkeypatch.setattr(auth_mod, "_login_sso", lambda *a, **k:
                        auth_mod.LoginResult(stage="sso", hint="yopiq"))
    monkeypatch.setattr(auth_mod, "login_with_browser",
                        lambda *a, **k: called.append(1) or auth_mod.LoginResult())
    result = auth_mod.login("a@b.uz", "parol", use_browser=False)
    assert called == []
    assert [row["stage"] for row in result.tried] == ["sso"]


def test_playwright_yoq_bolsa_korsatma_beriladi(monkeypatch):
    """Paket o'rnatilmagan bo'lsa — aniq o'rnatish buyrug'i chiqsin."""
    from fplbrain import browser_login

    def boom(**kwargs):
        raise browser_login.BrowserLoginError(browser_login.INSTALL_HINT)

    monkeypatch.setattr(browser_login, "capture_credentials", boom)
    result = auth_mod.login_with_browser("a@b.uz", "parol")
    assert result.ok is False
    assert result.stage == "brauzer"
    assert "pip install playwright" in result.detail


def test_brauzer_natijasi_qabul_qilinadi(monkeypatch):
    from fplbrain import browser_login

    monkeypatch.setattr(browser_login, "capture_credentials", lambda **k: {
        "ok": True, "token": "eyJ.a.b", "cookie": "", "entry_id": 555,
        "detail": "Brauzerdan token tutildi.",
    })
    monkeypatch.setattr(auth_mod, "whoami", lambda s, c: (555, "Ilkhomjon", ""))
    result = auth_mod.login_with_browser("a@b.uz", "parol")
    assert result.ok is True
    assert result.credentials.token == "eyJ.a.b"
    assert result.credentials.entry_id == 555


def test_brauzer_tekshiruvsiz_ham_qabul_qilinadi(monkeypatch):
    """Tekshiruv so'rovi bot himoyasiga urilsa ham, tutilgan token yo'qotilmaydi."""
    from fplbrain import browser_login

    monkeypatch.setattr(browser_login, "capture_credentials", lambda **k: {
        "ok": True, "token": "eyJ.a.b", "cookie": "", "entry_id": 777, "detail": "",
    })
    monkeypatch.setattr(auth_mod, "whoami", lambda s, c: (0, "", "HTTP 403: datadome"))
    result = auth_mod.login_with_browser("a@b.uz", "parol")
    assert result.ok is True
    assert result.credentials.entry_id == 777
    assert "tekshiruv" in result.hint.lower()


def test_login_fonda_ishlaydi(monkeypatch):
    """Sahifa kutib qolmasin: 202 qaytadi, natija esa holatdan olinadi."""
    import threading

    started = threading.Event()

    # SSO ni ham almashtiramiz — sinov tarmoqqa chiqmasligi kerak
    monkeypatch.setattr(auth_mod, "_login_sso", lambda *a, **k:
                        auth_mod.LoginResult(stage="sso", hint="yopiq"))

    def slow(email="", password="", data_dir=None, timeout=180.0,
             allow_visible=True, profile_key=""):
        started.wait(2)
        return auth_mod.LoginResult(
            ok=True, stage="brauzer", status=200,
            credentials=auth_mod.Credentials(token="eyJ.a.b", entry_id=999, name="Test"),
        )

    monkeypatch.setattr(auth_mod, "login_with_browser", slow)
    app = create_app(Config(), demo=True)
    c = app.test_client()

    r = c.post("/api/login", json={"email": "a@b.uz", "password": "p"})
    assert r.status_code == 202
    assert r.get_json()["running"] is True
    assert c.get("/api/status").get_json()["job_running"] is True

    started.set()
    for _ in range(50):
        if not c.get("/api/status").get_json()["job_running"]:
            break
        time.sleep(0.1)
    status = c.get("/api/status").get_json()
    assert status["job_running"] is False
    assert status["logged_in"] is True
    assert status["entry_id"] == 999


def test_web_login_token_bilan_holatni_ozgartiradi(monkeypatch):
    monkeypatch.setattr(auth_mod, "whoami", lambda s, c: (4242, "Ilkhomjon", ""))
    app = create_app(Config(), demo=True)
    c = app.test_client()

    r = c.post("/api/login", json={"token": "eyJ.a.b"})
    assert r.status_code == 200 and r.get_json()["ok"] is True

    status = c.get("/api/status").get_json()
    assert status["logged_in"] is True
    assert status["entry_id"] == 4242
    assert status["method"] == "token"

    assert c.post("/api/logout").get_json()["ok"] is True
    assert c.get("/api/status").get_json()["logged_in"] is False


def test_parol_javobga_qaytmaydi(monkeypatch):
    """Parol hech qachon javobda ham, saqlangan holatda ham ko'rinmasin."""
    monkeypatch.setattr(auth_mod, "login",
                        lambda *a, **k: auth_mod.LoginResult(stage="sso", hint="yopiq"))
    app = create_app(Config(), demo=True)
    c = app.test_client()
    secret = "juda-maxfiy-parol"
    r = c.post("/api/login", json={"email": "a@b.uz", "password": secret})
    assert secret not in r.get_data(as_text=True)
    for _ in range(50):
        body = c.get("/api/status").get_data(as_text=True)
        assert secret not in body
        if not c.get("/api/status").get_json()["job_running"]:
            break
        time.sleep(0.05)


def test_sso_rejimi_brauzerni_ochmaydi(monkeypatch):
    """«Faqat SSO» tugmasi brauzerni umuman ishga tushirmasligi kerak."""
    seen = {}

    def fake_login(email, password, client_id="", use_browser=True,
                   data_dir=None, redirect_uri="", profile_key=""):
        seen["use_browser"] = use_browser
        return auth_mod.LoginResult(stage="sso", hint="yopiq")

    monkeypatch.setattr(auth_mod, "login", fake_login)
    c = create_app(Config(), demo=True).test_client()
    c.post("/api/login", json={"mode": "sso", "email": "a@b.uz", "password": "p"})
    for _ in range(50):
        if not c.get("/api/status").get_json()["job_running"]:
            break
        time.sleep(0.05)
    assert seen["use_browser"] is False


def test_ikkinchi_urinish_birinchisini_buzmaydi(monkeypatch):
    """Bir vaqtda ikki kirish ketmasin — ikkinchisi 409 oladi."""
    import threading
    hold = threading.Event()

    monkeypatch.setattr(auth_mod, "login",
                        lambda *a, **k: (hold.wait(3), auth_mod.LoginResult())[1])
    c = create_app(Config(), demo=True).test_client()
    first = c.post("/api/login", json={"email": "a@b.uz", "password": "p"})
    assert first.status_code == 202
    second = c.post("/api/login", json={"email": "a@b.uz", "password": "p"})
    assert second.status_code == 409
    hold.set()


# ------------------------------------------------------------- mening jamoam
@pytest.fixture(scope="module")
def squad_payload(client):
    r = client.get("/api/squad")
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def test_tarkib_15_oyinchi_11_asosiy(squad_payload):
    players = squad_payload["players"]
    assert len(players) == 15
    assert sum(1 for p in players if p["in_xi"]) == 11
    assert sum(1 for p in players if not p["in_xi"]) == 4


def test_har_oyinchida_forma_va_egalik_bor(squad_payload):
    """Narx, Tarkib, EV yonida forma va egalik ham turishi kerak."""
    for p in squad_payload["players"]:
        assert isinstance(p["form"], (int, float))
        assert isinstance(p["ownership"], (int, float))
        assert "net_transfers" in p


def test_ev_qismlarga_ajratib_beriladi(squad_payload):
    """EV ishonchli bo'lishi uchun uning nimalardan yig'ilgani ko'rinishi kerak."""
    for p in squad_payload["players"]:
        d = p["detail"]
        assert d["parts"], "EV qismlari bo'sh"
        assert "ishtirok" in d["parts"]
        # qismlar yig'indisi EV ga teng bo'lishi kerak
        assert abs(sum(d["parts"].values()) - p["ev"]) < 0.05

    # Himoyachi uchun "toza darvoza bo'lsa" raqami EV dan katta bo'ladi
    dfd = [p for p in squad_payload["players"] if p["pos"] == 2 and p["detail"]["p_cs"]]
    assert dfd, "himoyachi topilmadi"
    assert any(p["detail"]["if_cs"] > p["ev"] for p in dfd)


def test_ft_va_ishlatilgan_transferlar_qaytariladi(squad_payload):
    assert "free_transfers" in squad_payload
    assert isinstance(squad_payload["transfers_made"], int)
    assert isinstance(squad_payload["unlimited_transfers"], bool)


def test_asosiy_11_likda_bitta_darvozabon(squad_payload):
    xi = [p for p in squad_payload["players"] if p["in_xi"]]
    assert sum(1 for p in xi if p["pos"] == 1) == 1
    # sxema qoidaga mos
    assert 3 <= sum(1 for p in xi if p["pos"] == 2) <= 5
    assert 1 <= sum(1 for p in xi if p["pos"] == 4) <= 3


def test_zaxiradagilar_uchun_sabab_yoziladi(squad_payload):
    """«Nega zaxirada?» degan savol javobsiz qolmasin."""
    bench = [p for p in squad_payload["players"] if not p["in_xi"]]
    assert all(p["reason"] for p in bench)
    assert sorted(p["bench_order"] for p in bench) == [1, 2, 3, 4]
    assert all(not p["reason"] for p in squad_payload["players"] if p["in_xi"])


def test_har_oyinchida_qaror_uchun_kerakli_malumot(squad_payload):
    for p in squad_payload["players"]:
        for key in ("ev", "p_start", "price", "selling", "fixture", "pos_short"):
            assert key in p, f"«{key}» yo'q"
        assert 0 <= p["p_start"] <= 100


def test_qiyinlik_rasmiy_fdr_dan_farq_qiladi(squad_payload):
    """Model qiyinligi alohida ko'rsatiladi — rasmiy FDR bilan bir xil emas."""
    fixtures = [p["fixture"] for p in squad_payload["players"]
                if not p["fixture"]["blank"]]
    assert fixtures
    assert all(f["eff_fdr"] is not None for f in fixtures)
    assert any(abs(f["eff_fdr"] - f["fdr"]) > 0.3 for f in fixtures)


def test_tarkib_keshlanadi_va_yangilanadi(client):
    first = client.get("/api/squad").get_json()
    assert client.get("/api/squad").get_json() == first
    assert client.get("/api/squad?refresh=1").status_code == 200


def test_entry_id_yoq_bolsa_401():
    from fplbrain.demo import FakeClient
    app = create_app(Config(), client=FakeClient())      # demo emas: entry_id 0
    r = app.test_client().get("/api/squad")
    assert r.status_code == 401
    assert "entry_id" in r.get_json()["error"]


# ------------------------------------------------------- saqlangan sessiya
def _jwt(exp: float) -> str:
    """Imzosiz, faqat `exp` bor JWT — muddatni o'qishni sinash uchun."""
    import base64
    import json as _json

    def part(obj):
        raw = base64.urlsafe_b64encode(_json.dumps(obj).encode()).decode()
        return raw.rstrip("=")

    return f"{part({'alg': 'none'})}.{part({'exp': exp})}.imzo"


def test_jwt_muddati_oqiladi():
    from fplbrain import session_store
    soon = time.time() + 600
    assert abs(session_store.jwt_expiry(_jwt(soon)) - soon) < 1
    assert session_store.jwt_expiry("jwt-emas") == 0.0
    assert session_store.jwt_expiry("") == 0.0


def test_sessiya_saqlanadi_va_oqiladi(tmp_path):
    from fplbrain import session_store
    token = _jwt(time.time() + 1800)
    saved = session_store.save(tmp_path, token=token, entry_id=34191, name="Test")
    assert saved.valid
    assert saved.valid and saved.seconds_left > 1700

    loaded = session_store.load(tmp_path)
    assert loaded.token == token
    assert loaded.entry_id == 34191
    assert loaded.valid is True
    assert loaded.needs_refresh is False
    # tashxisda token QIYMATI chiqmaydi
    assert token not in str(loaded.as_dict())


def test_muddati_otgan_sessiya_yaroqsiz(tmp_path):
    from fplbrain import session_store
    session_store.save(tmp_path, token=_jwt(time.time() - 10), entry_id=1)
    loaded = session_store.load(tmp_path)
    assert loaded.valid is False
    assert loaded.seconds_left == 0


def test_tugashiga_oz_qolsa_yangilash_kerak(tmp_path):
    from fplbrain import session_store
    session_store.save(tmp_path, token=_jwt(time.time() + 60), entry_id=1)
    assert session_store.load(tmp_path).needs_refresh is True


def test_sessiya_ochiriladi(tmp_path):
    from fplbrain import session_store
    session_store.save(tmp_path, token=_jwt(time.time() + 600), entry_id=1)
    assert session_store.clear(tmp_path) is True
    assert session_store.load(tmp_path).valid is False
    assert session_store.clear(tmp_path) is False       # ikkinchi marta yo'q


def test_buzuq_fayl_yiqitmaydi(tmp_path):
    from fplbrain import session_store
    file = session_store.path_for(tmp_path)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text("{buzuq", encoding="utf-8")
    assert session_store.load(tmp_path).valid is False


# --------------------------------------------- akkauntlar bir-biriga aralashmaydi
def test_har_email_uchun_alohida_kalit():
    from fplbrain import session_store
    a = session_store.account_key("bir@mail.uz")
    b = session_store.account_key("ikki@mail.uz")
    assert a != b
    # katta/kichik harf va bo'shliq farq qilmaydi
    assert a == session_store.account_key("  BIR@Mail.uz ")
    assert session_store.account_key("") == "default"


def test_ikki_akkaunt_bir_birini_kormaydi(tmp_path):
    """Asosiy kafolat: boshqa email — boshqa sessiya fayli."""
    from fplbrain import session_store
    a = session_store.account_key("bir@mail.uz")
    b = session_store.account_key("ikki@mail.uz")
    session_store.save(tmp_path, token=_jwt(time.time() + 900),
                       entry_id=111, name="Bir", key=a)
    session_store.save(tmp_path, token=_jwt(time.time() + 900),
                       entry_id=222, name="Ikki", key=b)

    assert session_store.load(tmp_path, a).entry_id == 111
    assert session_store.load(tmp_path, b).entry_id == 222
    assert sorted(session_store.known_keys(tmp_path)) == sorted([a, b])

    session_store.clear(tmp_path, a)
    assert session_store.load(tmp_path, a).valid is False
    assert session_store.load(tmp_path, b).entry_id == 222   # ikkinchisi buzilmadi


def test_har_akkaunt_ozining_brauzer_profilida(tmp_path):
    """Umumiy profil — aynan shu sabab boshqa parol eski hisobga kirardi."""
    from fplbrain import browser_login, session_store
    a = session_store.account_key("bir@mail.uz")
    b = session_store.account_key("ikki@mail.uz")
    assert browser_login.profile_dir(tmp_path, a) != browser_login.profile_dir(tmp_path, b)
    assert browser_login.profile_ready(tmp_path, a) is False
    (browser_login.profile_dir(tmp_path, a) / "Cookies").write_text("x")
    assert browser_login.profile_ready(tmp_path, a) is True
    assert browser_login.profile_ready(tmp_path, b) is False   # ikkinchisi toza


def _app_with_session(tmp_path, key="default", **kw):
    from fplbrain.demo import FakeClient
    cfg = Config()
    cfg.cache_dir = tmp_path / "cache"
    for name, value in kw.items():
        setattr(cfg, name, value)
    c = create_app(cfg, client=FakeClient()).test_client()
    c.set_cookie("fplacct", key)          # shu brauzer oldin kirgan akkaunt
    return c


def test_saqlangan_sessiya_cookie_orqali_tiklanadi(tmp_path):
    """Asosiy maqsad: qayta kirish shart bo'lmasin — kutish ham yo'q."""
    from fplbrain import session_store
    key = session_store.account_key("bir@mail.uz")
    session_store.save(tmp_path, token=_jwt(time.time() + 1800),
                       entry_id=34191, name="Ilhomjon", key=key)

    body = _app_with_session(tmp_path, key).get("/api/status").get_json()
    assert body["logged_in"] is True
    assert body["entry_id"] == 34191
    assert body["name"] == "Ilhomjon"
    assert body["seconds_left"] > 1700


def test_begona_brauzer_saqlangan_sessiyani_olmaydi(tmp_path):
    """Cookie si yo'q odam birovning sessiyasini KO'RMASLIGI kerak."""
    from fplbrain import session_store
    from fplbrain.demo import FakeClient
    key = session_store.account_key("bir@mail.uz")
    session_store.save(tmp_path, token=_jwt(time.time() + 1800),
                       entry_id=34191, name="Ilhomjon", key=key)

    cfg = Config()
    cfg.cache_dir = tmp_path / "cache"
    stranger = create_app(cfg, client=FakeClient()).test_client()
    body = stranger.get("/api/status").get_json()
    assert body["logged_in"] is False
    assert body["name"] == ""


def test_muddati_otgan_sessiya_tiklanmaydi(tmp_path):
    from fplbrain import session_store
    session_store.save(tmp_path, token=_jwt(time.time() - 10), entry_id=1)
    c = _app_with_session(tmp_path)
    assert c.get("/api/status").get_json()["logged_in"] is False


def test_chiqish_saqlangan_sessiyani_ochiradi(tmp_path):
    from fplbrain import session_store
    session_store.save(tmp_path, token=_jwt(time.time() + 1800), entry_id=7)
    c = _app_with_session(tmp_path)
    assert c.get("/api/status").get_json()["logged_in"] is True

    body = c.post("/api/logout").get_json()
    assert body["saqlangan_sessiya_ochirildi"] is True
    assert session_store.load(tmp_path).valid is False
    assert c.get("/api/status").get_json()["logged_in"] is False


def test_tez_kirish_oyna_ochmaydi(monkeypatch, tmp_path):
    """`/api/reconnect` hech qachon ko'rinadigan oyna ochmasligi kerak."""
    from fplbrain.demo import FakeClient

    seen = {}

    def fake_browser(email="", password="", data_dir=None, timeout=180.0,
                     allow_visible=True, profile_key=""):
        seen["allow_visible"] = allow_visible
        seen["password"] = password
        return auth_mod.LoginResult(stage="brauzer", hint="profil yo'q")

    monkeypatch.setattr(auth_mod, "login_with_browser", fake_browser)
    c = _app_with_session(tmp_path, "kalit")

    assert c.post("/api/reconnect").status_code == 202
    for _ in range(50):
        if not c.get("/api/status").get_json()["job_running"]:
            break
        time.sleep(0.05)
    assert seen["allow_visible"] is False
    assert seen["password"] == ""


# ------------------------------------------------- jamoa ID bilan tez ulanish
def test_jamoa_id_bilan_darhol_ulanadi(client):
    """Parolsiz, brauzersiz, kutishsiz — ko'p foydalanuvchi uchun asosiy yo'l."""
    r = client.post("/api/connect", json={"entry_id": 34191})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["entry_id"] == 34191
    assert body["public_only"] is True

    status = client.get("/api/status").get_json()
    assert status["entry_id"] == 34191
    assert status["public_only"] is True
    assert status["logged_in"] is False          # parol berilmagan


def test_ulangandan_keyin_tarkib_keladi(client):
    client.post("/api/connect", json={"entry_id": 34191})
    r = client.get("/api/squad?refresh=1")
    assert r.status_code == 200
    assert len(r.get_json()["players"]) == 15


def test_notogri_jamoa_id_rad_etiladi(client):
    assert client.post("/api/connect", json={"entry_id": 0}).status_code == 400
    assert client.post("/api/connect", json={"entry_id": "abc"}).status_code == 400


def test_ikki_brauzer_bir_birining_sessiyasini_kormaydi(tmp_path):
    """Ko'p foydalanuvchi: birinchi brauzerning ulanishi ikkinchisiga o'tmasin."""
    from fplbrain.demo import FakeClient
    cfg = Config()
    cfg.cache_dir = tmp_path / "cache"
    app = create_app(cfg, client=FakeClient())

    first, second = app.test_client(), app.test_client()
    assert first.post("/api/connect", json={"entry_id": 111}).status_code == 200
    assert first.get("/api/status").get_json()["entry_id"] == 111
    # ikkinchi brauzer hech narsa ko'rmaydi
    assert second.get("/api/status").get_json()["entry_id"] == 0


# ---------------------------------------------------------------- transferlar
@pytest.fixture(scope="module")
def transfer_payload(client):
    r = client.get("/api/transfers")
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def test_transfer_takliflari_keladi(transfer_payload):
    t = transfer_payload
    assert t["moves"], "hech qanday variant topilmadi"
    assert t["recommendation"] in ("transfer", "hold")
    assert t["weak"], "zaif bo'g'inlar ro'yxati bo'sh"


def test_har_taklifda_sotiladigan_va_olinadigan_bor(transfer_payload):
    for m in transfer_payload["moves"]:
        assert m["out"] and m["in"]
        assert len(m["out"]) == len(m["in"]) == m["n"]
        for p in m["out"]:
            assert p["selling"] > 0        # sotish narxi bo'lishi shart
        for p in m["in"]:
            assert p["price"] > 0


def test_bir_oyinchi_takliflarda_takrorlanmaydi(transfer_payload):
    """Bitta o'yinchining o'nta varianti emas, har biriga bitta eng yaxshisi."""
    outs = [tuple(sorted(p["element"] for p in m["out"]))
            for m in transfer_payload["moves"]]
    ins = [tuple(sorted(p["element"] for p in m["in"]))
           for m in transfer_payload["moves"]]
    assert len(outs) == len(set(outs))
    assert len(ins) == len(set(ins))


def test_foyda_hit_ayirilgan_holda(transfer_payload):
    for m in transfer_payload["moves"]:
        assert m["gain"] == pytest.approx(m["raw_gain"] - m["hit"], abs=0.02)
        assert m["worth_it"] == (m["gain"] > 0)


def test_takliflar_foyda_boyicha_saralangan(transfer_payload):
    gains = [m["gain"] for m in transfer_payload["moves"]]
    assert gains == sorted(gains, reverse=True)


def test_zaif_bogin_uchun_sabab_bor(transfer_payload):
    for p in transfer_payload["weak"]:
        assert p["reason"].strip(), f"{p['name']} uchun sabab yozilmagan"


def test_transfer_loginsiz_ham_ishlaydi(transfer_payload):
    """Jamoa ID bilan ham ishlashi kerak — faqat narxlar taxminiy bo'ladi."""
    assert "authenticated" in transfer_payload
    assert transfer_payload["bank"] >= 0


def test_transfer_entry_id_siz_401(client):
    app = create_app(Config(), demo=False)
    r = app.test_client().get("/api/transfers")
    assert r.status_code == 401


def test_ft_yoq_bolsa_hit_korsatiladi():
    """FT 0 bo'lsa har taklifda hit turishi kerak — va 2 talik ham ko'rilsin.

    Avval FT 0 bo'lganda ikkita transferli variantlar umuman hisoblanmasdi.
    Ular −8 ochko turadi, lekin ba'zan oqlaydi; ko'rsatmaslik qarorni
    foydalanuvchidan yashirish bo'lardi.
    """
    from fplbrain.demo import FakeClient
    from web import transferview

    class NoFreeTransfers(FakeClient):
        def my_team(self, entry_id):
            picks = self.entry_picks(entry_id, 3)["picks"]
            return {
                "picks": [{**p, "selling_price": 50, "purchase_price": 50}
                          for p in picks],
                "transfers": {"limit": 1, "made": 1, "status": "cost",
                              "cost": 4, "bank": 30, "value": 1000},
                "chips": [],
            }

        def entry_history(self, entry_id):
            return {"current": [], "chips": []}

    payload = transferview.build(NoFreeTransfers(), Config(), 1)
    assert payload["free_transfers"] == 0
    assert payload["transfers_status"] == "cost"
    assert all(m["hit"] >= 4 for m in payload["moves"] if m["n"] == 1)
    assert all(m["hit"] >= 8 for m in payload["moves"] if m["n"] == 2)


def test_transfer_keshlanadi(client):
    first = client.get("/api/transfers").get_json()
    assert client.get("/api/transfers").get_json() == first
    assert client.get("/api/transfers?refresh=1").status_code == 200


# ------------------------------------------------------------- jamoa tuzish
@pytest.fixture(scope="module")
def draft_payload(client):
    r = client.get("/api/draft")
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def test_jamoa_tuzish_loginsiz_ishlaydi(client):
    """Bu bo'lim mavjud tarkibga bog'liq emas — login ham, jamoa ID ham shart emas."""
    app = create_app(Config(), demo=True)
    r = app.test_client().get("/api/draft")
    assert r.status_code == 200
    assert "error" not in r.get_json()


def test_tuzilgan_jamoa_qoidalarga_mos(draft_payload):
    d = draft_payload
    assert d["legal"] is True
    assert len(d["players"]) == 15
    shape = {}
    for p in d["players"]:
        shape[p["pos"]] = shape.get(p["pos"], 0) + 1
    assert shape == {1: 2, 2: 5, 3: 5, 4: 3}
    assert d["cost"] <= d["budget"] + 1e-9
    assert all(c["count"] <= 3 for c in d["clubs"])


def test_tuzilgan_jamoada_11_lik_va_kapitan(draft_payload):
    xi = [p for p in draft_payload["players"] if p["in_xi"]]
    assert len(xi) == 11
    assert sum(1 for p in xi if p["pos"] == 1) == 1
    caps = [p for p in draft_payload["players"] if p["is_captain"]]
    assert len(caps) == 1 and caps[0]["in_xi"]


def test_h2h_uchun_kerakli_raqamlar_bor(draft_payload):
    """Ekspertlar bilan solishtirish uchun: ochko, sxema, narx, kapitan."""
    for key in ("expected_points", "formation", "cost", "bank", "captain",
                "budget", "event"):
        assert key in draft_payload, f"«{key}» yo'q"
    assert draft_payload["expected_points"] > 0


def test_byudjet_sorovdan_olinadi(client):
    r = client.get("/api/draft?budget=90")
    assert r.status_code == 200
    body = r.get_json()
    assert body["budget"] == 90.0
    assert body["cost"] <= 90.0 + 1e-9


def test_jamoa_tuzish_keshlanadi(client):
    first = client.get("/api/draft").get_json()
    assert client.get("/api/draft").get_json() == first
    assert client.get("/api/draft?refresh=1").status_code == 200
