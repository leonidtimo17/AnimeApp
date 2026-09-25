// Модели приложения — то, с чем работает интерфейс. Сырые ответы API (AniLibria, AnimeLib, Kodik, YummyAnime…)
// превращаются в них в services/*, и больше нигде их структура не нужна.

/**
 * Серия (ключ — номер серии: прогресс общий для всех озвучек).
 * @typedef {{key: string, ordinal: number, name?: string|null, duration?: number|null,
 *   opening?: {start: number, stop: number}|null, ending?: {start: number, stop: number}|null,
 *   streams?: Record<string, string>|null,   // встроенный плеер: качество → ссылка HLS/mp4
 *   animelib?: number|null,                  // серия в AnimeLib (ссылка Kodik — по запросу)
 *   kodik?: string|null,                     // готовая ссылка Kodik (YummyAnime)
 *   preview?: string|null}} Episode
 */

/**
 * Озвучка или субтитры.
 * @typedef {{id: string, name: string, kind: "voice"|"sub", native: boolean}} Translation
 */

/**
 * Откуда играть серию.
 * @typedef {{kind: "iframe"|"hls"|"mp4", url: string, team?: string|null, fallback?: boolean, subtitles?: Subtitle[]}} VideoSource
 */

/**
 * Субтитры (у источников Kodik они встроены в видео; отдельные дорожки пока не приходят).
 * @typedef {{lang: string, label: string, url: string}} Subtitle
 */

export {};
