"""Hisobotni bo'limlarga ajratilgan holda saqlash va o'qish.

Telegram boti tugmalar orqali alohida bo'limlarni ko'rsatishi uchun hisobot
bitta uzun matn emas, **kalitlangan bo'limlar to'plami** sifatida saqlanadi.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

STORE_NAME = "last_report.json"


@dataclass
class Section:
    key: str                  # callback_data uchun (64 baytdan kam)
    title: str                # tugma yozuvi
    text: str                 # HTML matn

    @property
    def empty(self) -> bool:
        return not self.text or not self.text.strip()


@dataclass
class Report:
    event: int
    mode: str
    generated: str            # ISO vaqt
    deadline: str
    summary: str              # menyu xabarining tepasidagi qisqa xulosa
    sections: list[Section] = field(default_factory=list)

    def add(self, key: str, title: str, text: str) -> None:
        section = Section(key=key, title=title, text=text)
        if not section.empty:
            self.sections.append(section)

    def get(self, key: str) -> Section | None:
        return next((s for s in self.sections if s.key == key), None)

    def full_text(self) -> str:
        """Hamma bo'limni bitta matnga birlashtiradi (eski uslub)."""
        return "\n\n".join(s.text for s in self.sections)

    # ------------------------------------------------------------- saqlash
    def save(self, store_dir: Path) -> Path:
        path = Path(store_dir) / STORE_NAME
        path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=1), encoding="utf-8"
        )
        return path

    @staticmethod
    def load(store_dir: Path) -> "Report | None":
        path = Path(store_dir) / STORE_NAME
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        sections = [Section(**s) for s in data.get("sections", [])]
        return Report(
            event=data.get("event", 0),
            mode=data.get("mode", ""),
            generated=data.get("generated", ""),
            deadline=data.get("deadline", ""),
            summary=data.get("summary", ""),
            sections=sections,
        )

    @property
    def age_text(self) -> str:
        """Hisobot qachon yasalgani — "12 daqiqa oldin" ko'rinishida."""
        try:
            made = datetime.fromisoformat(self.generated)
        except (TypeError, ValueError):
            return "noma'lum vaqt"
        delta = datetime.now(made.tzinfo) - made
        minutes = int(delta.total_seconds() // 60)
        if minutes < 1:
            return "hozirgina"
        if minutes < 60:
            return f"{minutes} daqiqa oldin"
        hours = minutes // 60
        if hours < 24:
            return f"{hours} soat oldin"
        return f"{hours // 24} kun oldin"
