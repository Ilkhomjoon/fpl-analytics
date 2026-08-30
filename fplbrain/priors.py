"""Priorlar — o'tgan mavsumsiz, faqat joriy bozor ma'lumotidan.

Mavsum boshida statistika kam. Ilgari bu bo'shliq o'tgan mavsum bilan
to'ldirilardi, lekin u ikki sababdan yomon: jamoa almashgan yoki roli
o'zgargan o'yinchini noto'g'ri baholaydi, va o'tgan mavsumda kam o'ynagan
(jarohat, yosh, yangi transfer) o'yinchini zaif deb ko'rsatadi.

Buning o'rniga ikkita **joriy** signal ishlatiladi:

1. **Egalik (`selected_by_percent`)** — ROL signali. Menejerlar ommaviy
   ravishda zaxira o'yinchini sotib olmaydi. 25% menejer olgan 6.5m lik
   o'yinchi deyarli aniq asosiy tarkibda. Bu ochiq ma'lumot (matbuot
   anjumani, mashqlar) asosidagi jamoaviy bashorat va u 2 o'yinlik
   namunadan ancha ishonchli.

2. **Narx** — SIFAT signali. FPL narxni jamoaviy talabga qarab o'zgartiradi,
   ya'ni narx bozorning o'yinchi haqidagi bahosi. 12m lik yarim himoyachidan
   4.5m likka qaraganda ko'proq hujum chiqimi kutiladi.

MUHIM chegara: egalik faqat ROL ni bashorat qiladi, CHIQIM ni emas. Aks
holda model shablonni takrorlaydi va "hamma olgan, siz olmang" deya olmay
qoladi — 2 millionchi o'rindan chiqish uchun esa aynan shu kerak.
"""

from __future__ import annotations

GK, DEF, MID, FWD = 1, 2, 3, 4


def enabler_discount(price: float) -> float:
    """Egalikning rol signali sifatidagi ishonchliligi (0.25–1.0).

    Menejerlar byudjetni to'ldirish uchun eng arzon o'yinchilarni oladi —
    ular o'ynamaydi. Shuning uchun arzon o'yinchida yuqori egalik "asosiy
    tarkib" degani EMAS. 4.0m → 0.25, 5.5m va undan qimmat → 1.0.
    """
    if price <= 4.0:
        return 0.25
    if price >= 5.5:
        return 1.0
    return 0.25 + (price - 4.0) / 1.5 * 0.75


def role_prior(ownership: float, price: float) -> float:
    """Asosiy tarkibda chiqish ehtimolining priori (0.20–0.93).

    Egalik egri chizig'i: own/(own+k) shakli — kam egalikda tez o'sadi,
    keyin to'yinadi. Lekin arzon o'yinchida signal chegiriladi (enabler).
    """
    own = max(0.0, ownership)
    from_ownership = 0.20 + 0.72 * (own / (own + 6.0)) * enabler_discount(price)

    # Narx ham rol haqida gapiradi: qimmat o'yinchi zaxirada o'tirmaydi
    from_price = 0.25 + max(0.0, min(1.0, (price - 4.0) / 8.0)) * 0.62

    # Ikkalasidan kuchlisini olamiz: har biri o'zicha yetarli dalil
    return max(0.20, min(0.93, max(from_ownership, from_price)))


# Narxdan kutilayotgan hujum chiqimi. Chegara qiymatlar Premier League
# o'rtachalaridan: eng arzon o'yinchi deyarli hech narsa bermaydi, eng
# qimmati esa mavsumiga ~20 gol+uzatma darajasida.
_XG90_RANGE = {                    # (eng arzon, eng qimmat, narx oralig'i)
    GK:  (0.00, 0.00, 1.0),
    DEF: (0.02, 0.14, 4.0),        # 4.0m → 0.02, 8.0m → 0.14
    MID: (0.04, 0.48, 9.0),        # 4.5m → 0.04, 13.5m → 0.48
    FWD: (0.12, 0.72, 10.0),       # 4.5m → 0.12, 14.5m → 0.72
}
_XA90_RANGE = {
    GK:  (0.01, 0.02, 1.0),
    DEF: (0.03, 0.18, 4.0),
    MID: (0.06, 0.38, 9.0),
    FWD: (0.05, 0.28, 10.0),
}
_BASE_PRICE = {GK: 4.0, DEF: 4.0, MID: 4.5, FWD: 4.5}


def _from_price(price: float, position: int, table: dict) -> float:
    low, high, span = table[position]
    t = max(0.0, min(1.0, (price - _BASE_PRICE[position]) / span))
    return low + (high - low) * t


def xg90_prior(price: float, position: int) -> float:
    """Narxdan kutilayotgan xG/90."""
    return _from_price(price, position, _XG90_RANGE)


def xa90_prior(price: float, position: int) -> float:
    """Narxdan kutilayotgan xA/90."""
    return _from_price(price, position, _XA90_RANGE)


# DefCon harakatlari narxga bog'liq emas — pozitsiya va o'yin uslubiga bog'liq.
# Arzon himoyachilar ko'proq CBIT to'playdi (ko'proq himoyalanadigan jamoalar).
_DC90_PRIOR = {GK: 0.0, DEF: 6.6, MID: 5.8, FWD: 3.2}


def dc90_prior(price: float, position: int) -> float:
    """Himoya harakatlari priori. Qimmat himoyachi hujumkorroq — kamroq CBIT."""
    base = _DC90_PRIOR[position]
    if position == DEF and price >= 5.5:
        base *= 0.88            # hujumkor fullbacklar kamroq himoyalanadi
    return base


def bonus90_prior(price: float, position: int) -> float:
    """Bonus to'plash moyilligi — narx bilan o'sadi."""
    base = {GK: 0.28, DEF: 0.24, MID: 0.22, FWD: 0.26}[position]
    lift = max(0.0, min(1.0, (price - _BASE_PRICE[position]) / 8.0))
    return base + lift * 0.55


def evidence_weight(nineties: float, k: float) -> float:
    """Joriy mavsum dalilining vazni: 0 (dalil yo'q) dan 1 (to'liq ishonch) gacha."""
    return nineties / (nineties + k) if (nineties + k) > 0 else 0.0
