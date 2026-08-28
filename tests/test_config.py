""".env faylini o'qish sinovlari — cookie qiymati buzilmasligi asosiy talab."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fplbrain.config import Config, load_env_file

# Haqiqiy cookie ga o'xshash: ichida `=`, `;`, `.`, `~`, `-` va bo'sh joylar bor
COOKIE = "pl_profile=eyJzIjogIld6..=; sessionid=abc123; access_token=xy.z-Q_1; datadome=A~B_c"


@pytest.fixture(autouse=True)
def _clean_env():
    keys = ["FPL_COOKIE", "FPL_ENTRY_ID", "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID", "FPL_LEAGUE_IDS"]
    saved = {k: os.environ.pop(k, None) for k in keys}
    yield
    for k, v in saved.items():
        os.environ.pop(k, None)
        if v is not None:
            os.environ[k] = v


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / ".env"
    p.write_text(text, encoding="utf-8")
    return p


def test_cookie_qiymati_ozgarmaydi(tmp_path):
    """Ichidagi `=` va `;` bo'yicha bo'linib ketmasligi kerak."""
    load_env_file(_write(tmp_path, f"FPL_COOKIE={COOKIE}\n"))
    assert os.environ["FPL_COOKIE"] == COOKIE


def test_qoshtirnoq_olib_tashlanadi(tmp_path):
    load_env_file(_write(tmp_path, f'FPL_COOKIE="{COOKIE}"\n'))
    assert os.environ["FPL_COOKIE"] == COOKIE


def test_izoh_bosh_satr_va_export(tmp_path):
    load_env_file(_write(tmp_path, (
        "# maxfiy qiymatlar\n"
        "\n"
        "FPL_ENTRY_ID=1234567\n"
        "export TELEGRAM_TOKEN=123456:AA-bb_cc\n"
        f"FPL_COOKIE={COOKIE}\n"
    )))
    assert os.environ["FPL_ENTRY_ID"] == "1234567"
    assert os.environ["TELEGRAM_TOKEN"] == "123456:AA-bb_cc"
    assert os.environ["FPL_COOKIE"] == COOKIE


def test_mavjud_muhit_ozgaruvchisi_ustun(tmp_path):
    """CI da secret berilgan bo'lsa, .env uni bosib ketmasin."""
    os.environ["FPL_COOKIE"] = "secretdan_kelgan"
    load_env_file(_write(tmp_path, f"FPL_COOKIE={COOKIE}\n"))
    assert os.environ["FPL_COOKIE"] == "secretdan_kelgan"


def test_bom_bilan_saqlangan_fayl(tmp_path):
    """Windows Notepad UTF-8 BOM qo'shadi — birinchi kalit buzilmasin."""
    p = tmp_path / ".env"
    p.write_text("TELEGRAM_CHAT_ID=-1001234567890\n", encoding="utf-8-sig")
    load_env_file(p)
    assert os.environ["TELEGRAM_CHAT_ID"] == "-1001234567890"


def test_yoq_fayl_xato_bermaydi(tmp_path):
    assert load_env_file(tmp_path / "yoq.env") == 0


def test_config_env_fayldan_oqiydi(tmp_path):
    env = _write(tmp_path, (
        f"FPL_COOKIE={COOKIE}\n"
        "FPL_ENTRY_ID=7654321\n"
        "FPL_LEAGUE_IDS=111, 222\n"
        "TELEGRAM_CHAT_ID=-1009999\n"
    ))
    cfg = Config.load(tmp_path / "yoq_config.yaml", env_file=env)
    assert cfg.fpl_cookie == COOKIE
    assert cfg.entry_id == 7654321
    assert cfg.mini_league_ids == [111, 222]
    assert cfg.telegram_chat_id == "-1009999"


# --------------------------------------------------------- sessiya xatolari
def test_authorror_bot_himoyasini_ajratadi():
    from fplbrain.api import AuthError

    datadome = AuthError(403, '{"url":"https://geo.captcha-delivery.com/","datadome":"x"}', "u")
    assert datadome.blocked_by_bot_protection is True
    assert "Bot himoyasi" in datadome.explain()

    plain = AuthError(403, '{"detail":"Authentication credentials were not provided."}', "u")
    assert plain.blocked_by_bot_protection is False
    assert "Sessiya qabul qilinmadi" in plain.explain()

    assert AuthError(401, "", "u").blocked_by_bot_protection is False


def test_403_qayta_urinmaydi(tmp_path, monkeypatch):
    """401/403 da qayta urinish behuda — darhol AuthError chiqsin."""
    from fplbrain.api import AuthError, FplClient

    client = FplClient(tmp_path, delay=0.0)
    calls = {"n": 0}

    class FakeResp:
        status_code = 403
        text = "datadome blocked"

    def fake_get(url, timeout=25):
        calls["n"] += 1
        return FakeResp()

    monkeypatch.setattr(client._session, "get", fake_get)
    with pytest.raises(AuthError) as exc:
        client.get("my-team/1/", ttl=0)
    assert calls["n"] == 1, "403 da faqat bitta so'rov bo'lishi kerak"
    assert exc.value.status == 403


# ------------------------------------------------------------ chip mavjudligi
def test_ishlatilgan_chip_qayta_taklif_qilinmaydi():
    from fplbrain.chips import ALL_CHIPS, available_chips

    history = [{"name": "bboost", "event": 1}]
    # birinchi yarim yillikda (GW1-19) bboost endi yo'q
    assert "bboost" not in available_chips(history, 2)
    assert set(available_chips(history, 2)) == set(ALL_CHIPS) - {"bboost"}
    # ikkinchi yarim yillikda (GW20+) chiplar yangilanadi
    assert set(available_chips(history, 20)) == set(ALL_CHIPS)
    # tarix bo'sh bo'lsa hammasi mavjud
    assert set(available_chips([], 5)) == set(ALL_CHIPS)
    assert set(available_chips(None, 5)) == set(ALL_CHIPS)



# ------------------------------------------------------- cookie ni tozalash
def test_cookie_tozalash():
    from tools.set_cookie import clean, cookie_names

    # satrga bo'linib ketgan, `cookie:` prefiksli, qo'shtirnoqli paste
    messy = '''cookie: pl_profile=eyJz..=;
       sessionid=abc123;   access_token=eyJh.x-Y_1;
    datadome=A~B'''
    result = clean(messy)
    assert "\n" not in result
    assert result.startswith("pl_profile=")
    assert result == "pl_profile=eyJz..=; sessionid=abc123; access_token=eyJh.x-Y_1; datadome=A~B"
    assert cookie_names(result) == ["pl_profile", "sessionid", "access_token", "datadome"]

    # oxiridagi ortiqcha `;` va bo'shliqlar
    assert clean("a=1;  b=2;  ") == "a=1; b=2"
    # butun qiymatni o'ragan qo'shtirnoq
    assert clean('"a=1; b=2"') == "a=1; b=2"


def test_env_kalitini_yangilaydi(tmp_path):
    from tools.set_cookie import upsert_env

    env = tmp_path / ".env"
    env.write_text(
        "TELEGRAM_TOKEN=123\nFPL_COOKIE=eski\nFPL_ENTRY_ID=7\n", encoding="utf-8"
    )
    assert upsert_env(env, "FPL_COOKIE", "yangi=1; x=2") == "yangilandi"
    text = env.read_text(encoding="utf-8")
    assert "FPL_COOKIE=yangi=1; x=2" in text
    assert "eski" not in text
    assert "TELEGRAM_TOKEN=123" in text      # boshqa satrlar tegilmasin
    assert "FPL_ENTRY_ID=7" in text

    # kalit yo'q bo'lsa qo'shiladi
    env2 = tmp_path / ".env2"
    env2.write_text("TELEGRAM_TOKEN=123\n", encoding="utf-8")
    assert upsert_env(env2, "FPL_COOKIE", "a=1") == "qo'shildi"
    assert "FPL_COOKIE=a=1" in env2.read_text(encoding="utf-8")


def test_cookie_sarlavhasida_satr_kochishi_qolmaydi(tmp_path):
    """Klient cookie ni normallashtirishi kerak — aks holda requests xato beradi."""
    from fplbrain.api import FplClient

    client = FplClient(tmp_path, cookie="pl_profile=a;\n  sessionid=b\n")
    assert "\n" not in client._session.headers["Cookie"]
    assert client._session.headers["Cookie"] == "pl_profile=a; sessionid=b"


def test_qirqilgan_cookie_aniqlanadi():
    """Konsol paste qirqib qo'ysa, birinchi bo'lak `nom=qiymat` bo'lmaydi."""
    from tools.set_cookie import clean, looks_truncated

    # PowerShell qirqib qo'ygan holat: boshi qiymatning o'rtasidan boshlanadi
    truncated = clean("0000000000001.CCbKQ71_8MV4eYUKCdM31hBdYhKl.1; datadome=Ve4iEX0")
    assert looks_truncated(truncated) is True

    butun = clean("access_token=eyJh.x; global_sso_id=2642-4eab; datadome=Ve4iEX0")
    assert looks_truncated(butun) is False


def test_sso_cookie_lari_tanilaydi():
    """FPL PingOne ga o'tgan — access_token/global_sso_id ham sessiya cookie si."""
    from tools.set_cookie import SESSION_COOKIES, cookie_names

    names = cookie_names("access_token=a; global_sso_id=b; datadome=c")
    assert [c for c in SESSION_COOKIES if c in names] == ["access_token", "global_sso_id"]


def test_erkin_transfer_muhitdan_beriladi(tmp_path, monkeypatch):
    """config.yaml bo'lmaganda ham (Actions) FT ni Secret orqali berish mumkin."""
    monkeypatch.setenv("FPL_FREE_TRANSFERS", "3")
    cfg = Config.load(tmp_path / "yoq.yaml", env_file=tmp_path / "yoq.env")
    assert cfg.free_transfers_override == 3

    monkeypatch.setenv("FPL_FREE_TRANSFERS", "notogri")
    cfg = Config.load(tmp_path / "yoq.yaml", env_file=tmp_path / "yoq.env")
    assert cfg.free_transfers_override == 0        # xato qiymat e'tiborsiz qoladi


def test_config_yaml_bolmasa_ham_yuklanadi(tmp_path):
    """Namuna fayl o'chirilgan bo'lsa ham standart qiymatlar bilan ishlasin."""
    cfg = Config.load(tmp_path / "umuman_yoq.yaml", env_file=tmp_path / "yoq.env")
    assert cfg.horizon == 5
    assert cfg.timezone == "Asia/Tashkent"
    assert cfg.mini_league_ids == []
