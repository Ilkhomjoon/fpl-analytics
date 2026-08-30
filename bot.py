#!/usr/bin/env python3
"""FPL boti — tahlilni tugmalar orqali bo'limlarga bo'lib ko'rsatadi.

    python bot.py

Ishlash tartibi: `run.py` tahlilni hisoblab, bo'limlarni `data/store/` ga
saqlaydi. Bot esa o'sha saqlangan bo'limlarni tugma bosilganda darhol
ko'rsatadi — qayta hisoblamaydi, shuning uchun tezkor.

"🔄 Yangilash" tugmasi tahlilni fonda qaytadan hisoblaydi.

Buyruqlar:
    /menu     — bo'limlar menyusi
    /yangila  — tahlilni qaytadan hisoblash
    /holat    — hisobot qachon yasalgani
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

from fplbrain.config import Config
from fplbrain.sections import Report
from fplbrain.store import Store
from fplbrain.telegram import (
    BACK_BUTTON, FULL_BUTTON, REFRESH_BUTTON, Telegram, build_keyboard,

)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("fplbot")

ROOT = Path(__file__).resolve().parent


class Bot:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.tg = Telegram(cfg.telegram_token, cfg.telegram_chat_id)
        self.store = Store(cfg.store_dir)
        self.refreshing = False

    # ------------------------------------------------------------ ruxsat
    def allowed(self, chat_id: str | int) -> bool:
        """Faqat sozlangan kanal/chat bilan ishlaydi — begona hech kim emas."""
        return str(chat_id) == str(self.cfg.telegram_chat_id)

    # ------------------------------------------------------------ ko'rinishlar
    def report(self) -> Report | None:
        return Report.load(self.cfg.store_dir)

    def menu_view(self) -> tuple[str, dict]:
        rep = self.report()
        if not rep:
            return (
                "Hisobot hali yasalmagan.\n\n"
                "<code>python run.py</code> ni ishga tushiring yoki "
                "🔄 Yangilash tugmasini bosing.",
                {"inline_keyboard": [[REFRESH_BUTTON]]},
            )
        text = (
            f"{rep.summary}\n\n"
            f"<i>Hisobot {rep.age_text} yasalgan. Bo'limni tanlang:</i>"
        )
        keyboard = build_keyboard(
            rep.sections, columns=2,
            extra_rows=[[FULL_BUTTON, REFRESH_BUTTON]],
        )
        return text, keyboard

    def section_view(self, key: str) -> tuple[str, dict]:
        rep = self.report()
        if not rep:
            return "Hisobot yo'q.", {"inline_keyboard": [[REFRESH_BUTTON]]}
        section = rep.get(key)
        if not section:
            return "Bu bo'lim topilmadi.", {"inline_keyboard": [[BACK_BUTTON]]}

        # Bir xabarga sig'masa, oxirida eslatma qoldiramiz
        text = section.text
        if len(text) > 3900:
            text = text[:3900].rsplit("\n", 1)[0] + "\n\n<i>…davomi kesildi</i>"
        return text, {"inline_keyboard": [[BACK_BUTTON, REFRESH_BUTTON]]}

    # ------------------------------------------------------------ yangilash
    def refresh_async(self, notify_id: int | None = None) -> None:
        if self.refreshing:
            self.tg.call("sendMessage", {
                "chat_id": self.cfg.telegram_chat_id,
                "text": "Hisoblash allaqachon ketmoqda, kuting.",
            })
            return
        threading.Thread(target=self._refresh, args=(notify_id,), daemon=True).start()

    def _refresh(self, notify_id: int | None) -> None:
        self.refreshing = True
        started = time.time()
        try:
            if notify_id:
                self.tg.edit(notify_id, "⏳ Tahlil hisoblanmoqda… (1-3 daqiqa)",
                             {"inline_keyboard": []})
            result = subprocess.run(
                [sys.executable, "run.py", "--save-only"],
                cwd=ROOT, capture_output=True, text=True, timeout=900,
            )
            if result.returncode != 0:
                tail = (result.stderr or result.stdout or "")[-500:]
                log.error("run.py xatosi: %s", tail)
                if notify_id:
                    self.tg.edit(notify_id, f"Hisoblashda xato:\n<code>{tail[-300:]}</code>",
                                 {"inline_keyboard": [[REFRESH_BUTTON]]})
                return
            log.info("Yangilandi (%.0f soniya)", time.time() - started)
            if notify_id:
                text, keyboard = self.menu_view()
                self.tg.edit(notify_id, text, keyboard)
        except subprocess.TimeoutExpired:
            log.error("run.py juda uzoq ishladi")
            if notify_id:
                self.tg.edit(notify_id, "Hisoblash juda uzoq ketdi, to'xtatildi.",
                             {"inline_keyboard": [[REFRESH_BUTTON]]})
        finally:
            self.refreshing = False

    # ------------------------------------------------------------ hodisalar
    def on_callback(self, query: dict) -> None:
        data = query.get("data", "")
        message = query.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        message_id = message.get("message_id")
        if not self.allowed(chat_id):
            self.tg.answer_callback(query["id"], "Ruxsat yo'q")
            return

        if data == "menu":
            self.tg.answer_callback(query["id"])
            text, keyboard = self.menu_view()
            self.tg.edit(message_id, text, keyboard, chat_id=chat_id)
        elif data == "refresh":
            self.tg.answer_callback(query["id"], "Hisoblanmoqda…")
            self.refresh_async(message_id)
        elif data == "full":
            self.tg.answer_callback(query["id"], "To'liq hisobot jo'natilmoqda")
            rep = self.report()
            if rep:
                self.tg.send(rep.full_text())
        elif data.startswith("s:"):
            self.tg.answer_callback(query["id"])
            text, keyboard = self.section_view(data[2:])
            self.tg.edit(message_id, text, keyboard, chat_id=chat_id)
        else:
            self.tg.answer_callback(query["id"])

    def on_message(self, message: dict) -> None:
        chat_id = (message.get("chat") or {}).get("id")
        if not self.allowed(chat_id):
            return
        text = (message.get("text") or "").strip().lower()
        command = text.split()[0] if text else ""
        command = command.split("@")[0]          # /menu@botname

        if command in ("/start", "/menu"):
            menu_text, keyboard = self.menu_view()
            self.tg.send_menu(menu_text, keyboard)
        elif command in ("/yangila", "/refresh"):
            message_id = self.tg.send_menu("⏳ Tahlil hisoblanmoqda…",
                                           {"inline_keyboard": []})
            self.refresh_async(message_id)
        elif command in ("/holat", "/status"):
            rep = self.report()
            if rep:
                self.tg.send(
                    f"GW{rep.event} · {rep.mode}\n"
                    f"Hisobot: {rep.age_text}\n"
                    f"Bo'limlar: {len(rep.sections)} ta"
                )
            else:
                self.tg.send("Hisobot hali yasalmagan.")
        elif command.startswith("/"):
            self.tg.send(
                "Buyruqlar:\n"
                "/menu — bo'limlar menyusi\n"
                "/yangila — tahlilni qaytadan hisoblash\n"
                "/holat — hisobot qachon yasalgani"
            )

    # ------------------------------------------------------------ asosiy sikl
    def run(self) -> int:
        if self.tg.dry_run:
            log.error("TELEGRAM_TOKEN yoki TELEGRAM_CHAT_ID berilmagan.")
            return 2

        offset = int(self.store.read("bot_offset", 0) or 0)
        log.info("Bot ishga tushdi. Kanal: %s", self.cfg.telegram_chat_id)

        # Ishga tushganda menyuni bir marta ko'rsatamiz
        text, keyboard = self.menu_view()
        self.tg.send_menu(text, keyboard)

        idle_errors = 0
        while True:
            try:
                updates = self.tg.get_updates(offset, timeout=25)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                idle_errors += 1
                log.warning("getUpdates xatosi (%d): %s", idle_errors, exc)
                time.sleep(min(60, 3 * idle_errors))
                continue

            if updates is None:
                time.sleep(3)
                continue
            idle_errors = 0

            for update in updates:
                offset = update["update_id"] + 1
                try:
                    if "callback_query" in update:
                        self.on_callback(update["callback_query"])
                    elif "message" in update:
                        self.on_message(update["message"])
                except Exception as exc:
                    log.exception("Hodisani qayta ishlashda xato: %s", exc)
            if updates:
                self.store.write("bot_offset", offset)


def main() -> int:
    cfg = Config.load()
    bot = Bot(cfg)
    try:
        return bot.run()
    except KeyboardInterrupt:
        log.info("To'xtatildi.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
