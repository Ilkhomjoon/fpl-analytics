"""Telegram jo'natuvchi — uzun hisobotni bo'laklarga bo'lib yuboradi."""

from __future__ import annotations

import html
import logging
import time

import requests

log = logging.getLogger(__name__)
LIMIT = 3800


def escape(text: str) -> str:
    return html.escape(text, quote=False)


def split_message(text: str, limit: int = LIMIT) -> list[str]:
    """Xabarni satr chegarasida bo'ladi (HTML teglarini buzmasdan)."""
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(block) <= limit:
            current = block
            continue
        # juda uzun blok — satrma-satr bo'lamiz
        current = ""
        for line in block.split("\n"):
            if len(current) + len(line) + 1 > limit:
                chunks.append(current)
                current = line
            else:
                current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


def build_keyboard(
    sections, columns: int = 2, extra_rows: list[list[dict]] | None = None
) -> dict:
    """Bo'limlardan inline klaviatura yasaydi."""
    buttons = [
        {"text": s.title, "callback_data": f"s:{s.key}"} for s in sections
    ]
    rows = [buttons[i:i + columns] for i in range(0, len(buttons), columns)]
    rows += extra_rows or []
    return {"inline_keyboard": rows}


BACK_BUTTON = {"text": "◀ Menyu", "callback_data": "menu"}
REFRESH_BUTTON = {"text": "🔄 Yangilash", "callback_data": "refresh"}
FULL_BUTTON = {"text": "📄 Hammasi", "callback_data": "full"}


class Telegram:
    def __init__(self, token: str, chat_id: str, dry_run: bool = False) -> None:
        self.token = token
        self.chat_id = chat_id
        self.dry_run = dry_run or not (token and chat_id)

    def send(self, text: str, disable_preview: bool = True) -> list[int]:
        """Xabarni jo'natadi. Tarmoq ishlamasa ham **dastur qulamaydi**."""
        parts = split_message(text)
        ids: list[int] = []
        self.last_error = None

        for i, part in enumerate(parts):
            if self.dry_run:
                print(f"\n{'='*60}\n[TELEGRAM {i+1}/{len(parts)}]\n{'='*60}\n{part}")
                continue

            sent = False
            for attempt in range(3):
                try:
                    resp = requests.post(
                        f"https://api.telegram.org/bot{self.token}/sendMessage",
                        json={
                            "chat_id": self.chat_id,
                            "text": part,
                            "parse_mode": "HTML",
                            "disable_web_page_preview": disable_preview,
                        },
                        timeout=20,
                    )
                except requests.exceptions.RequestException as exc:
                    # Ulanish yo'q: O'zbekistonda Telegram ba'zan to'g'ridan-to'g'ri
                    # ochilmaydi. Bu hisobotni yo'q qilishga asos emas.
                    self.last_error = exc
                    log.warning("Telegramga ulanmadi (%d-urinish): %s",
                                attempt + 1, type(exc).__name__)
                    time.sleep(2 * (attempt + 1))
                    continue

                if resp.status_code == 200:
                    ids.append(resp.json().get("result", {}).get("message_id", 0))
                    sent = True
                    break
                if resp.status_code == 429:            # tezlik chegarasi
                    wait = (resp.json().get("parameters") or {}).get("retry_after", 3)
                    time.sleep(min(30, wait + 1))
                    continue
                # 400/403 — xabar yoki sozlama xatosi, qayta urinish yordam bermaydi
                self.last_error = RuntimeError(f"{resp.status_code}: {resp.text[:200]}")
                log.error("Telegram rad etdi %s: %s", resp.status_code, resp.text[:300])
                break

            if not sent and self.last_error:
                log.error("Xabarning %d-qismi jo'natilmadi.", i + 1)
                break
            time.sleep(0.6)
        return ids

    @property
    def failed(self) -> bool:
        return getattr(self, "last_error", None) is not None

    # ------------------------------------------------------ past darajadagi API
    def call(self, method: str, payload: dict, timeout: int = 25) -> dict | None:
        """Telegram Bot API chaqiruvi. Xato bo'lsa None qaytaradi, qulamaydi."""
        if self.dry_run:
            log.info("[dry-run] %s: %s", method, str(payload)[:120])
            return None
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{self.token}/{method}",
                json=payload, timeout=timeout,
            )
        except requests.exceptions.RequestException as exc:
            self.last_error = exc
            log.warning("%s ishlamadi: %s", method, type(exc).__name__)
            return None
        if resp.status_code != 200:
            # 400 "message is not modified" — bir xil matnni qayta yozish, zararsiz
            if "message is not modified" not in resp.text:
                log.warning("%s rad etildi %s: %s", method, resp.status_code,
                            resp.text[:200])
            return None
        return resp.json().get("result")

    def send_menu(self, text: str, keyboard: dict) -> int | None:
        """Tugmali xabar jo'natadi; message_id qaytaradi."""
        if self.dry_run:
            print(f"\n{'='*60}\n[MENYU]\n{'='*60}\n{text}")
            for row in keyboard["inline_keyboard"]:
                print("  [" + "] [".join(b["text"] for b in row) + "]")
            return None
        result = self.call("sendMessage", {
            "chat_id": self.chat_id, "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": True, "reply_markup": keyboard,
        })
        return (result or {}).get("message_id")

    def edit(self, message_id: int, text: str, keyboard: dict | None = None,
             chat_id: str | None = None) -> bool:
        payload = {
            "chat_id": chat_id or self.chat_id, "message_id": message_id,
            "text": text[:4096], "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if keyboard:
            payload["reply_markup"] = keyboard
        return self.call("editMessageText", payload) is not None

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        """Tugma bosilganda "soat" belgisini o'chiradi."""
        self.call("answerCallbackQuery",
                  {"callback_query_id": callback_id, "text": text[:200]}, timeout=10)

    def get_updates(self, offset: int, timeout: int = 25) -> list[dict]:
        result = self.call("getUpdates", {
            "offset": offset, "timeout": timeout,
            "allowed_updates": ["message", "callback_query"],
        }, timeout=timeout + 10)
        return result or []
