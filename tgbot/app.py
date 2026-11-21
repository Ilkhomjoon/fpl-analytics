"""Ko'p foydalanuvchili bot: har kim o'z jamoa ID sini yuboradi, bo'limlar tugma bilan ochiladi.

    python userbot.py            # TELEGRAM_TOKEN .env dan
    python userbot.py --demo     # tarmoqsiz, soxta ma'lumot bilan

TAMOYILLAR

* **Parol yo'q.** Bot faqat jamoa ID si bilan, FPL ning ochiq ma'lumotida ishlaydi.
  Telegram chatida parol so'rash xavfli, serverda saqlash esa javobgarlik. Narxi:
  tarkib oxirgi deadline holatida, transferlar soni va sotish narxlari taxminiy.
* **Hisob web bilan bir xil.** Har bo'lim `web/*view.py` dagi o'sha funksiyani
  chaqiradi; bu yerda faqat matn ko'rinishi (`render.py`) va suhbat mantig'i.
* **Hech kim kutib qolmaydi.** Hisoblash 5–30 soniya oladi, shuning uchun u
  alohida oqimda ketadi: tugma darhol javob oladi, xabar esa tayyor bo'lgach
  yangilanadi. Bir foydalanuvchi — bir vaqtda bitta so'rov.
* **FPL ni bezovta qilmaslik.** Bir vaqtda eng ko'pi `WORKERS` ta hisob; natijalar
  `CACHE_TTL` soniya keshlanadi; raqiblar namunasi diskda (bir oraliq — bir marta).

Foydalanuvchilar ro'yxati `data/bot/users.json` da (git da yo'q): chat ID,
jamoa ID, jamoa nomi. Boshqa hech narsa saqlanmaydi.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fplbrain.telegram import Telegram
from web import (captainview, chipsview, draftview, h2hview, paceview, rankview,
                 rivalsview, squadview, transferview)

from . import render

log = logging.getLogger("userbot")

WORKERS = 2               # bir vaqtda nechta hisob (FPL ga bosim shu bilan cheklanadi)
CACHE_TTL = 600           # bo'lim natijasi shuncha soniya qayta hisoblanmaydi
WORLD_TTL = 600           # bir jamoa uchun umumiy asos (reyting, EV lar)
MAX_LEAGUE_BUTTONS = 6
MAX_RIVAL_BUTTONS = 8

# (kalit, tugma matni, jamoa ID kerakmi)
SECTIONS = [
    ("squad", "👕 Jamoam", True),
    ("rank", "🎯 O'rnim", True),
    ("captain", "⭐ Kapitan", True),
    ("transfers", "🔁 Transferlar", True),
    ("chips", "⚡ Chiplar", True),
    ("rivals", "🏆 Raqiblar", True),
    ("draft", "➕ Jamoa tuzish", False),
    ("h2h", "⚔️ H2H", False),
    ("pace", "📈 Sur'at", True),
]
TITLES = {key: title for key, title, _ in SECTIONS}
ENTRY_URL = re.compile(r"entry/(\d+)")

WELCOME = (
    "<b>FPL Brain</b> — jamoangiz uchun tahlil.\n\n"
    "Boshlash uchun <b>jamoa ID</b> ingizni yuboring. Uni FPL saytida "
    "«Points» sahifasining manzilidan olasiz:\n"
    "<code>fantasy.premierleague.com/entry/<b>1234567</b>/event/11</code>\n\n"
    "Raqamning o'zini yoki butun havolani yuborsangiz bo'ladi. Parol kerak emas — "
    "bot faqat ochiq ma'lumot bilan ishlaydi."
)
HELP = (
    "/menu — bo'limlar\n"
    "/id — jamoa ID ni almashtirish\n"
    "/help — shu yordam\n\n"
    "Bot ochiq ma'lumot bilan ishlaydi: tarkibingiz oxirgi deadline holatida "
    "ko'rinadi, shu turda qilgan transferlaringiz esa deadline'dan keyin."
)


class Users:
    """Chat → jamoa. Bitta JSON fayl; yozish qulf ostida va atom (vaqtinchalik fayl orqali)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.lock = threading.Lock()
        try:
            self.data: dict[str, dict] = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def get(self, chat_id) -> dict:
        return self.data.get(str(chat_id), {})

    def update(self, chat_id, **fields) -> None:
        with self.lock:
            row = self.data.setdefault(str(chat_id), {})
            row.update(fields)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)


class BotApp:
    def __init__(self, cfg, client, tg: Telegram | None = None,
                 users: Users | None = None, sync: bool = False) -> None:
        self.cfg, self.client = cfg, client
        self.tg = tg or Telegram(cfg.telegram_token, "multi")
        self.users = users or Users(Path(cfg.store_dir).parent / "bot" / "users.json")
        self.allowed = {str(c) for c in (getattr(cfg, "bot_allowed_chats", None) or [])}
        self.sync = sync                       # testlar uchun: hisob shu oqimning o'zida
        self.pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="fpl")
        self.busy: set[str] = set()
        self.busy_lock = threading.Lock()
        self.cache: dict[tuple, tuple[float, str, dict]] = {}
        self.worlds: dict[int, tuple[float, object]] = {}
        self.entry_locks: dict[int, threading.Lock] = {}
        self.locks_lock = threading.Lock()

    # ----------------------------------------------------------- yordamchi
    def permitted(self, chat_id) -> bool:
        """Ro'yxat bo'sh bo'lsa — hamma uchun ochiq; aks holda faqat ro'yxatdagilar."""
        return not self.allowed or str(chat_id) in self.allowed

    def send(self, chat_id, text: str, keyboard: dict | None = None) -> int | None:
        payload = {"chat_id": chat_id, "text": text[:4096], "parse_mode": "HTML",
                   "disable_web_page_preview": True}
        if keyboard:
            payload["reply_markup"] = keyboard
        return (self.tg.call("sendMessage", payload) or {}).get("message_id")

    def edit(self, chat_id, message_id, text: str, keyboard: dict | None = None) -> None:
        if not message_id:
            self.send(chat_id, text, keyboard)
            return
        self.tg.edit(message_id, text, keyboard or {"inline_keyboard": []}, chat_id=chat_id)

    def menu(self, chat_id) -> tuple[str, dict]:
        user = self.users.get(chat_id)
        buttons = [{"text": title, "callback_data": f"v:{key}"} for key, title, _ in SECTIONS]
        rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
        rows.append([{"text": "⚙️ Jamoa ID", "callback_data": "id"}])
        if user.get("entry_id"):
            head = (f"<b>{render.esc(user.get('team') or 'Jamoa')}</b> · "
                    f"ID {user['entry_id']}\nBo'limni tanlang:")
        else:
            head = ("Jamoa ID kiritilmagan — «Jamoa tuzish» va «H2H» ishlaydi, "
                    "qolganlari uchun ID yuboring.")
        return head, {"inline_keyboard": rows}

    @staticmethod
    def back(key: str = "", extra: list[list[dict]] | None = None) -> dict:
        rows = list(extra or [])
        last = [{"text": "◀ Menyu", "callback_data": "m"}]
        if key:
            last.append({"text": "🔄 Yangilash", "callback_data": f"r:{key}"})
        rows.append(last)
        return {"inline_keyboard": rows}

    # ------------------------------------------------------------ jamoa ID
    def set_entry(self, chat_id, text: str) -> None:
        match = ENTRY_URL.search(text) or re.fullmatch(r"\s*(\d{1,9})\s*", text)
        if not match:
            self.send(chat_id, "Jamoa ID raqam bo'lishi kerak. Masalan: <code>1234567</code>")
            return
        entry_id = int(match.group(1))
        try:
            entry = self.client.entry(entry_id) or {}
        except Exception as exc:
            log.info("jamoa %s topilmadi: %s", entry_id, exc)
            entry = {}
        if not entry.get("id") and not entry.get("name"):
            self.send(chat_id, f"<b>{entry_id}</b> ID li jamoa topilmadi. Raqamni tekshirib, "
                               "qayta yuboring.")
            return
        manager = " ".join(x for x in (entry.get("player_first_name"),
                                       entry.get("player_last_name")) if x)
        self.users.update(chat_id, entry_id=entry_id, team=entry.get("name", ""),
                          manager=manager, league=0, awaiting=False)
        text, keyboard = self.menu(chat_id)
        self.send(chat_id, f"Ulandi: <b>{render.esc(entry.get('name', ''))}</b>"
                           f"{' — ' + render.esc(manager) if manager else ''}.\n\n{text}", keyboard)

    # ------------------------------------------------------------- hisoblash
    def _entry_lock(self, entry_id: int) -> threading.Lock:
        with self.locks_lock:
            return self.entry_locks.setdefault(entry_id, threading.Lock())

    def world(self, entry_id: int, fresh: bool = False):
        """Bir jamoa uchun umumiy asos — bo'limlar orasida qayta qurilmaydi."""
        hit = self.worlds.get(entry_id)
        if hit and not fresh and time.time() - hit[0] < WORLD_TTL:
            return hit[1]
        world = squadview.World(self.client, self.cfg, entry_id)
        self.worlds[entry_id] = (time.time(), world)
        return world

    def build(self, key: str, user: dict, arg: int = 0, fresh: bool = False) -> tuple[str, dict]:
        """Bo'lim matni va tugmalari. Kesh kaliti: bo'lim + jamoa + qo'shimcha (liga/raqib)."""
        entry_id = int(user.get("entry_id") or 0)
        cache_key = (key, entry_id, arg)
        hit = self.cache.get(cache_key)
        if hit and not fresh and time.time() - hit[0] < CACHE_TTL:
            return hit[1], hit[2]

        c, cfg = self.client, self.cfg
        keyboard = self.back(key)
        if key == "h2h":
            text = render.h2h(h2hview.build(c, cfg))
        elif key == "draft":
            text = render.draft(draftview.build(c, cfg, entry_id or 1))
        else:
            with self._entry_lock(entry_id):
                world = self.world(entry_id, fresh)
                if key == "squad":
                    text = render.squad(squadview.build(c, cfg, entry_id, world=world))
                elif key == "rank":
                    text = render.rank(rankview.build(c, cfg, entry_id, world=world))
                elif key == "captain":
                    text = render.captain(captainview.build(c, cfg, entry_id, world=world))
                elif key == "transfers":
                    text = render.transfers(transferview.build(c, cfg, entry_id, world=world))
                elif key == "chips":
                    text = render.chips(chipsview.build(c, cfg, entry_id, world=world))
                elif key == "pace":
                    text = render.pace(paceview.build(c, cfg, entry_id))
                elif key == "rivals":
                    payload = rivalsview.build(c, cfg, entry_id, arg or user.get("league") or None,
                                               world=world)
                    text = render.rivals(payload)
                    keyboard = self.back(key, self._rival_buttons(payload))
                elif key == "duel":
                    text = render.duel(rivalsview.duel(c, cfg, entry_id, arg, world=world))
                    keyboard = {"inline_keyboard": [[
                        {"text": "◀ Raqiblar", "callback_data": "v:rivals"},
                        {"text": "◀ Menyu", "callback_data": "m"}]]}
                else:
                    text = "Bu bo'lim topilmadi."
        self.cache[cache_key] = (time.time(), text, keyboard)
        return text, keyboard

    @staticmethod
    def _rival_buttons(payload: dict) -> list[list[dict]]:
        if payload.get("error"):
            return []
        rows: list[list[dict]] = []
        rivals = render.duel_candidates(payload, limit=MAX_RIVAL_BUTTONS)
        buttons = [{"text": f"⚔ {m['name'][:18]}", "callback_data": f"du:{m['entry']}"}
                   for m in rivals]
        rows += [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
        current = payload["league"]["id"]
        leagues = [lg for lg in payload.get("leagues", []) if lg["private"] and lg["id"] != current]
        buttons = [{"text": f"🏆 {lg['name'][:20]}", "callback_data": f"lg:{lg['id']}"}
                   for lg in leagues[:MAX_LEAGUE_BUTTONS]]
        rows += [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
        return rows

    def start_job(self, chat_id, message_id, key: str, arg: int = 0, fresh: bool = False) -> None:
        """Bo'limni fonda hisoblab, xabarni yangilaydi."""
        user = self.users.get(chat_id)
        needs = key not in ("h2h", "draft")
        if needs and not user.get("entry_id"):
            self.edit(chat_id, message_id, WELCOME, self.back())
            return
        with self.busy_lock:
            if str(chat_id) in self.busy:
                self.send(chat_id, "Oldingi so'rov hali hisoblanmoqda — bir oz kuting.")
                return
            self.busy.add(str(chat_id))

        title = TITLES.get(key, "Yakkama-yakka")
        cached = (key, int(user.get("entry_id") or 0), arg) in self.cache and not fresh
        if not cached:
            self.edit(chat_id, message_id, f"⏳ <b>{title}</b> hisoblanmoqda…\n"
                      "<i>Birinchi marta 10–30 soniya, keyin tez.</i>")

        def job() -> None:
            try:
                text, keyboard = self.build(key, user, arg, fresh)
            except Exception as exc:
                log.exception("%s bo'limi (chat %s)", key, chat_id)
                text = (f"<b>{title}</b>\n\nHisoblashda xato: "
                        f"<code>{render.esc(type(exc).__name__)}</code>. Birozdan keyin qayta urining.")
                keyboard = self.back(key if key != "duel" else "")
            finally:
                with self.busy_lock:
                    self.busy.discard(str(chat_id))
            self.edit(chat_id, message_id, text, keyboard)

        if self.sync:
            job()
        else:
            self.pool.submit(job)

    # ------------------------------------------------------------- hodisalar
    def on_message(self, message: dict) -> None:
        chat_id = (message.get("chat") or {}).get("id")
        text = (message.get("text") or "").strip()
        if chat_id is None or not text:
            return
        if not self.permitted(chat_id):
            self.send(chat_id, "Bot hozircha yopiq sinovda. Ruxsat uchun kanal adminiga yozing.\n"
                               f"Sizning chat ID: <code>{chat_id}</code>")
            return
        command = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""
        user = self.users.get(chat_id)

        if command == "/start":
            if user.get("entry_id"):
                self.send(chat_id, *self.menu(chat_id))
            else:
                self.users.update(chat_id, awaiting=True)
                self.send(chat_id, WELCOME)
        elif command == "/menu":
            self.send(chat_id, *self.menu(chat_id))
        elif command == "/id":
            rest = text[len(command):].strip()
            if rest:
                self.set_entry(chat_id, rest)
            else:
                self.users.update(chat_id, awaiting=True)
                self.send(chat_id, "Yangi jamoa ID ni yuboring (raqam yoki havola).")
        elif command == "/help":
            self.send(chat_id, HELP)
        elif command:
            self.send(chat_id, "Bunday buyruq yo'q.\n\n" + HELP)
        elif ENTRY_URL.search(text) or re.fullmatch(r"\d{1,9}", text):
            self.set_entry(chat_id, text)
        else:
            self.send(chat_id, "Tushunmadim. /menu — bo'limlar, /id — jamoa ID.")

    def on_callback(self, query: dict) -> None:
        data = query.get("data", "")
        message = query.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        message_id = message.get("message_id")
        # Telegram javob uchun ~15 soniya beradi — boshqa ishdan OLDIN javob qaytariladi
        if not self.permitted(chat_id):
            self.tg.answer_callback(query.get("id", ""), "Ruxsat yo'q")
            return
        self.tg.answer_callback(query.get("id", ""), "")

        if data == "m":
            self.edit(chat_id, message_id, *self.menu(chat_id))
        elif data == "id":
            self.users.update(chat_id, awaiting=True)
            self.edit(chat_id, message_id, WELCOME, self.back())
        elif data.startswith("v:"):
            self.start_job(chat_id, message_id, data[2:])
        elif data.startswith("r:"):
            self.start_job(chat_id, message_id, data[2:], fresh=True)
        elif data.startswith("lg:") and data[3:].isdigit():
            self.users.update(chat_id, league=int(data[3:]))
            self.start_job(chat_id, message_id, "rivals", arg=int(data[3:]))
        elif data.startswith("du:") and data[3:].isdigit():
            self.start_job(chat_id, message_id, "duel", arg=int(data[3:]))

    def handle(self, update: dict) -> None:
        if "callback_query" in update:
            self.on_callback(update["callback_query"])
        elif "message" in update:
            self.on_message(update["message"])

    # ------------------------------------------------------------ asosiy sikl
    def run(self) -> int:
        if not self.cfg.telegram_token:
            log.error("TELEGRAM_TOKEN berilmagan (.env).")
            return 2
        offset_path = self.users.path.with_name("offset.json")
        try:
            offset = int(json.loads(offset_path.read_text()))
        except (OSError, ValueError):
            offset = 0
        # O'chiq turgan paytdagi tugma bosishlari eskirgan — javob berib bo'lmaydi
        stale = self.tg.get_updates(offset, timeout=0)
        if stale:
            offset = stale[-1]["update_id"] + 1
        log.info("Bot ishga tushdi. Foydalanuvchilar: %d, ruxsat: %s",
                 len(self.users.data), "ro'yxat" if self.allowed else "ochiq")

        errors = 0
        while True:
            try:
                updates = self.tg.get_updates(offset, timeout=25)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                errors += 1
                log.warning("getUpdates xatosi (%d): %s", errors, exc)
                time.sleep(min(60, 3 * errors))
                continue
            errors = 0
            for update in updates or []:
                offset = update["update_id"] + 1
                try:
                    self.handle(update)
                except Exception:
                    log.exception("hodisani qayta ishlashda xato")
            if updates:
                try:
                    offset_path.parent.mkdir(parents=True, exist_ok=True)
                    offset_path.write_text(json.dumps(offset))
                except OSError:
                    pass
