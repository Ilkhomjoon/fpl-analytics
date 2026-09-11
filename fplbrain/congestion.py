"""Jadval zichligi va rotatsiya xavfi.

NEGA KERAK? Ochiq xP modellarining tijoriy modellardan orqada qolishining
**asosiy** sababi — kutilayotgan daqiqalar. OpenFPL maqolasi buni ochiq
yozadi: tijoriy modellar "jamoa yangiliklari, jadval zichligi va bukmeker
koeffitsiyentlaridan olingan batafsil xMins" ishlatadi, ochiq modellar esa
FPL ning 0/25/50/75/100% belgisi bilan cheklanadi — u esa o'yinchi asosiy
tarkibda chiqadimi, zaxiradan kiradimi yoki dam oladimi, ayta olmaydi.

Bizda bukmeker ham, matbuot anjumani ham yo'q. Lekin **jadvalning o'zi**
bepul va u ko'p narsani aytadi:

* ikki o'yin orasidagi kun soni (`kickoff_time` dan hisoblanadi);
* qisqa oraliqdagi o'yinlar soni (DGW va chorshanba turlari);
* Yevropa kubogi — FPL API sida YO'Q, shuning uchun `config.yaml` dan
  o'qiladi (`european_teams`). Qattiq yozilmagan: ro'yxat har mavsum
  o'zgaradi va uni foydalanuvchi yangilaydi.

ROTATSIYA QANDAY MODELLASHTIRILADI? Zichlik "mumkin bo'lgan tarkiblar
sonini oshiradi" — ya'ni noaniqlikni oshiradi. Shuning uchun jazo emas,
**neytral tomon tortish** ishlatiladi: mustahkam o'yinchining tarkibga
tushish ehtimoli biroz tushadi, chetdagi o'yinchiniki esa biroz ko'tariladi.
Bu haqiqatga mos: rotatsiya kimdir uchun yo'qotish, kimdir uchun imkoniyat.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# Dam olish kunlari: shundan kam bo'lsa rotatsiya xavfi boshlanadi
FULL_REST_DAYS = 6.0        # bir haftadan ko'p dam — zichlik yo'q
TIGHT_REST_DAYS = 3.0       # 3 kun yoki kamroq — eng yuqori zichlik
# Qisqa oynadagi o'yinlar soni
WINDOW_DAYS = 12
WINDOW_NORMAL = 2           # 12 kunda 2 o'yin — odatiy
WINDOW_HEAVY = 4            # 4 va undan ko'p — juda zich
# Yevropa o'yini oraliqqa yana bitta o'yin qo'shadi
EUROPE_WEIGHT = 0.45


def _parse(kickoff: str | None) -> datetime | None:
    """FPL vaqti ISO formatda: `2026-09-13T13:00:00Z`."""
    if not kickoff:
        return None
    try:
        text = kickoff.replace("Z", "+00:00")
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


@dataclass
class TeamSchedule:
    """Bitta jamoaning barcha o'yin vaqtlari (o'ynalgani ham, oldindagisi ham)."""
    team: int
    kickoffs: list[datetime]

    def rest_before(self, moment: datetime) -> float:
        """Shu o'yingacha necha kun dam. Oldingi o'yin topilmasa — to'liq dam."""
        oldingi = [k for k in self.kickoffs if k < moment]
        if not oldingi:
            return FULL_REST_DAYS
        return (moment - max(oldingi)).total_seconds() / 86400.0

    def rest_after(self, moment: datetime) -> float:
        """Shu o'yindan keyin necha kun dam."""
        keyingi = [k for k in self.kickoffs if k > moment]
        if not keyingi:
            return FULL_REST_DAYS
        return (min(keyingi) - moment).total_seconds() / 86400.0

    def in_window(self, moment: datetime, days: int = WINDOW_DAYS) -> int:
        """Shu o'yin atrofidagi oynada nechta o'yin bor (shu o'yin ham sanaladi)."""
        yarim = timedelta(days=days / 2.0)
        return sum(1 for k in self.kickoffs
                   if moment - yarim <= k <= moment + yarim)


def build_schedules(fixtures: list[dict]) -> dict[int, TeamSchedule]:
    """Barcha uchrashuvlardan har jamoa uchun vaqt jadvali."""
    out: dict[int, list[datetime]] = {}
    for f in fixtures or []:
        moment = _parse(f.get("kickoff_time"))
        if moment is None:
            continue
        for key in ("team_h", "team_a"):
            team = f.get(key)
            if team:
                out.setdefault(int(team), []).append(moment)
    return {team: TeamSchedule(team, sorted(times)) for team, times in out.items()}


def _rest_pressure(days: float) -> float:
    """Dam kunlaridan 0..1 zichlik. 6+ kun → 0, 3 kun va kamroq → 1."""
    if days >= FULL_REST_DAYS:
        return 0.0
    if days <= TIGHT_REST_DAYS:
        return 1.0
    return (FULL_REST_DAYS - days) / (FULL_REST_DAYS - TIGHT_REST_DAYS)


def _window_pressure(count: int) -> float:
    """Oynadagi o'yin sonidan 0..1 zichlik."""
    if count <= WINDOW_NORMAL:
        return 0.0
    if count >= WINDOW_HEAVY:
        return 1.0
    return (count - WINDOW_NORMAL) / float(WINDOW_HEAVY - WINDOW_NORMAL)


def rotation_risk(
    schedule: TeamSchedule | None,
    kickoff: str | None,
    in_europe: bool = False,
) -> float:
    """0..1 — shu uchrashuvda tarkib o'zgarishi ehtimoli qanchalik yuqori.

    Uchta signal qo'shiladi: o'yindan OLDINGI dam, KEYINGI dam (keyingi o'yin
    yaqin bo'lsa murabbiy bugun o'yinchini asraydi) va qisqa oynadagi o'yinlar
    soni. Yevropa kubogi oraliqqa ko'rinmas o'yin qo'shadi — FPL jadvalida u
    yo'q, shuning uchun alohida qo'shiladi.
    """
    moment = _parse(kickoff)
    if schedule is None or moment is None:
        return EUROPE_WEIGHT if in_europe else 0.0

    oldin = _rest_pressure(schedule.rest_before(moment))
    keyin = _rest_pressure(schedule.rest_after(moment))
    oyna = _window_pressure(schedule.in_window(moment))

    # Eng kuchli signal ustun turadi, qolganlari qo'shimcha vazn beradi
    asosiy = max(oldin, keyin, oyna)
    qoshimcha = (oldin + keyin + oyna - asosiy) / 4.0
    risk = asosiy * 0.75 + qoshimcha
    if in_europe:
        risk += EUROPE_WEIGHT * (1.0 - risk)      # to'yinadi, 1 dan oshmaydi
    return round(max(0.0, min(1.0, risk)), 3)


def european_team_ids(cfg, teams: list[dict]) -> set[int]:
    """`config.yaml` dagi `european_teams` ro'yxatini jamoa ID lariga aylantiradi.

    Qisqa nom ham (`ARS`), to'liq nom ham (`Arsenal`), ID ham qabul qilinadi.
    FPL API Yevropa ishtirokini bermaydi — bu ro'yxat qo'lda beriladi va
    har mavsum o'zgaradi, shuning uchun kodga yozilmagan.
    """
    xohlangan = getattr(cfg, "european_teams", None) or []
    if not xohlangan:
        return set()
    nomlar: dict[str, int] = {}
    for t in teams or []:
        tid = int(t.get("id", 0) or 0)
        for key in ("short_name", "name"):
            nom = str(t.get(key, "")).strip().lower()
            if nom:
                nomlar[nom] = tid
    out: set[int] = set()
    for item in xohlangan:
        if isinstance(item, int):
            out.add(item)
            continue
        matn = str(item).strip().lower()
        if matn.isdigit():
            out.add(int(matn))
        elif matn in nomlar:
            out.add(nomlar[matn])
    return out
