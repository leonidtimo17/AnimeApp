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
import urllib.request

ANIMELIB_API = "https://api.cdnlibs.org/api"
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

    def progress(self, index, pos, dur):
        ep = self.job["episodes"][index]
        emit(type="progress", key=ep["key"], ordinal=ep["ordinal"], pos=int(pos * 1000), dur=int(dur * 1000))

    def current(self, index):
        emit(type="episode", key=self.job["episodes"][index]["key"])


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box} html,body{margin:0;height:100%;background:#000;color:#f2f2f5;
font-family:"Segoe UI",sans-serif;overflow:hidden}
#bar{height:56px;display:flex;align-items:center;gap:10px;padding:0 14px;background:#141418;border-bottom:1px solid #2a2a33}
#title{font-weight:700;font-size:16px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:40%}
#dub{color:#9a9aa6;font-size:13px;white-space:nowrap}
.sp{flex:1}
button,select{background:#24242c;color:#f2f2f5;border:1px solid #34343f;border-radius:9px;padding:7px 13px;
font:600 13px "Segoe UI";cursor:pointer}
button:hover,select:hover{background:#30303a} button:disabled{opacity:.4;cursor:default}
#next{background:#ff6a1a;border:none}
#frame{position:absolute;top:56px;left:0;right:0;bottom:0;width:100%;height:calc(100% - 56px);border:0}
#toast{position:absolute;right:24px;bottom:90px;display:none;gap:10px}
#toast button{padding:12px 20px;font-size:14px;border-radius:12px}
#msg{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);color:#9a9aa6;font-size:16px}
</style></head><body>
<div id="bar">
  <div id="title"></div><div id="dub"></div><div class="sp"></div>
  <button id="skip" title="Пропустить заставку">+85 с</button>
  <button id="prev">Пред.</button>
  <select id="eps"></select>
  <button id="next">След. серия</button>
</div>
<div id="msg">Загрузка…</div>
<iframe id="frame" allow="autoplay; fullscreen" allowfullscreen></iframe>
<div id="toast"><button id="stay">Остаться</button><button id="go" style="background:#ff6a1a;border:none"></button></div>
<script>
let job, idx = 0, pos = 0, dur = 0, lastSent = 0, seekTo = 0, timer = null, count = 0;
const $ = id => document.getElementById(id);
const api = () => window.pywebview.api;
function cmd(v){ $('frame').contentWindow.postMessage({key:'kodik_player_api', value:v}, '*'); }
function save(force){ if (dur > 0 && pos > 5 && (force || Date.now() - lastSent > 5000)) {
  lastSent = Date.now(); api().progress(idx, pos, dur); } }
async function load(i, start){
  save(true); stopCountdown();
  idx = i; pos = 0; dur = 0; seekTo = start || 0;
  $('eps').value = i; $('prev').disabled = i === 0; $('next').disabled = i >= job.episodes.length - 1;
  $('msg').textContent = 'Загрузка…'; $('frame').style.visibility = 'hidden';
  const r = await api().source(i);
  if (r.error) { $('msg').textContent = r.error; return; }
  $('dub').textContent = (r.team || job.dub) + (r.fallback ? ' (выбранной озвучки нет — другая)' : '');
  $('frame').src = r.src; $('frame').style.visibility = 'visible'; $('msg').textContent = '';
  api().current(i);
}
function stopCountdown(){ clearInterval(timer); timer = null; $('toast').style.display = 'none'; }
function countdown(){
  if (idx >= job.episodes.length - 1 || timer) return;
  count = 5; $('toast').style.display = 'flex'; $('go').textContent = 'Следующая серия через ' + count;
  timer = setInterval(() => { count--; if (count <= 0) { load(idx + 1, 0); return; }
    $('go').textContent = 'Следующая серия через ' + count; }, 1000);
}
window.addEventListener('message', e => {
  const d = e.data || {};
  if (d.key === 'kodik_player_duration_update') { dur = d.value;
    if (seekTo > 5) { const s = seekTo; seekTo = 0; setTimeout(() => cmd({method:'seek', seconds:s}), 600); } }
  else if (d.key === 'kodik_player_time_update') { pos = d.value; save(false);
    if (dur > 300 && dur - pos < 40) countdown(); }
  else if (d.key === 'kodik_player_video_ended') { pos = dur; save(true); countdown(); }
  else if (d.key === 'kodik_player_pause') save(true);
});
$('frame').onload = () => { if ($('frame').src) setTimeout(() => cmd({method:'play'}), 1500); };
$('prev').onclick = () => load(idx - 1, null);
$('next').onclick = () => load(idx + 1, null);
$('go').onclick = () => load(idx + 1, null);
$('stay').onclick = () => { clearInterval(timer); timer = null; $('toast').style.display = 'none'; };
$('eps').onchange = () => load(+$('eps').value, null);
$('skip').onclick = () => cmd({method:'seek', seconds: Math.floor(pos + 85)});
window.addEventListener('beforeunload', () => save(true));
window.addEventListener('pywebviewready', async () => {
  job = await api().job_data();
  $('title').textContent = job.title; $('dub').textContent = job.dub; document.title = job.title;
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
    window = webview.create_window(job["title"], html=PAGE, js_api=bridge, frameless=True, hidden=True,
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

    # Прогресс сохраняется каждые 5 с и на паузе, так что при закрытии теряется максимум 5 с.
    webview.start(announce, gui="edgechromium", private_mode=False,
                  storage_path=os.path.join(os.path.dirname(job_path), "webview"))
    emit(type="closed")
