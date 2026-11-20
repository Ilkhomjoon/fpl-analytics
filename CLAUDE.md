# fpl-analytics — ishni topshirish hujjati

> **Bu hujjat nima uchun.** Ish boshqa akkauntda davom etadi. Kod sizda —
> bu yerda esa kodda **ko'rinmaydigan** narsa: nega shunday qilingani,
> qaysi yo'l sinalib rad etilgani va qaysi xatolar qaytib kelmasligi kerak.
> Kodni qayta yozish mumkin, bu bilimni esa yo'q.

**Sana:** 2026-11-19 · **Holat:** web sahifada 9 ta bo'lim ishlaydi, 373 ta test o'tadi,
model `tools/backtest.py` bilan haqiqiy ochkoga solishtirilgan (4.1-bo'lim)

---

## 0. Eng avval: kod qayerda

**Kod faqat sizning kompyuteringizda.** Buni aniq bilish muhim:

| Joy | Nima bor |
|---|---|
| **Sizning kompyuteringiz**, `main` (2 ta commit: `9177cc9 Changes`, `3a8ff05 changes 39`) | **Hamma ish** — patch008 dan patch039 gacha |
| GitHub `Ilkhomjoon/fpl-analytics`, `web-modules` | Shu ishning nusxasi (push qilingandan keyin) |
| GitHub `Ilkhomjoon/fpl-analytics`, `main` | Eski kod + bot har kuni qo'shadigan snapshot commitlari |
| Claude konteyneri | **Hech narsa** — tozalangan |

Lokal `main` va GitHub `main` **ajralgan** (2 ga qarshi 87 commit). Shuning
uchun ish GitHub `main` ga emas, alohida `web-modules` branchiga chiqariladi.
Birlashtirish (`main` ga merge) — keyinroq alohida, o'ylangan qadam.

### Birinchi qiladigan ishingiz

```powershell
cd $env:USERPROFILE\OneDrive\Desktop\FPL\fpl-analytics
git status                       # "working tree clean" bo'lishi kerak
git branch web-modules           # joriy main dan yangi branch
git push -u origin web-modules   # ENG MUHIMI
```

Yangi akkaunt / boshqa kompyuterda:

```powershell
git clone https://github.com/Ilkhomjoon/fpl-analytics.git
cd fpl-analytics
git checkout web-modules
```

Zaxira nusxa uchun:

```powershell
git bundle create fpl-analytics-full.bundle --all
git format-patch origin/main..web-modules -o patches
```

`.bundle` — bitta fayl, ichida butun tarix. Boshqa joyda
`git clone fpl-analytics-full.bundle` bilan ochiladi.

---

## 1. Loyiha nima

Shaxsiy FPL tahlil dvigateli. **Maqsad:** mavsumni 2810 ochko bilan tugatish
(38 tur × 74). **Uzoq maqsad:** modelni FPLUzbekistan kanali a'zolariga
xizmat sifatida taklif qilib monetizatsiya qilish.

Ish tartibi: avval **web sahifada** modul-modul ishlanadi, tayyor bo'lgach
Telegram botga ko'chiriladi.

### Asosiy qarorlar (o'zgartirishdan oldin o'ylab ko'ring)

1. **O'tgan mavsum ishlatilmaydi.** Jamoa almashgan, roli o'zgargan yoki
   jarohatdan qaytgan o'yinchini o'tgan yil natijasi bilan baholash xato.
   Priorlar **joriy** bozordan: egalik (rol signali) + narx (sifat signali).
2. **Egalik faqat ROLni bashorat qiladi, chiqimni emas.** Aks holda model
   shablonni takrorlab qolardi va "hamma olgan, siz olmang" deya olmasdi.
3. **Login shart.** Jamoa ID yetarli emas: ochiq `picks` endpointi faqat
   deadline'dan keyin ochiladi, ya'ni qaror qabul qilinayotgan paytda bo'sh.
4. **Yetkazib berish — git patch.** `patchNNN.patch`, nomida chiziqcha yo'q
   (PowerShell muammosi), `git apply` bilan qo'llaniladi.

---

## 2. Arxitektura

```
fpl-analytics/
├── fplbrain/          model yadrosi — bot ham, web ham shuni ishlatadi
├── web/               Flask ilova + bitta HTML sahifa
├── tools/             sso_probe.py — DaVinci tashxisi; backtest.py — model tekshiruvi
├── tests/             348 ta test
├── run.py             Telegram bot / CLI hisobot
└── serve.py           web sahifani ishga tushirish
```

### `fplbrain/` — model yadrosi

Bu sessiyada **yangi** yaratilganlar:

| Modul | Vazifasi | Patch |
|---|---|---|
| `table.py` | Tugagan o'yinlardan liga jadvali, so'nish bilan forma | 008 |
| `pl_sso.py` | PingOne DaVinci login oqimi | 011–024 |
| `browser_login.py` | Playwright orqali zaxira login | 010 |
| `session_store.py` | Token diskda, JWT muddati, **har akkaunt alohida** | 019–020 |
| `congestion.py` | Jadval zichligidan rotatsiya xavfi | 029 |
| `builder.py` | Noldan 15 lik tuzish (byudjet + qoidalar) | 035 |
| `pace.py` | Mavsum sur'ati + jamoa ko'rsatkichlari | 036–039 |

Jiddiy **o'zgartirilganlar**: `ev.py` (model yuragi), `ratings.py`
(qiyinlik), `squad.py` (11 lik, FT), `config.py`, `auth.py`.

### `web/` — sahifa

| Fayl | Bo'lim |
|---|---|
| `app.py` | Flask, sessiyalar, hamma endpoint |
| `squadview.py` | «Jamoam» + `World` klassi (umumiy asos) |
| `transferview.py` | «Transferlar» |
| `draftview.py` | «Jamoa tuzish» |
| `paceview.py` | «Sur'at» |
| `static/index.html` | Butun interfeys — bitta fayl |

**`World` klassi muhim.** Reyting, uchrashuvlar va EV lar **bir marta**
quriladi, hamma bo'lim o'shani ishlatadi. Ikki marta qurish so'rovlarni
ikkilantiradi va — yomoni — ikki bo'lim bir xil o'yinchiga **boshqa-boshqa
EV** berishi mumkin edi.

---

## 3. EV modeli — to'liq spetsifikatsiya

Bu loyihaning yuragi. Har bir qism nima uchun borligi bilan.

### 3.1 Ochko jadvali

| Qism | DRV | HIM | YAR | HUJ |
|---|:--:|:--:|:--:|:--:|
| ishtirok (1 + 60' uchun yana 1) | ✅ | ✅ | ✅ | ✅ |
| gol | **10** | 6 | 5 | 4 |
| uzatma | 3 | 3 | 3 | 3 |
| toza darvoza | 4 | 4 | 1 | — |
| o'tkazilgan gol (−1 har 2 tasiga) | ✅ | ✅ | — | — |
| to'xtatish (har 3 tasiga +1) | ✅ | — | — | — |
| penalti to'xtatish (+5) | ✅ | — | — | — |
| DefCon (+2) | — | 10 CBIT | 12 CBIRT | 12 CBIRT |
| bonus | ✅ | ✅ | ✅ | ✅ |
| sariq (−1), qizil (−3) | ✅ | ✅ | ✅ | ✅ |
| o'z goli (−2), penalti o'tkazib yuborish (−2) | ✅ | ✅ | ✅ | ✅ |

> **Darvozabon goli 10 ochko**, 6 emas. 2024/25 dan beri shunday.
> Bu kodda 6 bo'lib turgan va tuzatilgan.

### 3.2 Daqiqalar

Uch manbadan: rol priori (egalik + narx) → so'nggi o'yinlar → xabarlar
(`chance_of_playing_next_round`).

So'nggi o'yinlar — **o'lchangan holat modeli** (`state_start_prob`, 3+ o'yin
tarixi bo'lganda): so'nggi o'yin holati × so'nggi 6 o'yindagi boshlash ulushi.
Masalan: ketma-ket 3+ marta 60+ → 0.91; bir marta → 0.73; o'tgan turda
o'ynamadi → 0.09 (zaxira) … 0.41 (doimiy asosiy); zaxiradan qisqa chiqish →
0.13. Batafsil tarix yo'q bo'lsa (ro'yxat rejimi) — mavsumdagi boshlash ulushi
+ `event_points` (o'tgan turdagi ochko: 0 / 1 / 2+).

Chiqadi: `p_start`, `p_appear`, `p60`, `xmins`.

**`p60` alohida muhim.** 60 daqiqa chegarasi ikkinchi ishtirok ochkosini,
butun toza darvozani va DefCon huquqini ushlab turadi. Shuning uchun
"o'rtacha daqiqa 68 ⇒ 68 ≥ 60 ⇒ ha" degan hisob **xato** — ehtimollik
kerak, nuqtaviy baho emas.

### 3.3 Hujum

`xG90`, `xA90` — empirik Bayes shrinkage bilan barqarorlashtirilgan.

**Penaltichi va standart pozitsiya egasi priorga qo'shiladi** (xG uchun
+0.11, xA uchun +0.05 / 90 daqiqa), xom qiymat ustiga EMAS. Sabab: FPL ning
`expected_goals` i penaltilarni **allaqachon** o'z ichiga oladi (penalti
xG ≈ 0.79). Ustiga qo'shish ikki marta hisoblash bo'lardi. Haqiqiy
bo'shliq — endigina penaltichi etib tayinlangan o'yinchi: uning
statistikasida penalti yo'q.

### 3.4 Himoya

- Toza darvoza: `P(CS) = e^(−λ_kiritilgan)`, keyin `× p60`
- Kiritilgan gol jarimasi: `E[⌊gollar/2⌋]` (Puasson bo'yicha)
- To'xtatish: **`E[⌊N/3⌋]`**, `E[N]/3` EMAS

> **Bu 50% xato edi.** λ=3 da o'rtachani bo'lish 1.00 beradi, to'g'ri
> qiymat esa **0.665**. Sabab: 2 ta to'xtatish ham, 0 ta ham — 0 ochko.
> Qizig'i: kiritilgan gol jarimasida bu boshidan to'g'ri yozilgan edi,
> shuning uchun nomuvofiqlik ko'zga tashlanmagan.

### 3.5 DefCon

Chegaradan o'tish ehtimoli **manfiy binomial** bilan (Puasson emas: himoya
harakatlari tarqoqroq). Yetarli o'yin bo'lsa, model natijasi haqiqiy
"chegaradan o'tish foizi" bilan 50/50 aralashtiriladi.

> **Qiyinlik DefCon ga TESKARI ta'sir qiladi.** Kuchli raqibga qarshi toza
> darvoza ehtimoli tushadi, lekin himoya harakatlari **ortadi** — to'p
> ko'proq o'z yarim maydonda bo'ladi. Bitta "qiyinlik koeffitsiyenti" ni
> butun o'yinchiga qo'llash bu yerda xato bo'lardi.

### 3.6 Bonus

90 daqiqalik o'rtacha **emas** — voqeaga bog'liq. Gol/uzatma bergan
o'yinchi BPS reytingida deyarli har doim yuqoriga chiqadi (YAR uchun gol
+18 BPS), toza darvoza himoyachiga +12 BPS beradi. O'rtacha tezlik shartli
holatlarga taqsimlanadi; umumiy daraja o'zgarmaydi.

Bonusni tashlab ketish — ochiq modellarning eng ko'p uchraydigan kamchiligi,
premiumning EV sini 10–15% pasaytiradi.

### 3.7 Forma

`form_weight: 0.10` — hujum tezliklariga **eng ko'pi bilan ±10%**.

| Forma | Ta'sir |
|---|---|
| 1.0 | −6% |
| 3.5 (mediana) | 0% |
| 6.0 | +7% |
| 7.3+ | +10% (to'yinadi) |

Baza — o'ynayotgan o'yinchilarning **medianasi**, har hisobda qaytadan
olinadi. Chegara muhim: xG si 0.5 bo'lgan "olovli" o'yinchi xG si 6.0
bo'lgan "sovuq" o'yinchidan yuqoriga chiqmasligi kerak. Test shuni
tekshiradi.

### 3.8 Rotatsiya (jadval zichligi)

`congestion.py` — uch signal `kickoff_time` dan: oldingi o'yindan necha kun,
keyingi o'yingacha necha kun, 12 kunlik oynadagi o'yinlar soni. Yevropa
kubogi FPL API sida yo'q — `config.yaml` dan o'qiladi.

**Jazo emas, noyaniqlikka tortish.** Zichlik "mumkin bo'lgan tarkiblar
sonini oshiradi", shuning uchun ehtimollar neytral qiymat (0.55) tomon
tortiladi: mustahkam o'yinchi biroz yo'qotadi (0.95 → 0.84), chetdagi biroz
yutadi (0.30 → 0.37). Rotatsiya kimdir uchun yo'qotish, kimdir uchun
imkoniyat.

### 3.9 Qiyinlik — pozitsiyaga bog'liq

**Bitta uchrashuv ikki xil qiyinlikka ega:**

- **DRV/HIM** uchun raqibning **hujumi** hal qiladi (gol ura oladimi?)
- **YAR/HUJ** uchun raqibning **himoyasi** (gol o'tkazadimi?)

Misol (GW3, 2026/27):

| Raqib | Uradi | O'tkazadi | Himoyachiga | Hujumchiga |
|---|---|---|---|---|
| Leeds (9-o'rin) | 1.00 | 0.67 | **2.8** oson | **3.8** qiyin |
| Crystal Palace (13-o'rin) | 1.33 | 2.67 | 3.0 o'rtacha | **1.6** oson |

Jadvaldagi **o'rin** bu farqni ko'rsatmaydi: Palace pastroq turadi, lekin
hujumchi uchun ancha qulay raqib.

### 3.10 Asosiy 11 lik tanlash

EV bo'yicha emas:

```
tanlov_bali = EV × (1 − 0.35 × (1 − tarkib_ehtimoli))
```

Plus ikki qoida:
- **Mustahkamlik almashuvi** — EV farqi 1.2 dan kichik bo'lsa, `p_start ≥
  0.75` bo'lgan o'yinchi `p_start ≤ 0.55` bo'lganidan ustun turadi
- **Sxema** — 1 DRV, 3-5 HIM, 2-5 YAR, 1-3 HUJ ichida eng yaxshi kombinatsiya

Sabab: EV o'rtacha qiymat, asosiy 11 lik esa **bir marta** o'ynaladi.

---

## 4. Kalibrovka — raqamlar haqiqatga mos keladimi

Ochiq manbalardagi xP modellari (FPL Review, FPL Copilot, OpenFPL maqolasi,
AIrsenal) bilan solishtirilgan. `tests/test_calibration.py` shularni
tekshiradi:

| Nima | Oraliq |
|---|---|
| Premium YAR | 6.0 – 7.3 |
| Elita HUJ | 7.0 – 8.0 |
| Mustahkam HIM, yaxshi raqib | 4.0 – 5.3 |
| DRV | 3.0 – 4.5 |
| Zaxira/rotatsiya | < 2.5 |
| **11 lik + kapitan** | **48 – 58** |
| O'rtacha menejerning haqiqiy natijasi | 50 – 54 |

Model 30 larda javob bersa — biror qism tushib qolgan (odatda: bonus,
DefCon yoki 60 daqiqalik ochko).

### 4.1 Backtest — haqiqiy ochko bilan solishtirish

`tools/backtest.py` har o'tgan tur uchun **faqat o'sha paytgacha bo'lgan**
ma'lumotdan bashorat qurib, haqiqiy ochko bilan solishtiradi (qismlar bo'yicha
ham: ishtirok, gol, toza darvoza, DefCon, bonus…). Modelga tegishdan oldin va
keyin ishga tushiring:

```powershell
python tools/backtest.py              # keshdan (data/cache/backtest_raw.json)
python tools/backtest.py --refresh    # FPL dan qayta yuklash (~460 so'rov)
```

2026/27, GW3-10, "safdagi" ~2800 o'yinchi-tur (patch040 oldin → keyin):

| Ko'rsatkich | Ro'yxat rejimi | Batafsil tarix rejimi |
|---|---|---|
| RMSE | 2.75 → 2.70 | 2.72 → 2.67 |
| Bias (bashorat − haqiqat) | −0.21 → +0.01 | −0.05 → +0.01 |
| Har turda top-20 ning haqiqiy ochkosi | 4.59 → 4.86 | 4.81 → 5.15 |
| Spearman (EV ≥ 2) | 0.217 → 0.223 | 0.196 → 0.233 |
| Sodda baza (mavsumiy PPG) RMSE | 2.97 | 2.97 |

"Ro'yxat rejimi" — faqat bootstrap (hamma o'yinchi shunday baholanadi);
"batafsil tarix" — `element-summary` bilan (jamoangiz va transfer nomzodlari).

**Backtestning cheklovlari:** jarohat bayroqlari tarixda yo'q; jamoalarning
`strength` qiymati va penaltichi belgilari — bugungi. 8 tur — kichik namuna:
EV ≥ 6 oralig'ida (~20 ta kuzatuv, 4-5 o'yinchi) model hali ~1.5 ochko
oshirib ko'rsatadi, lekin bu xulosa uchun yetarli emas. Koeffitsiyentlarni
shu 8 turga moslab "sozlash" — overfit; faqat tuzilmaviy xatolar tuzatilgan.

> **Aniqlik shifti.** FPL Review ning "Ultimate Truth" tahliliga ko'ra
> **mukammal** model ham RMSE ≈ 2.7–2.9, R² ≈ 0.11–0.19 dan yaxshi
> qilolmaydi — FPL ochkosi asosan tasodifdan iborat. R² ni quvish befoyda;
> muhimi **kalibrovka** va yuqoridagi ~40 o'yinchini to'g'ri tartiblash.

---

## 5. Qaytib kelmasligi kerak bo'lgan xatolar

Har biri haqiqatan sodir bo'lgan va test bilan qulflangan.

| # | Xato | To'g'risi |
|---|---|---|
| 1 | Darvozabon goli 6 ochko | **10** (2024/25 dan) |
| 2 | To'xtatish = `E[N]/3` | `E[⌊N/3⌋]` — 50% farq |
| 3 | DefCon ga qiyinlik to'g'ri ta'sir qiladi | **Teskari**: qiyin o'yin = ko'proq CBIT |
| 4 | Bitta qiyinlik raqami hamma pozitsiyaga | Himoya va hujum uchun **alohida** |
| 5 | `free_transfers_override` serverni bosib ketadi | Faqat **login yo'q** bo'lganda |
| 6 | FT = `limit` | `limit − made`, `status == "cost"` esa hal qiluvchi |
| 7 | Jamoa qiymati = o'zim hisoblagan | FPL ning `value` i, bankni qo'shish kerakmi — **tekshiriladi** |
| 8 | 11 lik EV kapitansiz | Kapitan **ikkilanadi** (~5 ochko farq) |
| 9 | Bonus — tekis o'rtacha | Voqeaga bog'liq |
| 10 | DaVinci: bo'sh `buttonValue` | Tugma ham maydon |
| 11 | DaVinci: birinchi tugma (`REGISTER`) | **Tanlanadi**, olinmaydi |
| 12 | Bitta brauzer profili hamma akkauntga | Har email — **o'z profili** |
| 13 | FPL `strength_attack/defence` = **0** (2026/27) → hujum priori 0.55 ga yopishadi, gollar −20% | Nol bo'lsa `strength_overall` (2..5) ga o'tiladi, liga o'rtachasi 1.0 ga normallanadi |
| 14 | DefCon/o'tkazilgan gol/to'xtatish: tezlik × daqiqa ulushi, keyin chegara | **O'ynagan holat** bo'yicha: `p60 × P(chegara \| 85 daqiqa)` — DefCon 3 barobar kam chiqardi |
| 15 | DefCon priori HIM 6.6 / YAR 5.8, dispersiya 1.8 | HIM 7.7, YAR 6.0–9.3 (narxga teskari), ichki dispersiya 1.4 + tezlik noaniqligi |
| 16 | Bonus lifti "o'rtacha o'yinchi"ga nisbatan | O'yinchining **o'z neytral uchrashuviga** nisbatan — aks holda premium ikki marta mukofotlanadi |
| 17 | Uzatma = xA | `xA + 0.22·xG` — FPL uzatmasi kengroq (jami uzatma/xA = 1.37, HUJ da 2.8) |
| 18 | "O'ynamadi" → boshlash ≤ 0.45; "zaxiradan qisqa" → ≤ 0.55 | O'lchangan: 0.09–0.41 va 0.13–0.24 (`state_start_prob`) |
| 19 | Toza darvoza = jamoaniki | O'yinchi maydonda bo'lgan vaqt uchun: `exp(−λ × daqiqa/90) × 1.04` |
| 20 | Ro'yxat rejimida o'rnini yo'qotgan o'yinchi mavsum o'rtachasi bilan | `event_points` — so'nggi o'yin izi (faqat jamoa turni tugatgan bo'lsa) |

### Haqiqiy FPL javobi (test uchun etalon)

```json
{"bank": 30, "cost": 4, "limit": 2, "made": 2, "status": "cost", "value": 976}
```

Kutilgan natija: tekin transfer **0**, jamoa qiymati **100.6m**
(976/10 = 97.6 + bank 3.0). `value` ga bank **kirmaydi**.

---

## 6. DaVinci login oqimi

Eng ko'p vaqt olgan qism. FPL ning haqiqiy login oqimi — PingOne DaVinci.
**Brauzersiz, 4–5 soniyada ishlaydi.**

### To'liq zanjir

| Bosqich | Nima bo'ladi | Parol |
|---|---|---|
| `discovery` | FPL sahifasidan `client_id` | yo'q |
| `authorize` | PKCE bilan `/as/authorize` → widget sozlamasi (`apiRoot`, `policyId`, `accessToken`) **va** `/as/resume` formasi bilan `state` | yo'q |
| `start` | `{apiRoot}/davinci/policy/{policyId}/start` → birinchi qadam | yo'q |
| `protect` | PingOne Protect, yagona maydoni `protectsdk` — **bo'sh ketaveradi** | yo'q |
| `login` | Maydonlar: `username`, `password`, **`buttonValue`** | ha |
| oraliq | «Logging you in…» ekrani, faqat tugma so'raydi | — |
| `resume` | `dvResponse` + `state` → `/as/resume` → `code` | — |
| `token` | `code` + PKCE verifier → `access_token` | — |

### Tugma tanlash — eng nozik joy

Login sahifasida **to'qqizta** tugma bor:
`REGISTER, TROUBLE, SIGNON, GOOGLE, FACEBOOK, X, APPLE, STARHUB, REGISTER`.

- Bo'sh yuborilsa: 400 — *«Could not determine what button was selected»*
- Birinchisi olinsa (`REGISTER`): server **200** qaytaradi, lekin oqim
  ro'yxatdan o'tish ekraniga ketadi. **200 kelgani to'g'ri ketdi degani emas.**

Yechim: hamma tugma qiymati va **turi bilan birga** yig'iladi, so'ng
tanlanadi — `form-submit` turi va «kirish» ma'nosidagi qiymat oldinga
chiqadi; `register`/`forgot`/`cancel`/ijtimoiy tarmoqlar **hech bir
qadamda** bosilmaydi.

### Muhim tafsilotlar

- **Hech qanday ID qattiq yozilmagan** — `apiRoot`, `policyId`,
  `connectionId`, `capabilityName`, maydon nomlari, `state` — hammasi
  serverning o'z javobidan olinadi
- `interactionToken` FPL **bermaydi**; cookie faqat `interactionId`
- `users.premierleague.com` **o'lik** (DNS da yo'q) — u yo'l olib tashlangan
- `grant_type=password` (ROPC) — **noto'g'ri usul**, FPL ishlatmaydi
- `/api/me/` login qilgan **o'sha sessiya** bilan so'ralishi kerak (Cloudflare
  `__cf_bm` cookie si o'sha yerda)

### Tashxis

```powershell
python tools/sso_probe.py                 # parolsiz — login qadamigacha
python tools/sso_probe.py --with-login    # oxirigacha: parol → resume → token
python tools/sso_probe.py --raw           # `screen` tuzilmasini ham saqlaydi
```

`data/sso_probe.json` ga bosqichlar, **serverning xato xabari** va javob
kalitlari yoziladi. Parol, token, cookie **yozilmaydi**.

---

## 7. Web sahifa — beshta bo'lim

| Bo'lim | Nima qiladi | Login |
|---|---|---|
| **O'yinchilar** | 500+ o'yinchi, 20+ ustun, filtr va saralash | yo'q |
| **Jamoam** | Tarkib + tavsiya etilgan 11 lik + har zaxira uchun sabab | ha (aniqroq) |
| **Transferlar** | Kimni sotib kimni olish, sof foyda (hit ayirilgan) | ha (aniqroq) |
| **Jamoa tuzish** | Noldan 15 lik: 100m, 2/5/5/3, klubdan ≤3 | yo'q |
| **Sur'at** | Maqsadga nisbatan progress + jamoa ko'rsatkichlari | ha |
| **Kapitan** | Variantlar: EV, 10+ ehtimoli, raqiblardagi ulush; o'ringa mos strategiya | ha |
| **Chiplar** | WC/FH/BB/TC — gorizontdagi har tur uchun qo'shiladigan ochko, chegara +8 | ha |
| **Raqiblar** | Mini-liga: xavf, imkoniyat, har raqib bo'yicha farq va kelgusi tur kutilmasi | ha |
| **H2H** | Model va ekspertlar Free Hit tarkiblari — tur bo'yicha hisob | yo'q |

Yangi to'rttasi (`captainview`, `chipsview`, `rivalsview`, `h2hview`) mavjud
`captain.py` / `chips.py` / `rivals.py` / `h2h.py` ustiga qurilgan — model
mantig'i o'zgarmagan. Bilish kerak:

* **Raqiblar tarkibi o'tgan deadline holatida** — kelgusi tur tarkiblari FPL da
  yopiq. Kapitandagi «raqiblarda» ustuni ham shunday (top-50, o'tgan tur).
* **Katta ligada** (FPLUzbekistan — siz 144-o'rinda) yetakchilar sahifasi yoniga
  o'rningizdan ±7 ta jamoa qo'shiladi; xavf/imkoniyat yetakchilar bo'yicha.
* **Birinchi yuklash sekin** (raqiblar ~18 s, kapitan ~20 s: 50 ta jamoa
  so'raladi), keyin 5–10 daqiqa keshda.
* **Chiplar faqat `horizon` turni ko'radi** — undan naridagi DGW ko'rinmaydi.

### Diqqatga sazovor yechimlar

**EV qismlarga ajraladi.** O'yinchi ustiga bosilsa: `+2.0 ishtirok, +1.6
toza darvoza, +0.5 defcon…` — yig'indisi EV ga **teng** (test tekshiradi).
Yonida «toza darvoza 35% → bo'lsa 6.2 ochko».

> **EV — o'rtacha, "yaxshi holat" emas.** CS ehtimoli 35% bo'lgan himoyachi
> CS dan `0.35 × 4 = 1.4` oladi, jami ~4. "5-7 ochko" — bu CS **ro'y
> bergan** holat. EV ni o'sha darajaga ko'tarish tanlovni buzadi.

**EV yonida natija taqsimoti turadi (`squadview.outlook`).** EV — o'rtacha va
ko'pincha eng **kam** uchraydigan natija: backtestda EV ≈ 4 bo'lgan himoyachi
42% holatda 1–2 ochko, 34% holatda 6+ olgan, 3–5 esa atigi 23%. Shuning uchun
ro'yxatda «6+ ochko» ehtimoli, o'yinchi tafsilotida esa 0–2 / 3–5 / 6+ / 10+
ehtimollari ko'rsatiladi. («Yaxshi kunda ↑8» raqami maydonda sinab ko'rilib,
olib tashlandi: zaif o'yinchida ham 6 chiqib, chalg'itardi — ehtimol foizi
o'yinchilarni ajratadi, yaxshi kun ochkosi esa yo'q.) **EV ning o'zi ko'tarilmaydi**
(«toza darvoza kutilsa 6 yozaylik» degan talab bo'lgan): u haqiqiy o'rtachaga
mos (4.0 vs 3.99) va 11 lik, transfer, kapitan, H2H hisoblari shunga tayanadi;
ko'tarilsa jamoa yig'indisi ~60 o'rniga ~75 chiqib, hamma solishtiruv buziladi.
Ehtimollar biroz optimistik: model «6+ 35%» deganida haqiqatda ~29%
(`tools/backtest.py`, «Taqsimot» bo'limi).

**Transferlarda bir o'yinchi bir marta.** Xom dvigatel bitta o'yinchi uchun
o'nlab variant beradi — u «NEW44 ni kimga almashtirsam?» degan savolga
javob beradi. Kerakligi boshqa: «kimni sotsam?».

**«Hech narsa qilmaslik» ham tavsiya.** Eng yaxshi variant hit ni oqlamasa,
sahifa ochiq aytadi.

**Sur'at o'lchagichida uch nuqta:** to'ldirilgan qism (sizning
yig'indingiz), kulrang belgi (reja), **ko'k belgi** (1-o'rin yig'indisi).
Oradagi masofa — farq.

---

## 8. Sozlamalar (`config.yaml`)

```yaml
entry_id: 34191
season_target: 2810            # 38 × 74
horizon: 5                     # necha tur oldinga
form_weight: 0.10              # forma ta'siri, 0 = o'chiq
strength_spread: 2.3           # FPL strength tarqalishini tiklash
table_weight: 0.45             # jadval o'rnining qiyinlikdagi vazni
xi_risk_aversion: 0.35         # 11 likda ishonchlilikka urg'u
bench_weight: 0.14
horizon_decay: 0.90
hit_cost: 4.0
team_form_shrink_matches: 10.0 # backtest: 6.0 so'nggi natijalarga ortiqcha ishonardi
shrink_defcon_90s: 2.0         # DefCon tezligi o'yinchiga xos, tez barqarorlashadi
european_teams: [ARS, LIV, MCI, NEW, TOT, AVL, CHE]   # qo'lda, har mavsum
# free_transfers_override: 0   # login bo'lsa E'TIBORSIZ qoladi
```

**`config.yaml` `.gitignore` da.** Shuningdek: `.env`, `cookie.txt`,
`data/profiles/`, `data/sessions/`, `data/browser/`, `data/sso_probe.json`,
`hisobot.html`.

---

## 9. Testlar — 348 ta

| Fayl | Nimani qulflaydi |
|---|---|
| `test_model.py` | EV qismlari, FT o'qish, jamoa qiymati |
| `test_calibration.py` | **Kattalik mezonlari** (yuqoridagi jadval) |
| `test_difficulty.py` | Pozitsiyaga bog'liq qiyinlik |
| `test_form.py` | Forma ±10% ichida va asosni qoplamaydi |
| `test_congestion.py` | Rotatsiya xavfi, Yevropa ro'yxati |
| `test_builder.py` | 15 lik qoidalari — byudjet, 2/5/5/3, klubdan ≤3 |
| `test_pace.py` | Sur'at, jamoa ko'rsatkichlari, yetakchi |
| `test_pl_sso.py` | DaVinci oqimi (soxta PingOne server) |
| `test_web.py` | Barcha endpointlar, ko'p foydalanuvchi ajratilishi |
| `test_table.py` | Arsenal/Villa regressiyasi |
| `test_backtest_fixes.py` | Backtest topgan xatolar (5-bo'lim, 13–20) |

```powershell
python -m pytest -q
```

---

## 10. Keyingi qadamlar

Tartib bo'yicha, eng foydalisidan:

1. **`git push`** — hammasidan muhim
2. **H2H sinovi** — GW11 dan boshlangan (pastda). **Kamida 8–10 tur** kerak:
   bir turda ±20 ochko farq model haqida deyarli hech narsa aytmaydi
3. ~~Kapitan, chiplar, mini-liga raqiblari, H2H~~ — web'da (7-bo'lim)
4. ~~MILP~~ — qilindi (`builder.solve_exact`)
5. **O'ringa mos funksiyalar** (kelishilgan reja, hali boshlanmagan): menejerning
   o'rni atrofidagi raqiblar bo'yicha xavf/imkoniyat, o'ringa mos kapitan,
   xavf darajasi maslahati, chiplar raqiblarga nisbatan, tur oldidan o'rin
   prognozi. Moslash kuchi mavsum oxiriga qarab ortishi kerak (20-turgacha
   kichik); ko'p foydalanuvchi uchun o'rin oraliqlari bo'yicha namuna haftada
   bir marta yig'iladi. Asos: `rivals.rank_neighbours`, `captain.rank_strategy`.
6. **Botga ko'chirish** — web tayyor; ekspertlar bilan yopiq sinov, so'ng
   ikkinchi davra (GW20) oldidan kanalda ishga tushirish

### H2H va jonli EV sinovi — har tur bajariladigan ish

Ekspertlar har tur oldidan **Free Hit** tarkib e'lon qiladi (kanalda «Ekspertlar
jamoasi»). Model ham noldan, 100m ichida, faqat shu tur uchun tuzadi — eng
halol taqqoslash shu. Ekspertlarning haqiqiy jamoasi: **FPLUzbekistan, ID 715763**.

```powershell
# deadline oldidan
python tools/h2h.py freeze                      # model tarkibini muzlatadi
python tools/h2h.py experts "Raya, Gabriel, … Haaland (c), Tavernier (v), … | Dubravka, Konsa, Van Hecke, Gomez"
python tools/ev_check.py save                   # barcha o'yinchilar bashoratini muzlatadi
# tur tugagach
python tools/h2h.py score                       # ikkala tarkib, FPL qoidalari bo'yicha
python tools/h2h.py table                       # barcha turlar
python tools/ev_check.py check                  # bashorat vs haqiqat
```

Tarkiblar `data/store/h2h/gwNN.json` da, bashoratlar `data/store/ev/` da —
ikkalasi ham git da. Ism xatolariga chidamli («De Cupyer», «Grob»); hisob
kapitan/vitse va avtoalmashtirishni hisobga oladi (GW10 ekspert tarkibi
jadvaldagi bilan bir xil chiqdi: 75).

**Ekspertlar jadvali** — `2026-27 GW Team.xlsx` (har varaq bitta tur: 10 ekspertning
Free Hit tanlovi + umumiy «GW Team», `1` = tanlangan, `2` = kapitan). Bu
tarkiblar haqiqiy jamoalarga **aloqasi yo'q**; jadvalda faqat 11 lik + kapitan
bor, shuning uchun H2H hisobi ham shunday (zaxira va avtoalmashtirishsiz).

```powershell
python tools/h2h.py import      # jadvaldan barcha turlarni yuklaydi
python tools/h2h.py backfill    # model orqaga qarab, ekspertlarga qarshi
```

Import jadval bilan tekshirilgan: «GW Team» ochkosi 10 turning hammasida bir xil.
**Repo ochiq**, shuning uchun: `.xlsx` va har ekspertning shaxsiy tanlovi
(`data/store/h2h_private/`) `.gitignore` da; git da faqat kanalda e'lon
qilinadigan umumiy «GW Team» va model tarkibi turadi.

Orqaga qarab natija (GW2-10, 9 tur): **model 611**, GW Team 637, ekspertlarning
o'rtachasi 594, FPL o'rtachasi 513; model GW Team ni 9 turdan 5 tasida yutgan.
Ya'ni model o'rtacha ekspert darajasida, umumiy tarkibdan biroz past. Bu
backtest (jarohat bayroqlarisiz, koeffitsiyentlar shu turlarda tekshirilgan) —
hukm emas; hisob GW11 dan jonli yuritiladi.

**Jamoa tuzuvchi endi aniq yechadi** (`builder.solve_exact`, PuLP + CBC).
Eski mahalliy qidiruv Haaland ni byudjetga sig'dira olmay tiqilib qolardi:
backfillda 498 → 518 ochko. `pulp>=2.8,<3` (3.x numpy talab qiladi).

### Model uchun eng katta imkoniyat

Research ko'rsatdi: tijoriy modellar ochiq modellardan **kutilayotgan
daqiqalar** bo'yicha ustun. `congestion.py` bu bo'shliqning bir qismini
yopdi, lekin jamoa yangiliklari (matbuot anjumani, murabbiy gaplari) hali
yo'q. Agar biror manba topilsa — eng katta yutuq shu yerda.

---

## 11. Ish qoidalari

- **Izohlar va tushuntirishlar — o'zbekcha**, git commit xabarlari —
  **inglizcha**
- Patch nomi: `patch040.patch` (chiziqchasiz), `git apply` bilan
- Har patch oldidan: `python -m pytest -q` o'tishi shart
- Ish `web-modules` branchida; `main` ga merge — alohida qaror
- **Hech qachon commit qilinmaydi:** cookie, token, parol, `config.yaml`,
  `.env`, `data/sessions/`, `data/profiles/`
- Cookie GitHub Secrets ga **yaramaydi**: `cf_clearance` va `datadome` IP va
  brauzerga bog'langan

---

## 12. Yangi suhbatni qanday boshlash

Boshqa akkauntda ishni davom ettirishda shu matnni bering:

> Men FPL tahlil dvigatelini qilyapman — `fpl-analytics`, Python,
> `web-modules` branchi. Ilova qilingan `HANDOVER.md` da loyihaning
> to'liq hujjati bor: EV modeli, kalibrovka mezonlari, tuzatilgan xatolar
> va DaVinci login oqimi. O'qib chiqing, keyin [vazifa] ustida ishlaymiz.
>
> Qoidalar: izohlar o'zbekcha, commit xabarlari inglizcha, yetkazib
> berish `patchNNN.patch` orqali, har patch oldidan testlar o'tishi shart.

Repo bilan birga bu faylni ham bering — ikkalasisiz boshqa model
loyihaning nega shunday qurilganini bilmaydi va qilingan xatolarni
takrorlaydi.
