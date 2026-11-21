#!/usr/bin/env python3
"""Ko'p foydalanuvchili FPL boti — har kim o'z jamoa ID si bilan.

    python userbot.py            # TELEGRAM_TOKEN .env dan olinadi
    python userbot.py --demo     # FPL ga ulanmasdan, soxta ma'lumot bilan

Eski `bot.py` (bitta chat, tayyor hisobot) o'zgarmagan — bu alohida bot.
To'liq tavsif: `tgbot/app.py`; serverga o'rnatish: `docs/DEPLOY.md`.
"""

from __future__ import annotations

import argparse
import logging
import sys

from fplbrain.api import FplClient
from fplbrain.config import Config
from tgbot.app import BotApp


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo", action="store_true", help="soxta ma'lumot bilan")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    cfg = Config.load(args.config)
    if args.demo:
        from fplbrain.demo import FakeClient
        client = FakeClient()
    else:
        client = FplClient(cfg.cache_dir, cfg.cache_ttl_seconds, cfg.request_delay,
                           cfg.max_workers)
    try:
        return BotApp(cfg, client).run()
    except KeyboardInterrupt:
        logging.getLogger("userbot").info("To'xtatildi.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
