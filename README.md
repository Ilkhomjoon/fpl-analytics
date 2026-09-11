# fpl-analytics

Shaxsiy FPL tahlil dvigateli: jamoangizni modellaydi, transfer va kapitan qarorlarini
kutilayotgan ochko (EV) bo'yicha baholaydi, raqiblaringiz bilan solishtiradi va
natijani har kuni Telegram kanalingizga jo'natadi.

```
                    ┌──▶ serve.py ──▶ web sahifa   (model ustida ishlash)
FPL API ──▶ fplbrain┤
                    └──▶ run.py ────▶ Telegram     (kunlik hisobot)
```

## Web sahifa

Modelni ko'z bilan ko'rib, sozlab borish uchun mahalliy sahifa. Har bir modul
shu yerda mukammal holatga keltiriladi, keyin botga o'tkaziladi.

```powershell
python serve.py            # http://127.0.0.1:8000
python serve.py --demo     # tarmoqsiz, soxta ma'lumot bilan
```

Sahifada ikki ko'rinish: **O'yinchilar** va **Jamoam**.

**Jamoam** — tarkibingiz va tavsiya etilgan 11 lik. Har o'yinchi yonida narx,
**forma**, **egalik %**, tarkibga tushish ehtimoli, EV, raqib va model
qiyinligi. Forma va egalik — FPL ning o'z raqamlari, EV esa model bahosi:
yonma-yon turgani uchun modelga qachon ishonish kerakligi ko'rinadi.
**Jamoa tuzish** — noldan 15 lik: 100.0m byudjet, 2/5/5/3 taqsimot, bitta
klubdan ko'pi 3 o'yinchi. Mavjud tarkibingizga umuman bog'liq emas.
Ikki maqsad: **wildcard** va **H2H sinov** — algoritm tuzgan jamoani
haqiqiy ekspertlar tuzgan jamoaga qarshi qo'yish (bir xil byudjet, bir xil
tur, kim ko'proq ochko oladi). Qoidalarga muvofiqligi javobda alohida
tekshiriladi.

**Transferlar** — kimni sotib, kimni olish. Har taklif yonida gorizontdagi
barcha turlar bo'yicha **sof foyda** (hit ayirilgan), narx farqi va qolgan
bank. Har sotiladigan o'yinchi uchun bittadan eng yaxshi variant beriladi —
bitta o'yinchining o'nta ko'rinishi emas. Yonida **zaif bo'g'inlar**: nima
uchun zaif ekani izohi bilan. Eng yaxshi variant ham foyda bermasa, sahifa
buni ochiq aytadi: «hozircha ushlab turing».

Zaxiradagilar uchun esa **nima uchun zaxirada** degan izoh. Ya'ni model qaroriga qarshi chiqish
mumkin: "Raya nega zaxirada?" degan savol javobsiz qolmaydi. Login qilingan
bo'lsa sotish narxlari va erkin transferlar soni aniq, aks holda taxminiy.

Birinchi modul — **o'yinchilar ro'yxati**: narx, egalik, asosiy tarkibda
boshlash soni, daqiqa, gol/uzatma, xG/xA va shu tur oldidagi transfer oqimi;
ustiga model hisoblagan rol, 90 daqiqalik chiqim, samara va umumiy ball.
Har bir ustundan saralash, pozitsiya/jamoa/narx/daqiqa bo'yicha filtr,
byudjet to'ldiruvchilarni yashirish.

> **Ro'yxat login talab qilmaydi.** `bootstrap-static/` ochiq endpoint —
> yuqoridagi ko'rsatkichlarning hammasi undan keladi. Login faqat
> `my-team/{id}` uchun kerak: aniq sotish narxlari, erkin transferlar soni,
> chip holati.

### Login va parol bilan kirish

Sahifadagi **«Kirish»** tugmasi faqat bitta narsani qiladi:

1. **PingOne DaVinci** (`fplbrain/pl_sso.py`) — FPL ning haqiqiy login oqimi.
   Brauzersiz, oddiy HTTP so'rovlar bilan, bir necha soniya. Uchinchi tomon
   ilovalari (FFM va boshqalar) ham aynan shuni bajaradi.

DaVinci o'tmasa, sahifa **«Brauzer orqali davom etish»** tugmasini
ko'rsatadi — bosish sizniki, o'zi ochilib ketmaydi. Bu:

2. **brauzer** (`fplbrain/browser_login.py`): kompyuteringizda
   haqiqiy Chromium ochiladi, email/parol o'zi yoziladi, captcha chiqsa siz bir
   marta bosasiz, token esa FPL ning o'z so'rovlaridan tutib olinadi.
   Diqqat: `/my-team` sahifasi tizimga kirmagan holatda login formasini
   ko'rsatmaydi — faqat «Log in» tugmasini beradi. Shuning uchun modul avval
   o'sha tugmani bosadi, SSO sahifasini (kerak bo'lsa iframe ichidan) topadi,
   formani to'ldiradi va kirgandan keyin `/my-team` ni qayta ochadi — token
   aynan o'sha sahifaning API so'rovida keladi.

DaVinci — bitta so'rov emas, **qadamlar zanjiri**. Har bir qadam o'zi nima
so'rayotganini aytadi, model shunga qarab javob beradi:

| Bosqich | Nima bo'ladi | Parol |
|---|---|---|
| `discovery` | FPL sahifasidan `client_id` (va imkon bo'lsa `redirect_uri`) | yo'q |
| `authorize` | PKCE bilan `/as/authorize`. Javobda widget sozlamasi (`apiRoot`, `policyId`, `accessToken`) **va** `/as/resume` formasi bilan uning `state` qiymati | yo'q |
| `start` | `{apiRoot}/davinci/policy/{policyId}/start` → **birinchi qadam**. FPL da bu login formasi emas, PingOne **Protect** qadami (yagona maydoni `protectsdk`) | yo'q |
| `qadamlar` | Har biri `connections/{id}/capabilities/{name}` ga yuboriladi. Kerakli maydonlar `screen.properties.formFieldsList` da yozilgan — o'qiladi, taxmin qilinmaydi | faqat parol maydoni bor qadamda |

**Protect qadami o'tdi** (`protectsdk` bo'sh ketaverar ekan) va login qadami
uchta maydon so'raydi: `username`, `password` va **`buttonValue`**. DaVinci
uchun **tugma ham maydon** — foydalanuvchi qaysi tugmani bosgani shu orqali
bilinadi. Bu ikki xato bergan:

1. **Bo'sh yuborilgani.** Server: «*Could not determine what button was
   selected by the user*» (400).
2. **Noto'g'ri tugma bosilgani.** Shablonda tugma bitta emas: `REGISTER`,
   `SIGNON`, `FORGOTTEN_PASSWORD`. Birinchisi olinganda server **200**
   qaytardi — lekin oqim ro'yxatdan o'tish ekraniga ketdi va `email` so'radi.
   200 kelgani oqim to'g'ri ketdi degani emas.

Haqiqiy sahifada tugma **to'qqizta**: `REGISTER`, `TROUBLE`, `SIGNON`,
`GOOGLE`, `FACEBOOK`, `X`, `APPLE`, `STARHUB` va yana `REGISTER`. Endi
hammasi qiymati va **turi bilan birga** yig'iladi, so'ng tanlanadi: formani
yuboradigan tur (`form-submit`) va «kirish» ma'nosidagi qiymat oldinga
chiqadi; `register`, `forgot`, `cancel` va ijtimoiy tarmoqlar esa oqimning
**hech bir qadamida** bosilmaydi — biz parol bilan kiryapmiz.

Parol o'tgani bilan oqim tugamaydi: keyin **oraliq ekranlar** keladi (faqat
tugma so'raydigan). Ular ham kuzatiladi va ekrandagi matn hisobotga tushadi —
«parol noto'g'ri» kabi xabar aynan shu yerda yozilgan bo'ladi. Parol
ketgandan keyin oqim yana `email` so'rasa, bu xato deb qayd etiladi.

> **Oqim to'liq tekshirilgan.** Haqiqiy hisob bilan boshidan oxirigacha
> ishladi: `discovery → authorize → start → protect → login (SIGNON) →`
> `"Logging you in…" ekrani → returnSuccessResponseRedirect → resume → token`.
> Brauzer ochilmaydi, parol faqat login qadamiga boradi.
| `resume` | `dvResponse` + `state` → `/as/resume` → redirect ichida `code` | — |
| `token` | `code` + PKCE verifier → `access_token` | — |

Ya'ni **parolsiz ham login qadamigacha borish mumkin** — `sso_probe` aynan
shuni qiladi.

**Hech qanday ID qattiq yozilmagan** — `apiRoot`, `policyId`, `connectionId`,
`capabilityName`, maydon nomlari, hattoki `state`, hammasi ish paytida
serverning o'z javobidan olinadi. Qattiq yozilgan qiymat keyingi o'zgarishda
jim buziladi.

`redirect_uri` sahifadan topilmasa, `config.yaml` da `fpl_redirect_uri` bilan
qo'lda berish mumkin (`client_id` uchun `fpl_client_id`).

Nima ishlamaydi va nega:

| Yo'l | Holati |
|---|---|
| `users.premierleague.com/accounts/login/` | **O'lgan.** Manzil DNS da yo'q: `getaddrinfo failed` |
| `grant_type=password` (ROPC) | **Noto'g'ri usul.** FPL uni ishlatmaydi, shuning uchun server rad etadi |
| `interactionToken` | FPL **bermaydi**. Cookie faqat `interactionId` — oqim usiz ketaveradi |
| **DaVinci SSO** | FPL ning haqiqiy oqimi |
| **Brauzer** | Kafolatli zaxira |
| Qo'lda token/cookie | Ishlaydi |

### Nega login kerak

Jamoa ID bilan ham ko'p narsa ochiladi, lekin **yetmaydi**. Ochiq
`entry/{id}/event/{gw}/picks/` faqat **deadline'dan keyin** ochiladi va
o'sha turdagi muzlatilgan tarkibni beradi. Ya'ni qaror qabul qiladigan
paytda — deadline oldidan, transfer o'ylayotganda — u bo'sh.

Login bergani:

- **jonli tarkib** — hozirgi 15 lik, siz endigina qilgan transfer bilan;
- **aniq sotish narxlari** — ochiq API dagi joriy narx emas, sizning
  o'zingizniki (yarim o'sish qoidasi bilan);
- **erkin transferlar soni va bank** — nechta FT **qoldi**, minus kerakmi;
- **chip holati** — qaysi chip ishlatilgan.

> FT — `limit` emas, `limit − made`. `limit` shu turda berilgan FT soni,
> `made` esa allaqachon qilinganlari. Faqat `limit` olinganda transferlar
> ishlatib bo'lingan bo'lsa ham «2 FT bor» ko'rinardi. Wildcard yoki free
> hit paytida `limit` umuman kelmaydi — bu cheksiz degani, sahifada `∞`.

Bularsiz "kimni sotish, kimni olish" degan savolga jiddiy javob yo'q.
Shuning uchun sahifada asosiy yo'l — **email va parol**. Jamoa ID
maydoni «Boshqa yo'llar» ichida qoldi: parol bermay ko'rmoqchi bo'lganlar
uchun zaxira, asosiy yo'l emas.

Jamoa ID — `fantasy.premierleague.com/entry/`**`34191`**`/history` dagi raqam.

### Login: tezlik va ajratilganlik

Login kerak bo'lganda uch qatlam ishlaydi:

1. **Token diskda saqlanadi** — `data/sessions/<kalit>.json`, **har akkaunt
   o'z faylida**, `0600` huquq bilan, parolsiz. Shu brauzerda keyingi safar
   kirish bir zumda tiklanadi.
2. **Muddati bilinadi.** Token — JWT, ichida `exp` bor; tugashiga 5 daqiqa
   qolganda sahifa uni **fonda, ko'rinmas brauzerda** yangilaydi.
3. **«Tez kirish»** — parol so'ramaydi, oyna ochmaydi.

**Har akkaunt alohida.** Bu shunchaki qulaylik emas, tuzatilgan xato edi:
bitta umumiy brauzer profili ishlatilganda unda oldingi hisobning cookie si
qolar edi va boshqa email/parol yozgan odam **birovning jamoasini** ko'rardi.
Endi profil ham (`data/profiles/<kalit>`), sessiya fayli ham email dan
olingan kalit bo'yicha ajratilgan.

**Brauzerlar ham alohida.** Sahifa har brauzerga o'z sessiyasini beradi
(`fplsid` cookie), saqlangan sessiya esa faqat `fplacct` cookie si bor
brauzerda tiklanadi. Login qilgan sessiya o'z API klienti bilan ishlaydi —
bitta umumiy klientga token qo'yish ko'p foydalanuvchida birovning tokeni
bilan so'rov yuborishga olib kelardi.

Kirish uzoq davom etishi mumkin (captcha, 2FA), shuning uchun u **fonda**
ishlaydi: sahifa kutib qolmaydi, holatni ko'rsatib turadi.

**Tashxis.** Urinish muvaffaqiyatsiz tugasa, sahifa har bir bosqichni alohida
ko'rsatadi — nomi, HTTP kodi va javob tuzilishi bilan; oxirgi xato
oldingilarini bosib ketmaydi. Batafsil hisobot uchun:

```powershell
python tools/sso_probe.py            # parolsiz — login qadamigacha boradi
python tools/sso_probe.py --raw      # `screen` tuzilmasini ham saqlaydi
python tools/sso_probe.py --with-login   # oqimni oxirigacha: parol → resume → token
```

`--with-login` endi login qadamida to'xtamaydi: `dvResponse` ni `/as/resume`
ga yuboradi va `code` ni tokenga almashtiradi. Oqim to'liq ishlasa
«DaVinci oqimi TO'LIQ ishladi — brauzer kerak emas» deb yozadi; ishlamasa
**qaysi qadamda** to'xtaganini aniq ko'rsatadi.

U `data/sso_probe.json` ga bosqichlarni, **serverning xato xabarini** va javob
kalitlarini yozadi — parol, token va cookie yozilmaydi. Xato xabari maxfiy emas
va tashxisning eng qimmatli qismi: «HTTP 403» yolg'iz o'zi hech narsa aytmaydi,
`message=...` esa aytadi. Notanish javobda esa faqat kalitlar yoziladi,
qiymatlar emas.

Parol serverda **saqlanmaydi**: faqat urinish paytida ishlatiladi va javobga
ham, jurnalga ham tushmaydi (buni tekshiradigan testlar bor). Token jarayon
xotirasida turadi — `serve.py` yopilganda yo'qoladi.

Sahifa faqat shu kompyuterda ochiladi (`127.0.0.1`). Bu ataylab: FPL ning bot
himoyasi bulut serveridan kelgan so'rovni to'sadi, sizning IP ingizdan esa
o'tish ehtimoli ancha yuqori.

## Telegram boti

Hisobot bitta uzun devor emas — **qisqa xulosa + tugmalar**. Tugmani bosganingizda
o'sha bo'lim o'sha xabarning o'zida ochiladi, "◀ Menyu" bilan orqaga qaytasiz.

```
📊 FPL — GW3
28-avgust · deadline 28.08 22:30 (6 soat qoldi)
O'rin: 2,434,397 (24.8%) · qiymat 100.0m · 2 FT · bank 1.0m
🔁 James ➜ Guéhi (+10.4 EV)
🅲 Szoboszlai — 5.1 EV · 10+: 14%

[🎯 Strategiya] [🔁 Transfer]
[🅲 Kapitan]    [🧠 Jamoam]
[📋 11 lik]     [📅 Turlar]
[👥 Raqiblar]   [💷 Narxlar]
[🎴 Chip]
[📄 Hammasi]    [🔄 Yangilash]
```

Ikki qism alohida ishlaydi:

- **`run.py`** tahlilni hisoblab, bo'limlarni `data/store/last_report.json` ga
  saqlaydi va menyu xabarini jo'natadi. Jadval bo'yicha (GitHub Actions) shu
  ishlaydi.
- **`bot.py`** tugma bosilishini tinglaydi va saqlangan bo'limni **darhol**
  ko'rsatadi — qayta hisoblamaydi. U sizning kompyuteringizda ishlab turishi
  kerak:

```powershell
python bot.py
```

Buyruqlar: `/menu`, `/yangila` (qaytadan hisoblash), `/holat`.

Bot faqat `TELEGRAM_CHAT_ID` da ko'rsatilgan kanal bilan ishlaydi — begona
odam tugmani bossa, javob bermaydi.

`bot.py` ishlamayotgan paytda tugmalar javob bermaydi. Faqat matn kerak bo'lsa:

```powershell
python run.py --full-text
```

## Nima qiladi

| Bo'lim | Mazmuni |
|---|---|
| ⭐ Reyting | Har pozitsiya bo'yicha eng yaxshi o'yinchilar: **rol × chiqim**. Byudjet to'ldiruvchilar belgilanadi |
| 💎 Samara | 1 million evaziga eng ko'p chiqim beradiganlar |
| 📊 Bozor | Shu tur oldidan kim olinmoqda, kim sotilmoqda — egalar soniga nisbatan |
| 📈 Sur'at | Mavsum maqsadiga (2508 ochko) nisbatan holat: sizning o'rtachangiz, yetakchiniki, qolgan turlarda kerakli o'rtacha |
| 🔄 Shablon | Top-100 da ommaviy, sizda yo'q o'yinchilar — kimni sotib kimni olish, EV va EO farqi bilan |
| 🎯 Strategiya | O'ringa mos yondashuv + **11 likka 11 lik** solishtiruv: shablon jamoadan qancha orqadasiz va aynan kim sizni har tur ortga tortyapti |
| 🩺 Yangi xabarlar | Kechadan beri paydo bo'lgan jarohat/diskvalifikatsiya xabarlari — sizdagi o'yinchilar birinchi |
| 💷 Narxlar | Kecha o'zgargan narxlar + bugun kechqurun kutilayotganlari (FPL ning `price_change_percent` va soatlik tezlik maydonlari asosida) |
| 🧠 Mening jamoam | Qiymat, bank, FT, eng yaxshi sxema, kelgusi turlar EV si, eng zaif 3 bo'g'in |
| 📋 11 lik | Tavsiya etilgan asosiy tarkib va zaxira tartibi — har o'yinchi yonida raqib, uning **jadvaldagi o'rni**, model qiyinligi va tarkibga tushish ehtimoli; zaxiradagilar uchun **nima uchun** degan izoh |
| 🔁 Transfer | FT soniga mos **reja**: asosiy tavsiya, hit arziydimi, va bir-birini istisno qiluvchi muqobillar |
| 🅲 Kapitan | To'liq **ochko taqsimoti**: P(10+), P(15+), tepasi va maydon kapitanidan ustunlik |
| 👥 Raqiblar | Mini-liga, top-100 va **mendan ±1% o'rindagi** jamoalar: EO, differensiallar, tahdidlar, kapitan taqsimoti |
| 🗓 FDR | Kelgusi 5 turda jadvali eng qulay **top-3 jamoa** — rasmiy FDR emas, raqibning **jadvaldagi o'rni va joriy natijalari** bilan tuzatilgan qiyinlik bo'yicha (ikkalasi yonma-yon ko'rsatiladi) |
| 📅 Turlar | Kelgusi 5 tur jadvali — eng qulay va eng og'ir jamoalar, sizning o'yinchilaringiz belgilangan |
| 🎴 Chip | WC / BB / TC / FH uchun eng foydali tur; ishlatilgan chiplar hisobga olinadi |

## Tez boshlash

Windows / PowerShell:

```powershell
git clone https://github.com/<foydalanuvchi>/fpl-analytics.git
cd fpl-analytics
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

Copy-Item .env.example .env                         # maxfiy qiymatlar

python serve.py --demo                              # web sahifa, soxta ma'lumot bilan
python serve.py                                     # web sahifa, haqiqiy ma'lumot
python run.py --demo --dry-run                      # soxta ma'lumot bilan namuna
python run.py --dry-run                             # haqiqiy ma'lumot, JO'NATMAYDI
python run.py                                       # Telegramga menyu jo'natadi
python bot.py                                       # tugmalarni tinglaydi
python run.py --dry-run --out                       # hisobot.html ga yozadi
```

`config.yaml` ixtiyoriy — bo'lmasa koddagi standart qiymatlar ishlaydi.
Model parametrlarini o'zgartirmoqchi bo'lsangiz, faylni o'zingiz yarating:

```yaml
# config.yaml — faqat o'zgartirmoqchi bo'lgan qiymatlarni yozing
entry_id: 1234567
mini_league_ids: [123456, 789012]
free_transfers_override: 0   # 0 = avtomatik aniqlansin
horizon: 5                   # necha tur oldinga qaraladi
min_gain_to_suggest: 1.5     # shundan kam foyda bersa transfer taklif qilinmaydi
minutes_prior_matches: 1.2   # mavsum o'rtasida 1.0 ga tushiring

# Yevropada o'ynayotgan jamoalar — ularning o'yinchilarida rotatsiya
# xavfi ortadi. FPL API buni bermaydi, shuning uchun qo'lda beriladi.
european_teams: [ARS, LIV, MCI, NEW, TOT, AVL, CHE]
```

Barcha parametrlar va ularning ma'nosi quyida, "Sozlash" bo'limida.

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
uchun FT ni `FPL_FREE_TRANSFERS` secret'i bilan bering (yoki lokalda
`config.yaml` dagi `free_transfers_override` bilan). `--check-auth` shu haqda
ham ogohlantiradi.

> **Diqqat:** `free_transfers_override` — bu *bilmaganda* ishlatiladigan
> zaxira, serverning javobini tuzatuvchi qiymat emas. Login qilingan bo'lsa
> u **e'tiborsiz qoladi**: aniq raqam `my-team` dan keladi. Avval teskarisi
> edi va bir marta yozilgan eski qiymat login qilingandan keyin ham kuchda
> qolib, sahifada noto'g'ri FT ko'rsatgan edi. Endi u ishlaganda sahifa
> buni ochiq aytadi.

> `config.yaml` `.gitignore` da, ya'ni GitHub da yo'q. Workflow uni
> `config.example.yaml` dan nusxalaydi; u ham bo'lmasa koddagi standart
> qiymatlar ishlatiladi va hammasi baribir ishlaydi.

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
| `FPL_FREE_TRANSFERS` | erkin transfer soni (ixtiyoriy) — Actions da `config.yaml` yo'q, shuning uchun FT ni shu yerdan berasiz |

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

**0. Model o'tgan mavsumga TAYANMAYDI.** Jamoa almashgan, roli o'zgargan yoki
jarohatdan qaytgan o'yinchini o'tgan yil natijasi bilan baholash xato. Priorlar
ikkita **joriy** bozor signalidan quriladi:

- **Egalik** (`selected_by_percent`) — ROL signali. Menejerlar ommaviy ravishda
  zaxira o'yinchini sotib olmaydi: 25% egalikdagi 6.5m lik qanot deyarli aniq
  asosiy tarkibda. Bu jamoaviy bashorat 2 o'yinlik namunadan ishonchliroq.
- **Narx** — SIFAT signali. FPL narxni talabga qarab o'zgartiradi, ya'ni narx
  bozorning bahosi. Undan xG90, xA90 va bonus priorlari chiqariladi.

Muhim chegara: **egalik faqat rolni bashorat qiladi, chiqimni emas.** Aks holda
model shablonni takrorlab qolardi va "hamma olgan, siz olmang" deya olmasdi —
yuqori o'ringa chiqish uchun esa aynan shu kerak.

**Byudjet to'ldiruvchi (enabler) muammosi.** Menejerlar 4.0m lik o'yinchini
byudjetni to'ldirish uchun oladi — u hech qachon o'ynamaydi. Egalik foizini
oddiy o'qish uni "ommaviy, demak asosiy" deb ko'rsatardi. Ikki himoya qo'yilgan:

1. Egalikning rol signali **narxga qarab chegiriladi**: 4.0m da ishonch 0.25,
   5.5m dan yuqorida 1.0. Arzon o'yinchida egalik rolni deyarli bashorat
   qilmaydi.
2. Egalik **daqiqalarni bosib o'tolmaydi**: rol `o'ynagan daqiqa ulushi × 1.25
   + 0.30` bilan cheklanadi. 60% egalikdagi, lekin 45 daqiqa o'ynagan o'yinchi
   asosiy tarkib deb baholanmaydi.

Bunday o'yinchilar hisobotda ⚠️ bilan belgilanadi va "Samara" ro'yxatidan
chiqarib tashlanadi.

**Reyting formulasi.** `reyting = rol × chiqim`:

- **rol** — o'ynagan daqiqalar ulushi (60%), asosiy tarkib ulushi (40%), va
  dalil kam bo'lganda chegirilgan egalik. Dalil to'planishi bilan egalikning
  vazni `1.5/(1.5+turlar)` bo'yicha pasayadi.
- **chiqim** — 90 daqiqalik ochko. xG/xA ga 75% (namuna kichik bo'lsa), haqiqiy
  gol/uzatmaga 25% vazn: kichik namunada asos natijadan barqarorroq bashorat
  beradi. Natija asosdan keskin farq qilsa, hisobotda alohida belgilanadi.
- **transfer oqimi** — `(kirgan − chiqgan) / egalar soni`. 100 ming transfer
  1% egalikda katta voqea, 50% egalikda kichik — shuning uchun mutlaq son
  emas, nisbat olinadi.

O'tgan mavsumni yoqish uchun `config.yaml` da `use_last_season: true`.

**1. Daqiqalar.** Uchta manbadan quriladi:

- **Rol priori** — yuqoridagi egalik + narx.
- **So'nggi turlar** — ketma-ket asosiy tarkibda 60+ daqiqa chiqishlar soni
  quyi chegara qo'yadi: 1 tur → 0.75, 2 tur → 0.82, 3+ tur → 0.88. Zanjir
  uzilsa chegara ham yo'qoladi. Mavsum boshida bu eng kuchli signal.
- **Xabarlar** — `chance_of_playing_next_round` hammasini proporsional
  pasaytiradi; 0% bo'lsa EV nolga tushadi.

Natijani `--explain` bilan har doim tekshirish mumkin.

**2. Uchrashuv kuchi.** Jamoa hujum/himoya reytingi **uchta** manbadan quriladi:

1. **Prior** — FPL ning `strength_*` qiymatlari. Muhim tuzatish: bu qiymatlar
   juda siqilgan — eng kuchli va eng zaif jamoa orasida atigi ~15% farq bor,
   haqiqatda esa gol tezliklari ikki barobar farq qiladi. Xom holda ishlatilsa
   **hamma jamoa o'rtacha ko'rinadi** va kuchli jamoa futbolchilari asossiz
   past baholanadi. Shuning uchun nisbat `strength_spread` (odatda 2.3)
   darajasiga ko'tariladi.
2. **Jarayon** — joriy mavsum xG (hujum — jamoa xG yig'indisi, himoya — asosiy
   darvozabonning `expected_goals_conceded_per_90`).
3. **Natija** — joriy mavsum jadvali: urilgan/kiritilgan gollar, so'nggi
   o'yinlarga ko'proq vazn berib (`table.py`).

O'yin o'ynalgani sari 2 va 3 ning vazni `n/(n+k)` bo'yicha ortadi.
Undan har uchrashuv uchun Poisson λ (o'z gollari / kiritilgan gollari) chiqadi.

**2a. Samarali qiyinlik (FDR o'rniga).** FPL ning rasmiy FDR si **mavsum
boshida** belgilanadi va keyin yangilanmaydi — u raqibning bugungi holatini
bilmaydi. Aniq misol: Arsenal — Aston Villa o'yinida rasmiy FDR 4 ("qiyin")
turardi, holbuki Villa mavsumni Brighton dan 0:4 yutqazib boshlagan va jadval
oxirida edi.

Shuning uchun model o'z qiyinligini hisoblaydi — 1.0 (oson) dan 5.0 (qiyin)
gacha, uchta qismdan:

- **model** — o'rtacha jamoa shu raqibga qarshi shu maydonda nima kutadi
  (qiyinlik raqibning xususiyati, o'zimizniki emas — aks holda "kuchli
  jamoaning jadvali oson" degan aylanma xulosa chiqardi);
- **jadval** — raqibning joriy o'rni (1-o'rin → 5.0, oxirgi o'rin → 1.0);
- **rasmiy FDR** — mavsum boshidagi taxmin.

Vaznlar o'yin soniga qarab siljiydi: mavsum boshida jadval bo'sh, shuning uchun
rasmiy FDR ustunroq; o'yinlar o'ynalgani sari uning vazni so'nadi, jadvalniki
esa ortadi. Hisobotda ikkalasi yonma-yon chiqadi: `AVL(u)·20 4→2.1`.

**2b. Qiyinlik pozitsiyaga bog'liq.** Bitta uchrashuv ikki xil qiyinlikka
ega va buni bitta raqam bilan ifodalab bo'lmaydi:

- **Darvozabon va himoyachi** uchun raqibning **hujumi** hal qiladi — u gol
  ura oladimi? Toza darvoza bizning hujumimizga bog'liq emas.
- **Yarim himoyachi va hujumchi** uchun raqibning **himoyasi** hal qiladi —
  u gol o'tkazadimi? Raqib qancha gol urgani bizga ahamiyatsiz.

Aniq misol (GW3, 2026/27):

| Raqib | Uradi | O'tkazadi | Himoyachiga | Hujumchiga |
|---|---|---|---|---|
| Leeds (9-o'rin) | 1.00 | 0.67 | **2.8** oson | **3.8** qiyin |
| Crystal Palace (13-o'rin) | 1.33 | 2.67 | **3.0** o'rtacha | **1.6** oson |

Ya'ni Leeds ga qarshi himoyachi qo'yish yaxshi, hujumchi qo'yish yomon —
Palace ga qarshi esa aksincha. Jadvaldagi **o'rin** bu farqni ko'rsatmaydi:
Palace pastroq (13-o'rin) turadi, lekin hujumchi uchun u Leeds dan ancha
qulay raqib. Avval faqat o'rin qaralardi va bu ikki holat bir xil ko'rinardi.

Sahifada har o'yinchi yonida **o'ziga tegishli** qiyinlik turadi; o'yinchi
ustiga bosilsa ikkalasi ham ko'rinadi.

**3. Hujum.** O'yinchining xG90 va xA90 si empirik Bayes shrinkage bilan
barqarorlashtiriladi (kam o'ynagan o'yinchi pozitsiya o'rtachasiga tortiladi), so'ng
uchrashuv koeffitsiyentiga ko'paytiriladi.

**3a. Forma — kichik vazn bilan.** FPL ning `form` maydoni so'nggi 30 kunda
olingan **ochko**, ya'ni natija. Unda omad ham bor: xG dan ortiq urgan
o'yinchi keyingi turda o'rtachaga qaytadi. Shuning uchun forma modelni
boshqarmaydi — u hujum tezliklarini (xG90, xA90, bonus) **eng ko'pi bilan
±10%** ga suradi:

| Forma | Koeffitsiyent |
|---|---|
| 1.0 (juda past) | −6% |
| 3.5 (mediana) | 0% |
| 6.0 | +7% |
| 7.3 va yuqori | +10% (to'yinadi) |

Nima uchun kerak? xG hali ko'rmagan o'zgarishlar bo'ladi: yangi rol,
endigina olingan penalti huquqi, standart pozitsiyalar. Forma ularni
darrov ko'radi.

Nima uchun kichik? Yuqori forma zaif asosni qoplamasligi kerak: xG si 0.5
bo'lgan "olovli" o'yinchi xG si 6.0 bo'lgan "sovuq" o'yinchidan yuqoriga
chiqmaydi. Test aynan shuni tekshiradi.

Forma **daqiqalarga tegmaydi** (ularning o'z modeli bor) va toza darvozaga
ham (u uchrashuvga bog'liq). Baza qiymat — o'ynayotgan o'yinchilarning
**medianasi**, har hisobda qaytadan olinadi, ya'ni eskirmaydi.
`config.yaml` da `form_weight: 0` bersangiz butunlay o'chadi.

**4. Himoya.** Toza darvoza `P(CS) = e^(−λ_kiritilgan)`, kiritilgan gol jarimasi esa
Poisson taqsimoti bo'yicha `E[⌊gollar/2⌋]`. Darvozabon to'xtatishlari raqib hujum
kuchiga qarab masshtablanadi.

**5. DefCon.** Himoyachi uchun 10 CBIT, yarim himoyachi/hujumchi uchun 12 CBIRT.
Ehtimollik **manfiy binomial** taqsimot bilan hisoblanadi — himoya harakatlari
Poisson dan ko'ra tarqoq, Poisson chegaradan o'tish ehtimolini kam ko'rsatadi.
Yetarli o'yin bo'lsa, model natijasi haqiqiy "chegaradan o'tish foizi" bilan
50/50 aralashtiriladi.

**6. Bonus va kartochka.** 90 daqiqalik bonus tezligi (shrinkage bilan), uchrashuv
kuchiga biroz bog'lab; sariq kartochka o'rtachasi ayiriladi. Qizil kartochka
(−3), o'z darvozasiga gol (−2) va o'tkazib yuborilgan penalti (−2) ham bor:
kam uchraydi, lekin kuchli siqilgan holda (k=10) hisobga olinadi — aks holda
bitta qizil kartochka butun mavsumga tarqalib ketardi.

**7. Penalti va standart pozitsiyalar.** Penaltichi va burchak/shtrafni
oladigan o'yinchi **priorda** ustunlik oladi (xG uchun +0.11, xA uchun +0.05
90 daqiqaga). Nega priorda? FPL ning `expected_goals` i penaltilarni
**allaqachon** o'z ichiga oladi (penalti xG ≈ 0.79) — xom qiymat ustiga
qo'shish ikki marta hisoblash bo'lardi. Haqiqiy bo'shliq boshqa joyda:
endigina penaltichi etib tayinlangan o'yinchi. Uning statistikasida penalti
yo'q, model esa uni narx priori tomon tortadi va penalti huquqini ko'rmaydi.
Dalil to'planishi bilan prior ta'siri o'z-o'zidan so'nadi.

### EV pozitsiyalar bo'yicha

Har bir pozitsiya uchun EV ga kiradigan qismlar — sahifada o'yinchi ustiga
bosilsa ham xuddi shu ro'yxat chiqadi:

| Qism | DRV | HIM | YAR | HUJ |
|---|:--:|:--:|:--:|:--:|
| ishtirok (1 + 60' uchun yana 1) | ✅ | ✅ | ✅ | ✅ |
| gol | 6 | 6 | 5 | 4 |
| uzatma (3) | ✅ | ✅ | ✅ | ✅ |
| toza darvoza | 4 | 4 | 1 | — |
| o'tkazilgan gol (−1 har 2 tasiga) | ✅ | ✅ | — | — |
| to'xtatish (har 3 tasiga +1) | ✅ | — | — | — |
| penalti to'xtatish (+5) | ✅ | — | — | — |
| DefCon (+2) | — | 10 CBIT | 12 CBIRT | 12 CBIRT |
| bonus (BPS moyilligi) | ✅ | ✅ | ✅ | ✅ |
| sariq (−1), qizil (−3) | ✅ | ✅ | ✅ | ✅ |
| o'z goli (−2), penalti o'tkazib yuborish (−2) | ✅ | ✅ | ✅ | ✅ |

**EV — o'rtacha, "yaxshi holat" emas.** Toza darvoza ehtimoli 35% bo'lgan
himoyachi CS dan `0.35 × 4 = 1.4` ochko oladi, ustiga 2 ochko ishtirok, biroz
DefCon va bonus — jami ~4. "5-6-7 ochko" esa toza darvoza **ro'y bergan**
holatdagi natija. EV ni shu darajaga ko'tarish tanlovni buzadi: EV ning butun
foydasi o'yinchilarni **bir xil o'lchov** bilan solishtirishda. Shuning uchun
sahifa ikkalasini ham ko'rsatadi: EV va yonida «toza darvoza 35% → bo'lsa 6.2
ochko».

**Diskvalifikatsiya kuzatuvi.** 5 ta sariq kartochka (GW19 gacha) — bir
o'yinlik chetlatish. Bu EV ga qo'shilmaydi (chetlatish keyingi o'yinga
tegishli), lekin 4 ta sariqi bor o'yinchi yonida `4🟨` belgisi turadi.

### Noldan jamoa tuzish (`builder.py`)

Byudjet ichida eng yaxshi 15 lik — butun sonli optimallashtirish masalasi.
Tashqi kutubxonasiz ikki bosqichda yechiladi:

1. **Ochko'z boshlang'ich** — har pozitsiyada eng yaxshilari olinadi, byudjet
   oshsa "narx birligiga eng kam EV yo'qotadigan" almashtirish qilinadi;
2. **Mahalliy qidiruv** — bitta va **ikkitalik** almashtirishlar sinaladi.

Ikkitalik almashtirish shart: qimmat o'yinchini olish uchun pul boshqa
joydan chiqishi kerak. «Bir o'yinchini arzonlashtirib, ikkinchisini
kuchaytirish» — FPL da eng ko'p ishlatiladigan harakat va u faqat juftlikda
ko'rinadi. Soxta olamda qidiruv boshlang'ichga **+6 ochko** qo'shadi.

**Maqsad funksiyasi — "15 ta EV yig'indisi" EMAS.** Zaxiradagi 4 kishi
deyarli ochko keltirmaydi, lekin yig'indida asosiy o'yinchidek turadi.
Shuning uchun har tur uchun asosiy 11 tanlanadi, **kapitan ikkilanadi**,
zaxira esa kichik vazn oladi — ya'ni maqsad haqiqiy ochko hisobiga mos
keladi.

Bu **global optimumni kafolatlamaydi**, lekin bir necha yuz millisoniyada
ishlaydi va amalda unga yaqin keladi. Kafolat kerak bo'lsa MILP (PuLP + CBC)
kerak — u qo'shimcha o'rnatma talab qiladi.

Qoidalar javobda **alohida tekshiriladi** (`legal`): 15 o'yinchi, 2/5/5/3,
bitta klubdan ≤3, byudjetdan oshmaslik. "Deyarli to'g'ri" jamoa FPL ga
kiritilmaydi, shuning uchun bu yerda taxmin qilinmaydi.

### Kalibrovka: raqamlar haqiqatga to'g'ri keladimi?

Ochiq manbalardagi xP modellari (FPL Review, FPL Copilot, OpenFPL maqolasi,
AIrsenal) va Premier League statistikasi bilan solishtirilgan mezonlar —
`tests/test_calibration.py` shularni tekshiradi:

| Nima | Kutilayotgan oraliq |
|---|---|
| Premium yarim himoyachi | 6.0 – 7.3 |
| Elita hujumchi | 7.0 – 8.0 |
| Mustahkam himoyachi, yaxshi raqib | 4.0 – 5.3 |
| Darvozabon | 3.0 – 4.5 |
| Zaxira/rotatsiya | 2.5 dan past |
| **11 lik + kapitan** | **48 – 58** |
| O'rtacha menejerning haqiqiy natijasi | 50 – 54 |

Model 30 larda javob bersa — biror qism tushib qolgan. Eng ko'p uchraydigan
sabablar: bonus hisobga olinmagan, DefCon yo'q, yoki 60 daqiqalik ochko
noto'g'ri.

**Aniqlik shifti.** FPL Review ning "Ultimate Truth" tahliliga ko'ra
**mukammal** model ham RMSE ≈ 2.7-2.9, R² ≈ 0.11-0.19 dan yaxshi natija
berolmaydi — FPL ochkosi asosan tasodifdan iborat. Ya'ni R² ni quvish
befoyda; muhimi **kalibrovka** va yuqoridagi ~40 o'yinchini to'g'ri
tartiblash.

### Tuzatilgan uchta jiddiy xato

1. **Darvozabon goli 10 ochko** (6 emas) — 2024/25 dan beri shunday.
2. **`E[⌊to'xtatishlar/3⌋]` — o'rtachani bo'lish emas.** 3 ta to'xtatish
   kutilganda o'rtachani bo'lish 1.00 ochko beradi, to'g'ri qiymat esa
   **0.665**: 2 ta to'xtatish ham, 0 ta ham bir xil — 0 ochko. Ya'ni
   darvozabon EV si **50%** oshirib ko'rsatilgan edi. Kiritilgan gol
   jarimasida bu xato boshidan yo'q edi.
3. **Qiyinlik DefCon ga TESKARI ta'sir qiladi.** Kuchli raqibga qarshi toza
   darvoza ehtimoli tushadi, lekin himoya harakatlari (CBIT/CBIRT) ortadi —
   to'p ko'proq o'z yarim maydonimizda bo'ladi. Bitta "qiyinlik
   koeffitsiyenti" ni butun o'yinchiga qo'llash shu yerda xato bo'lardi.

**Bonus endi voqeaga bog'liq.** Avval u 90 daqiqalik o'rtacha edi: o'yinda
nima bo'lishidan qat'i nazar bir xil chiqardi. Aslida gol yoki uzatma bergan
o'yinchi BPS reytingida deyarli har doim yuqoriga chiqadi, toza darvoza esa
himoyachiga +12 BPS beradi. Endi o'rtacha tezlik shartli holatlarga
taqsimlanadi — umumiy daraja o'zgarmaydi, lekin qaytim ehtimoli yuqori
o'yinchida bonus kattaroq bo'ladi. Bu naive modellarda eng ko'p uchraydigan
kamchilik: bonusni tashlab ketish premiumning EV sini 10-15% pasaytiradi.

**Kapitan.** «Kutilayotgan ochko» endi kapitanning ikki barobar ochkosini
ham o'z ichiga oladi. Busiz jamoa bahosi ~5 ochkoga past chiqar edi va
haqiqiy o'rtacha (turiga 50-54) bilan umuman solishtirib bo'lmasdi.

### Jadval zichligi va rotatsiya (`congestion.py`)

OpenFPL maqolasining asosiy xulosasi: ochiq modellar tijoriy modellardan
**aynan kutilayotgan daqiqalar** bo'yicha orqada qoladi. FPL ning
0/25/50/75/100% belgisi o'yinchi asosiy tarkibda chiqadimi, zaxiradan
kiradimi yoki dam oladimi — ayta olmaydi.

Bukmeker ham, matbuot anjumani ham bizda yo'q. Lekin **jadvalning o'zi**
bepul va ko'p narsa aytadi. Uch signal `kickoff_time` dan hisoblanadi:

- **oldingi o'yindan keyin necha kun** o'tgani (6+ kun → zichlik yo'q,
  3 kun va kamroq → eng yuqori);
- **keyingi o'yingacha necha kun** — keyingi o'yin yaqin bo'lsa murabbiy
  o'yinchini bugun asrashi mumkin;
- **12 kunlik oynadagi o'yinlar soni** — DGW va chorshanba turlarini ushlaydi.

**Yevropa kubogi FPL API sida yo'q**, shuning uchun `config.yaml` dan
o'qiladi:

```yaml
european_teams: [ARS, LIV, MCI, NEW, TOT, AVL, CHE]
```

Qisqa nom, to'liq nom yoki ID — hammasi ishlaydi. Kodga yozilmagan: ro'yxat
har mavsum o'zgaradi.

**Rotatsiya jazo emas.** Zichlik "mumkin bo'lgan tarkiblar sonini oshiradi",
ya'ni **noaniqlikni** oshiradi. Shuning uchun ehtimollar neytral qiymat
(0.55) tomon tortiladi: mustahkam o'yinchi biroz yo'qotadi, chetdagi biroz
yutadi. Bu haqiqatga mos — rotatsiya kimdir uchun yo'qotish, kimdir uchun
imkoniyat. Bundan tashqari zich haftada boshlagan o'yinchi ham erta
almashtiriladi, shuning uchun 60 daqiqa o'ynash ehtimoli alohida pasayadi —
u ishtirok ochkosini, toza darvozani va DefCon ni ushlab turadi.

Sahifada zich uchrashuv yonida **«zich»** yozuvi chiqadi.

**7. Ochko taqsimoti (kapitan uchun).** O'rtacha EV kapitan tanlash uchun
yetarli emas — ochko ikkilangani uchun **tepasi** hal qiladi. Shuning uchun gol,
uzatma, toza darvoza, DefCon va bonus bo'yicha to'liq taqsimot sanab chiqiladi
va undan P(10+), P(15+) hamda 90-foizli natija olinadi. Toza darvoza va
kiritilgan gol jarimasi bitta tasodifiy miqdordan (kiritilgan gollar soni)
chiqariladi, shuning uchun ular o'zaro zid bo'lmaydi. Shu hisobdan darvozabonda
P(10+) ≈ 1% chiqadi — model uni kapitanlikka umuman tavsiya qilmaydi.

**7a. Asosiy 11 lik.** Tanlov faqat EV bo'yicha emas. Sabab: EV — o'rtacha
qiymat, asosiy 11 lik esa **bir marta** o'ynaladi. 4.0 EV beradigan mustahkam
asosiy tarkib o'yinchisi bilan 4.2 EV beradigan, lekin tarkibga tushishi
shubhali o'yinchi orasida birinchisi afzal: ikkinchisi 0 ochko olib qolishi
mumkin va zaxira uni to'liq qoplamaydi (avtoalmashtirish faqat umuman
o'ynamagan holda ishlaydi).

Shuning uchun sxema `EV × (1 − λ·(1 − p_asosiy))` bali bo'yicha tanlanadi
(`xi_risk_aversion`), ustiga bitta qattiq qoida qo'yiladi: zaxiradagi
**mustahkam** o'yinchi (p ≥ 0.75) 11 likdagi **shubhali** o'yinchidan
(p < 0.55) atigi 1.2 ochkogacha orqada bo'lsa — o'rin almashadi. Qaytariladigan
yig'indi esa xom EV bo'lib qoladi, chunki boshqa bo'limlar (shablon bilan
solishtiruv, chip hisobi) aynan shu birlikda ishlaydi.

**8. Maydonga nisbatan holat.** Raqiblarning shablon 11 ligi tuziladi va
sizning 11 ligingiz bilan solishtiriladi. Bu — yagona asosli umumiy o'lchov
(ikkala tomon ham 11 o'yinchi qo'yadi). Undan keyin farqning tarkibi
ko'rsatiladi: qaysi o'yinchi sizda yo'qligi uchun har tur `EO × EV` ochko
yo'qotyapsiz va qaysi biri sizga ustunlik beryapti.

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
| `strength_spread` | FPL strength qiymatlarining tarqalishi | Kuchli va zaif jamoa keskin ajraladi (1.0 = FPL ning xom, tekis qiymati) |
| `team_form_shrink_matches` | Joriy natijaga ishonch | Model sekinroq reaksiya qiladi, mavsum boshida barqarorroq |
| `table_weight` | Jadval o'rnining qiyinlikdagi vazni | Raqibning jadvaldagi holati ko'proq hal qiladi |
| `xi_risk_aversion` | 11 likda ishonchlilikka urg'u | Shubhali o'yinchi kamroq qo'yiladi, EV biroz pasayadi |
| `european_teams` | Yevropada o'ynayotgan jamoalar | Ularning o'yinchilarida rotatsiya xavfi ortadi |
| `form_weight` | Formaning hujum tezligiga ta'siri | 0.10 = ±10%; 0 = forma umuman hisobga olinmaydi |
| `prior_season_weight` | O'tgan mavsum ta'siri | Mavsum boshida barqarorroq, lekin yangi o'zgarishlarga sekin |

Kapitan strategiyasi: `--strategy safe | balanced | aggressive`.
`safe` ommaviy kapitanni afzal ko'radi (o'rinni himoya qiladi), `aggressive`
differensialni (o'rinni ko'tarishga urinadi).

## Sinov va tekshiruv

```bash
python -m pytest tests/ -q      # 200 ta unit test, tarmoqsiz
python tools/calibrate.py       # EV real FPL oraliqlarida ekanini tekshiradi
python run.py --demo --dry-run  # to'liq hisobot, soxta ma'lumot bilan
```

### Model raqamlarini tekshirish

Har qanday o'yinchi bo'yicha modelning butun hisobini ko'rish mumkin:

```powershell
python run.py --explain Isak
```

Chiqadi: o'tgan mavsum ma'lumoti, joriy mavsum, so'nggi turlardagi daqiqalar,
`p(asosiy tarkib)` qanday chiqqani, xG90/xA90 shrinkage dan keyin, har tur
uchun EV va uning tarkibi, hamda ochko taqsimoti. Agar raqam noto'g'ri
ko'rinsa, aynan qaysi bosqichda xato borligi shu yerdan ko'rinadi.

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
run.py                 Telegram hisoboti (CLI)
serve.py               web sahifani ishga tushiradi
web/
  app.py               Flask API: /api/players, /api/squad, /api/login
  squadview.py         tarkib + 11 lik + qaror izohlari
  static/index.html    o'yinchilar jadvali (bitta fayl, tashqi kutubxonasiz)
fplbrain/
  config.py            sozlamalar
  api.py               FPL API klienti (kesh, retry, rate limit)
  auth.py              kirish yo'llari va ularning diagnostikasi
  session_store.py     tokenni diskda saqlash va muddatini bilish
  pl_sso.py            PingOne DaVinci oqimi (login/parol bilan)
  browser_login.py     haqiqiy Chromium da kirib, tokenni tutadi
  table.py             joriy mavsum jadvali va forma
  ratings.py           jamoa kuchi, uchrashuv λ lari, samarali qiyinlik
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
tools/sso_probe.py     login oqimi tashxisi
tests/                 unit testlar va soxta FPL olami
```
