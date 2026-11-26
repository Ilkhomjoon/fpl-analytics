"""Ko'p foydalanuvchili bot: suhbat mantig'i va bo'limlar matni (soxta Telegram bilan)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fplbrain.config import Config
from fplbrain.demo import FakeClient
from tgbot import render
from tgbot.app import SECTIONS, BotApp, Users

CHAT = 555
ALLOWED_TAGS = {"b", "i", "code"}


class FakeTelegram:
    """Yuborilgan hamma narsani yozib oladi."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.edits: list[dict] = []
        self.answers: list[str] = []
        self.next_id = 100

    def call(self, method: str, payload: dict, timeout: int = 25):
        if method == "sendMessage":
            self.sent.append(payload)
            self.next_id += 1
            return {"message_id": self.next_id}
        return {}

    def edit(self, message_id, text, keyboard=None, chat_id=None) -> bool:
        self.edits.append({"message_id": message_id, "text": text,
                           "keyboard": keyboard, "chat_id": chat_id})
        return True

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        self.answers.append(text)

    @property
    def last_text(self) -> str:
        return (self.edits or self.sent)[-1]["text"]


@pytest.fixture()
def bot(tmp_path):
    cfg = Config()
    cfg.store_dir = tmp_path / "store"
    return BotApp(cfg, FakeClient(), tg=FakeTelegram(),
                  users=Users(tmp_path / "users.json"), sync=True)


def say(bot, text, chat=CHAT):
    bot.handle({"message": {"chat": {"id": chat}, "text": text}})


def press(bot, data, chat=CHAT, message_id=7):
    bot.handle({"callback_query": {"id": "q", "data": data,
                                   "message": {"chat": {"id": chat}, "message_id": message_id}}})


def html_ok(text: str) -> bool:
    """Telegram qabul qiladigan HTML: faqat ruxsat etilgan teglar va ular juft."""
    stack = []
    for closing, tag in re.findall(r"<(/?)([a-zA-Z]+)[^>]*>", text):
        if tag not in ALLOWED_TAGS:
            return False
        if not closing:
            stack.append(tag)
        elif not stack or stack.pop() != tag:
            return False
    return not stack


# ------------------------------------------------------------------ suhbat
def test_start_jamoa_id_soraydi(bot):
    say(bot, "/start")
    assert "jamoa ID" in bot.tg.sent[-1]["text"]
    assert "Parol kerak emas" in bot.tg.sent[-1]["text"]


def test_id_raqam_yoki_havola_bilan_qabul_qilinadi(bot):
    say(bot, "34191")
    assert bot.users.get(CHAT)["entry_id"] == 34191
    assert "Ulandi" in bot.tg.sent[-1]["text"]
    say(bot, "https://fantasy.premierleague.com/entry/715763/event/11")
    assert bot.users.get(CHAT)["entry_id"] == 715763


def test_notogri_id_rad_etiladi(bot):
    say(bot, "salom")
    assert bot.users.get(CHAT) == {}
    say(bot, "/id abc")
    assert "raqam" in bot.tg.sent[-1]["text"]


def test_topilmagan_jamoa_saqlanmaydi(bot):
    bot.client.entry = lambda entry_id: (_ for _ in ()).throw(RuntimeError("404"))
    say(bot, "999")
    assert bot.users.get(CHAT) == {}
    assert "topilmadi" in bot.tg.sent[-1]["text"]


def test_foydalanuvchilar_bir_biridan_ajratilgan(bot):
    say(bot, "111", chat=1)
    say(bot, "222", chat=2)
    assert bot.users.get(1)["entry_id"] == 111 and bot.users.get(2)["entry_id"] == 222


def test_foydalanuvchilar_diskda_saqlanadi(tmp_path):
    users = Users(tmp_path / "users.json")
    users.update(CHAT, entry_id=34191, team="Ilkhomjoon")
    assert Users(tmp_path / "users.json").get(CHAT)["entry_id"] == 34191


def test_menyuda_hamma_bolim_bor(bot):
    say(bot, "34191")
    keyboard = bot.tg.sent[-1]["reply_markup"]["inline_keyboard"]
    data = {b["callback_data"] for row in keyboard for b in row}
    assert {f"v:{key}" for key, _, _ in SECTIONS} <= data


def test_idsiz_shaxsiy_bolim_id_soraydi(bot):
    press(bot, "v:squad")
    assert "jamoa ID" in bot.tg.last_text


def test_idsiz_ham_h2h_va_jamoa_tuzish_ishlaydi(bot):
    press(bot, "v:draft")
    assert "Noldan tuzilgan jamoa" in bot.tg.last_text
    press(bot, "v:h2h")
    assert "H2H" in bot.tg.last_text


def test_yopiq_sinovda_begona_kira_olmaydi(bot):
    bot.allowed = {"1"}
    say(bot, "/start", chat=2)
    assert "yopiq sinovda" in bot.tg.sent[-1]["text"] and "2" in bot.tg.sent[-1]["text"]
    press(bot, "v:h2h", chat=2)
    assert bot.tg.answers[-1] == "Ruxsat yo'q" and not bot.tg.edits


def test_tugma_darhol_javob_oladi(bot):
    say(bot, "34191")
    press(bot, "v:squad")
    assert bot.tg.answers == [""]
    # Avval "hisoblanmoqda", keyin natija
    assert "hisoblanmoqda" in bot.tg.edits[0]["text"]
    assert "Jamoam" in bot.tg.edits[-1]["text"]


def test_natija_keshlanadi_va_yangilash_qayta_hisoblaydi(bot):
    say(bot, "34191")
    calls = []
    original = bot.world
    bot.world = lambda entry_id, fresh=False: (calls.append(fresh), original(entry_id, fresh))[1]
    press(bot, "v:squad")
    press(bot, "v:squad")
    assert calls == [False]                        # ikkinchi marta keshdan
    press(bot, "r:squad")
    assert calls == [False, True]


def test_band_foydalanuvchi_ikkinchi_sorovni_boshlamaydi(bot):
    say(bot, "34191")
    bot.busy.add(str(CHAT))
    press(bot, "v:squad")
    assert "kuting" in bot.tg.sent[-1]["text"] and not bot.tg.edits


def test_bolimdagi_xato_botni_yiqitmaydi(bot):
    say(bot, "34191")
    bot.world = lambda *a, **k: (_ for _ in ()).throw(ValueError("ichki xato"))
    press(bot, "v:rank")
    assert "Hisoblashda xato" in bot.tg.last_text
    assert str(CHAT) not in bot.busy               # keyingi so'rov uchun bo'shatilgan
    assert "ichki xato" not in bot.tg.last_text    # ichki tafsilot foydalanuvchiga chiqmaydi


# ----------------------------------------------------------------- bo'limlar
@pytest.mark.parametrize("key", [key for key, _, _ in SECTIONS])
def test_har_bolim_togri_html_va_sigadigan_matn(bot, key):
    say(bot, "34191")
    press(bot, f"v:{key}")
    text = bot.tg.last_text
    assert len(text) <= 4096 and "Hisoblashda xato" not in text
    assert html_ok(text), text[:400]


def test_raqiblar_tugmalari_va_yakkama_yakka(bot):
    say(bot, "34191")
    press(bot, "lg:77")                        # soxta klientda ligalar ro'yxati yo'q — ID bilan
    assert bot.users.get(CHAT)["league"] == 77
    keyboard = bot.tg.edits[-1]["keyboard"]["inline_keyboard"]
    duel = [b for row in keyboard for b in row if b["callback_data"].startswith("du:")]
    assert duel, "raqib tugmalari bo'lishi kerak"
    press(bot, duel[0]["callback_data"])
    text = bot.tg.last_text
    assert "Siz va" in text and html_ok(text)
    back = bot.tg.edits[-1]["keyboard"]["inline_keyboard"][0][0]
    assert back["callback_data"] == "v:rivals"


# ------------------------------------------------------------------ matn
def test_xavfli_belgilar_ekranlanadi():
    assert render.esc("<b>x</b> & y") == "&lt;b&gt;x&lt;/b&gt; &amp; y"
    text = render.error({"error": "<script>", "hint": "a & b"}, "Bo'lim")
    assert "<script>" not in text and html_ok(text)


def test_uzun_matn_satr_chegarasida_kesiladi():
    text = "\n".join(f"<b>qator {i}</b>" for i in range(1000))
    out = render.clip(text, 500)
    assert len(out) < 560 and html_ok(out)
    assert out.endswith("</i>")


# ------------------------------------------------------------------- brend
class PhotoTelegram(FakeTelegram):
    """Rasm yubora oladigan soxta Telegram."""

    def __init__(self, fail: bool = False) -> None:
        super().__init__()
        self.photos: list[dict] = []
        self.fail = fail

    def send_photo(self, chat_id, photo, caption="", keyboard=None):
        self.photos.append({"chat_id": chat_id, "photo": str(photo), "caption": caption})
        return None if self.fail else {"photo": [{"file_id": "kichik"}, {"file_id": "KATTA"}]}


def _bot_with(tg, tmp_path):
    cfg = Config()
    cfg.store_dir = tmp_path / "store"
    return BotApp(cfg, FakeClient(), tg=tg, users=Users(tmp_path / "users.json"), sync=True)


def test_xush_kelibsiz_logo_bilan_va_file_id_qayta_ishlatiladi(tmp_path):
    from tgbot import app as app_mod
    bot = _bot_with(PhotoTelegram(), tmp_path)
    say(bot, "/start")
    first = bot.tg.photos[-1]
    assert first["photo"].endswith("banner.png") and app_mod.BRAND in first["caption"]
    assert not bot.tg.sent                              # matn takror yuborilmaydi
    say(bot, "/start", chat=2)
    assert bot.tg.photos[-1]["photo"] == "KATTA"        # ikkinchi safar fayl yuklanmaydi


def test_rasm_ketmasa_matn_yuboriladi(tmp_path):
    bot = _bot_with(PhotoTelegram(fail=True), tmp_path)
    say(bot, "/start")
    assert "jamoa ID" in bot.tg.sent[-1]["text"]


def test_xush_kelibsiz_matni_rasm_izohiga_sigadi():
    """Telegram rasm izohi 1024 belgidan oshmaydi."""
    from tgbot import app as app_mod
    assert len(app_mod.WELCOME) <= 1024 and html_ok(app_mod.WELCOME)
    assert app_mod.BANNER.is_file()


def test_menyuda_brend_nomi(bot):
    say(bot, "34191")
    assert "FPLUzbekistan" in bot.tg.sent[-1]["text"]