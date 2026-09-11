"""Mahalliy web ilova — o'yinchilar ro'yxati va model ko'rsatkichlari.

    python serve.py            # http://127.0.0.1:8000
    python serve.py --demo     # tarmoqsiz, soxta ma'lumot bilan

Nega mahalliy? FPL ning shaxsiy endpointlari oldida Cloudflare/DataDome
turadi va u bulut serveridan kelgan so'rovni to'sadi. Sizning
kompyuteringizdan — o'z IP ingiz bilan — o'tish ehtimoli ancha yuqori.

Nima ochiq, nima yopiq:

* **O'yinchilar ro'yxati loginsiz ishlaydi.** `bootstrap-static/` ochiq:
  narx, egalik, daqiqa, asosiy tarkib, gol/uzatma, xG/xA va shu tur
  oldidagi transfer oqimi — hammasi shu yerdan keladi.
* Login faqat `my-team/{id}` uchun kerak: aniq sotish narxi, erkin
  transferlar, chip holati.

Parol serverda saqlanmaydi: u faqat login so'rovi paytida ishlatiladi.
Token esa jarayon xotirasida turadi va dastur yopilganda yo'qoladi.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory

from fplbrain import auth as auth_mod
from fplbrain import rating as rating_mod
from fplbrain import session_store
from fplbrain.api import FplClient
from fplbrain.config import Config
from web import draftview, paceview, squadview, transferview

log = logging.getLogger("fplweb")

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"

POSITIONS = {1: "DRV", 2: "HIM", 3: "YAR", 4: "HUJ"}
POSITION_NAMES = {1: "Darvozabon", 2: "Himoyachi", 3: "Yarim himoyachi", 4: "Hujumchi"}


class Session:
    """Bitta foydalanuvchi (siz) uchun holat — jarayon xotirasida."""

    def __init__(self) -> None:
        self.credentials = auth_mod.Credentials()
        self.account_key = ""          # qaysi akkaunt profili ishlatilyapti
        self.client = None             # shu sessiyaning o'z API klienti
        self.public_entry_id = 0       # loginsiz, faqat jamoa ID bilan ulanish
        self.last_login: dict | None = None
        # Brauzer orqali kirish uzoq davom etadi (captcha, 2FA), shuning uchun
        # u fonda ishlaydi va sahifa holatni so'rab turadi.
        self.job_running = False
        self.job_started = 0.0
        self.expires_at = 0.0

    @property
    def logged_in(self) -> bool:
        return self.credentials.ok

    @property
    def entry_id(self) -> int:
        """Kim uchun tahlil qilyapmiz: login qilgan hisob yoki ochiq jamoa ID."""
        return self.credentials.entry_id or self.public_entry_id

    @property
    def seconds_left(self) -> int:
        if not self.expires_at:
            return 0
        return max(0, int(self.expires_at - time.time()))

    @property
    def needs_refresh(self) -> bool:
        """Tugashiga oz qoldi — jimgina yangilaymiz, foydalanuvchi kutmasin."""
        return self.logged_in and self.seconds_left < session_store.REFRESH_MARGIN


def team_matches_played(bootstrap: dict, fixtures: list[dict]) -> dict[int, int]:
    """Har jamoa nechta o'yin **tugatgani**. Yarim o'ynalgan tur sanalmaydi."""
    played = {t["id"]: 0 for t in bootstrap.get("teams", [])}
    counted = False
    for f in fixtures or []:
        if not (f.get("finished") or f.get("finished_provisional")):
            continue
        for side in ("team_h", "team_a"):
            tid = f.get(side)
            if tid in played:
                played[tid] += 1
                counted = True
    if not counted:
        for t in bootstrap.get("teams", []):
            played[t["id"]] = max(0, t.get("played", 0) or 0)
    return played


def create_app(cfg: Config | None = None, client=None, demo: bool = False) -> Flask:
    cfg = cfg or Config.load()
    if client is None:
        if demo:
            from fplbrain.demo import FakeClient
            client = FakeClient()
            # Demo da tarkib ham ko'rinsin — soxta klient istalgan ID ga javob beradi
            cfg.entry_id = cfg.entry_id or 1
        else:
            client = FplClient(
                cfg.cache_dir, cfg.cache_ttl_seconds, cfg.request_delay,
                cfg.max_workers, cookie=cfg.fpl_cookie,
            )

    app = Flask(__name__, static_folder=None)
    app.config["FPL"] = client

    # Har brauzerga ALOHIDA sessiya. Bitta global holat ko'p foydalanuvchi
    # uchun yaramaydi: ikkinchi odam birinchisining tokeni bilan ishlab
    # ketardi. `fplsid` — kim ekanini bilish uchun, `fplacct` — qaysi
    # saqlangan akkauntni tiklash uchun (ikkalasi ham httponly).
    SID_COOKIE, ACCT_COOKIE = "fplsid", "fplacct"
    sessions: dict[str, Session] = {}
    sessions_lock = threading.Lock()

    def _S() -> Session:
        return g.session

    @app.before_request
    def _attach_session():
        sid = request.cookies.get(SID_COOKIE) or ""
        with sessions_lock:
            current = sessions.get(sid)
            if current is None:
                sid = secrets.token_urlsafe(18)
                current = Session()
                sessions[sid] = current
                g.new_sid = sid
                # Shu brauzer oldin qaysi akkaunt bilan kirgan bo'lsa — o'shani
                # tiklaymiz. Cookie si yo'q begona odam hech narsa olmaydi.
                remembered = request.cookies.get(ACCT_COOKIE) or ""
                if remembered and not demo:
                    restore(current, remembered)
        g.session = current

    @app.after_request
    def _set_cookies(response):
        if getattr(g, "new_sid", None):
            response.set_cookie(SID_COOKIE, g.new_sid, httponly=True,
                                samesite="Lax", max_age=30 * 24 * 3600)
        if getattr(g, "set_account", None):
            response.set_cookie(ACCT_COOKIE, g.set_account, httponly=True,
                                samesite="Lax", max_age=30 * 24 * 3600)
        if getattr(g, "clear_account", False):
            response.delete_cookie(ACCT_COOKIE)
        return response

    lock = threading.Lock()
    cache: dict[str, object] = {"at": 0.0, "payload": None}
    squad_lock = threading.Lock()
    squad_cache: dict = {"at": 0.0, "payload": None, "entry": 0}
    transfer_lock = threading.Lock()
    transfer_cache: dict = {"at": 0.0, "payload": None, "entry": 0}
    draft_lock = threading.Lock()
    draft_cache: dict = {"at": 0.0, "payload": None, "budget": 0.0}
    pace_lock = threading.Lock()
    pace_cache: dict = {"at": 0.0, "payload": None, "entry": 0}

    # ------------------------------------------------------------- ma'lumot
    def snapshot(force: bool = False) -> dict:
        """Bootstrap + fixtures dan reyting jadvalini yig'adi (60 s kesh)."""
        with lock:
            fresh = cache["payload"] is not None and (time.time() - float(cache["at"])) < 60
            if fresh and not force:
                return cache["payload"]                     # type: ignore[return-value]

            bootstrap = client.bootstrap()
            try:
                fixtures = client.fixtures()
            except Exception as exc:                        # ro'yxat baribir chiqsin
                log.warning("fixtures olinmadi: %s", exc)
                fixtures = []

            teams = {t["id"]: t for t in bootstrap["teams"]}
            short = {tid: t["short_name"] for tid, t in teams.items()}
            played = team_matches_played(bootstrap, fixtures)
            ratings = rating_mod.rate_all(
                bootstrap["elements"], played, short,
                bootstrap.get("total_players", 0),
            )

            events = bootstrap.get("events", [])
            current = next((e for e in events if e.get("is_current")), None)
            nxt = next((e for e in events if e.get("is_next")), None)

            rows = []
            for element in bootstrap["elements"]:
                r = ratings.get(element["id"])
                if r is None:                               # klubdan ketganlar
                    continue
                tid = element["team"]
                rows.append({
                    "id": element["id"],
                    "name": element.get("web_name", "?"),
                    "full_name": " ".join(x for x in (
                        element.get("first_name"), element.get("second_name")
                    ) if x),
                    "team": short.get(tid, "?"),
                    "team_id": tid,
                    "team_played": played.get(tid, 0),
                    "pos": r.position,
                    "pos_short": POSITIONS.get(r.position, "?"),
                    "price": r.price,
                    "ownership": r.ownership,
                    "starts": r.starts,
                    "minutes": r.minutes,
                    "minutes_share": round(r.minutes_share * 100, 1),
                    "goals": r.goals,
                    "assists": r.assists,
                    "ga": r.goals + r.assists,
                    "xg": r.xg,
                    "xa": r.xa,
                    "xgi": round(r.xg + r.xa, 2),
                    "in_event": element.get("transfers_in_event", 0) or 0,
                    "out_event": element.get("transfers_out_event", 0) or 0,
                    "net": r.net_transfers,
                    "momentum": r.momentum,
                    "role": round(r.role * 100, 1),
                    "output90": r.output90,
                    "returns90": r.returns90,
                    "underlying90": r.underlying90,
                    "over": r.overperforming,
                    "value": r.value,
                    "score": r.score,
                    "points": element.get("total_points", 0) or 0,
                    "enabler": r.is_enabler,
                    "note": r.note,
                    "status": element.get("status", "a"),
                    "news": element.get("news") or "",
                })

            payload = {
                "players": rows,
                "teams": [
                    {"id": tid, "short": t["short_name"], "name": t["name"],
                     "played": played.get(tid, 0)}
                    for tid, t in sorted(teams.items(), key=lambda kv: kv[1]["short_name"])
                ],
                "positions": [
                    {"id": pid, "short": POSITIONS[pid], "name": POSITION_NAMES[pid]}
                    for pid in (1, 2, 3, 4)
                ],
                "event": (current or nxt or {}).get("id", 0),
                "next_event": (nxt or {}).get("id", 0),
                "deadline": (nxt or {}).get("deadline_time", ""),
                "total_players": bootstrap.get("total_players", 0),
                "generated": time.time(),
            }
            cache["payload"], cache["at"] = payload, time.time()
            return payload

    # ------------------------------------------------------------- sahifalar
    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.get("/static/<path:name>")
    def static_file(name: str):
        return send_from_directory(STATIC, name)

    # ----------------------------------------------------------------- API
    data_dir = Path(cfg.cache_dir).parent

    def client_for(session: Session):
        """Shu sessiyaning klienti.

        Login qilingan sessiya **o'z** klientini oladi: umumiy klientga token
        qo'yish ko'p foydalanuvchida birovning tokeni bilan so'rov yuborishga
        olib kelardi. Kesh papkasi umumiy — unda faqat ochiq ma'lumot yotadi.
        """
        return session.client or client

    def apply(session: Session, creds, expires_at: float = 0.0,
              key: str = "") -> None:
        session.credentials = creds
        session.account_key = key or session.account_key
        session.expires_at = expires_at or session_store.StoredSession(
            token=creds.token, saved_at=time.time()).expires_at
        if demo or not creds.ok:
            session.client = None
            return
        session.client = FplClient(
            cfg.cache_dir, cfg.cache_ttl_seconds, cfg.request_delay,
            cfg.max_workers, cookie=creds.cookie, token=creds.token,
        )

    def restore(session: Session, key: str) -> bool:
        """Saqlangan sessiyani tiklaydi — kirish shart emas, kutish yo'q."""
        stored = session_store.load(data_dir, key)
        if not stored.valid:
            return False
        apply(session, auth_mod.Credentials(
            token=stored.token, cookie=stored.cookie,
            entry_id=stored.entry_id, name=stored.name,
        ), stored.expires_at, key=key)
        log.info("Saqlangan sessiya tiklandi: %s (jamoa %s, %d daqiqa qoldi)",
                 stored.name or "?", stored.entry_id, stored.seconds_left // 60)
        return True

    def adopt(session: Session, result, key: str) -> dict:
        """Muvaffaqiyatli kirishni holatga, klientga va **diskka** o'tkazadi."""
        session.last_login = result.as_dict()
        if result.ok:
            apply(session, result.credentials, key=key)
            session_store.save(
                data_dir, token=result.credentials.token,
                cookie=result.credentials.cookie,
                entry_id=result.credentials.entry_id,
                name=result.credentials.name, key=key,
            )
        return session.last_login

    def start_login_job(session: Session, email: str, password: str,
                        use_browser: bool, allow_visible: bool = True,
                        browser_only: bool = False) -> None:
        """Kirishni fonda bajaradi — sahifa kutib qolmasin.

        Diqqat: `session` ni oqimga **qiymat sifatida** beramiz. Flask ning
        `g` obyekti fon oqimida mavjud emas.
        """
        key = session_store.account_key(email) if email else (
            session.account_key or "default")

        def worker() -> None:
            try:
                if browser_only or (not email and not password):
                    adopt(session, auth_mod.login_with_browser(
                        email, password, data_dir=data_dir,
                        allow_visible=allow_visible, profile_key=key), key)
                else:
                    adopt(session, auth_mod.login(
                        email, password, getattr(cfg, "fpl_client_id", ""),
                        use_browser=use_browser, data_dir=data_dir,
                        redirect_uri=getattr(cfg, "fpl_redirect_uri", ""),
                        profile_key=key,
                    ), key)
            except Exception as exc:                 # hech qachon jim qolmasin
                log.exception("kirish")
                session.last_login = {
                    "ok": False, "stage": "kirish",
                    "detail": f"{type(exc).__name__}: {exc}",
                    "hint": "Kutilmagan xato.", "tried": [],
                }
            finally:
                session.job_running = False

        session.job_running = True
        session.job_started = time.time()
        session.last_login = None
        threading.Thread(target=worker, daemon=True).start()

    def maybe_refresh() -> None:
        """Muddati tugayotgan bo'lsa — ko'rinmas brauzerda jimgina yangilaymiz."""
        session = _S()
        if demo or session.job_running or not session.needs_refresh:
            return
        log.info("Sessiya muddati tugayapti — jimgina yangilanmoqda")
        start_login_job(session, "", "", use_browser=True, allow_visible=False)

    @app.get("/api/status")
    def status():
        maybe_refresh()
        return jsonify({
            "logged_in": _S().logged_in,
            "entry_id": _S().entry_id or cfg.entry_id,
            "public_only": bool(_S().public_entry_id and not _S().logged_in),
            "name": _S().credentials.name,
            "method": "token" if _S().credentials.token else (
                "cookie" if _S().credentials.cookie else ""
            ),
            "last_login": _S().last_login,
            "job_running": _S().job_running,
            "job_seconds": round(time.time() - _S().job_started)
                           if _S().job_running else 0,
            "seconds_left": _S().seconds_left,
            "demo": demo,
        })

    @app.post("/api/connect")
    def connect():
        """Zaxira yo'l: faqat jamoa ID. Parol yo'q, brauzer yo'q, 0 soniya.

        FPL ning ochiq API si `entry/{id}` va **deadline'dan keyingi** tarkibni
        loginsiz beradi. Shuning uchun bu asosiy yo'l EMAS: transfer
        o'ylayotgan paytda — deadline oldidan — ochiq `picks` bo'sh bo'ladi,
        jonli tarkib, aniq sotish narxlari va erkin transferlar soni esa
        faqat login bilan keladi.
        """
        body = request.get_json(silent=True) or {}
        try:
            entry_id = int(body.get("entry_id") or 0)
        except (TypeError, ValueError):
            entry_id = 0
        if entry_id <= 0:
            return jsonify({"ok": False, "hint": "Jamoa ID raqam bo'lishi kerak."}), 400
        try:
            entry = client_for(_S()).entry(entry_id)
        except Exception as exc:
            return jsonify({
                "ok": False,
                "hint": "Bunday jamoa topilmadi yoki API javob bermadi.",
                "detail": f"{type(exc).__name__}: {exc}"[:200],
            }), 404
        _S().public_entry_id = entry_id
        name = " ".join(x for x in (entry.get("player_first_name"),
                                    entry.get("player_last_name")) if x)
        return jsonify({
            "ok": True, "entry_id": entry_id, "name": name.strip(),
            "team_name": entry.get("name", ""), "public_only": True,
        })

    @app.post("/api/login")
    def login():
        body = request.get_json(silent=True) or {}
        mode = (body.get("mode") or "").strip()
        token = (body.get("token") or "").strip()
        email = (body.get("email") or "").strip()
        password = body.get("password") or ""
        session = _S()

        # --- token: bir so'rov, darrov javob beradi ---
        if token:
            key = session_store.account_key(email) if email else "token"
            payload = adopt(session, auth_mod.login_with_token(token), key)
            if payload["ok"]:
                g.set_account = key
            return jsonify(payload), (200 if payload["ok"] else 401)

        if not (email and password):
            return jsonify({"ok": False,
                            "hint": "Email va parol yoki token kerak."}), 400

        if session.job_running:
            return jsonify({"ok": False, "running": True,
                            "hint": "Oldingi urinish hali tugamadi."}), 409

        # Boshqa email — boshqa profil. Shu sababli oldingi hisob bilan
        # aralashib ketish mumkin emas.
        key = session_store.account_key(email)
        session.account_key = key
        g.set_account = key
        # "sso" — faqat DaVinci (tez, oynasiz). "browser" — faqat brauzer.
        # Aks holda: avval DaVinci, o'tmasa brauzer.
        browser_only = mode == "browser"
        use_browser = mode not in ("sso",)
        start_login_job(session, email, password, use_browser=use_browser,
                        browser_only=browser_only)
        return jsonify({
            "ok": False, "running": True,
            "hint": {
                "sso": "DaVinci orqali kirilmoqda…",
                "browser": "Brauzer orqali kirilmoqda…",
            }.get(mode, "Avval DaVinci, o'tmasa brauzer."),
        }), 202

    @app.post("/api/reconnect")
    def reconnect():
        """Parolsiz tez kirish: shu akkauntning saqlangan profili bilan, oynasiz."""
        session = _S()
        if session.job_running:
            return jsonify({"ok": False, "running": True,
                            "hint": "Urinish allaqachon ketmoqda."}), 409
        key = session.account_key or request.cookies.get("fplacct") or ""
        if not key:
            return jsonify({
                "ok": False,
                "hint": "Saqlangan profil yo'q — bir marta email va parol bilan kiring.",
            }), 400
        session.account_key = key
        # Avval diskdagi sessiyani sinaymiz: agar muddati o'tmagan bo'lsa —
        # brauzer umuman ochilmaydi va javob bir zumda keladi.
        if restore(session, key):
            g.set_account = key
            session.last_login = {"ok": True, "stage": "saqlangan",
                                  "entry_id": session.credentials.entry_id,
                                  "name": session.credentials.name,
                                  "hint": "", "detail": "diskdan tiklandi",
                                  "tried": []}
            return jsonify(session.last_login), 200
        start_login_job(session, "", "", use_browser=True, allow_visible=False)
        return jsonify({"ok": False, "running": True,
                        "hint": "Saqlangan profil bilan jimgina kirilmoqda…"}), 202

    @app.post("/api/logout")
    def logout():
        session = _S()
        key = session.account_key or "default"
        session.credentials = auth_mod.Credentials()
        session.public_entry_id = 0
        session.client = None
        session.last_login = None
        session.expires_at = 0.0
        removed = session_store.clear(data_dir, key)    # diskdan ham o'chiramiz
        g.clear_account = True
        return jsonify({"ok": True, "saqlangan_sessiya_ochirildi": removed})

    @app.get("/api/players")
    def players():
        try:
            data = snapshot(force=request.args.get("refresh") == "1")
        except Exception as exc:
            log.exception("ma'lumot olinmadi")
            return jsonify({"error": str(exc)}), 502
        return jsonify(data)

    @app.get("/api/me")
    def me():
        """Xom `my-team` javobi — tekshirish uchun."""
        entry_id = _S().entry_id or cfg.entry_id
        if not entry_id:
            return jsonify({"error": "entry_id noma'lum — login qiling"}), 401
        api = client_for(_S())
        team = api.my_team(entry_id) if hasattr(api, "my_team") else None
        if not team:
            return jsonify({
                "error": "my-team olinmadi",
                "hint": "Sessiya qabul qilinmadi yoki bot himoyasi to'sdi.",
            }), 401
        return jsonify(team)

    @app.get("/api/squad")
    def squad():
        """Tarkib + tavsiya etilgan 11 lik + har bir qaror izohi."""
        maybe_refresh()
        entry_id = _S().entry_id or cfg.entry_id
        if not entry_id:
            return jsonify({
                "error": "entry_id noma'lum",
                "hint": "Jamoa ID bering yoki kirish qiling.",
            }), 401
        with squad_lock:
            fresh = (squad_cache.get("payload") is not None
                     and squad_cache.get("entry") == entry_id
                     and (time.time() - float(squad_cache["at"])) < 120)
            if fresh and request.args.get("refresh") != "1":
                return jsonify(squad_cache["payload"])
            try:
                payload = squadview.build(client_for(_S()), cfg, entry_id)
            except Exception as exc:
                log.exception("tarkib olinmadi")
                return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 502
            squad_cache.update(payload=payload, at=time.time(), entry=entry_id)
        return jsonify(payload)

    @app.get("/api/transfers")
    def transfers():
        """Kimni sotib, kimni olish — sof foyda va hit hisobi bilan.

        Tarkibdan sekinroq: nomzodlar uchun ham batafsil tarix yuklanadi.
        Shuning uchun alohida keshlanadi.
        """
        maybe_refresh()
        entry_id = _S().entry_id or cfg.entry_id
        if not entry_id:
            return jsonify({
                "error": "entry_id noma'lum",
                "hint": "Jamoa ID bering yoki kirish qiling.",
            }), 401
        with transfer_lock:
            fresh = (transfer_cache.get("payload") is not None
                     and transfer_cache.get("entry") == entry_id
                     and (time.time() - float(transfer_cache["at"])) < 300)
            if fresh and request.args.get("refresh") != "1":
                return jsonify(transfer_cache["payload"])
            try:
                payload = transferview.build(client_for(_S()), cfg, entry_id)
            except Exception as exc:
                log.exception("transfer tahlili olinmadi")
                return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 502
            transfer_cache.update(payload=payload, at=time.time(), entry=entry_id)
        return jsonify(payload)

    @app.get("/api/pace")
    def pace():
        """Mavsum sur'ati: maqsadga nisbatan progress va birinchi o'rin bilan farq."""
        entry_id = _S().entry_id or cfg.entry_id
        if not entry_id:
            return jsonify({
                "error": "entry_id noma'lum",
                "hint": "Jamoa ID bering yoki kirish qiling.",
            }), 401
        with pace_lock:
            fresh = (pace_cache.get("payload") is not None
                     and pace_cache.get("entry") == entry_id
                     and (time.time() - float(pace_cache["at"])) < 600)
            if fresh and request.args.get("refresh") != "1":
                return jsonify(pace_cache["payload"])
            try:
                payload = paceview.build(client_for(_S()), cfg, entry_id)
            except Exception as exc:
                log.exception("sur'at olinmadi")
                return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 502
            pace_cache.update(payload=payload, at=time.time(), entry=entry_id)
        return jsonify(payload)

    @app.get("/api/draft")
    def draft():
        """Noldan 15 lik: byudjet va FPL qoidalari ichida eng yaxshisi.

        Login ham, jamoa ID ham SHART EMAS — bu yerda mavjud tarkib
        ishlatilmaydi, jamoa butunlay yangidan tuziladi.
        """
        try:
            budget = float(request.args.get("budget") or 0) or None
        except ValueError:
            budget = None
        with draft_lock:
            fresh = (draft_cache.get("payload") is not None
                     and draft_cache.get("budget") == (budget or 0.0)
                     and (time.time() - float(draft_cache["at"])) < 300)
            if fresh and request.args.get("refresh") != "1":
                return jsonify(draft_cache["payload"])
            try:
                payload = draftview.build(client_for(_S()), cfg,
                                          _S().entry_id or cfg.entry_id or 1,
                                          budget=budget)
            except Exception as exc:
                log.exception("jamoa tuzilmadi")
                return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 502
            draft_cache.update(payload=payload, at=time.time(),
                               budget=(budget or 0.0))
        return jsonify(payload)

    return app
