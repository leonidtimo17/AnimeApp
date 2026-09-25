// Ошибки приложения: message — понятный пользователю текст, тип — что случилось.

export class AppError extends Error {
  constructor(message) { super(message); this.name = this.constructor.name; }
}
/** Сервер не ответил: нет интернета, таймаут, обрыв. transient — есть смысл повторить сразу (не таймаут). */
export class NetworkError extends AppError {
  constructor(message, { transient = true } = {}) { super(message); this.transient = transient; }
}
/** Сервер ответил ошибкой HTTP или непонятным ответом. */
export class ApiError extends AppError {
  constructor(message, status = null) { super(message); this.status = status; }
  get isClientError() { return this.status != null && this.status >= 400 && this.status < 500; }
}
/** Нет входа или доступ отозван (Shikimori). */
export class AuthenticationError extends ApiError {}
/** Видео не воспроизводится. */
export class PlayerError extends AppError {}
/** У серии нет видео в выбранном источнике. */
export class NoSourceError extends AppError {}
/** Неверные данные. */
export class ValidationError extends AppError {}

/** Запрос отменён — страница, которой он был нужен, уже закрыта. Такие ошибки не показываем. */
export const isAbort = (e) => e?.name === "AbortError";
export const abortError = () => Object.assign(new Error("Отменено"), { name: "AbortError" });
