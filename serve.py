#!/usr/bin/env python3
"""Web sahifani ishga tushiradi.

    python serve.py                 # http://127.0.0.1:8000
    python serve.py --demo          # tarmoqsiz, soxta ma'lumot bilan
    python serve.py --port 8080

Sahifa faqat shu kompyuterda ochiladi (127.0.0.1). Boshqa qurilmadan kirish
kerak bo'lsa `--host 0.0.0.0` bering — lekin unda sahifani (va login
qilingan sessiyani) bir tarmoqdagi hamma ko'radi, shuning uchun ehtiyot bo'ling.
"""

from __future__ import annotations

import argparse
import logging
import sys
import webbrowser

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("fplweb")


def main() -> int:
    parser = argparse.ArgumentParser(description="FPL tahlil — web sahifa")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--demo", action="store_true",
                        help="tarmoqsiz, soxta ma'lumot bilan")
    parser.add_argument("--no-browser", action="store_true",
                        help="brauzerni avtomatik ochmasin")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    from fplbrain.config import Config
    from web.app import create_app

    cfg = Config.load(args.config)
    app = create_app(cfg, demo=args.demo)

    url = f"http://{'127.0.0.1' if args.host == '0.0.0.0' else args.host}:{args.port}"
    if args.host == "0.0.0.0":
        log.warning("Sahifa butun tarmoqqa ochiq (--host 0.0.0.0). "
                    "Login qilingan sessiyani boshqalar ham ishlatadi.")
    log.info("Manzil: %s%s", url, "  (demo rejimi)" if args.demo else "")
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    app.run(host=args.host, port=args.port, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
