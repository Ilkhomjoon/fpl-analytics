#!/usr/bin/env python3
"""FPL login oqimini "ko'rib chiqadi" va hisobotni faylga yozadi.

    python tools/sso_probe.py                 # parolsiz, login qadamigacha
    python tools/sso_probe.py --raw           # `screen` tuzilmasini ham saqlaydi
    python tools/sso_probe.py --with-login    # parolni ham sinaydi

NEGA KERAK? Oqimdagi ID lar va maydon nomlari FPL ning o'zinikidir — ularni
taxmin qilib bo'lmaydi, serverdan so'rab olish kerak. Men bu hostlarga chiqa
olmayman, siz esa chiqasiz.

MUHIM: **parolsiz ham login qadamigacha borish mumkin.** Oqim qadamlardan
iborat va faqat oxirgisi parol so'raydi; qolganlari (masalan PingOne Protect)
bo'sh qiymat bilan o'tadi. Shuning uchun standart holatda skript login
qadamining maydon nomlarini ko'rsatib to'xtaydi — parol so'ramaydi.

MAXFIYLIK. Faylga bosqich nomi, URL, HTTP kodi, serverning xato xabari va
javob **kalitlari** tushadi. Parol, token, cookie qiymati YOZILMAYDI.
`--raw` bersangiz `screen` tuzilmasi ham qo'shiladi — jo'natishdan oldin
o'zingiz ko'rib chiqing.
"""

from __future__ import annotations

import argparse
import getpass
import json
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fplbrain import pl_sso                                   # noqa: E402

OUT = ROOT / "data" / "sso_probe.json"
MAX_WALK = 4


def redact(text: str, secrets_seen: list[str]) -> str:
    for value in secrets_seen:
        if value and len(value) > 6:
            text = text.replace(value, "<OLIB TASHLANDI>")
    return text


def describe(step) -> str:
    return f"{'OK' if step.ok else 'XATO'} — {step.detail}"


def main() -> int:
    parser = argparse.ArgumentParser(description="FPL login oqimi tashxisi")
    parser.add_argument("--with-login", action="store_true",
                        help="login qadamiga parolni ham yuborish")
    parser.add_argument("--redirect-uri", default="",
                        help="topilmasa qo'lda berish uchun")
    parser.add_argument("--raw", action="store_true",
                        help="`screen` tuzilmasini ham saqlash")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    session = pl_sso.new_session()
    report: dict = {"steps": [], "qadamlar": []}
    secrets_seen: list[str] = []

    print("1  FPL sahifasidan login parametrlari izlanmoqda…")
    params, step = pl_sso.discover_authorize(session, args.redirect_uri)
    report["steps"].append(step.as_dict())
    report["discovery"] = {
        "client_id_topildi": bool(params.get("client_id")),
        "redirect_uri": params.get("redirect_uri", ""),
        "parametrlar": sorted(params),
    }
    print(f"   {describe(step)}")
    if not step.ok:
        return finish(report, args, secrets_seen)

    print("2  PingOne widget sozlamasi olinmoqda (parolsiz)…")
    verifier, challenge = pl_sso.pkce_pair()
    secrets_seen.append(verifier)
    widget, step = pl_sso.start_authorize(
        session, params, challenge, secrets.token_urlsafe(16))
    report["steps"].append(step.as_dict())
    report["widget"] = widget.as_dict()
    secrets_seen += [v for v in (widget.access_token, widget.state) if v]
    print(f"   {describe(step)}")
    if not step.ok:
        return finish(report, args, secrets_seen)

    print("3  DaVinci oqimi boshlanmoqda (hamon parolsiz)…")
    node, step = pl_sso.start_policy(session, widget)
    report["steps"].append(step.as_dict())
    print(f"   {describe(step)}")
    if not step.ok:
        return finish(report, args, secrets_seen)

    # ---- qadamlarni parolsiz kuzatamiz: login qadamigacha ----
    print("4  Qadamlar kuzatilmoqda — login qadamigacha parol kerak emas…")
    for index in range(MAX_WALK):
        entry = {
            "raqam": index + 1,
            "turi": node.kind(),
            "capability": node.capability,
            "maydonlar": node.field_names,
        }
        if node.button_fields:
            # Tugma qiymati maxfiy emas, lekin oqim aynan shunga qarab
            # yiqilgan edi — hisobotda ko'rinib tursin
            entry["tugma"] = {
                "maydonlar": node.button_fields,
                "shablonda": node.buttons,          # hammasi: qiymat + tur
                "nomzodlar": node.button_candidates(),
                "tanlangan": (node.button_candidates() or ["—"])[0],
            }
        if args.raw:
            entry["screen"] = pl_sso.flow_debug(
                node.raw, include_screen=True).get("screen", "")
        report["qadamlar"].append(entry)
        print(f"   qadam {index + 1}: {node.describe()}")

        if node.wants_credentials:
            print("   → LOGIN QADAMI TOPILDI. Parolsiz shu yerda to'xtaymiz.")
            if node.buttons:
                topilgan = ", ".join(b["value"] for b in node.buttons)
                print(f"   tugmalar: {topilgan}")
                print(f"   bosiladi: {(node.button_candidates() or ['—'])[0]}")
            break

        payload, nxt, walk_step = pl_sso.advance(session, widget, node, "", "")
        report["steps"].append(walk_step.as_dict())
        if args.raw and isinstance(payload, dict):
            entry["keyingi_screen"] = pl_sso.flow_debug(
                payload, include_screen=True).get("screen", "")
        print(f"   {describe(walk_step)}")
        if not walk_step.ok or not nxt.ok:
            break
        node = nxt

    report["cookie_nomlari"] = pl_sso.cookie_names(session)
    report["login_qadami_topildi"] = node.wants_credentials
    report["login_maydonlari"] = node.field_names if node.wants_credentials else []

    if args.with_login and node.wants_credentials:
        email = input("   email: ").strip()
        password = getpass.getpass("   parol (ekranda ko'rinmaydi): ")
        secrets_seen += [password, email]
        print("5  Parol yuborilmoqda…")
        payload, nxt, step = pl_sso.advance(session, widget, node, email, password)
        report["steps"].append(step.as_dict())
        print(f"   {describe(step)}")

        # Paroldan keyin oqim darrov tugamasligi mumkin: "davom etish",
        # "eslab qol" kabi oraliq ekranlar bo'ladi. Ular ham kuzatiladi.
        dv = pl_sso.find_dv_response(payload)
        report["oraliq_ekranlar"] = []
        while not dv and nxt.ok:
            ekran = {
                "turi": nxt.kind(),
                "maydonlar": nxt.field_names,
                "tugmalar": nxt.buttons,
                "bosiladi": (nxt.button_candidates() or ["—"])[0],
                "matn": pl_sso.screen_text(nxt.raw),
            }
            report["oraliq_ekranlar"].append(ekran)
            print(f"   oraliq ekran: {nxt.describe()}")
            if ekran["matn"]:
                print(f"   ekranda: {ekran['matn'][:120]}")
            if nxt.wants_credentials or nxt.user_field:
                print("   → oqim yana ma'lumot so'ramoqda; shu yerda to'xtaymiz.")
                break
            if len(report["oraliq_ekranlar"]) >= MAX_WALK:
                print("   → oraliq ekranlar tugamadi; shu yerda to'xtaymiz.")
                break
            print(f"   davom etilmoqda ({ekran['bosiladi']})…")
            payload, nxt, step = pl_sso.advance(session, widget, nxt, email, password)
            report["steps"].append(step.as_dict())
            print(f"   {describe(step)}")
            if not step.ok:
                break
            dv = pl_sso.find_dv_response(payload)

        report["dvResponse_keldimi"] = bool(dv)
        if dv:
            secrets_seen.append(dv)
            print("6  /as/resume ga yuborilmoqda…")
            code, step = pl_sso.resume(session, widget, dv)
            report["steps"].append(step.as_dict())
            report["kod_keldimi"] = bool(code)
            print(f"   {describe(step)}")
            if code:
                secrets_seen.append(code)
                print("7  Kod tokenga almashtirilmoqda…")
                token, step = pl_sso.exchange_code(session, params, code, verifier)
                report["steps"].append(step.as_dict())
                report["token_keldimi"] = bool(token)
                if token:
                    secrets_seen.append(token)
                print(f"   {describe(step)}")
                if token:
                    print()
                    print("   ✅ DaVinci oqimi TO'LIQ ishladi — brauzer kerak emas.")

    return finish(report, args, secrets_seen)


def finish(report: dict, args, secrets_seen: list[str]) -> int:
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = redact(json.dumps(report, ensure_ascii=False, indent=2), secrets_seen)
    out.write_text(text, encoding="utf-8")
    print()
    print(f"Hisobot yozildi: {out}")
    print("Faylda parol ham, token ham yo'q — bosqichlar va javob kalitlari.")
    if args.raw:
        print("--raw berganingiz uchun `screen` tuzilmasi ham bor: "
              "jo'natishdan oldin ko'rib chiqing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
