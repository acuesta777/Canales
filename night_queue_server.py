#!/usr/bin/env python3
"""
night_queue_server.py — Dashboard visual para la cola nocturna.
Corre en http://localhost:5010

Uso:
    python3 night_queue_server.py
"""

import json, subprocess, threading, datetime, pickle, sys
from pathlib import Path
from flask import Flask, jsonify, request

BASE        = Path(__file__).parent
QUEUE_FILE  = BASE / "night_queue.json"
LOG_FILE    = BASE / "logs" / "night_queue_runner.log"
TOKENS_DIR  = BASE / "_jsonytapi" / "tokens"
CANALES_DIR = BASE / "_jsonytapi"
PORT        = 5010

app = Flask(__name__)
_runner_proc = None
_runner_lock = threading.Lock()

def list_canales():
    return sorted([
        f.stem for f in CANALES_DIR.glob("*.json")
        if f.stem not in ("tokens",) and not f.stem.startswith(".")
    ])

# ── helpers ───────────────────────────────────────────────────────────────────

def load_queue():
    if not QUEUE_FILE.exists():
        return {"queue": [], "history": []}
    try:
        return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"queue": [], "history": []}

def tail_log(n=60):
    try:
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
        return "\n".join(lines[-n:])
    except Exception:
        return ""

def runner_alive():
    global _runner_proc
    if _runner_proc is None:
        return False
    return _runner_proc.poll() is None

# ── API ───────────────────────────────────────────────────────────────────────

@app.route("/api/queue")
def api_queue():
    data = load_queue()
    pending  = [x for x in data["queue"]   if x["status"] == "pending"]
    running  = [x for x in data["queue"]   if x["status"] == "running"]
    done     = [x for x in data.get("history", []) if x["status"] == "done"]
    errors   = [x for x in data.get("history", []) if x["status"] == "error"]
    return jsonify({
        "pending":  pending,
        "running":  running,
        "done":     done,
        "errors":   errors,
        "alive":    runner_alive(),
        "log":      tail_log(80),
    })

@app.route("/api/run", methods=["POST"])
def api_run():
    global _runner_proc
    with _runner_lock:
        if runner_alive():
            return jsonify({"ok": False, "msg": "Ya hay un runner activo"})
        _runner_proc = subprocess.Popen(
            ["python3", str(BASE / "run_night_queue.py")],
            cwd=str(BASE),
            stdout=open(LOG_FILE, "a"),
            stderr=subprocess.STDOUT,
        )
    return jsonify({"ok": True, "pid": _runner_proc.pid})

@app.route("/api/stop", methods=["POST"])
def api_stop():
    global _runner_proc
    if _runner_proc and runner_alive():
        _runner_proc.terminate()
        return jsonify({"ok": True})
    return jsonify({"ok": False, "msg": "No hay runner activo"})

@app.route("/api/clear_history", methods=["POST"])
def api_clear_history():
    data = load_queue()
    data["history"] = []
    QUEUE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return jsonify({"ok": True})

@app.route("/api/canales")
def api_canales():
    return jsonify(list_canales())

@app.route("/api/set_canal", methods=["POST"])
def api_set_canal():
    body = request.get_json(force=True)
    item_id = body.get("id")
    canal   = body.get("canal", "").strip()
    data = load_queue()
    for item in data["queue"]:
        if item["id"] == item_id:
            item["canal"] = canal
            break
    QUEUE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return jsonify({"ok": True})

@app.route("/api/check_token", methods=["POST"])
def api_check_token():
    """Intenta refresh del token OAuth del canal. Retorna ok/revoked."""
    body  = request.get_json(force=True)
    canal = body.get("canal", "").strip()
    if not canal:
        return jsonify({"ok": False, "status": "error", "msg": "Canal vacío"})
    token_file = TOKENS_DIR / f"{canal}.pickle"
    if not token_file.exists():
        return jsonify({"ok": False, "status": "no_token",
                        "msg": "No hay token guardado — autoriza primero"})
    try:
        with open(token_file, "rb") as f:
            creds = pickle.load(f)
        if creds.valid:
            return jsonify({"ok": True, "status": "valid", "msg": "Token válido ✓"})
        if creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
            with open(token_file, "wb") as f:
                pickle.dump(creds, f)
            return jsonify({"ok": True, "status": "refreshed", "msg": "Token renovado ✓"})
        return jsonify({"ok": False, "status": "revoked",
                        "msg": "Token revocado — necesita re-autorización manual"})
    except Exception as e:
        return jsonify({"ok": False, "status": "error", "msg": str(e)[:120]})

# ── HTML ──────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Cola Nocturna</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
/* ── tokens ─────────────────────────────────── */
:root {
  --bg:        #0d0f14;
  --bg2:       #13161e;
  --bg3:       #1a1e2a;
  --border:    #252a38;
  --fg:        #e2e6f0;
  --fg2:       #8892a8;
  --accent:    #7c6af7;
  --accent2:   #5d4fe0;
  --green:     #22c55e;
  --green-bg:  #0d2b1a;
  --red:       #f87171;
  --red-bg:    #2b0d0d;
  --yellow:    #fbbf24;
  --yellow-bg: #2b1f05;
  --blue:      #60a5fa;
  --blue-bg:   #0d1b2b;
  --mono:      'JetBrains Mono', monospace;
  --sans:      'Inter', system-ui, sans-serif;
  color-scheme: dark;
}
@media (prefers-color-scheme: light) {
  :root:not([data-theme="dark"]) {
    --bg:        #f5f6fa;
    --bg2:       #ffffff;
    --bg3:       #eef0f6;
    --border:    #dde1ed;
    --fg:        #1a1e2a;
    --fg2:       #5a637a;
    --accent:    #5d4fe0;
    --accent2:   #4338ca;
    --green:     #16a34a;
    --green-bg:  #dcfce7;
    --red:       #dc2626;
    --red-bg:    #fee2e2;
    --yellow:    #d97706;
    --yellow-bg: #fef3c7;
    --blue:      #2563eb;
    --blue-bg:   #dbeafe;
    color-scheme: light;
  }
}
:root[data-theme="light"] {
  --bg:#f5f6fa;--bg2:#fff;--bg3:#eef0f6;--border:#dde1ed;
  --fg:#1a1e2a;--fg2:#5a637a;--accent:#5d4fe0;--accent2:#4338ca;
  --green:#16a34a;--green-bg:#dcfce7;--red:#dc2626;--red-bg:#fee2e2;
  --yellow:#d97706;--yellow-bg:#fef3c7;--blue:#2563eb;--blue-bg:#dbeafe;
  color-scheme: light;
}

* { box-sizing: border-box; margin: 0; padding: 0 }
body {
  background: var(--bg);
  color: var(--fg);
  font-family: var(--sans);
  font-size: 14px;
  min-height: 100dvh;
  padding-inline: 16px;
  padding-block: 24px;
}

/* ── layout ─── */
.shell { max-width: 860px; margin-inline: auto; display: flex; flex-direction: column; gap: 20px }

/* ── header ─── */
header { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px }
.logo { display: flex; align-items: center; gap: 10px }
.logo-icon { width: 36px; height: 36px; border-radius: 10px; background: linear-gradient(135deg,var(--accent),var(--accent2)); display: grid; place-items: center; font-size: 18px }
.logo-text { font-weight: 700; font-size: 17px; letter-spacing: -.3px }
.logo-sub { font-size: 12px; color: var(--fg2) }
.header-right { display: flex; align-items: center; gap: 10px }

/* ── pill status ─── */
.pill {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 4px 10px; border-radius: 99px; font-size: 12px; font-weight: 600;
}
.pill-idle    { background: var(--bg3); color: var(--fg2) }
.pill-running { background: var(--blue-bg); color: var(--blue) }
.pill-done    { background: var(--green-bg); color: var(--green) }
.pill-error   { background: var(--red-bg); color: var(--red) }
.pill-pending { background: var(--yellow-bg); color: var(--yellow) }
.dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor }
.dot-pulse { animation: pulse 1.2s ease-in-out infinite }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.35} }

/* ── stat strip ─── */
.stats {
  display: grid; grid-template-columns: repeat(4,1fr); gap: 10px;
}
@media(max-width:520px){ .stats{grid-template-columns:repeat(2,1fr)} }
.stat {
  background: var(--bg2); border: 1px solid var(--border); border-radius: 12px;
  padding: 14px 16px;
}
.stat-n { font-size: 28px; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1 }
.stat-label { font-size: 11px; color: var(--fg2); margin-top: 4px; text-transform: uppercase; letter-spacing: .05em }
.stat-pending .stat-n { color: var(--yellow) }
.stat-running .stat-n { color: var(--blue) }
.stat-done    .stat-n { color: var(--green) }
.stat-error   .stat-n { color: var(--red) }

/* ── action bar ─── */
.actions { display: flex; gap: 10px; flex-wrap: wrap }
.btn {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 9px 18px; border-radius: 9px; font-size: 13px; font-weight: 600;
  cursor: pointer; border: none; transition: opacity .15s, transform .1s;
}
.btn:active { transform: scale(.97) }
.btn-primary { background: var(--accent); color: #fff }
.btn-primary:hover { background: var(--accent2) }
.btn-primary:disabled { opacity: .4; cursor: not-allowed }
.btn-danger  { background: var(--red-bg); color: var(--red); border: 1px solid var(--red) }
.btn-ghost   { background: var(--bg3); color: var(--fg2); border: 1px solid var(--border) }
.btn-ghost:hover { color: var(--fg) }

/* ── section ─── */
.section { background: var(--bg2); border: 1px solid var(--border); border-radius: 14px; overflow: hidden }
.section-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 18px; border-bottom: 1px solid var(--border);
}
.section-title { font-weight: 600; font-size: 13px; display: flex; align-items: center; gap: 7px }
.section-count { background: var(--bg3); border-radius: 99px; padding: 2px 8px; font-size: 11px; font-weight: 600; color: var(--fg2) }
.empty { padding: 32px; text-align: center; color: var(--fg2); font-size: 13px }

/* ── item cards ─── */
.item-list { display: flex; flex-direction: column }
.item {
  display: flex; align-items: flex-start; gap: 14px;
  padding: 13px 18px; border-bottom: 1px solid var(--border);
  transition: background .15s;
}
.item:last-child { border-bottom: none }
.item:hover { background: var(--bg3) }
.item-icon { font-size: 20px; flex-shrink: 0; padding-top: 2px }
.item-body { flex: 1; min-width: 0 }
.item-name { font-weight: 600; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis }
.item-meta { font-size: 11px; color: var(--fg2); margin-top: 2px }
.item-right { flex-shrink: 0; display: flex; align-items: center; gap: 8px }
.item-dur { font-size: 12px; color: var(--fg2); font-variant-numeric: tabular-nums }
/* canal row */
.canal-row { display: flex; align-items: center; gap: 7px; margin-top: 8px; flex-wrap: wrap }
.canal-select {
  flex: 1; min-width: 140px; max-width: 240px;
  background: var(--bg3); color: var(--fg); border: 1px solid var(--border);
  border-radius: 7px; padding: 5px 8px; font-size: 12px; font-family: var(--sans);
  cursor: pointer;
}
.canal-select:focus { outline: 2px solid var(--accent); outline-offset: 1px }
.token-badge {
  font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 99px;
  cursor: pointer; border: none; font-family: var(--sans); transition: opacity .15s;
}
.token-unknown  { background: var(--bg3); color: var(--fg2) }
.token-valid    { background: var(--green-bg); color: var(--green) }
.token-refreshed{ background: var(--green-bg); color: var(--green) }
.token-revoked  { background: var(--red-bg); color: var(--red) }
.token-no_token { background: var(--yellow-bg); color: var(--yellow) }
.token-error    { background: var(--red-bg); color: var(--red) }

/* ── progress bar (item) ─── */
.progress-wrap { height: 3px; background: var(--bg3); border-radius: 99px; overflow: hidden; margin-top: 6px }
.progress-bar  { height: 100%; background: var(--blue); border-radius: 99px; animation: progress-slide 1.4s linear infinite }
@keyframes progress-slide { 0%{transform:translateX(-100%)} 100%{transform:translateX(400%)} }

/* ── big progress panel ─── */
.progress-panel {
  background: var(--bg2); border: 1px solid var(--border); border-radius: 14px;
  padding: 20px 22px; display: none; flex-direction: column; gap: 14px;
}
.progress-panel.visible { display: flex }
.prog-header { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px }
.prog-title { font-weight: 700; font-size: 15px; display: flex; align-items: center; gap: 8px }
.prog-counts { font-size: 13px; color: var(--fg2) }
.prog-counts strong { color: var(--fg); font-variant-numeric: tabular-nums }
.prog-track {
  height: 10px; background: var(--bg3); border-radius: 99px; overflow: hidden;
}
.prog-fill {
  height: 100%; border-radius: 99px;
  background: linear-gradient(90deg, var(--accent), var(--blue));
  transition: width .6s ease;
}
.prog-now {
  background: var(--blue-bg); border: 1px solid var(--blue);
  border-radius: 10px; padding: 10px 14px;
  display: flex; align-items: center; gap: 12px;
}
.prog-now-label { font-size: 11px; text-transform: uppercase; letter-spacing: .07em; color: var(--blue); font-weight: 600 }
.prog-now-name  { font-size: 14px; font-weight: 700; margin-top: 2px }
.prog-now-meta  { font-size: 11px; color: var(--fg2); margin-top: 2px }
.prog-step {
  display: flex; gap: 6px; flex-wrap: wrap;
}
.step-chip {
  font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 99px;
  background: var(--bg3); color: var(--fg2); border: 1px solid var(--border);
}
.step-chip.active { background: var(--blue-bg); color: var(--blue); border-color: var(--blue) }
.step-chip.done   { background: var(--green-bg); color: var(--green); border-color: var(--green) }

/* ── log ─── */
.log-wrap { background: var(--bg); border: 1px solid var(--border); border-radius: 14px; overflow: hidden }
.log-head { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-bottom: 1px solid var(--border) }
.log-title { font-size: 12px; font-weight: 600; color: var(--fg2); text-transform: uppercase; letter-spacing: .06em }
pre.log {
  font-family: var(--mono); font-size: 11.5px; color: var(--fg2);
  padding: 14px 16px; overflow-x: auto; white-space: pre-wrap;
  word-break: break-all; max-height: 280px; overflow-y: auto;
  line-height: 1.6;
}
pre.log .ok   { color: var(--green) }
pre.log .err  { color: var(--red) }
pre.log .warn { color: var(--yellow) }

/* ── footer ─── */
footer { text-align: center; font-size: 11px; color: var(--fg2) }
.refresh-indicator { display: inline-flex; align-items: center; gap: 5px }
</style>
</head>
<body>
<div class="shell">

  <!-- header -->
  <header>
    <div class="logo">
      <div class="logo-icon">🌙</div>
      <div>
        <div class="logo-text">Cola Nocturna</div>
        <div class="logo-sub">Renders en espera</div>
      </div>
    </div>
    <div class="header-right">
      <div id="status-pill" class="pill pill-idle"><div class="dot"></div> Inactivo</div>
    </div>
  </header>

  <!-- stats -->
  <div class="stats">
    <div class="stat stat-pending"><div class="stat-n" id="n-pending">—</div><div class="stat-label">En cola</div></div>
    <div class="stat stat-running"><div class="stat-n" id="n-running">—</div><div class="stat-label">Corriendo</div></div>
    <div class="stat stat-done"   ><div class="stat-n" id="n-done">—</div><div class="stat-label">Completados</div></div>
    <div class="stat stat-error"  ><div class="stat-n" id="n-errors">—</div><div class="stat-label">Con error</div></div>
  </div>

  <!-- progress panel -->
  <div class="progress-panel" id="progress-panel">
    <div class="prog-header">
      <div class="prog-title"><div class="dot dot-pulse" style="color:var(--blue)"></div> <span id="prog-title-text">Trabajando...</span></div>
      <div class="prog-counts">Completados: <strong id="prog-done-n">0</strong> · Faltan: <strong id="prog-left-n">0</strong></div>
    </div>
    <div class="prog-track"><div class="prog-fill" id="prog-fill" style="width:0%"></div></div>
    <div class="prog-now" id="prog-now">
      <div style="font-size:24px">🎬</div>
      <div>
        <div class="prog-now-label">Procesando ahora</div>
        <div class="prog-now-name" id="prog-now-name">—</div>
        <div class="prog-now-meta" id="prog-now-meta">—</div>
      </div>
    </div>
    <div class="prog-step">
      <span class="step-chip" id="step-render">Render</span>
      <span class="step-chip" id="step-verify">Verificar</span>
      <span class="step-chip" id="step-upload">Subir</span>
    </div>
  </div>

  <!-- actions -->
  <div class="actions">
    <button class="btn btn-primary" id="btn-run" onclick="runQueue()">▶ Ejecutar cola ahora</button>
    <button class="btn btn-danger"  id="btn-stop" onclick="stopQueue()" style="display:none">■ Detener</button>
    <button class="btn btn-ghost"   onclick="clearHistory()">Limpiar historial</button>
  </div>

  <!-- pending -->
  <div class="section">
    <div class="section-head">
      <div class="section-title">🕐 En cola <span class="section-count" id="c-pending">0</span></div>
    </div>
    <div class="item-list" id="list-pending"><div class="empty">Cola vacía — agrega videos desde el dashboard</div></div>
  </div>

  <!-- running -->
  <div class="section" id="sec-running" style="display:none">
    <div class="section-head">
      <div class="section-title"><div class="dot dot-pulse" style="color:var(--blue)"></div> Corriendo ahora</div>
    </div>
    <div class="item-list" id="list-running"></div>
  </div>

  <!-- done -->
  <div class="section">
    <div class="section-head">
      <div class="section-title">✅ Completados <span class="section-count" id="c-done">0</span></div>
    </div>
    <div class="item-list" id="list-done"><div class="empty">Aún no hay renders completados</div></div>
  </div>

  <!-- errors -->
  <div class="section" id="sec-errors" style="display:none">
    <div class="section-head">
      <div class="section-title">❌ Con error <span class="section-count" id="c-errors">0</span></div>
    </div>
    <div class="item-list" id="list-errors"></div>
  </div>

  <!-- log -->
  <div class="log-wrap">
    <div class="log-head">
      <div class="log-title">📄 Log en tiempo real</div>
      <div class="refresh-indicator"><div class="dot dot-pulse" style="color:var(--accent)"></div><span style="font-size:11px;color:var(--fg2)">actualiza cada 5s</span></div>
    </div>
    <pre class="log" id="log">Esperando actividad...</pre>
  </div>

  <footer>Cola Nocturna · <span id="last-update">—</span></footer>

</div>
<script>
let alive = false
let canales = []
const tokenStatus = {}   // item_id → {status, msg}

async function loadCanales() {
  const r = await fetch('/api/canales')
  canales = await r.json()
}

function fmtTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleTimeString('es-MX', {hour:'2-digit',minute:'2-digit'})
}

function dur(start, end) {
  if (!start) return ''
  const s = (new Date(end || Date.now()) - new Date(start)) / 1000
  const m = Math.floor(s / 60), sec = Math.floor(s % 60)
  return m > 0 ? `${m}m ${sec}s` : `${sec}s`
}

function tokenLabel(id) {
  const t = tokenStatus[id]
  if (!t) return `<button class="token-badge token-unknown" onclick="checkToken('${id}')">⚡ Verificar token</button>`
  const labels = {valid:'✓ Token OK', refreshed:'✓ Token renovado', revoked:'✗ Revocado', no_token:'⚠ Sin token', error:'✗ Error'}
  return `<button class="token-badge token-${t.status}" title="${t.msg}" onclick="checkToken('${id}')">${labels[t.status]||t.status}</button>`
}

function canalSelector(item) {
  if (item.status !== 'pending') {
    return item.canal ? `<span style="font-size:11px;color:var(--fg2)">📺 ${item.canal}</span>` : ''
  }
  const opts = canales.map(c =>
    `<option value="${c}" ${item.canal===c?'selected':''}>${c}</option>`
  ).join('')
  return `<div class="canal-row">
    <select class="canal-select" onchange="setCanal('${item.id}', this.value)">
      <option value="">— elige canal —</option>
      ${opts}
    </select>
    ${item.canal ? tokenLabel(item.id) : ''}
  </div>`
}

function renderItem(item, withProgress) {
  const icons = {pending:'⏳', running:'▶️', done:'✅', error:'❌'}
  const started = item.started_at ? `Iniciado ${fmtTime(item.started_at)}` : `Agregado ${fmtTime(item.added_at)}`
  const duration = item.started_at ? dur(item.started_at, item.finished_at) : ''
  const prog = withProgress ? `<div class="progress-wrap"><div class="progress-bar"></div></div>` : ''
  const pill = item.status === 'done'
    ? `<span class="pill pill-done">✓ Listo</span>`
    : item.status === 'error'
    ? `<span class="pill pill-error">✗ Error</span>`
    : item.status === 'running'
    ? `<span class="pill pill-running">Corriendo</span>`
    : `<span class="pill pill-pending">En cola</span>`
  return `<div class="item">
    <div class="item-icon">${icons[item.status] || '⏳'}</div>
    <div class="item-body">
      <div class="item-name">${item.nombre || item.personaje}</div>
      <div class="item-meta">${item.carpeta} · ${started}</div>
      ${canalSelector(item)}
      ${prog}
    </div>
    <div class="item-right">
      ${duration ? `<div class="item-dur">${duration}</div>` : ''}
      ${pill}
    </div>
  </div>`
}

async function setCanal(id, canal) {
  await fetch('/api/set_canal', {method:'POST', body: JSON.stringify({id, canal}),
    headers:{'Content-Type':'application/json'}})
  if (canal) checkToken(id)
  else delete tokenStatus[id]
}

async function checkToken(id) {
  // find canal for this item
  const r0 = await fetch('/api/queue')
  const d0  = await r0.json()
  const all  = [...d0.pending, ...d0.running]
  const item = all.find(x => x.id === id)
  if (!item || !item.canal) return
  const badge = document.querySelector(`[onclick="checkToken('${id}')"]`)
  if (badge) { badge.textContent = '…'; badge.className = 'token-badge token-unknown' }
  const r = await fetch('/api/check_token', {method:'POST',
    body: JSON.stringify({canal: item.canal}), headers:{'Content-Type':'application/json'}})
  const d = await r.json()
  tokenStatus[id] = {status: d.status, msg: d.msg}
  // re-render just that item's badge
  if (badge) {
    const labels = {valid:'✓ Token OK', refreshed:'✓ Token renovado', revoked:'✗ Revocado', no_token:'⚠ Sin token', error:'✗ Error'}
    badge.textContent = labels[d.status] || d.status
    badge.className   = `token-badge token-${d.status}`
    badge.title       = d.msg
  }
  if (d.status === 'revoked' || d.status === 'no_token') {
    alert(`⚠️ ${item.canal}: ${d.msg}\n\nNecesitas re-autorizar este canal antes de continuar.`)
  }
}

function colorLog(text) {
  return text
    .replace(/✅[^\n]*/g, m => `<span class="ok">${m}</span>`)
    .replace(/❌[^\n]*/g, m => `<span class="err">${m}</span>`)
    .replace(/⚠[^\n]*/g, m => `<span class="warn">${m}</span>`)
    .replace(/ERROR[^\n]*/g, m => `<span class="err">${m}</span>`)
}

async function refresh() {
  try {
    const r = await fetch('/api/queue')
    const d = await r.json()
    alive = d.alive

    // stats
    document.getElementById('n-pending').textContent = d.pending.length
    document.getElementById('n-running').textContent = d.running.length
    document.getElementById('n-done').textContent    = d.done.length
    document.getElementById('n-errors').textContent  = d.errors.length
    document.getElementById('c-pending').textContent = d.pending.length
    document.getElementById('c-done').textContent    = d.done.length
    document.getElementById('c-errors').textContent  = d.errors.length

    // status pill
    const pill = document.getElementById('status-pill')
    if (d.alive) {
      pill.className = 'pill pill-running'
      pill.innerHTML = '<div class="dot dot-pulse"></div> Corriendo'
    } else if (d.errors.length) {
      pill.className = 'pill pill-error'
      pill.innerHTML = '<div class="dot"></div> Errores'
    } else if (d.done.length && !d.pending.length) {
      pill.className = 'pill pill-done'
      pill.innerHTML = '<div class="dot"></div> Completado'
    } else {
      pill.className = 'pill pill-idle'
      pill.innerHTML = '<div class="dot"></div> Inactivo'
    }

    // buttons
    document.getElementById('btn-run').disabled = d.alive || d.pending.length === 0
    document.getElementById('btn-stop').style.display = d.alive ? '' : 'none'

    // lists
    const lp = document.getElementById('list-pending')
    lp.innerHTML = d.pending.length
      ? d.pending.map(x => renderItem(x, false)).join('')
      : '<div class="empty">Cola vacía — agrega videos desde el dashboard</div>'

    const secR = document.getElementById('sec-running')
    const lr   = document.getElementById('list-running')
    if (d.running.length) {
      secR.style.display = ''
      lr.innerHTML = d.running.map(x => renderItem(x, true)).join('')
    } else {
      secR.style.display = 'none'
    }

    const ld = document.getElementById('list-done')
    ld.innerHTML = d.done.length
      ? [...d.done].reverse().map(x => renderItem(x, false)).join('')
      : '<div class="empty">Aún no hay renders completados</div>'

    const secE = document.getElementById('sec-errors')
    const le   = document.getElementById('list-errors')
    if (d.errors.length) {
      secE.style.display = ''
      le.innerHTML = [...d.errors].reverse().map(x => renderItem(x, false)).join('')
    } else {
      secE.style.display = 'none'
    }

    // progress panel
    const panel = document.getElementById('progress-panel')
    if (d.alive || d.running.length) {
      panel.classList.add('visible')
      const total    = d.done.length + d.errors.length + d.running.length + d.pending.length
      const finished = d.done.length + d.errors.length
      const left     = d.pending.length
      const pct      = total > 0 ? Math.round(finished / total * 100) : 0
      document.getElementById('prog-fill').style.width    = pct + '%'
      document.getElementById('prog-done-n').textContent  = finished
      document.getElementById('prog-left-n').textContent  = left
      if (d.running.length) {
        const cur = d.running[0]
        const name = cur.nombre || cur.personaje
        document.getElementById('prog-now-name').textContent  = name
        document.getElementById('prog-now-meta').textContent  = cur.carpeta + (cur.started_at ? ' · iniciado ' + fmtTime(cur.started_at) : '')
        document.getElementById('prog-title-text').textContent = `Trabajando en: ${name}`
        // derive step from log tail
        const log = d.log || ''
        const hasUpload  = log.includes('Subiendo')  || log.includes('Subido')
        const hasVerify  = log.includes('verificando') || log.includes('verificar')
        const hasRender  = log.includes('Iniciando') || log.includes('Render OK') || log.includes('render')
        document.getElementById('step-render').className  = 'step-chip' + (hasRender ? (hasVerify || hasUpload ? ' done' : ' active') : '')
        document.getElementById('step-verify').className  = 'step-chip' + (hasVerify ? (hasUpload ? ' done' : ' active') : '')
        document.getElementById('step-upload').className  = 'step-chip' + (hasUpload ? ' active' : '')
      } else {
        document.getElementById('prog-title-text').textContent = 'Procesando cola...'
        document.getElementById('prog-now-name').textContent   = '—'
        document.getElementById('prog-now-meta').textContent   = '—'
      }
    } else {
      panel.classList.remove('visible')
    }

    // log
    const pre = document.getElementById('log')
    const atBottom = pre.scrollHeight - pre.scrollTop <= pre.clientHeight + 30
    pre.innerHTML = colorLog(d.log || 'Esperando actividad...')
    if (atBottom) pre.scrollTop = pre.scrollHeight

    document.getElementById('last-update').textContent =
      new Date().toLocaleTimeString('es-MX', {hour:'2-digit',minute:'2-digit',second:'2-digit'})

  } catch(e) {
    console.warn('refresh error', e)
  }
}

async function runQueue() {
  const btn = document.getElementById('btn-run')
  btn.disabled = true
  const r = await fetch('/api/run', {method:'POST'})
  const d = await r.json()
  if (!d.ok) { alert(d.msg); btn.disabled = false }
  else setTimeout(refresh, 500)
}

async function stopQueue() {
  if (!confirm('¿Detener el runner? El render actual puede quedar incompleto.')) return
  await fetch('/api/stop', {method:'POST'})
  setTimeout(refresh, 500)
}

async function clearHistory() {
  if (!confirm('¿Limpiar el historial de completados y errores?')) return
  await fetch('/api/clear_history', {method:'POST'})
  refresh()
}

loadCanales().then(refresh)
setInterval(refresh, 5000)
</script>
</body>
</html>"""

@app.route("/")
def index():
    return HTML

if __name__ == "__main__":
    print(f"🌙 Cola Nocturna Dashboard → http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
