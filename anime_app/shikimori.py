"""Связь с Shikimori (по желанию пользователя).

- вход через OAuth: браузер → пользователь разрешает доступ → копирует код → вставляет в приложение;
- статусы, оценки и просмотренные серии отправляются в список пользователя на Shikimori
  (там строится его статистика);
- обсуждения серий — комментарии Shikimori: читать может каждый, писать — после входа.

Ключи OAuth-приложения — в shiki_config.py (не хранится в git, см. shiki_config.example.py).
"""
import html
import re
import time
import urllib.parse

from PySide6.QtCore import QObject, QTimer, Signal

from .sources import SHIKI, SHIKI_OFFSET, Sources

try:
    from . import shiki_config as _cfg
    CONFIG = {"id": _cfg.CLIENT_ID, "secret": _cfg.CLIENT_SECRET, "app": getattr(_cfg, "APP_NAME", "AnimeApp")}
    if not CONFIG["id"]:
        CONFIG = None
except ImportError:
    CONFIG = None

REDIRECT = "urn:ietf:wg:oauth:2.0:oob"
SCOPE = "user_rates comments"
TO_SHIKI = {"planned": "planned", "watching": "watching", "completed": "completed",
            "postponed": "on_hold", "dropped": "dropped"}
FROM_SHIKI = {"planned": "planned", "watching": "watching", "rewatching": "watching", "completed": "completed",
              "on_hold": "postponed", "dropped": "dropped"}


class Shikimori(QObject):
    changed = Signal()   # вошли/вышли/изменились настройки

    def __init__(self, api, db, parent=None):
        super().__init__(parent)
        self.api = api
        self.db = db
        self._timers = {}
        self._topics = {}
        db.listeners.append(self._on_db_change)

    # ================================================================ вход
    @property
    def configured(self):
        return CONFIG is not None

    def _auth(self):
        return self.db.setting("shiki_auth") or {}

    def user(self):
        return self._auth().get("user")

    def logged_in(self):
        return bool(self._auth().get("access"))

    def sync_on(self):
        return self.logged_in() and self.db.setting("shiki_sync", True)

    def set_sync(self, on):
        self.db.set_setting("shiki_sync", bool(on))
        self.changed.emit()

    def authorize_url(self):
        return (f"{SHIKI}/oauth/authorize?client_id={urllib.parse.quote(CONFIG['id'])}"
                f"&redirect_uri={urllib.parse.quote(REDIRECT)}&response_type=code&scope={urllib.parse.quote(SCOPE)}")

    def _token(self, form, on_ok, on_err):
        def ok(d):
            if not d.get("access_token"):
                on_err("Shikimori не выдал доступ")
                return
            on_ok({"access": d["access_token"], "refresh": d.get("refresh_token"),
                   "expires": time.time() + (d.get("expires_in") or 86400)})
        self.api.fetch(f"{SHIKI}/oauth/token", None, ok, on_err, headers={"User-Agent": CONFIG["app"]},
                       form={"client_id": CONFIG["id"], "client_secret": CONFIG["secret"], "redirect_uri": REDIRECT,
                             **form})

    def login(self, code, on_ok, on_err):
        def got(tok):
            self.db.set_setting("shiki_auth", tok)

            def me(u):
                tok["user"] = {"id": u["id"], "nickname": u.get("nickname"), "avatar": u.get("avatar")}
                self.db.set_setting("shiki_auth", tok)
                self.changed.emit()
                on_ok(tok["user"])
            self.call("/api/users/whoami", me, on_err)
        self._token({"grant_type": "authorization_code", "code": code.strip()}, got, on_err)

    def logout(self):
        self.db.set_setting("shiki_auth", None)
        self.changed.emit()

    def call(self, path, on_ok, on_err=None, params=None, json_body=None, method=None):
        """Запрос от имени пользователя; просроченный токен обновляется сам."""
        on_err = on_err or (lambda _m: None)
        a = self._auth()
        if not a.get("access"):
            on_err("Вы не вошли в Shikimori")
            return

        def send(a):
            self.api.fetch(f"{SHIKI}{path}", params, on_ok, on_err, json_body=json_body, method=method,
                           headers={"Authorization": f"Bearer {a['access']}", "User-Agent": CONFIG["app"]})
        if a.get("expires", 0) - 60 > time.time():
            send(a)
            return

        def refreshed(tok):
            new = {**a, **tok}
            self.db.set_setting("shiki_auth", new)
            send(new)

        def failed(msg):
            if str(msg).startswith("HTTP 4"):
                self.logout()   # доступ отозван
            on_err(msg)
        self._token({"grant_type": "refresh_token", "refresh_token": a.get("refresh")}, refreshed, failed)

    # ================================================================ список и прогресс
    def sid_of(self, anime_id):
        if anime_id >= SHIKI_OFFSET:
            return anime_id - SHIKI_OFFSET
        rel = self.db.cached_release(anime_id) or {}
        return (rel.get("shikimori") or {}).get("id")

    def _watched_count(self, anime_id):
        n = 0
        for p in self.db.progress_for(anime_id).values():
            o = p.get("ordinal")
            if p.get("watched") and o is not None and float(o) == int(float(o)):
                n = max(n, int(float(o)))
        return n

    def _on_db_change(self, _kind, anime_id):
        if not self.sync_on() or not self.sid_of(anime_id):
            return
        # Небольшая задержка: несколько изменений подряд уходят одним запросом
        t = self._timers.get(anime_id)
        if t is None:
            t = QTimer(self, singleShot=True, interval=2500)
            t.timeout.connect(lambda aid=anime_id: self.push(aid))
            self._timers[anime_id] = t
        t.start()

    def push(self, anime_id, done=None):
        """Отправить статус, оценку и число просмотренных серий. done(ok: bool)."""
        done = done or (lambda _ok: None)
        sid, me = self.sid_of(anime_id), self.user()
        if not sid or not me:
            done(False)
            return
        entry = self.db.library_entry(anime_id)
        eps = self._watched_count(anime_id)

        def got(rates):
            rate = (rates or [None])[0]
            if not rate and not entry.get("status") and not eps and not entry.get("score"):
                done(False)
                return
            body = {"episodes": max((rate or {}).get("episodes") or 0, eps),   # не уменьшаем
                    "status": TO_SHIKI.get(entry.get("status")) or (rate or {}).get("status")
                    or ("watching" if eps else "planned")}
            if entry.get("score"):
                body["score"] = entry["score"]
            if rate:
                self.call(f"/api/v2/user_rates/{rate['id']}", lambda _d: done(True), lambda _e: done(False),
                          json_body={"user_rate": body}, method="PATCH")
            else:
                body.update(user_id=me["id"], target_id=sid, target_type="Anime")
                self.call("/api/v2/user_rates", lambda _d: done(True), lambda _e: done(False),
                          json_body={"user_rate": body})
        self.call("/api/v2/user_rates", got, lambda _e: done(False),
                  params={"user_id": me["id"], "target_id": sid, "target_type": "Anime"})

    def push_all(self, on_step, on_done):
        ids = [i for i in self.db.tracked_ids() if self.sid_of(i)]
        state = {"i": 0, "ok": 0}

        def nxt(ok=None):
            if ok:
                state["ok"] += 1
            if state["i"] >= len(ids):
                on_done(state["ok"])
                return
            aid = ids[state["i"]]
            state["i"] += 1
            on_step(state["i"], len(ids))
            self.push(aid, nxt)
        nxt()

    def import_list(self, on_done, on_err):
        """Статусы и оценки с Shikimori → «Моя библиотека»."""
        me = self.user()

        def got(rates):
            n = 0
            for r in rates or []:
                a = r.get("anime") or {}
                if not a.get("id"):
                    continue
                item = Sources.shiki_item(a)
                aid = self._local_id(a["id"]) or item["id"]
                if not self.db.cached_release(aid):
                    self.db.cache_anime(item["release"], item["poster"], item["subtitle"], full=True)
                self.db.set_entry_quiet(aid, FROM_SHIKI.get(r.get("status")), r.get("score") or None)
                n += 1
            on_done(n)
        self.call(f"/api/users/{me['id']}/anime_rates", got, on_err, params={"limit": 5000})

    def _local_id(self, sid):
        for aid in self.db.tracked_ids():
            if aid < SHIKI_OFFSET and self.sid_of(aid) == sid:
                return aid
        return None

    # ================================================================ обсуждения
    def topic(self, sid, ordinal, on_ok):
        """on_ok({"id", "episode": bool}) — тема серии, а если её нет — общая тема тайтла; или None."""
        key = (sid, ordinal)
        if key in self._topics:
            on_ok(self._topics[key])
            return

        def done(t):
            self._topics[key] = t
            on_ok(t)

        def whole():
            self.anime_topic(sid, done)
        o = float(ordinal or 0)
        if o != int(o):
            whole()
            return

        def got(items):
            t = (items or [None])[0]
            if t and t.get("id") and int(t.get("episode") or 0) == int(o):
                done({"id": t["id"], "episode": True})
            else:
                whole()
        self.api.fetch(f"{SHIKI}/api/animes/{sid}/topics", {"kind": "episode", "episode": int(o), "limit": 1},
                       got, lambda _e: whole(), cache_ttl=3600)

    def anime_topic(self, sid, on_ok):
        self.api.fetch(f"{SHIKI}/api/animes/{sid}", None,
                       lambda a: on_ok({"id": a["topic_id"], "episode": False} if a.get("topic_id") else None),
                       lambda _e: on_ok(None), cache_ttl=3600)

    def comments(self, topic_id, page, on_ok, on_err):
        self.api.fetch(f"{SHIKI}/api/comments", {"commentable_id": topic_id, "commentable_type": "Topic",
                                                  "page": page, "limit": 30, "desc": 1}, on_ok, on_err)

    def post_comment(self, topic_id, body, on_ok, on_err):
        self.call("/api/comments", on_ok, on_err,
                  json_body={"comment": {"body": body, "commentable_id": topic_id, "commentable_type": "Topic"}})


def render_body(body):
    """BBCode комментария → простой безопасный HTML (без чужой разметки). Время 12:34 — ссылка t:<сек>."""
    s = html.escape(body or "")
    s = re.sub(r"\[(b|i|u|s)\]([\s\S]*?)\[/\1\]", r"<\1>\2</\1>", s, flags=re.I)
    s = re.sub(r"\[spoiler(?:=[^\]]*)?\]([\s\S]*?)\[/spoiler\]",
               r'<span style="background:#3a3a44;color:#3a3a44">\1</span>', s, flags=re.I)
    s = re.sub(r"\[quote(?:=[^\]]*)?\]([\s\S]*?)\[/quote\]",
               r'<div style="color:#9a9aa6;margin:4px 0 4px 8px">«\1»</div>', s, flags=re.I)
    s = re.sub(r"\[comment=[^\]]*\]([\s\S]*?)\[/comment\]", r"@\1", s, flags=re.I)
    s = re.sub(r"\[(?:url|character|person|anime|manga|ranobe|user)=[^\]]*\]([\s\S]*?)"
               r"\[/(?:url|character|person|anime|manga|ranobe|user)\]", r"\1", s, flags=re.I)
    s = re.sub(r"\[(?:image|poster|img)[^\]]*\](?:[\s\S]*?\[/(?:img|poster)\])?", "🖼", s, flags=re.I)
    s = re.sub(r"\[replies=[^\]]*\]", "", s, flags=re.I)
    s = re.sub(r"\[/?[a-z_]+(?:=[^\]]*)?\]", "", s, flags=re.I)

    def ts(m):
        sec = 0
        for x in m.group(2).split(":"):
            sec = sec * 60 + int(x)
        return f'{m.group(1)}<a href="t:{sec}" style="color:#ff6a1a;font-weight:700;text-decoration:none">{m.group(2)}</a>'
    s = re.sub(r"(^|[^\d:])(\d{1,2}:\d{2}(?::\d{2})?)(?![\d:])", ts, s)
    return s.replace("\n", "<br>")
