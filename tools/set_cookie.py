#!/usr/bin/env python3
"""Cookie ni xavfsiz va xatosiz `.env` ga yozadi.

Odatiy ishlatish — cookie ni nusxalab olib, shunchaki:

    python tools/set_cookie.py

Skript uni **buferdan** (clipboard) o'qiydi. Konsolga yopishtirish shart emas:
PowerShell bir necha kilobaytlik matnni qirqib tashlaydi, cookie esa uzun.

Boshqa usullar:
    python tools/set_cookie.py --from-file cookie.txt   # faylga saqlab qo'ygan bo'lsangiz
    python tools/set_cookie.py --stdin                  # quvur orqali (Linux/macOS)

Cookie qiymati ekranga hech qachon chiqarilmaydi.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
KEY = "FPL_COOKIE"

# Sessiyani tasdiqlaydigan cookie lar.
# FPL PingOne SSO ga o'tgan: hozir asosiylari access_token va global_sso_id.
# Eski Django nomlari (sessionid, pl_profile) hamon uchrashi mumkin.
SESSION_COOKIES = (
    "access_token", "global_sso_id", "refresh_token",
    "pl_profile", "sessionid", "csrftoken",
)
# Brauzer va IP ga bog'langan bot himoyasi tokenlari
BROWSER_BOUND = ("cf_clearance", "datadome")


# ------------------------------------------------------------------ o'qish
def read_clipboard() -> str:
    """Windows/macOS/Linux buferidan matn oladi."""
    # 1) tkinter — standart kutubxona, qo'shimcha jarayonsiz
    try:
        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        try:
            return root.clipboard_get()
        finally:
            root.destroy()
    except Exception:
        pass

    # 2) OS buyruqlari
    commands = []
    if sys.platform == "win32":
        commands = [["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"]]
    elif sys.platform == "darwin":
        commands = [["pbpaste"]]
    else:
        commands = [["xclip", "-selection", "clipboard", "-o"], ["xsel", "-b"]]

    for cmd in commands:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout
        except Exception:
            continue
    return ""


# ---------------------------------------------------------------- tozalash
def clean(raw: str) -> str:
    """Yopishtirilgan matndan yaroqli cookie sarlavhasini yasaydi."""
    text = raw.strip()
    text = re.sub(r"^\s*cookie\s*:\s*", "", text, flags=re.IGNORECASE)
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    text = re.sub(r"\s+", " ", text)
    parts = [p.strip() for p in text.split(";")]
    return "; ".join(p for p in parts if p)


def cookie_names(cookie: str) -> list[str]:
    return [p.split("=", 1)[0].strip() for p in cookie.split(";") if "=" in p]


def looks_truncated(cookie: str) -> bool:
    """Birinchi bo'lak `nom=qiymat` ko'rinishida bo'lmasa, boshi qirqilgan."""
    first = cookie.split(";", 1)[0].strip()
    if "=" not in first:
        return True
    name = first.split("=", 1)[0]
    # cookie nomida bo'lmaydigan belgilar bo'lsa — bu qiymatning qoldig'i
    return not re.fullmatch(r"[A-Za-z0-9_.\-]+", name)


# -------------------------------------------------------------------- yozish
def upsert_env(path: Path, key: str, value: str) -> str:
    """`.env` dagi kalitni yangilaydi yoki qo'shadi. Boshqa satrlar tegilmaydi."""
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    out, replaced = [], False
    for line in lines:
        if line.strip().startswith(f"{key}=") or line.strip().startswith(f"export {key}="):
            if not replaced:
                out.append(f"{key}={value}")
                replaced = True
            continue
        out.append(line)
    if not replaced:
        out.append(f"{key}={value}")
    path.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")
    return "yangilandi" if replaced else "qo'shildi"


# --------------------------------------------------------------------- asosiy
def main() -> int:
    parser = argparse.ArgumentParser(description="FPL cookie ni .env ga yozadi")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--from-file", metavar="FAYL", help="cookie saqlangan matn fayli")
    source.add_argument("--stdin", action="store_true", help="standart kirishdan o'qish")
    parser.add_argument("--force", action="store_true",
                        help="ogohlantirishlarga qaramay yozish")
    args = parser.parse_args()

    if args.from_file:
        raw = Path(args.from_file).read_text(encoding="utf-8-sig")
        source_name = args.from_file
    elif args.stdin:
        raw = sys.stdin.read()
        source_name = "standart kirish"
    else:
        raw = read_clipboard()
        source_name = "bufer (clipboard)"
        if not raw.strip():
            print("Buferda matn topilmadi.")
            print("Cookie ni nusxalab, qaytadan urinib ko'ring, yoki:")
            print("  1) cookie ni cookie.txt fayliga saqlang")
            print("  2) python tools/set_cookie.py --from-file cookie.txt")
            return 2

    cookie = clean(raw)
    if not cookie or "=" not in cookie:
        print(f"Cookie o'qilmadi ({source_name}) — bo'sh yoki formati noto'g'ri.")
        return 2

    names = cookie_names(cookie)
    found = [c for c in SESSION_COOKIES if c in names]
    problems = []

    if looks_truncated(cookie):
        problems.append(
            "Qatorning BOSHI qirqilganga o'xshaydi — birinchi bo'lak `nom=qiymat` "
            "emas.\n  Konsolga yopishtirgan bo'lsangiz shunday bo'ladi: cookie ni "
            "cookie.txt ga\n  saqlab, `--from-file cookie.txt` bilan bering."
        )
    if not found:
        problems.append(
            f"Sessiya cookie si topilmadi ({', '.join(SESSION_COOKIES[:3])} ...).\n"
            "  Ehtimol noto'g'ri qator nusxalangan yoki qirqilgan."
        )

    if problems and not args.force:
        print(f"Manba: {source_name} · {len(cookie)} belgi, {len(names)} ta cookie\n")
        for p in problems:
            print(f"  ⚠ {p}")
        print("\nHech narsa yozilmadi. Baribir yozish uchun: --force")
        return 2

    action = upsert_env(ENV_PATH, KEY, cookie)
    print(f"Manba: {source_name}")
    print(f".env fayliga {action}. Uzunligi: {len(cookie)} belgi, {len(names)} ta cookie.")
    print(f"Sessiya cookie lari: {', '.join(found) or 'topilmadi (--force bilan yozildi)'}")

    bound = [c for c in BROWSER_BOUND if c in names]
    if bound:
        print(f"Eslatma: {', '.join(bound)} bor — brauzer va IP ga bog'langan, "
              "faqat shu kompyuterda ishlaydi.")

    print("\nEndi tekshiring:  python run.py --check-auth")
    return 0


if __name__ == "__main__":
    sys.exit(main())
