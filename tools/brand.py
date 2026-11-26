"""Logodan sahifa va bot uchun rasmlar yasaydi.

    python tools/brand.py

Manba: `assets/brand/FPLUzekistan.png` (2172×724, shaffof fon). Undan:

    web/static/logo-mark.png     sher belgisi — sahifa burchagi (ikkala mavzuda)
    web/static/favicon.png       brauzer ikonkasi
    tgbot/assets/banner.png      botning xush kelibsiz rasmi (to'q fon)
    tgbot/assets/avatar.png      bot avatari — @BotFather orqali qo'yiladi

Logodagi «FPL» yozuvi OQ — u faqat to'q fonda ko'rinadi. Shuning uchun
sahifada yozuv rasm emas, matn (mavzuga qarab rangi o'zgaradi), rasm sifatida
esa faqat belgi ishlatiladi. Botdagi rasmlar to'q fonga qo'yiladi.

Logo almashsa: yangi faylni shu nom bilan qo'yib, skriptni qayta ishga tushiring.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "brand" / "FPLUzekistan.png"
DARK = (9, 11, 16, 255)          # sahifaning tungi foni bilan bir xil


def trim(image: Image.Image) -> Image.Image:
    box = image.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox()
    return image.crop(box) if box else image


def split_mark(image: Image.Image) -> Image.Image:
    """Belgi va yozuv orasidagi bo'sh ustunlarni topib, belgini ajratadi."""
    alpha = image.getchannel("A")
    width, height = image.size
    filled = [alpha.crop((x, 0, x + 1, height)).getbbox() is not None for x in range(width)]
    x = next(i for i, f in enumerate(filled) if f)
    run = 0
    for i in range(x, width):
        run = 0 if filled[i] else run + 1
        if run >= max(6, width // 120):              # yetarlicha keng bo'shliq
            return trim(image.crop((0, 0, i - run + 1, height)))
    raise SystemExit("Belgi va yozuv orasida bo'shliq topilmadi.")


def fit(image: Image.Image, size: int) -> Image.Image:
    scale = size / max(image.size)
    return image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                        Image.LANCZOS)


def on_canvas(image: Image.Image, size: tuple[int, int], pad: float, colour=DARK) -> Image.Image:
    canvas = Image.new("RGBA", size, colour)
    room = (size[0] * (1 - 2 * pad), size[1] * (1 - 2 * pad))
    scale = min(room[0] / image.width, room[1] / image.height)
    logo = image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
    canvas.alpha_composite(logo, ((size[0] - logo.width) // 2, (size[1] - logo.height) // 2))
    return canvas


def main() -> None:
    if not SOURCE.exists():
        sys.exit(f"Manba topilmadi: {SOURCE}")
    full = trim(Image.open(SOURCE).convert("RGBA"))
    mark = split_mark(full)

    static = ROOT / "web" / "static"
    assets = ROOT / "tgbot" / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    fit(mark, 256).save(static / "logo-mark.png", optimize=True)
    on_canvas(mark, (96, 96), 0.08, (0, 0, 0, 0)).save(static / "favicon.png", optimize=True)
    on_canvas(full, (1280, 640), 0.09).convert("RGB").save(assets / "banner.png", optimize=True)
    on_canvas(mark, (640, 640), 0.14).convert("RGB").save(assets / "avatar.png", optimize=True)
    for path in (static / "logo-mark.png", static / "favicon.png",
                 assets / "banner.png", assets / "avatar.png"):
        print(f"  {path.relative_to(ROOT)}  {Image.open(path).size}  {path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
