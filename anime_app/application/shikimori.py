"""Связь с Shikimori (по желанию пользователя).

- вход через OAuth: браузер → пользователь разрешает доступ → копирует код → вставляет в приложение;
- статусы, оценки и просмотренные серии отправляются в список пользователя на Shikimori
  (там строится его статистика);
- обсуждения серий — комментарии Shikimori: читать может каждый, писать — после входа.

Ключи OAuth-приложения — в anime_app/shiki_config.py (не хранится в git, см. shiki_config.example.py).
"""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.cache import TTLCache
from ..core.config import MemoryTTL
from ..core.errors import AppError, AuthenticationError
from ..core.logging import get_logger
from ..domain.ids import SHIKI_OFFSET
from ..domain.library import watched_count
from ..domain.shikimori import FROM_SHIKI, comment_body, rate_update
from ..infrastructure.api.shikimori import ShikimoriApi, shiki_item
from ..infrastructure.database.repositories import AnimeRepository
from .library import LibraryService, Preferences, ProgressService

log = get_logger("shikimori")
PUSH_DELAY_MS = 2500   # несколько изменений подряд уходят одним запросом


def load_config() -> dict | None:
    try:
        from .. import shiki_config as cfg
    except ImportError:
        return None
    if not getattr(cfg, "CLIENT_ID", ""):
        return None
    return {"id": cfg.CLIENT_ID, "secret": cfg.CLIENT_SECRET, "app": getattr(cfg, "APP_NAME", "AnimeApp"),
            # Должен в точности совпадать с Redirect URI приложения на Shikimori
            "redirect": getattr(cfg, "REDIRECT_URI", "urn:ietf:wg:oauth:2.0:oob")}


class ShikimoriAccount(QObject):
    changed = Signal()   # вошли/вышли/изменились настройки

    def __init__(self, api: ShikimoriApi, prefs: Preferences, library: LibraryService, progress: ProgressService,
                 anime: AnimeRepository, config: dict | None = None, parent=None):
        super().__init__(parent)
        self.api = api
        self.prefs = prefs
        self.library = library
        self.progress = progress
        self.anime = anime
        self.config = config
        self._timers: dict[int, QTimer] = {}
        self._topics: TTLCache[tuple, dict | None] = TTLCache(max_size=200, default_ttl=MemoryTTL.TOPICS)
        library.entry_changed.connect(self._entry_changed)
        progress.episode_changed.connect(lambda aid: self._schedule_push(aid))

    # ================================================================ вход
    @property
    def configured(self) -> bool:
        return self.config is not None

    def _auth(self) -> dict:
        return self.prefs.get("shiki_auth") or {}

    def user(self):
        return self._auth().get("user")

    def logged_in(self) -> bool:
        return bool(self._auth().get("access"))

    def sync_on(self) -> bool:
        return self.logged_in() and self.prefs.get("shiki_sync", True)

    def set_sync(self, on) -> None:
        self.prefs.set("shiki_sync", bool(on))
        self.changed.emit()

    def authorize_url(self) -> str:
        return self.api.authorize_url(self.config["id"], self.config["redirect"])

    def _token(self, form, on_ok, on_err):
        def ok(d):
            if not d.get("access_token"):
                on_err(AuthenticationError("Shikimori не выдал доступ"))
                return
            on_ok({"access": d["access_token"], "refresh": d.get("refresh_token"),
                   "expires": time.time() + (d.get("expires_in") or 86400)})
        self.api.token({"client_id": self.config["id"], "client_secret": self.config["secret"],
                        "redirect_uri": self.config["redirect"], **form}, self.config["app"], ok, on_err)

    def login(self, code, on_ok, on_err):
        def got(tok):
            self.prefs.set("shiki_auth", tok)

            def me(u):
                tok["user"] = {"id": u["id"], "nickname": u.get("nickname"), "avatar": u.get("avatar")}
                self.prefs.set("shiki_auth", tok)
                self.changed.emit()
                on_ok(tok["user"])
            self.call("/api/users/whoami", me, on_err)
        self._token({"grant_type": "authorization_code", "code": code.strip()}, got, on_err)

    def logout(self):
        self.prefs.set("shiki_auth", None)
        self.changed.emit()

    def call(self, path, on_ok, on_err=None, params=None, json_body=None, method=None):
        """Запрос от имени пользователя; просроченный токен обновляется сам."""
        on_err = on_err or (lambda err: log.info("Shikimori %s: %s", path, err))
        a = self._auth()
        if not a.get("access"):
            on_err(AuthenticationError("Вы не вошли в Shikimori"))
            return

        def send(a):
            self.api.authorized(path, a["access"], self.config["app"], on_ok, on_err, params=params,
                                json_body=json_body, method=method)
        if a.get("expires", 0) - 60 > time.time():
            send(a)
            return

        def refreshed(tok):
            new = {**a, **tok}
            self.prefs.set("shiki_auth", new)
            send(new)

        def failed(err: AppError):
            if getattr(err, "is_client_error", False):
                log.warning("Доступ к Shikimori отозван — выходим")
                self.logout()
            on_err(err)
        self._token({"grant_type": "refresh_token", "refresh_token": a.get("refresh")}, refreshed, failed)

    # ================================================================ список и прогресс
    def sid_of(self, anime_id) -> int | None:
        anime_id = int(anime_id)
        if anime_id >= SHIKI_OFFSET:
            return anime_id - SHIKI_OFFSET
        rel = self.anime.release(anime_id) or {}
        return (rel.get("shikimori") or {}).get("id")

    def _entry_changed(self, kind: str, anime_id: int) -> None:
        if kind in ("status", "score"):     # избранное на Shikimori не отправляется
            self._schedule_push(anime_id)

    def _schedule_push(self, anime_id: int) -> None:
        if not self.sync_on() or not self.sid_of(anime_id):
            return
        t = self._timers.get(anime_id)
        if t is None:
            t = QTimer(self, singleShot=True, interval=PUSH_DELAY_MS)
            t.timeout.connect(lambda aid=anime_id: self._push_scheduled(aid))
            self._timers[anime_id] = t
        t.start()

    def _push_scheduled(self, anime_id: int) -> None:
        timer = self._timers.pop(anime_id, None)    # таймер одноразовый — не копим их весь сеанс
        if timer is not None:
            timer.deleteLater()
        self.push(anime_id)

    def push(self, anime_id, done=None):
        """Отправить статус, оценку и число просмотренных серий. done(ok: bool)."""
        done = done or (lambda _ok: None)
        sid, me = self.sid_of(anime_id), self.user()
        if not sid or not me:
            done(False)
            return
        entry = self.library.entry(anime_id)
        eps = watched_count(self.progress.for_anime(anime_id))

        def got(rates):
            rate = (rates or [None])[0]
            body = rate_update(entry, eps, rate)
            if body is None:
                done(False)
                return
            fail = lambda err: (log.info("Не удалось отправить на Shikimori: %s", err), done(False))  # noqa: E731
            if rate:
                self.call(f"/api/v2/user_rates/{rate['id']}", lambda _d: done(True), fail,
                          json_body={"user_rate": body}, method="PATCH")
            else:
                body.update(user_id=me["id"], target_id=sid, target_type="Anime")
                self.call("/api/v2/user_rates", lambda _d: done(True), fail, json_body={"user_rate": body})
        self.call("/api/v2/user_rates", got, lambda _e: done(False),
                  params={"user_id": me["id"], "target_id": sid, "target_type": "Anime"})

    def rate(self, sid, cb):
        """Моя запись об этом тайтле на Shikimori: cb({episodes, status, score}) или cb(None)."""
        me = self.user()
        if not sid or not me:
            cb(None)
            return
        self.call("/api/v2/user_rates", lambda rates: cb((rates or [None])[0]), lambda _e: cb(None),
                  params={"user_id": me["id"], "target_id": sid, "target_type": "Anime"})

    def stats(self, cb):
        """Статистика профиля: {статус: сколько тайтлов}."""
        me = self.user()
        if not me:
            cb(None)
            return
        self.api.user(me["id"], lambda u: cb({s["name"]: s["size"] for s in
                                              ((u.get("stats") or {}).get("statuses") or {}).get("anime") or []}),
                      lambda _e: cb(None))

    def pull_progress(self, anime_id, episodes, cb=None):
        """Серии, отмеченные на Shikimori, отмечаем и здесь — чтобы продолжить с нужной."""
        cb = cb or (lambda _n: None)
        if not self.sync_on():
            cb(0)
            return

        def got(rate):
            seen = (rate or {}).get("episodes") or 0
            cb(self.progress.mark_watched_quiet(anime_id, episodes, seen) if seen else 0)
        self.rate(self.sid_of(anime_id), got)

    def push_all(self, on_step, on_done):
        ids = [i for i in self.library.tracked_ids() if self.sid_of(i)]
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
            # {id Shikimori: наш id} — один запрос вместо поиска по всем тайтлам для каждой записи
            local = {sid: aid for aid, sid in self.anime.shiki_ids().items() if aid < SHIKI_OFFSET}
            n = 0
            with self.anime.db.transaction():
                for r in rates or []:
                    a = r.get("anime") or {}
                    if not a.get("id"):
                        continue
                    item = shiki_item(a)
                    aid = local.get(a["id"]) or item["id"]
                    if not self.anime.release(aid):
                        self.anime.save(item["release"], item["poster"], item["subtitle"], full=True)
                    self.library.import_entry(aid, FROM_SHIKI.get(r.get("status")), r.get("score") or None)
                    n += 1
            self.library.changed.emit()
            on_done(n)
        self.call(f"/api/users/{me['id']}/anime_rates", got, on_err, params={"limit": 5000})

    # ================================================================ обсуждения
    def topic(self, sid, ordinal, on_ok):
        """on_ok({"id", "episode": bool}) — тема серии, а если её нет — общая тема тайтла; или None."""
        key = (sid, ordinal)
        if key in self._topics:
            on_ok(self._topics.get(key))
            return

        def done(t):
            self._topics.set(key, t)
            on_ok(t)

        o = float(ordinal or 0)
        if o != int(o):
            self.anime_topic(sid, done)
            return

        def got(items):
            t = (items or [None])[0]
            if t and t.get("id") and int(t.get("episode") or 0) == int(o):
                done({"id": t["id"], "episode": True})
            else:
                self.anime_topic(sid, done)
        self.api.episode_topic(sid, int(o), got, lambda _e: self.anime_topic(sid, done))

    def anime_topic(self, sid, on_ok):
        self.api.anime(sid, lambda a: on_ok({"id": a["topic_id"], "episode": False} if a.get("topic_id") else None),
                       lambda _e: on_ok(None))

    def comments(self, topic_id, page, on_ok, on_err, scope=None):
        return self.api.comments(topic_id, page, on_ok, on_err, scope=scope)

    def post_comment(self, topic_id, text, *, episode_label, moment, spoiler, on_ok, on_err):
        body = comment_body(text, episode_label=episode_label, moment=moment, spoiler=spoiler)
        self.call("/api/comments", on_ok, on_err,
                  json_body={"comment": {"body": body, "commentable_id": topic_id, "commentable_type": "Topic"}})
