# fpl-analytics

Shaxsiy FPL tahlil dvigateli: jamoangizni modellaydi, transfer va kapitan qarorlarini
kutilayotgan ochko (EV) bo'yicha baholaydi, raqiblaringiz bilan solishtiradi va
natijani har kuni Telegram kanalingizga jo'natadi.

```
run.py ──▶ FPL API ──▶ EV modeli ──▶ transfer / kapitan / chip ──▶ Telegram
                          ▲                    ▲
                    jamoa reytingi       raqiblar tahlili
```

## Nima qiladi

| Bo'lim | Mazmuni |
|---|---|
| 🩺 Yangi xabarlar | Kechadan beri paydo bo'lgan jarohat/diskvalifikatsiya xabarlari — sizdagi o'yinchilar birinchi |
| 💷 Narxlar | Kecha o'zgargan narxlar + bugun kechqurun kutilayotganlari (FPL ning `price_change_percent` va soatlik tezlik maydonlari asosida) |
| 🧠 Mening jamoam | Qiymat, bank, FT, eng yaxshi sxema, kelgusi turlar EV si, eng zaif 3 bo'g'in |
| 📋 11 lik | GW uchun tavsiya etilgan asosiy tarkib va zaxira tartibi |
| 🔁 Transfer | 1 va 2 transferli variantlar, hit matematikasi, byudjet va "jamoadan 3 tadan" qoidasi bilan |
| 🅲 Kapitan | EV, "haul" ehtimoli va raqiblardagi kapitanlik ulushi (EO) bo'yicha reyting |
| 👥 Raqiblar | Mini-liga, top-100 va **mendan ±1% o'rindagi** jamoalar: EO, differensiallar, tahdidlar, kapitan taqsimoti |
| 🎴 Chip | WC / BB / TC / FH uchun eng foydali tur, byudjetga mos ideal tarkib bilan solishtirib |

## Tez boshlash

Windows / PowerShell:

```powershell
git clone https://github.com/<foydalanuvchi>/fpl-analytics.git
cd fpl-analytics
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

Copy-Item config.example.yaml config.yaml           # sozlamalar
Copy-Item .env.example .env                         # maxfiy qiymatlar

python run.py --demo --dry-run                      # soxta ma'lumot bilan namuna
python run.py --dry-run                             # haqiqiy ma'lumot, JO'NATMAYDI
python run.py                                       # Telegramga jo'natadi
python run.py --dry-run --out                       # hisobot.html ga yozadi
```

> `--dry-run` — "Telegramga jo'natma" degani. Kanalga borishi uchun uni olib
> tashlang. Konsolda o'qish noqulay bo'lsa, `--out` bilan HTML faylga yozing
> va brauzerda oching (`start hisobot.html`).

`Activate.ps1` ishga tushmasa, bir marta:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

> **Windows eslatmasi.** Windows da IANA vaqt zonasi bazasi OS bilan kelmaydi,
> shuning uchun `tzdata` paketi kerak — u `requirements.txt` da bor. Agar baribir
> `ZoneInfoNotFoundError` chiqsa, `pip install tzdata` qiling. Paket bo'lmasa ham
> dastur ishlaydi: `Asia/Tashkent` uchun UTC+5 siljishiga qaytadi va ogohlantirish
> yozadi.

### `.env` fayli

Maxfiy qiymatlar shu faylda turadi va dastur uni ishga tushganda **avtomatik
o'qiydi** (`.gitignore` da, repoga tushmaydi). Format oddiy:

```
TELEGRAM_TOKEN=123456789:AAExampleTokenFromBotFather
TELEGRAM_CHAT_ID=-1001234567890
FPL_ENTRY_ID=1234567
FPL_LEAGUE_IDS=123456,789012
FPL_COOKIE=pl_profile=eyJz...; sessionid=abc...; access_token=eyJh...
```

Qoidalar:

- Har bir qiymat **bitta satrda**. Cookie uzun bo'lsa ham satrni bo'lmang.
- `=` atrofida bo'sh joy qo'ymang: `KEY=qiymat`, `KEY = qiymat` emas.
- Qo'shtirnoq shart emas. Qo'ysangiz ham ishlaydi, lekin **butun qiymatni**
  o'rab qo'ying, o'rtasida emas.
- Cookie ichidagi `=` va `;` belgilariga tegmang — ular o'sha yerda turishi kerak.
  Fayl birinchi `=` bo'yicha ajratadi, qolgani qiymat sanaladi.
- `#` bilan boshlangan satr — izoh.
- Fayl nomi aynan `.env` (`.env.txt` emas). Notepad saqlaganda "Save as type:
  All Files" ni tanlang, aks holda `.txt` qo'shib yuboradi.

Vaqtinchalik sinash uchun `$env:` ham ishlaydi va u `.env` dan **ustun turadi**:

```powershell
$env:FPL_COOKIE="pl_profile=...; sessionid=..."
python run.py --check-auth
```

Nima yuklanganini har ishga tushganda birinchi satrda ko'rasiz (qiymatlarning
o'zi hech qachon chiqarilmaydi):

```
INFO fplbrain: Sozlamalar: entry_id=1234567 · liga=2 · telegram=bor · cookie=bor
```

## Kerakli ma'lumotlar

**FPL jamoa ID** — FPL saytida "Pick Team" → "View Gameweek History" ga kiring,
URL `fantasy.premierleague.com/entry/**1234567**/history` ko'rinishida bo'ladi.
O'rtadagi raqam sizning `entry_id` ingiz.

**Mini-liga ID** — liga sahifasi URL ida: `/leagues/**123456**/standings/c`.

**Telegram bot tokeni** — [@BotFather](https://t.me/BotFather) → `/newbot`.
Mavjud botni ham ishlatsa bo'ladi.

**Kanal chat_id** — shaxsiy kanal yarating, botni **admin** qiling, kanalga bitta
xabar yozing va oching:
`https://api.telegram.org/bot<TOKEN>/getUpdates` — javobdagi `chat.id`
(`-100...` bilan boshlanadi) kerakli qiymat.

## FPL sessiyasi bilan ulanish (ixtiyoriy, lekin tavsiya etiladi)

Ochiq API o'zgacha ikki narsani bermaydi: **aniq sotish narxi** va **erkin
transfer soni**. Ularsiz model ikkalasini ham taxminlaydi — bu byudjet
hisobida 0.1–0.3m, hit qarorida esa butun boshli 4 ochkolik xatoga olib
kelishi mumkin. Sessiya cookie qo'shsangiz, ikkalasi ham aniq bo'ladi va
chip holati (qaysi chip hali ishlatilmagan) ham o'qiladi.

Cookie ni olish:

1. Brauzerda [fantasy.premierleague.com](https://fantasy.premierleague.com) ga
   kiring (login qilingan holatda).
2. `F12` → **Network** tabi → sahifani yangilang.
3. Ro'yxatdan `me/` yoki `my-team/` so'rovini toping → **Headers** →
   **Request Headers** → `cookie:` qatorini to'liq nusxalang.
4. `.env` ga yozing:

```
FPL_COOKIE=pl_profile=...; sessionid=...; csrftoken=...
```

PowerShell da:

```powershell
$env:FPL_COOKIE="pl_profile=...; sessionid=..."
```

`cookie:` qatorini **Copy value** bilan nusxalab olgach:

```powershell
python tools/set_cookie.py
```

Skript uni **buferdan** o'qiydi — konsolga yopishtirish shart emas va
yopishtirmang ham: PowerShell bir necha kilobaytlik matnni qirqib tashlaydi,
cookie esa odatda 2–4 KB. Qirqilgan cookie 403 beradi.

Bufer ishlamasa, cookie ni faylga saqlab bering:

```powershell
python tools/set_cookie.py --from-file cookie.txt
```

Skript qatorni tozalaydi (satr ko'chishi, `cookie:` prefiksi, ortiqcha
bo'shliqlar), qirqilganini aniqlaydi va shubhali bo'lsa **yozmaydi**.
`.env` dagi boshqa satrlarga tegmaydi, cookie qiymatini ekranga chiqarmaydi.

> FPL PingOne SSO ga o'tgan, shuning uchun asosiy sessiya cookie lari
> `access_token` va `global_sso_id`. Eski `sessionid` / `pl_profile` endi
> bo'lmasligi mumkin — bu normal.

Ishlayotganini tekshirish:

```powershell
python run.py --check-auth
```

To'liq hisobotni ishga tushirmasdan sessiya holatini, erkin transfer sonini,
bankni va mavjud chiplarni ko'rsatadi.

### Xavfsizlik — buni o'qing

Cookie **parol emas, lekin paroldan kam ham emas**: uni qo'lga kiritgan odam
sizning FPL akkauntingizga sizdek kira oladi. Qatorda `access_token` va
`refresh_token` bor, `refresh_token` esa bir yilgacha amal qiladi.

- Cookie ni hech kimga yubormang — chatga, screenshotga, issue ga, hech qayerga.
- `.env` dan boshqa joyga yozmang (u `.gitignore` da).
- Agar tasodifan biror joyga yopishtirib yuborgan bo'lsangiz: FPL da **log out**
  qiling **va parolni almashtiring**. Faqat log out `refresh_token` ni bekor
  qilmasligi mumkin.

### GitHub Actions da cookie ishlamaydi

Brauzer cookie sida `cf_clearance` (Cloudflare) va `datadome` bor — bular
sizning IP va brauzer barmoq izingizga bog'langan bot himoyasi tokenlari.
GitHub Actions boshqa IP dan ishlagani uchun ular o'tmaydi.

Shuning uchun: **cookie ni faqat o'z kompyuteringizda ishlating.** Actions
uchun `config.yaml` da `free_transfers_override` ni qo'lda yozib qo'ying —
o'zgarganda yangilaysiz. `--check-auth` shu haqda ham ogohlantiradi.

Cookie umuman qo'shmasangiz ham hamma narsa ishlayveradi — hisobot oxirida
"taxminiy" degan eslatma chiqadi.

## GitHub Actions (har kuni avtomatik)

Repo → **Settings → Secrets and variables → Actions** da qo'shing:

| Secret | Qiymat |
|---|---|
| `TELEGRAM_TOKEN` | bot tokeni |
| `TELEGRAM_CHAT_ID` | kanal ID si |
| `FPL_ENTRY_ID` | jamoa ID si |
| `FPL_LEAGUE_IDS` | mini-liga ID lari, vergul bilan |

`.github/workflows/daily.yml` ikki marta ishga tushadi:

- **01:00 UTC = 06:00 Toshkent** — har kuni; kechagi narx o'zgarishlari allaqachon bo'lgan bo'ladi
- **13:00 UTC = 18:00 Toshkent** — payshanba va juma; deadline oldidan

Deadline'gacha `deadline_report_hours` (default 30) soatdan kam qolganda hisobot
avtomatik **to'liq** rejimga o'tadi.

> Snapshot fayllari (`data/store/`) repoga commit qilinadi — narx va egalik
> o'zgarishini kunlar bo'yicha solishtirish uchun shu kerak. Repo **private**
> bo'lgani ma'qul.

## Model qanday ishlaydi

Har bir o'yinchi uchun har bir uchrashuvda kutilayotgan ochko hisoblanadi:

**1. Daqiqalar.** `starts`, oxirgi 6 o'yin daqiqalari va `chance_of_playing_next_round`
dan `p(asosiy tarkib)`, `p(60+ daqiqa)` va kutilayotgan daqiqa chiqariladi. Mavsum
boshida ma'lumot kam bo'lgani uchun o'tgan mavsum (yoki narx) prior sifatida
aralashtiriladi, o'yinlar ortgani sari prior vazni tushadi.

**2. Uchrashuv kuchi.** Jamoa hujum/himoya reytingi FPL ning `strength_*` qiymatlari
va joriy mavsum xG ma'lumotidan (hujum — jamoa xG yig'indisi, himoya — asosiy
darvozabonning `expected_goals_conceded_per_90`) shrinkage bilan birlashtiriladi.
Undan har uchrashuv uchun Poisson λ (o'z gollari / kiritilgan gollari) chiqadi.

**3. Hujum.** O'yinchining xG90 va xA90 si empirik Bayes shrinkage bilan
barqarorlashtiriladi (kam o'ynagan o'yinchi pozitsiya o'rtachasiga tortiladi), so'ng
uchrashuv koeffitsiyentiga ko'paytiriladi.

**4. Himoya.** Toza darvoza `P(CS) = e^(−λ_kiritilgan)`, kiritilgan gol jarimasi esa
Poisson taqsimoti bo'yicha `E[⌊gollar/2⌋]`. Darvozabon to'xtatishlari raqib hujum
kuchiga qarab masshtablanadi.

**5. DefCon.** Himoyachi uchun 10 CBIT, yarim himoyachi/hujumchi uchun 12 CBIRT.
Ehtimollik **manfiy binomial** taqsimot bilan hisoblanadi — himoya harakatlari
Poisson dan ko'ra tarqoq, Poisson chegaradan o'tish ehtimolini kam ko'rsatadi.
Yetarli o'yin bo'lsa, model natijasi haqiqiy "chegaradan o'tish foizi" bilan
50/50 aralashtiriladi.

**6. Bonus va kartochka.** 90 daqiqalik bonus tezligi (shrinkage bilan), uchrashuv
kuchiga biroz bog'lab; sariq kartochka o'rtachasi ayiriladi.

Transfer qarori butun tarkib darajasida hisoblanadi: almashtirishdan **keyingi**
tarkibning har turdagi eng yaxshi 11 ligi qayta tanlanadi, zaxira `bench_weight`
vazni bilan qo'shiladi va gorizont bo'ylab `horizon_decay` bilan diskontlanadi.
Shuning uchun "zaxiradagi o'yinchini yaxshilash" ning qiymati to'g'ri baholanadi.

### Sozlash

Modelning xatti-harakatini `config.yaml` orqali o'zgartirasiz:

| Parametr | Ma'nosi | Ko'tarsangiz |
|---|---|---|
| `horizon` | Necha tur oldinga qaraladi | Uzoq muddatli fikrlash, fixture almashinuvi muhimroq |
| `horizon_decay` | Uzoq turlarga ishonch | Kelajakdagi turlar og'irroq baholanadi |
| `bench_weight` | Zaxira EV vazni | Zaxirani kuchaytiruvchi transferlar yuqoriroq turadi |
| `min_gain_to_suggest` | Taklif chegarasi | Kamroq, lekin ishonchliroq takliflar |
| `shrink_*_90s` | Kam o'ynaganlarga ishonchsizlik | Model konservativroq, "bir o'yinlik portlash" ga uchmaydi |
| `prior_season_weight` | O'tgan mavsum ta'siri | Mavsum boshida barqarorroq, lekin yangi o'zgarishlarga sekin |

Kapitan strategiyasi: `--strategy safe | balanced | aggressive`.
`safe` ommaviy kapitanni afzal ko'radi (o'rinni himoya qiladi), `aggressive`
differensialni (o'rinni ko'tarishga urinadi).

## Sinov va tekshiruv

```bash
python -m pytest tests/ -q      # 23 ta unit test, tarmoqsiz
python tools/calibrate.py       # EV real FPL oraliqlarida ekanini tekshiradi
python run.py --demo --dry-run  # to'liq hisobot, soxta ma'lumot bilan
```

`tools/calibrate.py` tanish arxetiplarni tekshiradi — premium hujumchi uyda
kuchsiz raqibga qarshi 6–9.5 EV, oddiy himoyachi mehmonda kuchli raqibga qarshi
1.5–4 EV va hokazo. Modelni o'zgartirgandan keyin shuni ishga tushiring: agar
sonlar oraliqdan chiqsa, model realizmini yo'qotgan bo'ladi.

## Cheklovlar

- FPL ochiq API si **erkin transfer sonini** bermaydi — u tarixdan taxminlanadi.
  Aniq qiymat kerak bo'lsa `config.yaml` ga qo'lda yozing.
- Xarid narxlari transfer tarixidan tiklanadi; GW1 dan beri saqlanib qolgan
  o'yinchilar uchun `cost_change_start` orqali hisoblanadi.
- Raqiblar tarkibi faqat **deadline'dan keyin** ochiladi, shuning uchun tahlil
  oxirgi tugagan tur ma'lumotiga tayanadi.
- Overall ligadan chuqur sahifalarni olish (±1% guruhlari) sekin bo'lishi mumkin;
  xato bo'lsa, hisobot shu bo'limsiz yasalaveradi.
- Model o'yin ichidagi ma'lumotni (jonli xabarlar, matbuot anjumani) bilmaydi —
  jarohat xabarlari faqat FPL API ga tushganda ko'rinadi.

## Fayllar

```
run.py                 boshqaruvchi skript (CLI)
fplbrain/
  config.py            sozlamalar
  api.py               FPL API klienti (kesh, retry, rate limit)
  ratings.py           jamoa kuchi va uchrashuv λ lari
  ev.py                EV modeli — model yuragi
  squad.py             tarkib, eng yaxshi 11 lik, sotish narxi
  transfers.py         transfer dvigateli
  captain.py           kapitan reytingi
  chips.py             chip vaqtini baholash
  rivals.py            mini-liga / top-N / ±1% tahlili
  market.py            narx, xabar va egalik signallari
  report.py            o'zbekcha hisobot matni
  telegram.py          jo'natish va xabarni bo'lish
  demo.py              tarmoqsiz demo klient
tools/calibrate.py     model kalibrovkasi
tests/                 unit testlar va soxta FPL olami
```
