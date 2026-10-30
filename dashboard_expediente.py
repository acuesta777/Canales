#!/usr/bin/env python3
"""
dashboard_expediente.py — Aprobación de clips para canal Expediente de Famosos.
Puerto 5004. Abre http://localhost:5004

Flujo:
  1. Selecciona personaje en el sidebar
  2. Revisa clips (video preview al hover)
  3. Rechaza los que no sirven
  4. "Aprobar todos" guarda clips_order en metadata.json
  5. Corre: python3 nocturno_expediente.py --solo-render
"""

import json, pathlib, re, random, subprocess, sys
from flask import Flask, Response, jsonify, request, render_template_string

BASE  = pathlib.Path(__file__).parent
NICHO = "expediente"

app = Flask(__name__)

# ── helpers ────────────────────────────────────────────────────────────────────

def _clip_idx(f):
    m = re.search(r"(\d+)", f.stem)
    return int(m.group(1)) if m else 0

def meta_path(slug):
    return BASE / NICHO / slug / "metadata.json"

def read_meta(slug):
    p = meta_path(slug)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))

def save_meta(slug, meta):
    meta_path(slug).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

def personajes():
    base = BASE / NICHO
    if not base.exists():
        return []
    return sorted([d.name for d in base.iterdir()
                   if d.is_dir() and (d / "clips").exists()])

def clip_files(slug):
    clips_dir = BASE / NICHO / slug / "clips"
    if not clips_dir.exists():
        return []
    return sorted([f for f in clips_dir.glob("*.mp4") if re.search(r"\d+", f.stem)],
                  key=_clip_idx)

def clips_status(slug):
    meta     = read_meta(slug)
    rejected = set(meta.get("rejected_yt_clips", {}).keys())
    deleted  = set(meta.get("deleted_yt_clips", {}).keys())
    order    = meta.get("clips_order", [])
    files    = clip_files(slug)
    clips = []
    for f in files:
        estado = "rechazado" if f.name in rejected else \
                 "eliminado"  if f.name in deleted  else "pendiente"
        clips.append({"name": f.name, "estado": estado})
    return clips, bool(order)

# ── video serving ──────────────────────────────────────────────────────────────

def _serve_video(path):
    path = pathlib.Path(path)
    size = path.stat().st_size
    rng  = request.headers.get("Range")
    if rng:
        parts = rng.replace("bytes=", "").split("-")
        start = int(parts[0])
        end   = int(parts[1]) if parts[1] else size - 1
        length = end - start + 1
        def gen():
            with open(path, "rb") as f:
                f.seek(start)
                rem = length
                while rem > 0:
                    chunk = f.read(min(524288, rem))
                    if not chunk: break
                    rem -= len(chunk)
                    yield chunk
        r = Response(gen(), 206, mimetype="video/mp4", direct_passthrough=True)
        r.headers["Content-Range"]  = f"bytes {start}-{end}/{size}"
        r.headers["Accept-Ranges"]  = "bytes"
        r.headers["Content-Length"] = str(length)
        return r
    r = Response(open(path, "rb"), 200, mimetype="video/mp4", direct_passthrough=True)
    r.headers["Accept-Ranges"]  = "bytes"
    r.headers["Content-Length"] = str(size)
    return r

@app.route("/clip/<slug>/<clip_name>")
def serve_clip(slug, clip_name):
    p = BASE / NICHO / slug / "clips" / clip_name
    if not p.exists():
        return "Not found", 404
    return _serve_video(p)

# ── APIs ───────────────────────────────────────────────────────────────────────

@app.route("/api/clips/<slug>")
def api_clips(slug):
    clips, aprobado = clips_status(slug)
    meta = read_meta(slug)
    activos = [c for c in clips if c["estado"] == "pendiente"]
    return jsonify({
        "clips":    clips,
        "total":    len(clips),
        "activos":  len(activos),
        "aprobado": aprobado,
        "titulo":   meta.get("titulo", slug),
    })

@app.route("/api/rechazar/<slug>", methods=["POST"])
def api_rechazar(slug):
    data = request.get_json(force=True)
    name = data.get("clip")
    if not name:
        return jsonify({"ok": False}), 400
    meta = read_meta(slug)
    meta.setdefault("rejected_yt_clips", {})[name] = True
    save_meta(slug, meta)
    return jsonify({"ok": True})

@app.route("/api/restaurar/<slug>", methods=["POST"])
def api_restaurar(slug):
    data = request.get_json(force=True)
    name = data.get("clip")
    meta = read_meta(slug)
    meta.get("rejected_yt_clips", {}).pop(name, None)
    save_meta(slug, meta)
    return jsonify({"ok": True})

@app.route("/api/aprobar/<slug>", methods=["POST"])
def api_aprobar(slug):
    data    = request.get_json(force=True)
    order   = data.get("clips_order", [])
    meta    = read_meta(slug)
    rejected = set(meta.get("rejected_yt_clips", {}).keys())
    if not order:
        files = [f.name for f in clip_files(slug) if f.name not in rejected]
        random.shuffle(files)
        order = files
    meta["clips_order"] = order
    save_meta(slug, meta)
    return jsonify({"ok": True, "clips_order": len(order)})

# ── UI ─────────────────────────────────────────────────────────────────────────

PAGE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Expediente — Aprobación de clips</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d0d0d;color:#e0e0e0;font-family:monospace;display:flex;height:100vh;overflow:hidden}
/* sidebar */
#sidebar{width:220px;min-width:220px;background:#111;border-right:1px solid #222;overflow-y:auto;padding:12px 0}
#sidebar h2{font-size:11px;color:#555;padding:8px 14px;letter-spacing:2px;text-transform:uppercase}
.pers-btn{display:block;width:100%;text-align:left;background:none;border:none;color:#aaa;padding:9px 14px;cursor:pointer;font-size:12px;font-family:monospace;border-left:3px solid transparent;transition:.15s}
.pers-btn:hover{color:#fff;background:#1a1a1a}
.pers-btn.active{color:#0f0;border-left-color:#0f0;background:#151515}
.pers-badge{float:right;font-size:10px;padding:1px 5px;border-radius:10px;background:#222;color:#666}
.pers-badge.ok{background:#0a2a0a;color:#0f0}
/* main */
#main{flex:1;display:flex;flex-direction:column;overflow:hidden}
#toolbar{background:#111;border-bottom:1px solid #222;padding:10px 16px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
#toolbar h1{font-size:13px;color:#0f0;flex:1;min-width:120px}
#stats{font-size:11px;color:#666}
#btn-aprobar{background:#0f0;color:#000;border:none;padding:7px 18px;font-size:12px;font-family:monospace;font-weight:bold;cursor:pointer;border-radius:3px}
#btn-aprobar:disabled{background:#1a3a1a;color:#3a6a3a;cursor:not-allowed}
#btn-aprobar.done{background:#0a2a0a;color:#0f0;cursor:default}
#grid{flex:1;overflow-y:auto;padding:14px;display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px;align-content:start}
/* card */
.card{position:relative;border-radius:5px;overflow:hidden;background:#1a1a1a;border:1px solid #2a2a2a;cursor:pointer;transition:.15s}
.card:hover{border-color:#444}
.card.rechazado{opacity:.3;border-color:#500}
.card.rechazado:hover{opacity:.5}
.card video{width:100%;height:90px;object-fit:cover;display:block;background:#000}
.card-label{font-size:9px;color:#555;padding:4px 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.card-X{position:absolute;top:3px;right:3px;background:rgba(200,0,0,.8);color:#fff;border:none;border-radius:50%;width:18px;height:18px;font-size:10px;cursor:pointer;display:flex;align-items:center;justify-content:center;font-family:monospace}
.card-X:hover{background:red}
.card.rechazado .card-X{background:rgba(0,150,0,.7)}
.card.rechazado .card-X:hover{background:green}
#empty{color:#444;font-size:13px;padding:40px;text-align:center;grid-column:1/-1}
</style>
</head>
<body>
<div id="sidebar">
  <h2>Personajes</h2>
  <div id="pers-list"></div>
</div>
<div id="main">
  <div id="toolbar">
    <h1 id="titulo">← Selecciona un personaje</h1>
    <span id="stats"></span>
    <button id="btn-aprobar" disabled onclick="aprobarTodos()">✓ Aprobar todos</button>
  </div>
  <div id="grid"><div id="empty">Selecciona un personaje en el sidebar</div></div>
</div>

<script>
const PERSONAJES = {{PERSONAJES}};
let currentSlug = null;
let clipsData   = [];

// ── sidebar ──────────────────────────────────────────────────────────────────
function renderSidebar() {
  const list = document.getElementById('pers-list');
  list.innerHTML = '';
  PERSONAJES.forEach(slug => {
    const btn = document.createElement('button');
    btn.className = 'pers-btn';
    btn.dataset.slug = slug;
    btn.innerHTML = slug.replace(/_/g,' ') + '<span class="pers-badge" id="badge-'+slug+'">…</span>';
    btn.onclick = () => loadPersonaje(slug);
    list.appendChild(btn);
  });
  // cargar badges
  PERSONAJES.forEach(slug => {
    fetch('/api/clips/'+slug).then(r=>r.json()).then(d=>{
      const b = document.getElementById('badge-'+slug);
      if (!b) return;
      b.textContent = d.aprobado ? '✓' : d.activos;
      if (d.aprobado) b.className = 'pers-badge ok';
    });
  });
}

// ── personaje ────────────────────────────────────────────────────────────────
async function loadPersonaje(slug) {
  currentSlug = slug;
  document.querySelectorAll('.pers-btn').forEach(b => b.classList.toggle('active', b.dataset.slug===slug));
  document.getElementById('grid').innerHTML = '<div id="empty">Cargando…</div>';
  document.getElementById('btn-aprobar').disabled = true;

  const d = await fetch('/api/clips/'+slug).then(r=>r.json());
  clipsData = d.clips;
  document.getElementById('titulo').textContent = d.titulo || slug;
  renderGrid(d);
}

function renderGrid(d) {
  const grid = document.getElementById('grid');
  const activos = d.clips.filter(c=>c.estado==='pendiente').length;
  const rechazados = d.clips.filter(c=>c.estado==='rechazado').length;
  document.getElementById('stats').textContent =
    activos + ' activos · ' + rechazados + ' rechazados · ' + d.clips.length + ' total';

  const btn = document.getElementById('btn-aprobar');
  if (d.aprobado) {
    btn.textContent = '✓ Ya aprobado';
    btn.className = 'done';
    btn.disabled = false;
  } else {
    btn.textContent = '✓ Aprobar todos (' + activos + ')';
    btn.disabled = activos === 0;
    btn.className = '';
  }

  if (!d.clips.length) {
    grid.innerHTML = '<div id="empty">Sin clips</div>';
    return;
  }

  grid.innerHTML = '';
  d.clips.forEach(clip => {
    const card = document.createElement('div');
    card.className = 'card' + (clip.estado==='rechazado'?' rechazado':'');
    card.id = 'card-'+clip.name;
    card.innerHTML = `
      <video src="/clip/${currentSlug}/${clip.name}" muted preload="none"
        onmouseenter="this.play()" onmouseleave="this.pause();this.currentTime=0"></video>
      <div class="card-label">${clip.name}</div>
      <button class="card-X" onclick="toggleRechazo(event,'${clip.name}')" title="${clip.estado==='rechazado'?'Restaurar':'Rechazar'}">
        ${clip.estado==='rechazado'?'↩':'✕'}
      </button>`;
    grid.appendChild(card);
  });
}

async function toggleRechazo(e, name) {
  e.stopPropagation();
  const clip = clipsData.find(c=>c.name===name);
  if (!clip) return;
  const endpoint = clip.estado==='rechazado' ? '/api/restaurar/'+currentSlug : '/api/rechazar/'+currentSlug;
  await fetch(endpoint, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({clip: name})});
  clip.estado = clip.estado==='rechazado' ? 'pendiente' : 'rechazado';
  const card = document.getElementById('card-'+name);
  card.classList.toggle('rechazado', clip.estado==='rechazado');
  card.querySelector('.card-X').textContent = clip.estado==='rechazado' ? '↩' : '✕';
  card.querySelector('.card-X').title = clip.estado==='rechazado' ? 'Restaurar' : 'Rechazar';
  updateStats();
  updateBadge();
}

function updateStats() {
  const activos    = clipsData.filter(c=>c.estado==='pendiente').length;
  const rechazados = clipsData.filter(c=>c.estado==='rechazado').length;
  document.getElementById('stats').textContent =
    activos + ' activos · ' + rechazados + ' rechazados · ' + clipsData.length + ' total';
  const btn = document.getElementById('btn-aprobar');
  if (!btn.classList.contains('done')) {
    btn.textContent = '✓ Aprobar todos (' + activos + ')';
    btn.disabled = activos === 0;
  }
}

function updateBadge() {
  const b = document.getElementById('badge-'+currentSlug);
  if (!b) return;
  const activos = clipsData.filter(c=>c.estado==='pendiente').length;
  b.textContent = activos;
  b.className = 'pers-badge';
}

async function aprobarTodos() {
  if (!currentSlug) return;
  const activos = clipsData.filter(c=>c.estado==='pendiente').map(c=>c.name);
  const shuffled = [...activos].sort(()=>Math.random()-.5);
  const r = await fetch('/api/aprobar/'+currentSlug, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({clips_order: shuffled})
  });
  const d = await r.json();
  if (d.ok) {
    const btn = document.getElementById('btn-aprobar');
    btn.textContent = '✓ Aprobado (' + d.clips_order + ' clips)';
    btn.className = 'done';
    const b = document.getElementById('badge-'+currentSlug);
    if (b) { b.textContent='✓'; b.className='pers-badge ok'; }
    // auto-cargar siguiente
    const idx = PERSONAJES.indexOf(currentSlug);
    if (idx >= 0 && idx < PERSONAJES.length-1) {
      setTimeout(()=>loadPersonaje(PERSONAJES[idx+1]), 800);
    }
  }
}

renderSidebar();
if (PERSONAJES.length) loadPersonaje(PERSONAJES[0]);
</script>
</body>
</html>
"""

@app.route("/")
def index():
    p_list = personajes()
    html = PAGE.replace("{{PERSONAJES}}", json.dumps(p_list))
    return html

if __name__ == "__main__":
    print("\n" + "="*50)
    print("  EXPEDIENTE CLIPS  →  http://localhost:5004")
    print("="*50 + "\n")
    app.run(host="0.0.0.0", port=5004, threaded=True)
