"""Окно веб-плеера для озвучек, доступных только через плеер Kodik.

Запускается отдельным процессом (`main.py --webplayer <job.json>`), потому что
использует системный WebView2 (Edge) — в нём есть кодеки H.264, которых нет в Qt WebEngine.
Kodik встраивается штатно, через его публичный iframe-API (postMessage):
получаем время/длительность/конец серии и отправляем команды seek/play.

Прогресс отправляется в основное приложение строками JSON в stdout.
"""
import json
import os
import sys
import urllib.parse
import urllib.request

ANIMELIB_API = "https://api.cdnlibs.org/api"
ANISKIP_API = "https://api.aniskip.com/v2/skip-times"
HEADERS = {"User-Agent": "Mozilla/5.0 AnimeApp/1.0", "Site-Id": "5"}


def emit(**msg):
    if sys.stdout is None:
        return
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


class Bridge:
    def __init__(self, job):
        self.job = job

    def job_data(self):
        return self.job

    def source(self, index):
        """Ссылка Kodik для серии и выбранной команды озвучки."""
        ep = self.job["episodes"][index]
        if ep.get("kodik"):  # готовая ссылка (YummyAnime)
            return {"src": ep["kodik"], "team": self.job.get("dub"), "fallback": False}
        req = urllib.request.Request(f"{ANIMELIB_API}/episodes/{ep['animelib_id']}", headers=HEADERS)
        try:
            data = json.loads(urllib.request.urlopen(req, timeout=20).read())["data"]
        except Exception as exc:  # noqa: BLE001 — показываем ошибку в окне
            return {"error": str(exc)}
        players = [p for p in data.get("players") or [] if p.get("player") == "Kodik" and p.get("src")]
        team = int(self.job["team_id"])
        exact = [p for p in players if (p.get("team") or {}).get("id") == team]
        chosen = (exact or players or [None])[0]
        if not chosen:
            return {"error": "Для этой серии нет видео"}
        src = chosen["src"]
        return {
            "src": ("https:" + src) if src.startswith("//") else src,
            "team": (chosen.get("team") or {}).get("name"),
            "fallback": not exact,
        }

    def skip_times(self, index, dur):
        """Разметка заставки/титров от AniSkip (id MyAnimeList = id Shikimori) под длительность этой серии."""
        ep = self.job["episodes"][index]
        sid, o = self.job.get("sid"), float(ep.get("ordinal") or 0)
        if not sid or o != int(o) or not dur or dur < 60:
            return None
        q = urllib.parse.urlencode([("types[]", "op"), ("types[]", "ed"), ("episodeLength", round(dur))])
        try:
            req = urllib.request.Request(f"{ANISKIP_API}/{sid}/{int(o)}?{q}", headers=HEADERS)
            data = json.loads(urllib.request.urlopen(req, timeout=15).read())
        except Exception:  # noqa: BLE001 — разметки нет
            return None
        res = {}
        for r in data.get("results") or [] if data.get("found") else []:
            iv = r.get("interval") or {}
            res.setdefault("opening" if r.get("skipType") == "op" else "ending",
                           {"start": iv.get("startTime"), "stop": iv.get("endTime")})
        return res or None

    def tick(self, pos):
        emit(type="time", pos=pos)

    def setting(self, key, value):
        emit(type="setting", key=key, value=value)

    def sleep(self, until, minutes, episode):
        emit(type="sleep", until=until, min=minutes, episode=episode)

    def progress(self, index, pos, dur):
        ep = self.job["episodes"][index]
        emit(type="progress", key=ep["key"], ordinal=ep["ordinal"], pos=int(pos * 1000), dur=int(dur * 1000))

    def current(self, index):
        emit(type="episode", key=self.job["episodes"][index]["key"])


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><style>
@font-face{font-family:FA;src:url(data:font/ttf;base64,%%FONT%%)}
*{box-sizing:border-box} html,body{margin:0;height:100%;background:#000;color:#f2f2f5;
font-family:"Segoe UI",sans-serif;overflow:hidden;user-select:none}
body{display:flex;flex-direction:column}
.fa{font-family:FA;font-weight:900;font-style:normal}
#stage{position:relative;flex:1;min-height:0}
#frame{position:absolute;inset:0;width:100%;height:100%;border:0;transition:transform .2s}
#stage{overflow:hidden}
button.on{color:#ff6a1a}
#menu{position:absolute;right:16px;bottom:64px;background:#1c1c22;border:1px solid #333;border-radius:10px;padding:6px;
display:none;min-width:220px;z-index:5}
#menu div{padding:8px 14px;border-radius:7px;cursor:pointer;font-size:14px}
#menu div:hover{background:#2c2c35} #menu div.on{color:#ff6a1a} #menu .t{color:#9a9aa6;cursor:default;font-size:12px}
#menu .t:hover{background:none}
#msg{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);color:#9a9aa6;font-size:16px}
/* Своя панель управления под видео (поверх iframe нельзя: он забирает клики и движения мыши) */
#panel{background:#101014;border-top:1px solid #24242c;padding:8px 16px 10px}
#seek{position:relative;height:22px;cursor:pointer;touch-action:none}
#seek .tr,#seek .pl{position:absolute;left:0;top:9px;height:4px;border-radius:2px}
#seek .tr{right:0;background:rgba(255,255,255,.22)} #seek .pl{background:#ff6a1a;width:0}
#seek .kn{position:absolute;top:4px;width:14px;height:14px;margin-left:-7px;border-radius:7px;background:#fff;left:0}
#seek:hover .tr,#seek:hover .pl{top:8px;height:6px}
#tip{position:absolute;bottom:24px;transform:translateX(-50%);background:rgba(0,0,0,.85);padding:2px 8px;border-radius:6px;
font-size:12px;font-weight:600;display:none;white-space:nowrap}
.row{display:flex;align-items:center;gap:4px;margin-top:2px}
.sp{flex:1}
button,select{background:none;color:#f2f2f5;border:0;border-radius:9px;padding:8px 11px;font:600 14px "Segoe UI";cursor:pointer}
button .fa{font-size:17px} button:hover,select:hover{background:rgba(255,255,255,.1)}
button:disabled{opacity:.35;cursor:default;background:none}
#play .fa{font-size:20px}
select{background:#1c1c22;border:1px solid #2c2c35}
#time{font-weight:600;font-size:14px;margin:0 10px;color:#d8d8e0;font-variant-numeric:tabular-nums}
#skip{border:1px solid #34343f}
#ad{color:#ffb070;font-size:13px;font-weight:600;display:none;margin-right:8px}
body.ad #ad{display:block} body.ad .ctl{opacity:.35;pointer-events:none}
#toast{position:absolute;right:22px;bottom:20px;display:none;gap:10px}
#toast button{padding:12px 20px;font-size:14px;border-radius:12px;background:rgba(20,20,24,.92);border:1px solid rgba(255,255,255,.3)}
#toast #go{background:#ff6a1a;border-color:#ff6a1a}
#osd{position:absolute;left:50%;top:18%;transform:translateX(-50%);background:rgba(0,0,0,.72);border-radius:12px;
padding:10px 20px;font-weight:700;font-size:16px;display:none}
</style></head><body>
<div id="stage">
  <div id="msg">Загрузка…</div>
  <iframe id="frame" allow="autoplay; fullscreen" allowfullscreen></iframe>
  <div id="osd"></div>
  <div id="toast"><button id="stay">Смотреть титры</button><button id="go"></button></div>
</div>
<div id="panel">
  <div id="seek" class="ctl"><div class="tr"></div><div class="pl"></div><div class="kn"></div><div id="tip"></div></div>
  <div class="row">
    <button id="prev" title="Предыдущая серия (P)"><i class="fa">&#xf048;</i></button>
    <button id="rw" class="ctl" title="Назад на 10 с (←)"><i class="fa">&#xf2ea;</i></button>
    <button id="play" class="ctl" title="Пауза / воспроизведение (пробел)"><i class="fa">&#xf04b;</i></button>
    <button id="ff" class="ctl" title="Вперёд на 10 с (→)"><i class="fa">&#xf2f9;</i></button>
    <button id="next" title="Следующая серия (N)"><i class="fa">&#xf051;</i></button>
    <span id="time">0:00 / 0:00</span>
    <select id="eps" title="Серия"></select>
    <div class="sp"></div>
    <span id="ad">Идёт реклама Kodik…</span>
    <button id="skip" class="ctl" title="Пропустить заставку (S)"><i class="fa">&#xf04e;</i>&nbsp; Пропустить заставку</button>
    <button id="sleep" title="Таймер сна"><i class="fa">&#xf186;</i></button>
    <button id="zoom" title="Заполнить экран, без чёрных полос (Z)"><i class="fa">&#xf065;</i></button>
  </div>
  <div id="menu"></div>
</div>
<script>
let lastTickSent = 0;
let job, idx = 0, pos = 0, dur = 0, lastSent = 0, seekTo = 0, timer = null, count = 0, playing = false, dragging = false;
const $ = id => document.getElementById(id);
const api = () => window.pywebview.api;
const PLAY = '<i class="fa">&#xf04b;</i>', PAUSE = '<i class="fa">&#xf04c;</i>';
function fmt(s){ s = Math.max(0, Math.floor(s||0)); const h = Math.floor(s/3600), m = Math.floor(s/60)%60, x = s%60;
  return h ? `${h}:${String(m).padStart(2,'0')}:${String(x).padStart(2,'0')}` : `${m}:${String(x).padStart(2,'0')}`; }
function cmd(v){ $('frame').contentWindow.postMessage({key:'kodik_player_api', value:v}, '*'); }
let osdT; function osd(t){ const o=$('osd'); o.textContent=t; o.style.display='block'; clearTimeout(osdT); osdT=setTimeout(()=>o.style.display='none',1000); }
function save(force){ if (dur > 0 && pos > 5 && (force || Date.now() - lastSent > 5000)) {
  lastSent = Date.now(); api().progress(idx, pos, dur); } }
function render(){
  $('time').textContent = `${fmt(pos)} / ${fmt(dur)}`;
  if (!dragging && dur) { const f = Math.min(1, pos/dur); $('seek').querySelector('.pl').style.width = f*100+'%'; $('seek').querySelector('.kn').style.left = f*100+'%'; }
  $('play').innerHTML = playing ? PAUSE : PLAY;
}
function seek(s){ s = Math.max(0, Math.min(dur ? dur - 1 : s, s)); cmd({method:'seek', seconds: Math.floor(s)}); pos = s; render(); }
function setAd(on){ document.body.classList.toggle('ad', on); }
async function load(i, start){
  save(true); stopCountdown(); setAd(false);
  idx = i; pos = 0; dur = 0; playing = false; started = false; lastTick = Date.now(); seekTo = start || 0; render();
  $('eps').value = i; $('prev').disabled = i === 0; $('next').disabled = i >= job.episodes.length - 1;
  $('msg').textContent = 'Загрузка…'; $('frame').style.visibility = 'hidden';
  const r = await api().source(i);
  if (r.error) { $('msg').textContent = r.error; return; }
  if (r.fallback) osd('Выбранной озвучки для этой серии нет — включена другая: ' + (r.team || ''));
  $('frame').src = r.src; $('frame').style.visibility = 'visible'; $('msg').textContent = '';
  api().current(i);
}
function stopCountdown(){ clearInterval(timer); timer = null; $('toast').style.display = 'none'; }
function countdown(){
  if (idx >= job.episodes.length - 1 || timer || sleep.episode) return;
  count = 10; $('toast').style.display = 'flex'; $('go').textContent = 'Следующая серия через ' + count;
  timer = setInterval(() => { count--; if (count <= 0) { load(idx + 1, 0); return; }
    $('go').textContent = 'Следующая серия через ' + count; }, 1000);
}
window.addEventListener('message', e => {
  const d = e.data || {};
  if (d.key === 'kodik_player_duration_update') { dur = d.value; render();
    const ep = job.episodes[idx];
    if (!(ep.opening && ep.opening.stop) || !(ep.ending && ep.ending.start)) api().skip_times(idx, dur).then(s => {
      if (!s || job.episodes[idx] !== ep) return;
      if (!(ep.opening && ep.opening.stop) && s.opening) ep.opening = s.opening;
      if (!(ep.ending && ep.ending.start) && s.ending) ep.ending = s.ending;
    });
    if (seekTo > 5) { const s = seekTo; seekTo = 0; setTimeout(() => { cmd({method:'seek', seconds:s}); osd('Продолжаем с ' + fmt(s)); }, 600); } }
  else if (d.key === 'kodik_player_time_update') { if (Date.now() - lastTickSent > 1000) { lastTickSent = Date.now(); api().tick(d.value); } pos = d.value; playing = true; started = true; userPaused = false; lastTick = Date.now(); setAd(false); render(); save(false);
    const ep = job.episodes[idx], op = ep.opening;
    if (ep.ending && ep.ending.start ? pos >= ep.ending.start : dur > 300 && dur - pos < 40) countdown();
    if (job.autoskip && op && op.stop && op.start != null && pos >= op.start && pos < op.stop - 2 && !ep._skipped) {
      ep._skipped = true; seek(op.stop); osd('Заставка пропущена'); } }
  else if (d.key === 'kodik_player_play') { playing = true; userPaused = false; lastTick = Date.now(); render(); }
  else if (d.key === 'kodik_player_pause') { playing = false; userPaused = true; render(); save(true); }
  else if (d.key === 'kodik_player_video_ended') { pos = dur; playing = false; render(); save(true);
    if (sleep.episode) { sleep.episode = false; api().sleep(0, 0, false); osd('Таймер сна — серия закончилась. Спокойной ночи!'); }
    else countdown(); }
  else if (d.event === 'adShown' || d.title === 'vastStarted' || d.key === 'kodik_player_advert_started') setAd(true);
  else if (d.key === 'kodik_player_advert_ended' || d.title === 'currentVastEnded') setAd(false);
});
// --- перемотка по своей полосе
const bar = $('seek');
const frac = x => { const r = bar.getBoundingClientRect(); return Math.min(1, Math.max(0, (x - r.left) / r.width)); };
bar.addEventListener('pointerdown', e => { if (!dur) return; dragging = true; bar.setPointerCapture(e.pointerId); move(e); });
bar.addEventListener('pointermove', e => { const f = frac(e.clientX), t = $('tip');
  t.textContent = fmt(f * dur); t.style.left = f*100 + '%'; t.style.display = dur ? 'block' : 'none'; if (dragging) move(e); });
bar.addEventListener('pointerleave', () => $('tip').style.display = 'none');
bar.addEventListener('pointerup', e => { if (!dragging) return; dragging = false; seek(frac(e.clientX) * dur); });
function move(e){ const f = frac(e.clientX); bar.querySelector('.pl').style.width = f*100+'%'; bar.querySelector('.kn').style.left = f*100+'%';
  $('time').textContent = `${fmt(f*dur)} / ${fmt(dur)}`; }
// --- кнопки
$('frame').onload = () => { if ($('frame').src) setTimeout(() => cmd({method:'play'}), 1500); };
const toggle = () => { cmd({method: playing ? 'pause' : 'play'}); playing = !playing; render(); };
$('play').onclick = toggle;
$('rw').onclick = () => { seek(pos - 10); osd('−10 с'); };
$('ff').onclick = () => { seek(pos + 10); osd('+10 с'); };
$('prev').onclick = () => load(idx - 1, null);
$('next').onclick = () => load(idx + 1, null);
$('go').onclick = () => load(idx + 1, null);
$('stay').onclick = () => { clearInterval(timer); timer = null; $('toast').style.display = 'none'; };
$('eps').onchange = () => load(+$('eps').value, null);
// Точное время заставки — от YummyAnime или AniSkip; иначе стандартные 85 секунд
function skipOpening(){ const op = job.episodes[idx].opening; seek(op && op.stop && pos < op.stop ? op.stop : pos + 85); osd('Заставка пропущена'); }
$('skip').onclick = skipOpening;
// --- масштаб: iframe увеличиваем так, чтобы кадр 16:9 закрыл всю область
let fill = false;
function applyZoom(){
  const st = $('stage'), w = st.clientWidth, h = st.clientHeight, vw = Math.min(w, h * 16 / 9), vh = vw * 9 / 16;
  $('frame').style.transform = fill && vw && vh ? `scale(${Math.max(w / vw, h / vh).toFixed(3)})` : '';
  $('zoom').innerHTML = fill ? '<i class="fa">&#xf066;</i>' : '<i class="fa">&#xf065;</i>';
}
function toggleZoom(){ fill = !fill; applyZoom(); api().setting('zoom_fill', fill); osd(fill ? 'Заполнить экран' : 'Весь кадр'); }
$('zoom').onclick = toggleZoom;
window.addEventListener('resize', applyZoom);
// --- таймер сна
let sleep = {until: 0, min: 0, episode: false};
const sleepOn = () => sleep.episode || sleep.until > Date.now();
function setSleep(min, episode){
  sleep = {until: min ? Date.now() + min * 60000 : 0, min, episode};
  api().sleep(sleep.until, min, episode);
  osd(min ? `Таймер сна: остановлю через ${min} мин` : episode ? 'Остановлю после этой серии' : 'Таймер сна выключен');
}
$('sleep').onclick = e => {
  e.stopPropagation();
  const m = $('menu');
  if (m.style.display === 'block') { m.style.display = 'none'; return; }
  const left = sleep.until > Date.now() ? ` · осталось ${Math.ceil((sleep.until - Date.now()) / 60000)} мин` : '';
  const items = [['Выключен', 0, false, !sleepOn()], ['После этой серии', 0, true, sleep.episode],
    ...[15, 30, 45, 60, 90].map(x => [`Через ${x} минут`, x, false, sleep.until > Date.now() && sleep.min === x])];
  m.innerHTML = `<div class="t">Таймер сна${left}</div>` + items.map(([t, mi, ep, on], i) => `<div data-i="${i}" class="${on ? 'on' : ''}">${t}</div>`).join('');
  m.onclick = ev => { const d = ev.target.closest('[data-i]'); if (!d) return; const [, mi, ep] = items[+d.dataset.i]; setSleep(mi, ep); m.style.display = 'none'; };
  m.style.display = 'block';
};
document.addEventListener('click', () => $('menu').style.display = 'none');
setInterval(() => {
  $('sleep').classList.toggle('on', sleepOn());
  if (sleep.until && Date.now() >= sleep.until) {
    sleep = {until: 0, min: 0, episode: false}; api().sleep(0, 0, false);
    if (playing) { cmd({method: 'pause'}); playing = false; render(); }
    osd('Таймер сна — видео остановлено. Спокойной ночи!');
  }
}, 1000);
document.addEventListener('keydown', e => {
  if (e.target.tagName === 'SELECT') return;
  const k = e.key.toLowerCase();
  if (k === ' ' || k === 'k') { toggle(); e.preventDefault(); }
  else if (k === 'arrowleft') { seek(pos - (e.shiftKey ? 30 : 10)); osd(e.shiftKey ? '−30 с' : '−10 с'); }
  else if (k === 'arrowright') { seek(pos + (e.shiftKey ? 30 : 10)); osd(e.shiftKey ? '+30 с' : '+10 с'); }
  else if (k === 'n') load(idx + 1, null);
  else if (k === 'p' && idx > 0) load(idx - 1, null);
  else if (k === 's') skipOpening();
  else if (k === 'z') toggleZoom();
});
// --- восстановление после обрыва сети (смена Wi-Fi/VPN): если видео должно идти, а время не обновляется — перезагружаем с того же места
let lastTick = Date.now(), userPaused = false, started = false;
setInterval(() => {
  if (!started || userPaused || !dur || document.body.classList.contains('ad')) return;
  if (Date.now() - lastTick > 15000) { lastTick = Date.now(); osd('Связь прервалась — переподключаемся…'); load(idx, pos); }
}, 3000);
window.addEventListener('online', () => { if (started && !userPaused) lastTick = 0; });
window.addEventListener('beforeunload', () => save(true));
window.addEventListener('pywebviewready', async () => {
  job = await api().job_data();
  document.title = job.title;
  fill = !!job.zoom_fill; applyZoom();
  if (job.sleep) sleep = job.sleep;
  job.episodes.forEach((ep, i) => { const o = document.createElement('option'); o.value = i;
    o.textContent = ep.key + ' серия' + (ep.name ? ' — ' + ep.name : ''); $('eps').appendChild(o); });
  load(job.index, job.position / 1000);
});
</script></body></html>"""


def run(job_path):
    import webview

    with open(job_path, encoding="utf-8") as f:
        job = json.load(f)
    # Разрешаем автозапуск видео со звуком после переключения серий.
    os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--autoplay-policy=no-user-gesture-required")
    bridge = Bridge(job)
    # Окно без рамки и скрытое: основное приложение встраивает его в себя по HWND.
    # Шрифт иконок встраиваем в страницу: она загружается из строки и не видит файлы на диске.
    import base64
    font_path = os.path.join(os.path.dirname(__file__), "assets", "fonts", "fa-solid-900.ttf")
    with open(font_path, "rb") as f:
        page = PAGE.replace("%%FONT%%", base64.b64encode(f.read()).decode("ascii"))
    window = webview.create_window(job["title"], html=page, js_api=bridge, frameless=True, hidden=True,
                                   width=1280, height=780, background_color="#000000")

    def announce():
        import time
        for _ in range(200):
            try:
                emit(type="hwnd", value=int(window.native.Handle.ToInt64()))
                return
            except Exception:  # noqa: BLE001 — окно ещё создаётся
                time.sleep(0.05)
        emit(type="error", message="Не удалось создать окно плеера")

    def commands():
        """Команды из основного приложения (строки JSON в stdin): перемотка из обсуждения серии."""
        announce()
        for line in sys.stdin:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("cmd") == "seek":
                t = int(msg.get("t") or 0)
                window.evaluate_js(f"seek({t}); osd('Перемотка на ' + fmt({t}))")

    # Прогресс сохраняется каждые 5 с и на паузе, так что при закрытии теряется максимум 5 с.
    webview.start(commands if sys.stdin else announce, gui="edgechromium", private_mode=False,
                  storage_path=os.path.join(os.path.dirname(job_path), "webview"))
    emit(type="closed")
