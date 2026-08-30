"""Bot va bo'limlar — tarmoqsiz sinovlar."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bot as bot_module
from fplbrain.config import Config
from fplbrain.sections import Report
from fplbrain.telegram import build_keyboard


def make_report() -> Report:
    rep = Report(event=3, mode="deadline", generated="2026-08-28T12:00:00+05:00",
                 deadline="2026-08-28T22:30:00+05:00", summary="<b>Xulosa</b>")
    rep.add("strategy", "🎯 Strategiya", "Strategiya matni")
    rep.add("captain", "🅲 Kapitan", "Kapitan matni")
    rep.add("bosh", "Bo'sh", "   ")          # bo'sh bo'lim qo'shilmasligi kerak
    return rep


# ------------------------------------------------------------------ bo'limlar
def test_bosh_bolim_qoshilmaydi():
    rep = make_report()
    assert [s.key for s in rep.sections] == ["strategy", "captain"]
    assert rep.get("bosh") is None


def test_saqlash_va_oqish(tmp_path):
    rep = make_report()
    rep.save(tmp_path)
    loaded = Report.load(tmp_path)
    assert loaded is not None
    assert loaded.event == 3
    assert loaded.summary == "<b>Xulosa</b>"
    assert [s.key for s in loaded.sections] == ["strategy", "captain"]
    assert loaded.get("captain").text == "Kapitan matni"


def test_yoq_fayl_none_qaytaradi(tmp_path):
    assert Report.load(tmp_path) is None


def test_buzilgan_fayl_none_qaytaradi(tmp_path):
    (tmp_path / "last_report.json").write_text("{buzilgan", encoding="utf-8")
    assert Report.load(tmp_path) is None


def test_toliq_matn_bolimlarni_birlashtiradi():
    rep = make_report()
    full = rep.full_text()
    assert "Strategiya matni" in full and "Kapitan matni" in full


# ------------------------------------------------------------------ klaviatura
def test_klaviatura_ikki_ustunli():
    rep = make_report()
    kb = build_keyboard(rep.sections, columns=2)
    rows = kb["inline_keyboard"]
    assert rows[0][0]["callback_data"] == "s:strategy"
    assert rows[0][1]["callback_data"] == "s:captain"
    # callback_data Telegram chegarasidan (64 bayt) oshmasin
    for row in rows:
        for button in row:
            assert len(button["callback_data"].encode()) <= 64


def test_qoshimcha_qatorlar_oxiriga_qoshiladi():
    rep = make_report()
    extra = [[{"text": "X", "callback_data": "x"}]]
    kb = build_keyboard(rep.sections, columns=2, extra_rows=extra)
    assert kb["inline_keyboard"][-1] == extra[0]


# ------------------------------------------------------------------ bot
class FakeTelegram:
    """Tarmoqqa chiqmaydigan Telegram o'rnini bosuvchi."""

    def __init__(self):
        self.dry_run = False
        self.calls = []
        self.edits = []
        self.answers = []

    def call(self, method, payload, timeout=25):
        self.calls.append((method, payload))
        return {}

    def edit(self, message_id, text, keyboard=None, chat_id=None):
        self.edits.append((message_id, text, keyboard))
        return True

    def answer_callback(self, callback_id, text=""):
        self.answers.append((callback_id, text))

    def send(self, text):
        self.calls.append(("send", text))
        return [1]

    def send_menu(self, text, keyboard):
        self.calls.append(("send_menu", text))
        return 42


@pytest.fixture
def fake_bot(tmp_path):
    cfg = Config()
    cfg.store_dir = tmp_path
    cfg.telegram_chat_id = "-1001234"
    cfg.telegram_token = "x"
    make_report().save(tmp_path)
    b = bot_module.Bot(cfg)
    b.tg = FakeTelegram()
    return b


def test_begona_chatga_javob_bermaydi(fake_bot):
    """Xavfsizlik: faqat sozlangan kanal bilan ishlasin."""
    assert fake_bot.allowed("-1001234") is True
    assert fake_bot.allowed("-999") is False

    fake_bot.on_callback({
        "id": "q1", "data": "s:strategy",
        "message": {"message_id": 1, "chat": {"id": -999}},
    })
    assert fake_bot.tg.answers == [("q1", "Ruxsat yo'q")]
    assert fake_bot.tg.edits == []          # hech narsa ko'rsatilmadi


def test_bolim_tugmasi_matnni_almashtiradi(fake_bot):
    fake_bot.on_callback({
        "id": "q2", "data": "s:captain",
        "message": {"message_id": 7, "chat": {"id": "-1001234"}},
    })
    assert fake_bot.tg.edits
    message_id, text, keyboard = fake_bot.tg.edits[-1]
    assert message_id == 7
    assert "Kapitan matni" in text
    assert keyboard["inline_keyboard"][0][0]["callback_data"] == "menu"


def test_menyu_tugmasi_qaytaradi(fake_bot):
    fake_bot.on_callback({
        "id": "q3", "data": "menu",
        "message": {"message_id": 7, "chat": {"id": "-1001234"}},
    })
    _, text, keyboard = fake_bot.tg.edits[-1]
    assert "Xulosa" in text
    assert any(b["callback_data"] == "s:strategy"
               for row in keyboard["inline_keyboard"] for b in row)


def test_notanish_bolim_xato_bermaydi(fake_bot):
    fake_bot.on_callback({
        "id": "q4", "data": "s:yoq_bunaqa",
        "message": {"message_id": 7, "chat": {"id": "-1001234"}},
    })
    _, text, _ = fake_bot.tg.edits[-1]
    assert "topilmadi" in text


def test_uzun_bolim_kesiladi(fake_bot, tmp_path):
    rep = Report(event=3, mode="daily", generated="2026-08-28T12:00:00+05:00",
                 deadline="", summary="x")
    rep.add("uzun", "Uzun", "qator\n" * 2000)
    rep.save(tmp_path)
    text, _ = fake_bot.section_view("uzun")
    assert len(text) <= 4096          # Telegram chegarasi
    assert "kesildi" in text


def test_hisobot_yoq_bolsa_menyu_yangilash_taklif_qiladi(tmp_path):
    cfg = Config()
    cfg.store_dir = tmp_path / "bosh"
    cfg.store_dir.mkdir()
    cfg.telegram_chat_id = "-1"
    cfg.telegram_token = "x"
    b = bot_module.Bot(cfg)
    b.tg = FakeTelegram()
    text, keyboard = b.menu_view()
    assert "yasalmagan" in text
    assert keyboard["inline_keyboard"][0][0]["callback_data"] == "refresh"


def test_holat_buyrugi(fake_bot):
    fake_bot.on_message({"chat": {"id": "-1001234"}, "text": "/holat"})
    method, payload = fake_bot.tg.calls[-1]
    assert method == "send"
    assert "GW3" in payload


# --------------------------------------------------- eskirgan tugma bosishlari
def test_callback_ga_darhol_javob_beriladi(fake_bot):
    """Telegram ~15 soniya beradi — javob boshqa ishdan OLDIN ketishi kerak."""
    order = []
    fake_bot.tg.answer_callback = lambda cid, text="": order.append("answer")
    fake_bot.tg.edit = lambda *a, **k: order.append("edit") or True

    fake_bot.on_callback({
        "id": "q", "data": "s:captain",
        "message": {"message_id": 1, "chat": {"id": "-1001234"}},
    })
    assert order[0] == "answer", f"javob kechikdi: {order}"


def test_toliq_hisobot_siklni_bloklamaydi(fake_bot):
    """"Hammasi" uzun xabar jo'natadi — u alohida oqimda ketishi kerak."""
    import threading

    sent = threading.Event()
    fake_bot.tg.send = lambda text: sent.set()
    fake_bot.on_callback({
        "id": "q", "data": "full",
        "message": {"message_id": 1, "chat": {"id": "-1001234"}},
    })
    assert sent.wait(timeout=2), "to'liq hisobot jo'natilmadi"
    # javob jo'natishdan oldin berilgan bo'lishi kerak
    assert fake_bot.tg.answers[-1][0] == "q"


def test_zararsiz_400_ogohlantirish_bermaydi(tmp_path, caplog):
    """"query is too old" — eskirgan tugma, foydalanuvchiga ko'rsatish shart emas."""
    import logging

    from fplbrain.telegram import Telegram

    tg = Telegram("token", "-1")

    class Resp:
        status_code = 400
        text = '{"ok":false,"description":"Bad Request: query is too old"}'

    tg._session = None
    import fplbrain.telegram as tmod
    orig = tmod.requests.post
    tmod.requests.post = lambda *a, **k: Resp()
    try:
        with caplog.at_level(logging.WARNING):
            assert tg.call("answerCallbackQuery", {}) is None
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    finally:
        tmod.requests.post = orig
