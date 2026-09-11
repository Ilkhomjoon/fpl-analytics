"""Brauzer orqali kirish — haqiqiy Chromium da, soxta "FPL" ga qarshi.

Soxta sayt haqiqiy xatti-harakatni takrorlaydi:

  `/my-team`  → tizimga kirmagan foydalanuvchiga login formasi KO'RSATILMAYDI,
                faqat «Log in» tugmasi bo'ladi (aynan shu joyda oldingi
                versiya to'xtab qolgandi);
  `/login`    → email va parol formasi;
  yuborilgach → `/my-team` ga qaytadi va u FPL kabi `X-Api-Authorization`
                sarlavhasi bilan API so'rovini yuboradi.

Playwright o'rnatilmagan bo'lsa sinovlar o'tkazib yuboriladi.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fplbrain import browser_login

pytest.importorskip("playwright.sync_api", reason="Playwright o'rnatilmagan")

from flask import Flask, jsonify, request              # noqa: E402
from werkzeug.serving import make_server               # noqa: E402

ENTRY_ID = 424242
TOKEN = "eyJhbGciOiJIUzI1NiJ9.soxta.imzo"

# Tizimga kirmagan holat: forma yo'q, faqat «Log in»
LOGGED_OUT = """
<!doctype html><meta charset=utf-8><title>Fantasy</title>
<h1>Register to Play Fantasy Premier League</h1>
<a href="/login">Log in</a> <a href="/register">Register now</a>
"""

LOGIN_PAGE = """
<!doctype html><meta charset=utf-8><title>Kirish</title>
<form id=f>
  <input type=email name=email placeholder=email>
  <input type=password name=password placeholder=parol>
  <button type=submit>Sign in</button>
</form>
<script>
document.getElementById('f').addEventListener('submit', (e) => {
  e.preventDefault();
  document.cookie = "pl_profile=soxta; path=/";
  location.href = '/my-team';
});
</script>
"""

LOGGED_IN = """
<!doctype html><meta charset=utf-8><title>Mening jamoam</title>
<p id=done>kirdingiz</p>
<script>
(async () => {
  const h = {'X-Api-Authorization':'Bearer %s'};
  await fetch('/api/me/', {headers:h});
  await fetch('/api/my-team/%d/', {headers:h});
})();
</script>
""" % (TOKEN, ENTRY_ID)


@pytest.fixture(scope="module")
def fake_fpl():
    app = Flask(__name__)
    state = {"signed_in": False}

    @app.get("/my-team")
    def my_team():
        return LOGGED_IN if state["signed_in"] else LOGGED_OUT

    @app.get("/login")
    def login_page():
        state["signed_in"] = True          # forma yuborilgandan keyin kirgan bo'ladi
        return LOGIN_PAGE

    @app.get("/api/me/")
    def me():
        assert request.headers.get("X-Api-Authorization") == f"Bearer {TOKEN}"
        return jsonify({"player": {"entry": ENTRY_ID, "first_name": "Test"}})

    @app.get("/api/my-team/<int:entry>/")
    def team(entry: int):
        return jsonify({"picks": [], "entry": entry})

    server = make_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def _capture(fake_fpl, tmp_path, **kwargs):
    return browser_login.capture_credentials(
        email="test@example.com", password="parol",
        data_dir=tmp_path, timeout=30.0, headless=True,
        start_url=f"{fake_fpl}/my-team", cookie_domain="127.0.0.1", **kwargs,
    )


def test_log_in_tugmasi_bosilib_forma_topiladi(fake_fpl, tmp_path):
    """Asosiy holat: `/my-team` da forma yo'q, «Log in» orqali o'tiladi."""
    result = _capture(fake_fpl, tmp_path)
    assert result["ok"] is True, result["detail"]
    assert result["token"] == TOKEN
    assert result["entry_id"] == ENTRY_ID
    assert "pl_profile=soxta" in result["cookie"]


def test_profil_har_akkaunt_uchun_alohida(tmp_path):
    """Profil kalit bo'yicha ajratiladi — hisoblar aralashmasin."""
    default = browser_login.profile_dir(tmp_path)
    other = browser_login.profile_dir(tmp_path, "kalit2")
    assert default.exists() and default.name == "default"
    assert other.exists() and other != default


def test_login_tugmasi_ham_forma_ham_yoq_bolsa_aniq_aytiladi(tmp_path):
    """Sahifada hech nima bo'lmasa — nima qilingani hisobotda qolsin."""
    app = Flask(__name__)

    @app.get("/bosh")
    def empty():
        return "<!doctype html><meta charset=utf-8><p>bo'sh sahifa</p>"

    server = make_server("127.0.0.1", 0, app)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        result = browser_login.capture_credentials(
            email="a@b.uz", password="p", data_dir=tmp_path, timeout=6.0,
            headless=True, start_url=f"http://127.0.0.1:{server.server_port}/bosh",
            cookie_domain="127.0.0.1",
        )
        assert result["ok"] is False
        assert "Log in" in result["detail"] or "topilmadi" in result["detail"]
    finally:
        server.shutdown()
