// Таймер сна: остановить видео через N минут или после текущей серии.
// Один на всё приложение: живёт между сериями и сменой озвучки. Тикает, только когда заведён.
import { createEmitter } from "../../core/events.js";
import { sheet } from "../../components/Sheet.js";
import { t } from "../../i18n/index.js";

const state = { until: 0, min: 0, episode: false };
const changes = createEmitter();

export const sleepActive = () => state.episode || state.until > Date.now();
export const afterEpisode = () => state.episode;

function set(min, episode) {
  Object.assign(state, { min, episode, until: min ? Date.now() + min * 60_000 : 0 });
  changes.emit();
  return min ? t("sleep.set_minutes", { n: min }) : episode ? t("sleep.set_episode") : t("sleep.off_done");
}

/** Меню таймера сна; osd(text) — подсказка на экране плеера. */
export function sleepMenu(osd) {
  const pick = (min, episode) => osd(set(min, episode), 1800);
  const left = state.until > Date.now() ? ` · ${t("sleep.left", { n: Math.ceil((state.until - Date.now()) / 60_000) })}` : "";
  sheet([{ title: `${t("sleep.title")}${left}`, items: [
    { label: t("sleep.off"), on: !sleepActive(), action: () => pick(0, false) },
    { label: t("sleep.after_episode"), on: state.episode, action: () => pick(0, true) },
    ...[15, 30, 45, 60, 90].map((m) => ({ label: t("sleep.in_minutes", { n: m }), on: state.until > Date.now() && state.min === m, action: () => pick(m, false) })),
  ] }]);
}

/**
 * Подключить таймер к плееру: подсветка кнопок [data-a=sleep] и остановка видео, когда время вышло.
 * Интервал работает только пока таймер заведён по времени. Возвращает функцию отключения.
 */
export function attachSleep(root, pause, osd) {
  let tick = null;
  const paint = () => root.querySelectorAll("[data-a=sleep]").forEach((b) => b.classList.toggle("on", sleepActive()));
  const check = () => {
    if (state.until && Date.now() >= state.until) {
      Object.assign(state, { until: 0, min: 0 });
      pause();
      osd(t("sleep.stopped"), 4000);
      changes.emit();
    }
  };
  const sync = () => {
    paint();
    clearInterval(tick);
    tick = state.until ? setInterval(check, 1000) : null;
  };
  const off = changes.subscribe(sync);
  sync();
  return () => { off(); clearInterval(tick); };
}

/** Серия закончилась: если таймер «после этой серии» — следующую не включаем (true). */
export function sleepAfterEpisode(osd) {
  if (!state.episode) return false;
  state.episode = false;
  changes.emit();
  osd(t("sleep.episode_over"), 4000);
  return true;
}
