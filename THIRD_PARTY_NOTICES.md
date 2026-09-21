# Сторонние компоненты

Установщик для Windows и APK для Android включают компоненты других авторов. Их лицензии
разрешают распространение при условии, что эти уведомления сохраняются вместе с приложением.

| Компонент | Где используется | Лицензия | Сайт |
|---|---|---|---|
| Qt 6 / PySide6 (включая Qt Multimedia) | Windows | LGPL-3.0 | https://www.qt.io, https://doc.qt.io/qtforpython-6/licenses.html |
| FFmpeg (в составе Qt Multimedia) | Windows | LGPL-2.1+ | https://ffmpeg.org/legal.html |
| pywebview | Windows (плеер Kodik) | BSD-3-Clause | https://github.com/r0x0r/pywebview |
| pythonnet | Windows (плеер Kodik) | MIT | https://github.com/pythonnet/pythonnet |
| Microsoft Edge WebView2 (runtime/loader) | Windows (плеер Kodik) | лицензия Microsoft WebView2 | https://developer.microsoft.com/microsoft-edge/webview2/ |
| Python 3.11 | Windows | PSF License | https://docs.python.org/3/license.html |
| Capacitor (@capacitor/core, android, app) | Android | MIT | https://capacitorjs.com |
| hls.js | Android | Apache-2.0 | https://github.com/video-dev/hls.js |
| Font Awesome Free 6.7.2 | Windows и Android | иконки — CC BY 4.0, шрифты — SIL OFL 1.1, код — MIT | https://fontawesome.com/license/free |

## LGPL (Qt, PySide6, FFmpeg)
Библиотеки Qt, PySide6 и FFmpeg подключаются динамически: они лежат отдельными файлами (`.dll`, `.pyd`)
в папке установленной программы, и их можно заменить своими версиями. Исходный код этих библиотек
доступен на сайтах их авторов (ссылки выше). Полный текст LGPL-3.0: https://www.gnu.org/licenses/lgpl-3.0.html

## Данные и видео
Приложение не хранит и не распространяет видео. Каталог, описания, постеры и видеопотоки загружаются
во время работы из сторонних сервисов (AniLibria, AnimeVost, AnimeLib, Kodik, Shikimori, Pollinations)
и принадлежат их правообладателям. Названия этих сервисов упоминаются только для указания источника.
