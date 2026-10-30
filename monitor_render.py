#!/usr/bin/env python3
"""
monitor_render.py — Monitor visual de renders en tiempo real.
Uso: python3 monitor_render.py
Abre http://localhost:5099
"""
import threading, pathlib, re, time, json
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

def get_log_file():
    """Devuelve el log de render más reciente en /tmp/"""
    logs = sorted(pathlib.Path("/tmp").glob("render_*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
    return logs[0] if logs else pathlib.Path("/tmp/render_mono.log")

HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Monitor Render</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0d0d0d; color: #e0e0e0; font-family: 'Courier New', monospace; padding: 24px; }
  h1 { font-size: 18px; color: #fff; margin-bottom: 20px; letter-spacing: 2px; text-transform: uppercase; }
  .card { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 10px; padding: 20px; margin-bottom: 16px; }
  .label { font-size: 11px; color: #666; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; }
  .value { font-size: 28px; font-weight: bold; color: #fff; }
  .sub { font-size: 13px; color: #888; margin-top: 4px; }
  .bar-bg { background: #111; border-radius: 6px; height: 14px; margin-top: 10px; overflow: hidden; }
  .bar-fill { height: 100%; border-radius: 6px; background: linear-gradient(90deg, #00c853, #69f0ae); transition: width 1s ease; }
  .grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; }
  .log-box { background: #0a0a0a; border: 1px solid #222; border-radius: 8px; padding: 14px; height: 220px; overflow-y: auto; font-size: 12px; line-height: 1.7; }
  .log-line { color: #aaa; }
  .log-line.ok { color: #69f0ae; }
  .log-line.err { color: #ff5252; }
  .log-line.warn { color: #ffd740; }
  .log-line.prog { color: #82b1ff; }
  .status-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 8px; }
  .dot-running { background: #69f0ae; animation: pulse 1.5s infinite; }
  .dot-done { background: #fff; }
  .dot-error { background: #ff5252; }
  .dot-idle { background: #555; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
  .status-row { display: flex; align-items: center; font-size: 14px; margin-bottom: 16px; }
  .eta { color: #ffd740; font-size: 20px; font-weight: bold; }
</style>
</head>
<body>
<h1>⚙ Monitor Render</h1>
<div id="status-row" class="status-row">
  <span class="status-dot dot-idle" id="dot"></span>
  <span id="status-text">Cargando...</span>
</div>
<div class="grid">
  <div class="card">
    <div class="label">Progreso</div>
    <div class="value" id="pct">—%</div>
    <div class="bar-bg"><div class="bar-fill" id="bar" style="width:0%"></div></div>
    <div class="sub" id="planos">—</div>
  </div>
  <div class="card">
    <div class="label">Video construido</div>
    <div class="value" id="built">—</div>
    <div class="sub" id="total-dur">de — seg</div>
  </div>
  <div class="card">
    <div class="label">Tiempo restante est.</div>
    <div class="eta" id="eta">—</div>
    <div class="sub" id="elapsed">—</div>
  </div>
</div>
<div class="card" style="margin-top:0">
  <div class="label" style="margin-bottom:10px">Log en vivo</div>
  <div class="log-box" id="log"></div>
</div>

<script>
let startTime = null;

function fmt(s) {
  s = Math.round(s);
  const m = Math.floor(s/60), sec = s%60;
  return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
}

async function poll() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();

    const dot = document.getElementById('dot');
    const stxt = document.getElementById('status-text');
    dot.className = 'status-dot';
    if (d.running) { dot.classList.add('dot-running'); stxt.textContent = 'Renderizando...'; }
    else if (d.done) { dot.classList.add('dot-done'); stxt.textContent = '✅ Render completado'; }
    else if (d.error) { dot.classList.add('dot-error'); stxt.textContent = '❌ Error en render'; }
    else { dot.classList.add('dot-idle'); stxt.textContent = 'Sin render activo'; }

    if (d.pct !== null) {
      document.getElementById('pct').textContent = d.pct + '%';
      document.getElementById('bar').style.width = d.pct + '%';
    }
    if (d.planos) document.getElementById('planos').textContent = 'Plano ' + d.planos;
    if (d.built !== null) document.getElementById('built').textContent = fmt(d.built);
    if (d.total !== null) document.getElementById('total-dur').textContent = 'de ' + Math.round(d.total) + ' seg';

    if (d.running && d.pct > 0) {
      if (!startTime) startTime = Date.now() - (d.elapsed_s || 0) * 1000;
      const elapsed = (Date.now() - startTime) / 1000;
      const remaining = elapsed / (d.pct / 100) - elapsed;
      document.getElementById('eta').textContent = fmt(remaining);
      document.getElementById('elapsed').textContent = 'Transcurrido: ' + fmt(elapsed);
    } else if (d.done) {
      document.getElementById('eta').textContent = '—';
    }

    // Log
    const logEl = document.getElementById('log');
    const atBottom = logEl.scrollHeight - logEl.scrollTop < logEl.clientHeight + 40;
    logEl.innerHTML = d.lines.map(l => {
      let cls = 'log-line';
      if (l.includes('✓') || l.includes('✅')) cls += ' ok';
      else if (l.includes('✗') || l.includes('❌') || l.includes('Error') || l.includes('FALLÓ')) cls += ' err';
      else if (l.includes('⚠')) cls += ' warn';
      else if (l.match(/\\[\\d+\\]/)) cls += ' prog';
      return `<div class="${cls}">${l.replace(/\x1b\[[0-9;]*m/g,'')}</div>`;
    }).join('');
    if (atBottom) logEl.scrollTop = logEl.scrollHeight;

  } catch(e) {}
  setTimeout(poll, 2000);
}
poll();
</script>
</body>
</html>"""

def parse_log():
    LOG_FILE = get_log_file()
    if not LOG_FILE.exists():
        return {"running": False, "done": False, "error": False, "pct": None,
                "built": None, "total": None, "planos": None, "lines": [], "elapsed_s": 0}

    lines = LOG_FILE.read_text(errors="replace").splitlines()
    tail  = lines[-60:] if len(lines) > 60 else lines

    pct = built = total = planos = None
    done = error = False

    for l in lines:
        # Duración total del audio
        m = re.search(r'Audio: ([\d.]+)s', l)
        if m: total = float(m.group(1))

        # Progreso: [120] 38% — 623s / 1644s
        m = re.search(r'\[(\d+)\]\s+(\d+)%\s*—\s*([\d.]+)s\s*/\s*([\d.]+)s', l)
        if m:
            planos = m.group(1)
            pct    = int(m.group(2))
            built  = float(m.group(3))
            total  = float(m.group(4))

        if '✅' in l and 'Render' in l and 'FALLÓ' not in l:
            done = True
        if 'FALLÓ' in l or '❌' in l:
            error = True

    # ¿Sigue corriendo?
    running = False
    if not done and not error:
        import subprocess
        r = subprocess.run(["pgrep", "-f", "render_farandula_mono"], capture_output=True)
        running = r.returncode == 0

    return {
        "running": running, "done": done, "error": error,
        "pct": pct, "built": built, "total": total,
        "planos": planos, "lines": tail, "elapsed_s": 0
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML.encode())
        elif self.path == "/api/status":
            data = parse_log()
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a): pass


class ThreadedServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    srv = ThreadedServer(("127.0.0.1", 5099), Handler)
    print("Monitor en http://localhost:5099  (Ctrl+C para salir)")
    import webbrowser
    threading.Timer(0.5, lambda: webbrowser.open("http://localhost:5099")).start()
    srv.serve_forever()
