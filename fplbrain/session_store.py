"""Kirish sessiyasini diskda saqlash — har safar qaytadan login qilmaslik uchun.

Muammo: token faqat jarayon xotirasida tursa, `serve.py` har yopilib
ochilganda qaytadan kirish kerak bo'ladi. Brauzer oynasi ochilib, siz uni
kutib turasiz. Bu vaqtingizni oladi.

Yechim ikki qismdan iborat:

1. **Token diskda saqlanadi** (`data/session.json`). Keyingi ishga tushishda
   u o'qiladi va agar muddati o'tmagan bo'lsa — kirish **bir zumda** tiklanadi,
   hech qanday oyna ochilmaydi.
2. **Muddati bilinadi.** FPL tokeni — JWT, uning ichida `exp` (tugash vaqti)
   yozilgan. Shuni o'qib, oldindan yangilash mumkin: siz kutmaysiz, yangilanish
   fonda bo'ladi.

MAXFIYLIK. Fayl faqat sizning kompyuteringizda, `.gitignore` da, va faqat
egasiga o'qish/yozish huquqi bilan (`0600`) yaratiladi. Ichida **parol yo'q** —
faqat token. Chiqish (`logout`) faylni o'chiradi.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

FOLDER = "sessions"
# Har akkaunt o'z faylida — bitta umumiy fayl ko'p foydalanuvchi uchun
# yaramaydi va birovning tokenini boshqasiga berib qo'yishi mumkin.
# Muddati noma'lum bo'lsa shuncha vaqt yaroqli deb hisoblaymiz
ASSUMED_LIFETIME = 45 * 60
# Tugashiga shundan kam qolsa — oldindan yangilaymiz
REFRESH_MARGIN = 5 * 60


def jwt_expiry(token: str) -> float:
    """JWT ichidagi `exp` (unix vaqt). O'qib bo'lmasa 0.

    Imzo tekshirilmaydi — bizga faqat tugash vaqti kerak, tokenning o'zi
    serverda tekshiriladi.
    """
    parts = (token or "").split(".")
    if len(parts) != 3:
        return 0.0
    try:
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)          # base64url to'ldirish
        data = json.loads(base64.urlsafe_b64decode(payload))
        return float(data.get("exp") or 0)
    except Exception:
        return 0.0


@dataclass
class StoredSession:
    token: str = ""
    cookie: str = ""
    entry_id: int = 0
    name: str = ""
    saved_at: float = 0.0

    @property
    def expires_at(self) -> float:
        """Tugash vaqti (unix). JWT dan olinadi, bo'lmasa taxmin qilinadi."""
        return jwt_expiry(self.token) or (self.saved_at + ASSUMED_LIFETIME)

    @property
    def seconds_left(self) -> int:
        return max(0, int(self.expires_at - time.time()))

    @property
    def valid(self) -> bool:
        return bool(self.token or self.cookie) and self.seconds_left > 0

    @property
    def needs_refresh(self) -> bool:
        """Tugashiga oz qoldi — foydalanuvchi kutmasin, oldindan yangilaymiz."""
        return self.seconds_left < REFRESH_MARGIN

    def as_dict(self) -> dict:
        """Tashxis uchun — token QIYMATI chiqmaydi."""
        return {
            "entry_id": self.entry_id,
            "name": self.name,
            "seconds_left": self.seconds_left,
            "valid": self.valid,
            "method": "token" if self.token else ("cookie" if self.cookie else ""),
        }


def account_key(email: str) -> str:
    """Email dan barqaror, qisqa kalit. Email ning o'zi diskda saqlanmaydi."""
    normalised = (email or "").strip().lower()
    if not normalised:
        return "default"
    return hashlib.sha256(normalised.encode()).hexdigest()[:16]


def path_for(data_dir, key: str = "default") -> Path:
    return Path(data_dir) / FOLDER / f"{key or 'default'}.json"


def known_keys(data_dir) -> list[str]:
    """Saqlangan sessiyalar kalitlari — tashxis uchun."""
    folder = Path(data_dir) / FOLDER
    if not folder.exists():
        return []
    return sorted(f.stem for f in folder.glob("*.json"))


def load(data_dir, key: str = "default") -> StoredSession:
    """Saqlangan sessiyani o'qiydi. Fayl yo'q yoki buzuq bo'lsa — bo'sh sessiya."""
    file = path_for(data_dir, key)
    if not file.exists():
        return StoredSession()
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("sessiya fayli o'qilmadi: %s", exc)
        return StoredSession()
    return StoredSession(
        token=data.get("token", ""),
        cookie=data.get("cookie", ""),
        entry_id=int(data.get("entry_id") or 0),
        name=data.get("name", ""),
        saved_at=float(data.get("saved_at") or 0),
    )


def save(data_dir, token: str = "", cookie: str = "", entry_id: int = 0,
         name: str = "", key: str = "default") -> StoredSession:
    """Sessiyani faqat egasi o'qiy oladigan faylga yozadi."""
    session = StoredSession(token=token, cookie=cookie, entry_id=entry_id,
                            name=name, saved_at=time.time())
    file = path_for(data_dir, key)
    file.parent.mkdir(parents=True, exist_ok=True)
    try:
        file.write_text(json.dumps({
            "token": session.token, "cookie": session.cookie,
            "entry_id": session.entry_id, "name": session.name,
            "saved_at": session.saved_at,
        }), encoding="utf-8")
        # Windows da `chmod` cheklangan, lekin xato bermaydi
        os.chmod(file, 0o600)
    except Exception as exc:
        log.warning("sessiya saqlanmadi: %s", exc)
    return session


def clear(data_dir, key: str = "default") -> bool:
    """Chiqishda faylni o'chiradi. Qaytaradi: fayl bor edimi."""
    file = path_for(data_dir, key)
    try:
        if file.exists():
            file.unlink()
            return True
    except Exception as exc:
        log.warning("sessiya o'chirilmadi: %s", exc)
    return False
