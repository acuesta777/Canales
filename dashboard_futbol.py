#!/usr/bin/env python3
"""
dashboard_futbol.py — Secuencia completa de los primeros 10 minutos.

Muestra clip por clip en orden temporal (0-600s):
  - Imágenes Flow en sus timestamps exactos
  - Clips del video llenando los huecos

El usuario puede rechazar cualquier clip irrelevante.

Uso:
    python3 dashboard_futbol.py futbol/rene_higuita/
    → http://localhost:5003
"""

import sys, json, pathlib, subprocess, math
from flask import Flask, jsonify, send_file, request, abort

PORT = 5003
SRT_MAX = 600  # 10 min

if len(sys.argv) < 2:
    print("Uso: python3 dashboard_futbol.py futbol/personaje/")
    sys.exit(1)

CARPETA    = pathlib.Path(sys.argv[1]).resolve()
FLOW_META  = CARPETA / "flow_meta.json"
FLOW_DIR   = CARPETA / "flow_images"
CLIPS_DIR  = CARPETA / "clips"
THUMBS_DIR = CARPETA / "thumbs"
RECHAZADOS = CARPETA / "clips_rechazados.json"
SEQ_CACHE  = CARPETA / "sequence_cache.json"

THUMBS_DIR.mkdir(exist_ok=True)
FLOW_DIR.mkdir(exist_ok=True)

app = Flask(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_json(p, default):
    if p.exists():
        try: return json.loads(p.read_text())
        except: pass
    return default

def save_json(p, d):
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2))

def get_clip_duration(path):
    cmd = ["/opt/homebrew/bin/ffprobe", "-v", "quiet",
           "-print_format", "json", "-show_streams", str(path)]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=5)
        d = json.loads(r.stdout)
        for s in d.get("streams", []):
            if s.get("duration"):
                return float(s["duration"])
    except: pass
    return 5.0

def make_thumb(clip_path, thumb_path):
    if thumb_path.exists(): return True
    ffmpeg = "/opt/homebrew/bin/ffmpeg"
    ffprobe = "/opt/homebrew/bin/ffprobe"
    # Detectar duración para elegir timestamp
    try:
        r = subprocess.run([ffprobe, "-v", "quiet", "-print_format", "json",
                            "-show_streams", str(clip_path)],
                           capture_output=True, timeout=5)
        dur = 5.0
        for s in json.loads(r.stdout).get("streams", []):
            if s.get("duration"):
                dur = float(s["duration"]); break
    except: dur = 5.0
    # Probar varios timestamps hasta encontrar frame no negro
    for ss in [min(2, dur*0.4), min(1, dur*0.2), min(3, dur*0.6), 0.5]:
        tmp = thumb_path.with_suffix(".tmp.jpg")
        cmd = [ffmpeg, "-y", "-ss", str(ss), "-i", str(clip_path),
               "-vframes", "1",
               "-vf", "scale=320:180:force_original_aspect_ratio=decrease,pad=320:180:(ow-iw)/2:(oh-ih)/2",
               "-q:v", "5", str(tmp)]
        try:
            subprocess.run(cmd, capture_output=True, timeout=10)
        except: continue
        if not tmp.exists(): continue
        # Verificar brillo medio (>5 = no negro)
        cp = subprocess.run([ffprobe, "-v", "quiet", "-f", "lavfi",
                             f"-i", f"movie={tmp},signalstats",
                             "-show_entries", "frame_tags=lavfi.signalstats.YAVG",
                             "-print_format", "csv"],
                            capture_output=True, timeout=5)
        try:
            yavg = float(cp.stdout.decode().strip().split(",")[-1])
        except: yavg = 50
        if yavg > 5:
            tmp.rename(thumb_path); return True
        tmp.unlink(missing_ok=True)
    # Fallback: primer frame
    cmd = [ffmpeg, "-y", "-ss", "0", "-i", str(clip_path), "-vframes", "1",
           "-vf", "scale=320:180:force_original_aspect_ratio=decrease,pad=320:180:(ow-iw)/2:(oh-ih)/2",
           "-q:v", "5", str(thumb_path)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=10)
    except: pass
    return thumb_path.exists()

def make_flow_thumb(img_path, thumb_path):
    if thumb_path.exists(): return True
    cmd = ["/opt/homebrew/bin/ffmpeg", "-y", "-i", str(img_path),
           "-vf", "scale=320:180:force_original_aspect_ratio=decrease,pad=320:180:(ow-iw)/2:(oh-ih)/2",
           "-q:v", "5", str(thumb_path)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=15)
        return thumb_path.exists()
    except: return False

def fmt(s):
    m, sec = int(s // 60), int(s % 60)
    return f"{m:02d}:{sec:02d}"

# ─────────────────────────────────────────────────────────────────────────────
# Construir la secuencia de 10 minutos
# ─────────────────────────────────────────────────────────────────────────────

def build_sequence():
    """
    Construye la lista ordenada de slots para los primeros 10 min:
      - Cada slot de Flow va en su timestamp exacto
      - Los huecos entre Flow se llenan con clips del video (5s c/u)
    Retorna lista de dicts con: idx, type(flow/clip), start, end, duration, ...
    """
    flow_segs  = load_json(FLOW_META, [])
    rechazados = load_json(RECHAZADOS, {})  # {path: True} para clips, {flow_SID: True} para flow

    # Clips disponibles: excluir los que están en la blacklist (por path)
    all_clips = sorted(CLIPS_DIR.glob("*.mp4")) if CLIPS_DIR.exists() else []
    pool = [c for c in all_clips if not rechazados.get(str(c))]

    # Construir mapa de ocupación Flow: lista de (start, end, seg)
    flow_sorted = sorted(flow_segs, key=lambda s: s.get("start", 0))
    # Filtrar solo los que tienen imagen descargada
    flow_with_img = [(s["start"], s["end"], s) for s in flow_sorted
                     if (FLOW_DIR / f"flow_{s['segment_id']:04d}.jpg").exists()
                     and s.get("start", 0) <= SRT_MAX]

    sequence = []
    idx = 0
    clip_idx = 0
    t = 0.0
    CLIP_DUR = 5.0

    for (f_start, f_end, seg) in flow_with_img:
        # Llenar huecos antes de este Flow
        while t < f_start - 0.5 and clip_idx < len(pool):
            slot_end = min(t + CLIP_DUR, f_start)
            dur = slot_end - t
            clip = pool[clip_idx % len(pool)]
            rechaz = rechazados.get(f"clip_{idx}", False)
            sequence.append({
                "idx": idx,
                "type": "clip",
                "start": round(t, 2),
                "end":   round(slot_end, 2),
                "duration": round(dur, 2),
                "path": str(clip),
                "name": clip.name,
                "pool_idx": clip_idx,
                "rechazado": rechaz,
            })
            idx += 1
            clip_idx += 1
            t = slot_end
            if t >= f_start - 0.5:
                break

        # Insertar slot Flow
        rechaz = rechazados.get(f"flow_{seg['segment_id']}", False)
        # No insertar flow rechazados (se excluyen de la secuencia)
        if rechaz:
            idx += 1; t = seg.get("end", f_end); continue
        sequence.append({
            "idx": idx,
            "type": "flow",
            "segment_id": seg["segment_id"],
            "start": round(seg.get("start", f_start), 2),
            "end":   round(seg.get("end", f_end), 2),
            "duration": round(seg.get("duration", f_end - f_start), 2),
            "trigger": seg.get("trigger", seg.get("trigger_type", "")),
            "scene": seg.get("scene", ""),
            "ia_prompt": seg.get("ia_prompt", ""),
            "rechazado": rechaz,
        })
        idx += 1
        t = seg.get("end", f_end)

    # Llenar huecos restantes hasta 10 min
    while t < SRT_MAX and clip_idx < len(pool):
        slot_end = min(t + CLIP_DUR, SRT_MAX)
        clip = pool[clip_idx % len(pool)]
        rechaz = rechazados.get(f"clip_{idx}", False)
        sequence.append({
            "idx": idx,
            "type": "clip",
            "start": round(t, 2),
            "end":   round(slot_end, 2),
            "duration": round(slot_end - t, 2),
            "path": str(clip),
            "name": clip.name,
            "pool_idx": clip_idx,
            "rechazado": False,  # nunca True: los rechazados ya no están en pool
        })
        idx += 1
        clip_idx += 1
        t = slot_end

    return sequence

# ─────────────────────────────────────────────────────────────────────────────
# Generar thumbnails en segundo plano
# ─────────────────────────────────────────────────────────────────────────────

def ensure_thumbs(sequence):
    for slot in sequence:
        if slot["type"] == "clip":
            tp = THUMBS_DIR / f"th_{slot['idx']:04d}.jpg"
            if not tp.exists():
                make_thumb(pathlib.Path(slot["path"]), tp)
        elif slot["type"] == "flow":
            sid = slot["segment_id"]
            orig = FLOW_DIR / f"flow_{sid:04d}.jpg"
            tp   = THUMBS_DIR / f"flow_{sid:04d}_th.jpg"
            if orig.exists() and not tp.exists():
                make_flow_thumb(orig, tp)

# ─────────────────────────────────────────────────────────────────────────────
# Rutas Flask
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return HTML_PAGE

@app.route("/api/sequence")
def api_sequence():
    seq = build_sequence()
    for slot in seq:
        if slot["type"] == "clip":
            tp = THUMBS_DIR / f"th_{slot['idx']:04d}.jpg"
            slot["preview_url"] = f"/thumb/clip/{slot['idx']}" if tp.exists() else None
            slot["video_url"]   = f"/media/clip/{pathlib.Path(slot['path']).name}"
        elif slot["type"] == "flow":
            sid = slot["segment_id"]
            zp  = FLOW_DIR / f"flow_{sid:04d}_zp.mp4"
            tp  = THUMBS_DIR / f"flow_{sid:04d}_th.jpg"
            orig= FLOW_DIR   / f"flow_{sid:04d}.jpg"
            slot["video_url"]   = f"/media/flow/{sid}" if zp.exists() else None
            slot["preview_url"] = f"/thumb/flow/{sid}" if (tp.exists() or orig.exists()) else None
    return jsonify(seq)

@app.route("/api/make_thumbs", methods=["POST"])
def api_make_thumbs():
    seq = build_sequence()
    ensure_thumbs(seq)
    return jsonify({"ok": True, "total": len(seq)})

@app.route("/thumb/clip/<int:idx>")
def thumb_clip(idx):
    tp = THUMBS_DIR / f"th_{idx:04d}.jpg"
    if tp.exists(): return send_file(str(tp), mimetype="image/jpeg")
    abort(404)

@app.route("/thumb/repl/<stem>")
def thumb_repl(stem):
    tp = THUMBS_DIR / f"th_repl_{stem}.jpg"
    if tp.exists(): return send_file(str(tp), mimetype="image/jpeg")
    abort(404)

@app.route("/thumb/flow/<int:sid>")
def thumb_flow(sid):
    tp   = THUMBS_DIR / f"flow_{sid:04d}_th.jpg"
    orig = FLOW_DIR   / f"flow_{sid:04d}.jpg"
    if tp.exists():   return send_file(str(tp),   mimetype="image/jpeg")
    if orig.exists(): return send_file(str(orig), mimetype="image/jpeg")
    abort(404)

@app.route("/media/flow/<int:sid>")
def media_flow(sid):
    zp = FLOW_DIR / f"flow_{sid:04d}_zp.mp4"
    if zp.exists(): return send_file(str(zp), mimetype="video/mp4")
    abort(404)

@app.route("/media/clip/<path:clip_name>")
def media_clip(clip_name):
    p = CLIPS_DIR / clip_name
    if p.exists(): return send_file(str(p), mimetype="video/mp4")
    abort(404)

@app.route("/api/reject", methods=["POST"])
def api_reject():
    """
    Rechaza un clip y devuelve un reemplazo que NO esté ya en uso en otro slot.
    Solo repite si no quedan clips sin usar.
    """
    data      = request.json
    slot_type = data.get("type")
    old_idx   = data.get("idx", 0)
    rechazados = load_json(RECHAZADOS, {})

    if slot_type == "flow":
        sid = data.get("segment_id")
        rechazados[f"flow_{sid}"] = True
        save_json(RECHAZADOS, rechazados)
        return jsonify({"ok": True, "removed": True})

    elif slot_type == "clip":
        rejected_path = data.get("path", "")

        # 1. Recoger todos los paths actualmente en uso (ANTES de blacklistear)
        current_seq = build_sequence()
        in_use = {s["path"] for s in current_seq
                  if s["type"] == "clip" and s["path"] != rejected_path}

        # 2. Blacklistear el clip rechazado
        rechazados[rejected_path] = True
        save_json(RECHAZADOS, rechazados)

        # 3. Todos los clips disponibles (ni blacklisted ni el rechazado)
        all_clips = sorted(CLIPS_DIR.glob("*.mp4")) if CLIPS_DIR.exists() else []
        available = [c for c in all_clips if not rechazados.get(str(c))]

        # 4. Buscar reemplazo: primero uno que no esté en uso
        replacement = None
        is_repeat   = False
        for c in available:
            if str(c) not in in_use:
                replacement = c
                break
        # Si todos están en uso, tomar cualquier disponible (repetir el menos malo)
        if not replacement and available:
            replacement = available[0]
            is_repeat   = True

        if not replacement:
            return jsonify({"ok": True, "removed": True,
                            "msg": "Sin clips disponibles para reemplazar"})

        # 5. Construir el nuevo slot con el reemplazo
        slot_start = data.get("start", 0)
        slot_end   = data.get("end", 5)
        slot_dur   = data.get("duration", 5)
        new_slot = {
            "idx":       old_idx,
            "type":      "clip",
            "start":     slot_start,
            "end":       slot_end,
            "duration":  slot_dur,
            "path":      str(replacement),
            "name":      replacement.name,
            "rechazado": False,
            "repetido":  is_repeat,
            "video_url": f"/media/clip/{replacement.name}",
            "preview_url": None,
        }
        tp = THUMBS_DIR / f"th_repl_{replacement.stem}.jpg"
        if not tp.exists():
            make_thumb(replacement, tp)
        if tp.exists():
            new_slot["preview_url"] = f"/thumb/repl/{replacement.stem}"

        return jsonify({"ok": True, "new_slot": new_slot})

    return jsonify({"ok": False})

@app.route("/api/summary")
def api_summary():
    seq = build_sequence()
    return jsonify({
        "total": len(seq),
        "flow":  sum(1 for s in seq if s["type"] == "flow"),
        "clips": sum(1 for s in seq if s["type"] == "clip"),
        "rechazados": sum(1 for s in seq if s.get("rechazado")),
        "duracion_total": round(sum(s["duration"] for s in seq), 1),
    })

# ─────────────────────────────────────────────────────────────────────────────
# HTML
# ─────────────────────────────────────────────────────────────────────────────

HTML_PAGE = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Secuencia 10 min — Fútbol</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0f0f0f;color:#eee;font-family:system-ui,sans-serif}
header{background:#1a1a2e;padding:16px 24px;display:flex;align-items:center;gap:16px;border-bottom:2px solid #16213e}
header h1{font-size:1.2rem;color:#f59e0b}
.stats{display:flex;gap:10px;margin-left:auto;font-size:.82rem;flex-wrap:wrap}
.stat{background:#16213e;padding:4px 12px;border-radius:20px}
.stat.g{background:#1a472a;color:#4ade80}
.stat.r{background:#4a1a1a;color:#f87171}
.stat.y{background:#3a2a00;color:#fbbf24}
.stat.b{background:#0c1a3a;color:#60a5fa}
.toolbar{padding:12px 24px;display:flex;gap:10px;align-items:center;background:#111;border-bottom:1px solid #222;flex-wrap:wrap}
button{cursor:pointer;border:none;border-radius:6px;padding:8px 16px;font-size:.85rem;font-weight:600}
.btn-th{background:#1d4ed8;color:#fff}
.btn-th:hover{background:#1e40af}
#msg{font-size:.85rem;color:#60a5fa}
.min-label{grid-column:1/-1;font-size:.72rem;color:#374151;padding:4px 0 2px;letter-spacing:2px;border-top:1px solid #1a1a2e;margin-top:4px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px;padding:20px 24px}
.card{background:#1a1a2e;border-radius:10px;overflow:hidden;border:2px solid #222;transition:border-color .2s}
.card.flow-card{border-color:#92400e}
.card.rechazado{border-color:#7f1d1d;opacity:.45}
.img-wrap{position:relative;width:100%;aspect-ratio:16/9;background:#111}
.img-wrap img{width:100%;height:100%;object-fit:cover;display:block}
.no-img{display:flex;align-items:center;justify-content:center;height:100%;color:#374151;font-size:2rem}
.bdg{position:absolute;bottom:6px;left:6px;font-size:.65rem;font-weight:700;padding:2px 8px;border-radius:12px}
.bdg-flow{background:#d97706;color:#fff}
.bdg-clip{background:#374151;color:#9ca3af}
.bdg-repeat{background:#7c3aed;color:#fff}
.repeat-card{border-color:#7c3aed !important}
.seq-num{position:absolute;top:6px;left:6px;background:rgba(0,0,0,.75);color:#d1d5db;font-size:.65rem;padding:2px 7px;border-radius:10px;font-family:monospace}
.ts{position:absolute;top:6px;right:6px;background:rgba(0,0,0,.75);color:#d1d5db;font-size:.65rem;padding:2px 7px;border-radius:10px}
.info{padding:8px 12px}
.trigger{font-size:.68rem;color:#f59e0b;font-weight:700;text-transform:uppercase;margin-bottom:3px}
.scene{font-size:.8rem;color:#ccc;line-height:1.35;margin-bottom:4px}
.clip-name{font-size:.7rem;color:#6b7280;font-family:monospace}
.dur{font-size:.68rem;color:#9ca3af;margin-top:2px}
.actions{display:flex;gap:8px;padding:8px 12px;border-top:1px solid #222}
.btn-rej{background:#1f2937;color:#d1d5db;flex:1;padding:6px;border-radius:5px;font-size:.78rem}
.btn-rej:hover{background:#dc2626;color:#fff}
.btn-rest{background:#14532d;color:#86efac;flex:1;padding:6px;border-radius:5px;font-size:.78rem}
.btn-rest:hover{background:#16a34a;color:#fff}
</style>
</head>
<body>
<header>
  <h1>⚽ Secuencia 10 min — René Higuita</h1>
  <div class="stats">
    <span class="stat b" id="s-total">…</span>
    <span class="stat y" id="s-flow">…</span>
    <span class="stat"   id="s-clips">…</span>
    <span class="stat r" id="s-rej">…</span>
  </div>
</header>
<div class="toolbar">
  <button class="btn-th" onclick="makeThumbs()">🖼 Generar thumbnails de clips</button>
  <span id="msg"></span>
</div>
<div class="grid" id="grid"></div>

<script>
function fmt(s){const m=Math.floor(s/60),sec=Math.floor(s%60);return`${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`}
function msg(t,ok=true){const e=document.getElementById('msg');e.style.color=ok?'#4ade80':'#f87171';e.textContent=t;setTimeout(()=>e.textContent='',4000)}

let allSlots=[];

function renderGrid(slots){
  allSlots=slots;
  // Detectar clips repetidos (mismo path en >1 slot)
  const pathCount={};
  slots.forEach(s=>{if(s.type==='clip')pathCount[s.path]=(pathCount[s.path]||0)+1;});

  const g=document.getElementById('grid');g.innerHTML='';
  let lastMin=-1;
  slots.forEach((slot,i)=>{
    const curMin=Math.floor(slot.start/60);
    if(curMin!==lastMin){
      const lbl=document.createElement('div');
      lbl.className='min-label';
      lbl.textContent=`${String(curMin).padStart(2,'0')}:00 ─────────────────────────────`;
      g.appendChild(lbl);lastMin=curMin;
    }
    const isRepeat=slot.type==='clip'&&(slot.repetido||(pathCount[slot.path]||0)>1);
    const c=document.createElement('div');
    c.className=`card ${slot.type==='flow'?'flow-card':''} ${isRepeat?'repeat-card':''}`;
    c.id=`card-${i}`;
    let thumb;
    if(slot.video_url){
      thumb=`<video autoplay muted loop playsinline style="width:100%;height:100%;object-fit:cover"><source src="${slot.video_url}?t=${Date.now()}" type="video/mp4"></video>`;
    } else if(slot.preview_url){
      thumb=`<img src="${slot.preview_url}?t=${Date.now()}" loading="lazy">`;
    } else {
      thumb=`<div class="no-img">${slot.type==='flow'?'🖼':'🎬'}</div>`;
    }
    const bdg=slot.type==='flow'
      ?`<span class="bdg bdg-flow">FLOW</span>`
      :isRepeat
        ?`<span class="bdg bdg-repeat">REPETIDO</span>`
        :`<span class="bdg bdg-clip">CLIP</span>`;
    const body=slot.type==='flow'
      ?`<div class="trigger">${slot.trigger||''}</div><div class="scene">${slot.scene||''}</div>`
      :`<div class="clip-name">${slot.name||''}</div>`;
    c.innerHTML=`
      <div class="img-wrap">${thumb}${bdg}
        <span class="seq-num">#${i+1}</span>
        <span class="ts">${fmt(slot.start)}→${fmt(slot.end)}</span>
      </div>
      <div class="info">${body}<div class="dur">${slot.duration.toFixed(1)}s</div></div>
      <div class="actions"><button class="btn-rej" onclick="reject(${i})">✗ Rechazar</button></div>`;
    g.appendChild(c);
  });
  document.getElementById('s-total').textContent=`${slots.length} slots`;
  document.getElementById('s-flow').textContent=`${slots.filter(s=>s.type==='flow').length} flow`;
  document.getElementById('s-clips').textContent=`${slots.filter(s=>s.type==='clip').length} clips`;
  document.getElementById('s-rej').textContent=`${slots.filter(s=>isRepeat(s,pathCount)).length} repetidos`;
}
function isRepeat(s,pc){return s.type==='clip'&&(s.repetido||(pc[s.path]||0)>1);}

async function load(){const r=await fetch('/api/sequence');renderGrid(await r.json())}

async function makeThumbs(){
  msg('Generando thumbnails...');
  await fetch('/api/make_thumbs',{method:'POST'});
  msg('✓ Listo — recargando...');
  await load();
}

async function reject(i){
  const slot=allSlots[i];
  const r=await fetch('/api/reject',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(slot)});
  const d=await r.json();
  const c=document.getElementById(`card-${i}`);

  if(d.removed){
    // Flow rechazado: eliminar tarjeta
    c.style.transition='opacity .3s';c.style.opacity='0';
    setTimeout(()=>c.remove(),300);
    allSlots.splice(i,1);
    msg('Imagen Flow eliminada de la secuencia');
  } else if(d.new_slot){
    const ns=d.new_slot;
    allSlots[i]=ns;
    // Actualizar video
    const wrap=c.querySelector('.img-wrap');
    const vid=`<video autoplay muted loop playsinline style="width:100%;height:100%;object-fit:cover"><source src="${ns.video_url}?t=${Date.now()}" type="video/mp4"></video>`;
    const old=wrap.querySelector('video,img,.no-img');
    if(old) old.outerHTML=vid; else wrap.insertAdjacentHTML('afterbegin',vid);
    // Badge y borde según si es repetido
    const bdgEl=wrap.querySelector('.bdg');
    if(ns.repetido){
      if(bdgEl){bdgEl.className='bdg bdg-repeat';bdgEl.textContent='REPETIDO';}
      c.className='card repeat-card';
      msg(`⚠ Sin clips nuevos — repetido: ${ns.name}`,false);
    } else {
      if(bdgEl){bdgEl.className='bdg bdg-clip';bdgEl.textContent='CLIP';}
      c.className='card';
      c.style.borderColor='#16a34a';
      setTimeout(()=>c.style.borderColor='',1500);
      msg(`✓ Nuevo clip: ${ns.name}`);
    }
    c.querySelector('.clip-name').textContent=ns.name;
  }
  document.getElementById('s-rej').textContent=`${allSlots.filter(s=>s.rechazado).length} rechazados`;
}

load();
</script>
</body>
</html>"""

def pre_generate_thumbs():
    """Genera todos los thumbnails (Flow + clips) antes de arrancar."""
    seq = build_sequence()
    total = 0
    # Flow thumbnails
    for seg in load_json(FLOW_META, []):
        sid  = seg["segment_id"]
        orig = FLOW_DIR / f"flow_{sid:04d}.jpg"
        tp   = THUMBS_DIR / f"flow_{sid:04d}_th.jpg"
        if orig.exists() and not tp.exists():
            make_flow_thumb(orig, tp)
            total += 1
    # Clip thumbnails
    for slot in seq:
        if slot["type"] == "clip":
            tp = THUMBS_DIR / f"th_{slot['idx']:04d}.jpg"
            if not tp.exists():
                if make_thumb(pathlib.Path(slot["path"]), tp):
                    total += 1
    if total:
        print(f"  {total} thumbnails generados")

def calcular_cobertura():
    """Calcula si hay suficientes clips para cubrir los 10 min sin repetir."""
    import math as _math
    CLIP_DUR = 5.0
    flow_segs     = load_json(FLOW_META, [])
    rechazados    = load_json(RECHAZADOS, {})
    all_clips     = sorted(CLIPS_DIR.glob("*.mp4")) if CLIPS_DIR.exists() else []
    clips_have    = len([c for c in all_clips if not rechazados.get(str(c))])
    flow_dur      = sum(s.get("duration", 5) for s in flow_segs)
    gap_time      = max(0, SRT_MAX - flow_dur)
    clips_needed  = _math.ceil(gap_time / CLIP_DUR)
    deficit       = max(0, clips_needed - clips_have)
    return {
        "clips_have":   clips_have,
        "clips_needed": clips_needed,
        "flow_slots":   len(flow_segs),
        "flow_dur":     round(flow_dur, 1),
        "gap_time":     round(gap_time, 1),
        "deficit":      deficit,
    }

if __name__ == "__main__":
    import math as _math
    print(f"\n{'='*60}")
    print(f"  Secuencia 10 min — {CARPETA.name}")
    print(f"{'='*60}")

    cob = calcular_cobertura()
    print(f"  Flow:          {cob['flow_slots']} imágenes ({cob['flow_dur']}s)")
    print(f"  Tiempo libre:  {cob['gap_time']}s → necesita {cob['clips_needed']} clips")
    print(f"  Clips disp.:   {cob['clips_have']}")
    if cob["deficit"] > 0:
        print(f"  ⚠ DÉFICIT:    {cob['deficit']} clips — habrá repetidos")
        print(f"     Solución: python3 harvester_clips_futbol.py {CARPETA} --solo-flow")
        print(f"     (el harvester manda los extras a Baserow automáticamente)")
    else:
        print(f"  ✓ Cobertura completa — sin repetidos")

    seq = build_sequence()
    flow_count = sum(1 for s in seq if s["type"] == "flow")
    clip_count = sum(1 for s in seq if s["type"] == "clip")
    print(f"  Secuencia:     {len(seq)} slots ({flow_count} flow + {clip_count} clips)")
    print(f"  Generando thumbnails...")
    pre_generate_thumbs()
    print(f"  → http://localhost:{PORT}\n")
    app.run(host="0.0.0.0", port=PORT, debug=False)
