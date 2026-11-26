"""Botning Telegramdagi ko'rinishini sozlaydi: nom, tavsif, buyruqlar menyusi.

    python tools/bot_profile.py            # nima o'zgarishini ko'rsatadi
    python tools/bot_profile.py --apply    # Telegramga yozadi

Token `.env` dagi `TELEGRAM_TOKEN`. Bir marta ishga tushirish yetadi; matnni
o'zgartirsangiz — qayta.

**Avatar bu yerdan qo'yilmaydi**: Telegram Bot API botning profil rasmini
o'zgartirishga ruxsat bermaydi. Uni @BotFather orqali qo'ying:
`/setuserpic` → botni tanlang → `tgbot/assets/avatar.png` ni yuboring.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fplbrain.config import Config                                   # noqa: E402

NAME = "FPLUzbekistan"
SHORT = "FPL jamoangiz uchun shaxsiy tahlil: tarkib, kapitan, transferlar va raqiblar."
DESCRIPTION = (
    "FPLUzbekistan — Fantasy Premier League jamoangiz uchun shaxsiy tahlil.\n\n"
    "• Kim o'ynaydi va kimni kapitan qilish\n"
    "• Kimni sotib, kimni olish\n"
    "• O'rningizdagi raqiblarga nisbatan xavf va imkoniyat\n"
    "• Mini-ligadagi raqibingiz bilan yakkama-yakka\n\n"
    "Parol kerak emas — faqat jamoa ID. Boshlash uchun «Start» ni bosing."
)
COMMANDS = [
    {"command": "menu", "description": "Bo'limlar"},
    {"command": "id", "description": "Jamoa ID ni almashtirish"},
    {"command": "help", "description": "Yordam"},
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="Telegramga yozish")
    args = parser.parse_args()
    token = Config.load().telegram_token
    if not token:
        sys.exit("TELEGRAM_TOKEN topilmadi (.env).")

    def call(method: str, **payload) -> dict:
        resp = requests.post(f"https://api.telegram.org/bot{token}/{method}",
                             json=payload, timeout=25)
        return resp.json()

    me = call("getMe").get("result") or {}
    print(f"Bot: @{me.get('username')} — hozirgi nomi «{me.get('first_name')}»")
    steps = [
        ("Nom", "setMyName", {"name": NAME}),
        ("Qisqa tavsif", "setMyShortDescription", {"short_description": SHORT}),
        ("Tavsif", "setMyDescription", {"description": DESCRIPTION}),
        ("Buyruqlar", "setMyCommands", {"commands": COMMANDS}),
    ]
    for title, method, payload in steps:
        if not args.apply:
            value = next(iter(payload.values()))
            print(f"  {title}: {value if isinstance(value, str) else [c['command'] for c in value]}")
            continue
        result = call(method, **payload)
        print(f"  {title}: {'OK' if result.get('ok') else 'XATO — ' + str(result.get('description'))}")
    if not args.apply:
        print("\nHech narsa o'zgartirilmadi. Yozish uchun: python tools/bot_profile.py --apply")
    else:
        print("\nAvatar: @BotFather → /setuserpic → tgbot/assets/avatar.png")


if __name__ == "__main__":
    main()
