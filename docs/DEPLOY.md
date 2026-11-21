# Botni ishga tushirish

`userbot.py` — ko'p foydalanuvchili bot: har kim o'z jamoa ID sini yuboradi va
bo'limlarni tugma bilan ochadi. Parol so'ralmaydi.

## 1. Bot tokeni

Telegramda **@BotFather** → `/newbot` → nom va username → token beriladi
(`1234567890:AA…` ko'rinishida).

> **Yangi bot oching.** Eski `bot.py` (kanal uchun hisobot) ishlatadigan token
> bilan `userbot.py` ni bir vaqtda ishga tushirib bo'lmaydi: Telegram bitta
> tokenga bitta tinglovchiga ruxsat beradi, ikkalasi bir-birining xabarlarini
> "yeb" qo'yadi.

## 2. O'z kompyuteringizda sinash

```powershell
cd $env:USERPROFILE\OneDrive\Desktop\FPL\fpl-analytics
pip install -r requirements.txt
```

`.env` fayliga (loyiha papkasida) tokenni yozing:

```
TELEGRAM_TOKEN=1234567890:AA...
```

```powershell
python userbot.py
```

Telegramda botingizga `/start` yozing va jamoa ID ni yuboring. To'xtatish: `Ctrl+C`.
FPL ga ulanmasdan ko'rish uchun: `python userbot.py --demo`.

## 3. Yopiq sinov (faqat ekspertlar)

`config.yaml` ga ruxsat etilgan chat ID larni yozing:

```yaml
bot_allowed_chats: [123456789, 987654321]
```

Ro'yxatda yo'q odam botga yozsa, bot unga **o'z chat ID sini** ko'rsatadi — u
sizga yuboradi, siz ro'yxatga qo'shasiz va botni qayta ishga tushirasiz.
Ro'yxat bo'sh bo'lsa, bot hamma uchun ochiq.

## 4. Serverga o'rnatish (Ubuntu VPS)

Eng arzon tarif yetadi (1 vCPU, 1 GB RAM).

```bash
sudo apt update && sudo apt install -y python3-venv git
git clone https://github.com/Ilkhomjoon/fpl-analytics.git
cd fpl-analytics && git checkout web-modules
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
nano .env            # TELEGRAM_TOKEN=...
nano config.yaml     # entry_id, mini_league_ids, bot_allowed_chats, european_teams
.venv/bin/python userbot.py     # sinab ko'ring, keyin Ctrl+C
```

Doimiy ishlashi uchun — `systemd` xizmati. `/etc/systemd/system/fplbot.service`:

```ini
[Unit]
Description=FPL Brain bot
After=network-online.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/fpl-analytics
ExecStart=/home/ubuntu/fpl-analytics/.venv/bin/python userbot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now fplbot
journalctl -u fplbot -f        # jurnalni kuzatish
```

Yangilash:

```bash
cd ~/fpl-analytics && git pull && .venv/bin/pip install -r requirements.txt
sudo systemctl restart fplbot
```

## 5. Bilish kerak

- **Serverda `config.yaml` va `.env` alohida yaratiladi** — ular git da yo'q.
  Model sozlamalari (`team_form_shrink_matches: 10.0`, `shrink_defcon_90s: 2.0`)
  koddagi standart qiymatlarda bor, ularni yozish shart emas.
- **H2H ma'lumoti** (`data/store/h2h/`) git orqali keladi: tarkiblarni o'z
  kompyuteringizda muzlatib push qilsangiz, serverda `git pull` yetadi.
  Ekspertlarning shaxsiy tanlovlari serverga **bormaydi** (git da yo'q) —
  serverdagi H2H da «ekspertlar o'rtachasi» va «model o'rni» bo'sh chiqadi.
- **Foydalanuvchilar** `data/bot/users.json` da: chat ID, jamoa ID, jamoa nomi.
  Server almashsa, shu faylni ko'chiring.
- **Birinchi so'rov sekin** (10–30 soniya): raqiblar namunasi yuklanadi va
  `data/cache/bands/` da saqlanadi. Bir oraliqdagi keyingi foydalanuvchilar
  uchun tez.
- **Yuk**: bir vaqtda 2 ta hisob (`tgbot/app.py`, `WORKERS`). Ko'p odam birdan
  yozsa, navbat bilan javob oladi. O'nlab foydalanuvchi uchun yetarli;
  yuzlab uchun namunalarni oldindan (fon rejimida) yig'ish kerak bo'ladi.
- **Telegram O'zbekistonda** ba'zan to'g'ridan-to'g'ri ochilmaydi — serverni
  xorijda (Yevropa) olgan ma'qul.
