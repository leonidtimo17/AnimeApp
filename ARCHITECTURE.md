# Архитектура AnimeApp

Две версии с одинаковыми правилами: ПК (Python + PySide6, `anime_app/`) и планшет (HTML/JS в оболочке Capacitor,
`mobile/www/`). Обе устроены одинаково — слоями, где каждый слой знает только о тех, что ниже.

```
presentation / pages, components   интерфейс: показывает данные и передаёт действия пользователя
        ↓
application / services, features   сценарии: «смотреть», «найти озвучки», «синхронизировать с Shikimori»
        ↓
domain                             правила: выбор озвучки и качества, продолжение просмотра, рекомендации
        ↓
infrastructure / core              внешний мир: HTTP, API, SQLite/localStorage/IndexedDB, картинки, сеть
```

## 1. Слои и их ответственность

| Слой | ПК | Планшет | Что можно | Чего нельзя |
|---|---|---|---|---|
| core | `anime_app/core/` | `js/core/{errors,events,cache}`, `js/utils/` | ошибки, кэш LRU+TTL, адреса, сроки кэша, журнал, форматирование | Qt/DOM, бизнес-правила |
| domain | `anime_app/domain/` | `js/domain/` | чистые функции и простые классы правил | сеть, база, Qt, DOM |
| infrastructure | `anime_app/infrastructure/` | `js/core/{api,network,state}` | HTTP, API сервисов, хранилища, замер скорости | знать об интерфейсе |
| application | `anime_app/application/` | `js/services/`, `js/features/*` (логика) | сценарии, связывающие правила и данные | рисовать интерфейс (ПК) |
| presentation | `anime_app/presentation/` | `js/pages/`, `js/components/`, `js/features/*` (UI) | виджеты, страницы, плеер | SQL, прямые запросы к API, решения о кэше и повторах |

Правила слоёв проверяются тестом `tests/test_architecture.py`: domain и core не импортируют Qt и другие слои,
infrastructure и application не импортируют интерфейс, интерфейс не трогает базу, замер скорости вызывается только из
NetworkService (и одной кнопки «Проверить скорость»).

Точка сборки зависимостей — `anime_app/app.py` (ПК) и `js/app/bootstrap.js` (планшет): только там создаются сервисы
и связываются слои. Экраны получают готовый `AppContext` (ПК) или импортируют модули-сервисы (планшет).

## 2. Где бизнес-логика

`domain/` — всё, что можно проверить без сети и интерфейса:

- `titles` — сопоставление названий между каталогами («Mushoku Tensei III» = «… 3»), поисковые запросы;
- `episodes` — единый формат серии, продолжение просмотра (`resume_target`), объединение серий разных озвучек;
- `dubs` — порядок озвучек, выбор по умолчанию (сохранённая → любимая → встроенный плеер);
- `quality` — качество по скорости, понижение при подгрузках (`QualityPolicy`);
- `upcoming`, `franchise` — предстоящие серии, сезоны и фильмы;
- `taste` — профиль вкуса, оценка кандидатов, разбор ответа ИИ;
- `library` (ПК) — статусы и правило «серия просмотрена»; `shikimori` — статусы Shikimori и разметка комментариев;
- `sleep_timer` (ПК; на планшете — `features/player/sleep-timer.js`).

Сценарии, которым нужны данные, — в `application/` (ПК) и `services/` + `features/` (планшет):
`SourceResolver` / `services/sources.js` (поиск озвучек во всех источниках), `PlaybackService` / `features/player/launch.js`
(сценарий «Смотреть»), `SearchSession` / `features/search/search-session.js`, `RecommendationService`,
`ShikimoriAccount` / `services/shiki.js`, `LibraryService` и `ProgressService`, `BackupService`.

## 3. Где API

- ПК: `infrastructure/http/client.py` — `HttpClient`; клиенты сервисов в `infrastructure/api/`:
  `anilibria.py` (каталог, релизы, зеркала), `shikimori.py` (каталог, франшизы, комментарии, OAuth),
  `sources.py` (AnimeLib, AnimeVost, YummyAnime, AniSkip — поиск тайтла и разбор серий), `ai.py` (Ollama, Pollinations).
- Планшет: `js/core/api/http.js` — `request()`; `js/core/api/anilibria.js`; остальные источники — `js/services/sources.js`,
  Shikimori — `js/services/shiki.js`.

Клиенты API только отправляют запросы и превращают ответы в формат приложения; об интерфейсе они не знают.

## 4. Где база данных

- ПК: `infrastructure/database/connection.py` — одно соединение SQLite (WAL, `synchronous=NORMAL`), схема и миграции;
  `repositories.py` — `AnimeRepository`, `LibraryRepository`, `ProgressRepository`, `SettingsRepository`,
  `HttpCacheRepository`. Файл `library.db` совместим со всеми прошлыми версиями (добавлены только индексы).
  Интерфейс работает с базой только через сервисы `LibraryService`, `ProgressService`, `Preferences`.
- Планшет: `js/core/state/store.js` — данные пользователя в localStorage (ключ `animeapp:v1`, формат прежний).

## 5. Где кэш

| Что | ПК | Планшет | Срок |
|---|---|---|---|
| Ответы API в памяти | `HttpClient.memory` (LRU, ≤200 записей, ≤16 МБ) | `http.js` memory (LRU, ≤8 МБ) | как у записи |
| Ответы API на диске | таблица `http_cache` (чистка старше 14 дней) | IndexedDB `animeapp-cache` (≤600 записей) | `core/config.TTL` / `anilibria.TTL` |
| Офлайн | последний сохранённый ответ любой давности | то же | — |
| Постеры | `QNetworkDiskCache` 500 МБ + память ≤64 МБ + готовые обрезанные копии ≤48 МБ | кэш WebView | — |
| Найденные озвучки, серии, франшизы, темы | `TTLCache` 30–60 мин, ограничены по числу | `MemoryCache`, так же | 30–60 мин |

Сроки: справочники и франшизы — сутки, карточки Shikimori и поиск — час, каталог — 10 мин, свежие серии — 5 мин,
карточка релиза — 2 мин. Ссылки на видео не кэшируются (`TTL.PLAYER_SOURCE = 0`): они привязаны к сети и VPN.

## 6. Сеть и состояние сети

`HttpClient` / `request()`:
- один менеджер соединений на приложение (keep-alive);
- таймаут у каждого запроса;
- одинаковые GET-запросы в пути объединяются;
- повтор только временных ошибок (обрыв, 429/502/503/504) с паузой 0.6 → 1.2 → … с;
- отмена: у экрана есть `RequestScope` (ПК) или `AbortSignal` навигации (планшет). Запрос прерывается, только когда
  его результат не нужен никому: если его ждут другие части приложения, он доработает и попадёт в кэш.

**NetworkService** (`infrastructure/network/service.py`, `js/core/network/network.js`) хранит `NetworkState`:
`is_online`, `bandwidth_mbps`, `checked_at`, `measuring`.

```
запуск → главная загрузила «свежие серии» → постеры догрузились → ОДИН замер скорости
       → NetworkState.bandwidth → плеер выбирает качество
```

- Скорость меряется **один раз за запуск**: два сегмента HLS последней серии свежего релиза (тот же запрос, что у главной),
  после «разгона» соединения. Результат сохраняется и доступен сразу при следующем запуске, пока идёт новый замер.
- Больше приложение скорость само не меряет: ни по таймеру, ни перед серией, ни во время просмотра, ни при смене сети.
  Повторный замер — только кнопкой «Качество → Проверить скорость интернета».
- «Есть ли интернет» узнаём без замеров: `QNetworkInformation` / события `online`/`offline` и результаты настоящих запросов.
- Смена сети (событие ОС) снимает потолок качества и ускоряет проверку, идёт ли видео, — без замера скорости.

## 7. Плеер

ПК (`presentation/player/`):
- `window.py` — `PlayerWindow`: раскладка страницы просмотра, события, горячие клавиши, полный экран, мини-плеер;
- `domain/quality.QualityPolicy` — какое качество включить: по сохранённой скорости, понижение при подгрузках и ошибках;
- `watchdog.py` — `PlaybackWatchdog`: видео «встало» → переподключение. Он не делает запросов и работает, только пока
  видео играет. Прогресс тоже сохраняется только во время воспроизведения (раз в 5 с);
- `seekbar.py`, `video_view.py`, `menus.py`, `watch_ui.py` (блок под видео и список серий, кадры грузятся только
  для видимых строк), `comments_panel.py`;
- `kodik_page.py` + `webplayer.py` — плеер Kodik в отдельном процессе (WebView2), встроенный в окно.

Планшет (`js/features/player/`):
- `player.js` — страница просмотра;
- `native-player.js` (HLS через hls.js, mp4) и `kodik-player.js`;
- `launch.js` — сценарий «Смотреть»;
- `menus.js`, `hotkeys.js`, `gestures.js`, `sleep-timer.js`;
- таймеры (сторож, сохранение прогресса, таймер сна) работают, только пока нужны, и снимаются при закрытии плеера.

Для HLS встроенный плеер собирает общий плейлист из всех качеств: hls.js сам меняет качество по фактической загрузке
сегментов видео, без отдельных замеров.

## 8. Состояние интерфейса (планшет)

- **Данные пользователя** — только в `store.js`. Меняются только его функциями; подписка `subscribe()` (для интерфейса)
  и `onChange()` (для Shikimori) возвращает функцию отписки.
- **Состояние сети** — только в `NetworkService` (`app/network.js`), подписка `subscribe()`.
- **Кэш** — в `http.js` и `services/sources.js`, экраны его не трогают.
- **Состояние экрана** живёт в замыкании страницы и исчезает вместе с ней. Навигация (`app/router.js`) даёт странице
  `nav.signal` и `nav.onCleanup()`: при уходе запросы отменяются, таймеры и обработчики снимаются.
- **Состояние плеера** — внутри `native-player`/`kodik-player`, наружу — через объект управления (`ep`, `time`, `seek`, `go`).

## 9. Как добавить новую функцию

1. Правило, которое можно проверить без сети, — функцией в `domain/` с тестом (`tests/test_domain.py`,
   `mobile/tests/domain.test.mjs`).
2. Запрос к новому API — метод клиента в `infrastructure/api/` (ПК) или функция с `request()` в `services/` (планшет);
   укажите `cache_ttl`/`ttl`, если ответ можно кэшировать.
3. Сценарий, связывающий правило и данные, — сервис в `application/` (ПК) или модуль в `features/<имя>/` (планшет).
   Ему передаются зависимости, а не весь контекст. Долгие операции — асинхронно, с обратным вызовом или Promise.
4. Экран: ПК — класс-наследник `Page` в `presentation/pages/`, регистрация в `main_window.py`;
   планшет — функция `(view, arg, nav)` в `js/pages/`, регистрация в `app/bootstrap.js`. Запросы передают `scope` /
   `nav.signal`, ошибки показываются через `widgets/states.error_text` / `components/StateView.showError`.
5. Сервис создаётся в `app.py` (ПК) и добавляется в `Services`/`AppContext`.

## 10. Как добавить компонент

- ПК: виджет в `presentation/widgets/`. Цвета и радиусы — из `presentation/theme.py`, стиль — через `setObjectName`
  и правило в `QSS`, а не `setStyleSheet` на месте. Картинки — `ctx.images.load_cover(url, w, h, radius, self, cb)`.
- Планшет: модуль в `js/components/` с функцией, возвращающей разметку, и (если нужно) одним обработчиком событий
  на контейнер (как `AnimeCard.renderCards`). Стили — в `css/components.css` с токенами из `css/tokens.css`.
  Один тип кнопки — один класс: `.btn`, `.chip`, `.pl-btn`. Картинки — `LazyImage.lazyImg()`.

## Тесты

- ПК: `python -m pytest` — правила, база (SQLite во временной папке), HttpClient против локального HTTP-сервера
  (объединение запросов, отмена, повторы, кэш, офлайн), NetworkService (один замер), разбор ответов источников,
  сервисы, архитектурные правила.
- Планшет: `cd mobile && npm test` — кэш, HTTP (объединение, отмена, повторы), NetworkService, правила, поиск,
  хранилище, разбор ответов источников.
