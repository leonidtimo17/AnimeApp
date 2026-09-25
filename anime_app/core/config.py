"""Адреса сервисов, сроки свежести кэша, таймауты и пути к файлам программы — в одном месте."""
import os

PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # anime_app/
PROJECT_DIR = os.path.dirname(PACKAGE_DIR)                                   # рядом лежат main.py, TERMS.md
ASSETS_DIR = os.path.join(PACKAGE_DIR, "assets")
FONTS_DIR = os.path.join(ASSETS_DIR, "fonts")

USER_AGENT = "AnimeApp/1.0 (desktop)"

# Все API публичные и бесплатные, ключи не нужны.
ANILIBRIA_MIRRORS = ["https://anilibria.top", "https://api.anilibria.app"]
ANILIBRIA_MEDIA = "https://anilibria.top"      # относительные пути кадров серий
SHIKI = "https://shikimori.io"
ANIMELIB_API = "https://api.cdnlibs.org/api"
ANIMELIB_HEADERS = {"Site-Id": "5"}
ANIMEVOST_API = "https://api.animetop.info/v1"
YANI_API = "https://api.yani.tv"
ANISKIP_API = "https://api.aniskip.com/v2/skip-times"
OLLAMA = "http://localhost:11434"
POLLINATIONS = "https://text.pollinations.ai/"

REQUEST_TIMEOUT_MS = 20_000


class TTL:
    """Сколько секунд ответ считается свежим. Без интернета отдаётся последний сохранённый ответ любой давности.

    Долго живут справочники и метаданные тайтлов, коротко — то, что часто меняется.
    Ссылки на видео (релиз для плеера) не кэшируются вовсе: они привязаны к сети/VPN и устаревают.
    """
    REFERENCES = 86_400          # жанры, годы
    FRANCHISE = 86_400           # граф франшизы, «Похожее»
    SHIKI_ANIME = 3_600          # карточка тайтла Shikimori, темы обсуждений
    SEARCH = 3_600               # поиск по каталогам и источникам
    CATALOG = 600
    SCHEDULE = 900
    LATEST = 300
    RELEASE = 120                # карточка релиза AniLibria (для страницы тайтла)
    VOST_PLAYLIST = 900
    YANI_VIDEOS = 1_800
    ANISKIP = 7 * 86_400
    SHIKI_USER_STATS = 300
    PLAYER_SOURCE = 0            # ссылки на поток — всегда свежие


class MemoryTTL:
    """Сроки жизни кэшей в памяти (вычисленные данные, которых нет в HTTP-кэше)."""
    DUBS = 1_800                 # найденные озвучки тайтла
    EPISODES = 1_800             # серии озвучки
    FRANCHISE = 3_600
    TOPICS = 3_600
