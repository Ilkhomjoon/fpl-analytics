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


class Telegram:
    def __init__(self, token: str, chat_id: str, dry_run: bool = False) -> None:
        self.token = token
        self.chat_id = chat_id
        self.dry_run = dry_run or not (token and chat_id)

    def send(self, text: str, disable_preview: bool = True) -> list[int]:
        parts = split_message(text)
        ids: list[int] = []
        for i, part in enumerate(parts):
            if self.dry_run:
                print(f"\n{'='*60}\n[TELEGRAM {i+1}/{len(parts)}]\n{'='*60}\n{part}")
                continue
            resp = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": part,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": disable_preview,
                },
                timeout=25,
            )
            if resp.status_code != 200:
                log.error("Telegram xatosi %s: %s", resp.status_code, resp.text[:300])
            else:
                ids.append(resp.json().get("result", {}).get("message_id", 0))
            time.sleep(0.6)
        return ids
