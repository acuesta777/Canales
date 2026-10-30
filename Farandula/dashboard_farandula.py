#!/usr/bin/env python3
"""
dashboard_farandula.py — Panel de aprobación de clips para canal Farandula.

Al rechazar un clip:
  1. Auto-busca otro clip/imagen en iCloud (inmediato)
  2. Si no hay → busca en Brave (inmediato)
  3. Si Brave falla → slot queda como needs_flow
Botón "→ Flow": manda en batch TODOS los needs_flow a Baserow.

Uso:
  python3 dashboard_farandula.py "VIVIENDO DE FAVOR TELEVISA/"
  Abre http://localhost:5002
"""

import json, pathlib, sys, subprocess, threading, time, gzip, hashlib, unicodedata, math
import urllib.request, urllib.parse, random
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from flask import Flask, jsonify, request, send_file

app = Flask(__name__)

# ─── Servidor estático de clips en puerto 5003 ────────────────────────────────
# Flask (GIL) no puede servir muchos videos en paralelo sin pausas.
# Este servidor ThreadingMixIn sirve cada clip en su propio hilo sin bloquear.

STATIC_PORT = 5003
_STATIC_ROOTS: list = []  # rutas que este servidor puede servir

class _ClipHandler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass  # silenciar logs
    def do_GET(self):
        # Soporta ?p=RUTA_ABSOLUTA_ENCODED para servir por path exacto
        qs = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
        if "p" in qs:
            target = pathlib.Path(urllib.parse.unquote(qs["p"][0]))
        else:
            raw = urllib.parse.unquote(self.path.lstrip("/").split("?")[0])
            target = None
            for root in _STATIC_ROOTS:
                candidate = pathlib.Path(root) / raw
                if candidate.exists() and candidate.is_file():
                    target = candidate
                    break
        if not target or not pathlib.Path(target).exists():
            self.send_error(404)
            return
        target = pathlib.Path(target)
        size = target.stat().st_size
        rng  = self.headers.get("Range", "")
        if rng.startswith("bytes="):
            start, end = rng[6:].split("-")
            start = int(start)
            end   = int(end) if end else size - 1
            length = end - start + 1
            self.send_response(206)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            with open(target, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(65536, remaining))
                    if not chunk: break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        else:
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(size))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            with open(target, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk: break
                    self.wfile.write(chunk)

class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

def _start_static_server():
    srv = _ThreadedHTTPServer(("0.0.0.0", STATIC_PORT), _ClipHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()

_start_static_server()
# ─────────────────────────────────────────────────────────────────────────────

VIDEO_FOLDER = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
META_FILE        = VIDEO_FOLDER / "dashboard_meta.json" if VIDEO_FOLDER else None
RECHAZADOS_FILE  = VIDEO_FOLDER / "clips_rechazados.json" if VIDEO_FOLDER else None
HOOK_STATE_FILE  = VIDEO_FOLDER / "hook_images_state.json" if VIDEO_FOLDER else None

FFMPEG  = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"
YTDLP   = "/opt/homebrew/bin/yt-dlp"
HOME    = pathlib.Path.home()
ICLOUD      = HOME / "Library/Mobile Documents/com~apple~CloudDocs/Artistas"
UPLOAD_DIR  = HOME / "Downloads/Upload"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Registrar raíces para el servidor estático de clips
if VIDEO_FOLDER:
    _STATIC_ROOTS.extend([
        str(ICLOUD),
        str(VIDEO_FOLDER / "hook_images"),
        str(VIDEO_FOLDER),
        str(UPLOAD_DIR),
    ])

# Jobs de fondo (add_to_section): job_id → {status, done, total, msg, added, label}
_JOBS: dict = {}
_JOBS_LOCK = threading.Lock()

BRAVE_KEY_FILE   = HOME / ".brave_key"
PEXELS_KEY_FILE  = HOME / ".pexels_key"
PIXABAY_KEY_FILE = HOME / ".pixabay_key"
BASEROW_TOKEN    = '4QrZH5MkTLHKtGqTG97Gz2yQTAIhknMq'
BASEROW_TABLE_ID = '1100194'
BASEROW_API_BASE = 'https://api.baserow.io/api'

MIN_W, MIN_H = 400, 300
SHOT_DUR     = 7.5

# ─── helpers ──────────────────────────────────────────────────────────────────

def norm(text):
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")

def buscar_carpeta_icloud(nombre):
    if not ICLOUD.exists():
        return None
    nombre_n = norm(nombre)
    for d in ICLOUD.iterdir():
        if d.is_dir() and norm(d.name) == nombre_n:
            return d
    for d in ICLOUD.iterdir():
        if d.is_dir() and nombre_n in norm(d.name):
            return d
    apellido = nombre_n.split()[-1] if nombre_n.split() else nombre_n
    if len(apellido) > 3:
        for d in ICLOUD.iterdir():
            if d.is_dir() and apellido in norm(d.name):
                return d
    return None

def load_meta():
    if META_FILE and META_FILE.exists():
        return json.loads(META_FILE.read_text())
    return {}

def save_meta(meta):
    META_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=2))

def load_rechazados():
    """Lista negra de paths rechazados — persiste aunque iCloud re-sincronice el archivo."""
    if RECHAZADOS_FILE and RECHAZADOS_FILE.exists():
        return set(json.loads(RECHAZADOS_FILE.read_text()))
    return set()

def save_rechazados(paths_set):
    RECHAZADOS_FILE.write_text(json.dumps(sorted(paths_set), ensure_ascii=False, indent=2))

def get_dims(path):
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=10
        )
        w, h = r.stdout.strip().split(",")
        return int(w), int(h)
    except Exception:
        return 0, 0

def get_duration(path):
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nokey=1:noprint_wrappers=1", str(path)],
            capture_output=True, text=True, timeout=10
        )
        return round(float(r.stdout.strip()), 2)
    except Exception:
        return 0.0

def validar_aspecto(path, min_ratio=1.0, max_ratio=2.5):
    w, h = get_dims(path)
    if h == 0: return True
    return min_ratio <= w / h <= max_ratio

def thumbs_dir():
    d = VIDEO_FOLDER / "_thumbs"
    d.mkdir(exist_ok=True)
    return d

def make_thumbnail(src_path, thumb_path):
    src   = pathlib.Path(src_path)
    thumb = pathlib.Path(thumb_path)
    if thumb.exists():
        return True
    thumb.parent.mkdir(parents=True, exist_ok=True)
    ext = src.suffix.lower()
    if ext in ('.jpg', '.jpeg', '.png', '.webp'):
        try:
            from PIL import Image
            img = Image.open(src).convert("RGB")
            img.thumbnail((320, 180))
            img.save(str(thumb), "JPEG", quality=70)
            return True
        except Exception:
            pass
    elif ext == '.mp4':
        subprocess.run(
            [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
             "-ss", "1", "-i", str(src),
             "-vframes", "1", "-vf", "scale=320:180:force_original_aspect_ratio=decrease,pad=320:180:(ow-iw)/2:(oh-ih)/2",
             str(thumb)],
            capture_output=True, timeout=15
        )
        return thumb.exists()
    return False

# ─── iCloud replacement ──────────────────────────────────────────────────────

def paths_ya_usados_global(meta, excluir_label=None, excluir_fname=None):
    """Paths reales en uso en TODO el timeline (no rechazados). Excluye el clip que se está reemplazando."""
    usados = set()
    for lbl, section in meta.items():
        for fname, info in section.get("clips", {}).items():
            if lbl == excluir_label and fname == excluir_fname:
                continue
            if info.get("estado") != "rechazado":
                usados.add(str(info.get("path", "")))
    return usados

def buscar_reemplazo_icloud(nombre, usados_paths, rechazados_paths=None):
    """Busca un clip/imagen de iCloud cuyo path no esté ya usado ni rechazado."""
    if rechazados_paths is None:
        rechazados_paths = set()
    carpeta = buscar_carpeta_icloud(nombre)
    if not carpeta:
        return None
    excluidos = usados_paths | rechazados_paths
    candidatos = []
    for f in carpeta.iterdir():
        if str(f) in excluidos:
            continue
        if f.suffix == ".mp4" and "_zp" not in f.stem and not f.stem.startswith(("tmp","flow")):
            candidatos.append(f)
        elif f.suffix.lower() in ('.jpg','.jpeg','.png','.webp') and validar_aspecto(f):
            candidatos.append(f)
    if not candidatos:
        return None
    return random.choice(candidatos)

# ─── Brave search ─────────────────────────────────────────────────────────────

def leer_brave_key():
    try:
        return BRAVE_KEY_FILE.read_text().strip()
    except Exception:
        return None

def buscar_brave(query, count=10):
    api_key = leer_brave_key()
    if not api_key:
        return []
    url = (f"https://api.search.brave.com/res/v1/images/search"
           f"?q={urllib.parse.quote(query)}&count={count}&safesearch=off")
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    })
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            raw = r.read()
            try: raw = gzip.decompress(raw)
            except Exception: pass
            data = json.loads(raw)
        items = []
        for item in data.get("results", []):
            props   = item.get("properties", {}) or {}
            img_url = props.get("url") or item.get("url", "")
            if not img_url:
                continue
            # Filtrar imágenes que Brave reporta como pequeñas
            iw = props.get("width") or props.get("image_width") or 0
            ih = props.get("height") or props.get("image_height") or 0
            if iw and ih and (iw < MIN_W or ih < MIN_H):
                continue
            thumb = (item.get("thumbnail", {}) or {}).get("src") or img_url
            page  = item.get("page_url") or item.get("source", "")
            items.append({"url": img_url, "thumb": thumb, "page": page, "source": "brave"})
        return items
    except Exception:
        return []

def _url_original(url):
    """Intenta obtener la URL de imagen original quitando prefijos de resize CDN."""
    import re
    # Patrón: https://cdn.example.com/HASH/320x200/uploads/... → https://cdn.example.com/uploads/...
    m = re.search(r'(https?://[^/]+)/[^/]+/\d+x\d+(/uploads/.+)', url)
    if m:
        return m.group(1) + m.group(2)
    return url

def descargar_imagen_brave(url, dest_path, timeout=20):
    try:
        subprocess.run(
            ["curl", "-sL", "--max-time", str(timeout),
             "-A", "Mozilla/5.0", "-o", str(dest_path), url],
            capture_output=True, timeout=timeout + 5
        )
        if not dest_path.exists() or dest_path.stat().st_size < 5000:
            dest_path.unlink(missing_ok=True)
            return False
        w, h = get_dims(dest_path)
        if w < MIN_W or h < MIN_H:
            print(f"[descarga] muy pequeña {w}x{h}: {url[:80]}", flush=True)
            dest_path.unlink(missing_ok=True)
            return False
        return True
    except Exception as e:
        print(f"[descarga] excepción: {e} url={url[:80]}", flush=True)
        dest_path.unlink(missing_ok=True)
        return False

def buscar_reemplazo_brave(nombre, srt_text, slot, label, search_query=None):
    """Busca en Brave y guarda imagen en _brave_reemplazos/. Devuelve Path o None."""
    # Usar el search_query pre-calculado del harvester si está disponible
    query = search_query or f"{nombre} comediante actor Mexico television"
    urls = buscar_brave(query)
    brave_dir = VIDEO_FOLDER / "_brave_reemplazos" / label.replace(" ", "_")
    brave_dir.mkdir(parents=True, exist_ok=True)
    for url in urls:
        dest = brave_dir / f"brave_{slot:03d}_{abs(hash(url)) % 9999:04d}.jpg"
        if descargar_imagen_brave(url, dest):
            return dest
    return None

# ─── Baserow ──────────────────────────────────────────────────────────────────

def _baserow_curl(method, path, data=None):
    url = BASEROW_API_BASE + path
    cmd = ['curl', '-s', '-X', method, url,
           '-H', f'Authorization: Token {BASEROW_TOKEN}',
           '-H', 'Content-Type: application/json']
    if data:
        cmd += ['-d', json.dumps(data)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {}

def limpiar_baserow():
    existing, page = [], 1
    while True:
        data = _baserow_curl('GET', f'/database/rows/table/{BASEROW_TABLE_ID}/?user_field_names=true&size=200&page={page}')
        existing += [r['id'] for r in data.get('results', [])]
        if not data.get('next'): break
        page += 1
    for rid in existing:
        _baserow_curl('DELETE', f'/database/rows/table/{BASEROW_TABLE_ID}/{rid}/')
    return len(existing)

# ─── Hook images helpers ──────────────────────────────────────────────────────

def load_hook_state():
    if HOOK_STATE_FILE and HOOK_STATE_FILE.exists():
        return json.loads(HOOK_STATE_FILE.read_text())
    return {}

def save_hook_state(state):
    HOOK_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))

def get_hook_images():
    """Retorna JPEGs del hook. Si hay MP4 animado con el mismo stem base, lo usa en su lugar."""
    if not VIDEO_FOLDER:
        return []
    hook_dir = VIDEO_FOLDER / "hook_images"
    if not hook_dir.exists():
        return []
    imgs = list(hook_dir.glob("hook_[0-9]*.jpg")) + list(hook_dir.glob("[0-9]*_hook_*.jpg"))
    return sorted(set(imgs), key=lambda f: f.name)

def get_hook_media(jpg_path):
    """Busca MP4 animado de VEO3 que empiece con el mismo número de orden que el JPG."""
    hook_dir = jpg_path.parent
    import re as _re
    # Soporta: hook_0001.jpg  →  001_*.mp4
    #          01_hook_0001.jpg → 001_*.mp4
    m = _re.search(r'(\d+)', jpg_path.stem)
    if m:
        n = int(m.group(1))
        prefix = f"{n:03d}_"
        matches = sorted(hook_dir.glob(f"{prefix}*.mp4"))
        if matches:
            return matches[0]
        # También busca hook_NNNN_zp.mp4 (VEO3 copiados por harvester)
        zp = hook_dir / f"hook_{n:04d}_zp.mp4"
        if zp.exists():
            return zp
    return jpg_path


# ─── Hook timeline mixto (Flow + YT) ─────────────────────────────────────────

HOOK_YT_STATE_FILE = VIDEO_FOLDER / "hook_yt_state.json" if VIDEO_FOLDER else None

def load_hook_yt_state():
    if HOOK_YT_STATE_FILE and HOOK_YT_STATE_FILE.exists():
        return json.loads(HOOK_YT_STATE_FILE.read_text())
    return {}  # {segment_id: "ruta_clip_relativa_a_iCloud"}

def save_hook_yt_state(state):
    tmp = HOOK_YT_STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    tmp.replace(HOOK_YT_STATE_FILE)

def pick_yt_clip_for_artist(icloud_folder, exclude_paths=None):
    """Selecciona un clip MP4 de la carpeta iCloud del artista, excluyendo los ya usados."""
    folder = ICLOUD / icloud_folder
    if not folder.exists():
        return None
    exclude = set(exclude_paths or [])
    candidates = [f for f in sorted(folder.glob("*.mp4")) if "_zp" not in f.stem and str(f) not in exclude]
    if not candidates:
        candidates = [f for f in sorted(folder.glob("*_zp.mp4")) if str(f) not in exclude]
    return candidates[0] if candidates else None

def extract_hook_yt_preview(src_path, out_path, duration=5.0):
    """Extrae 5s del clip de iCloud y lo re-encodea a 640x360 para preview rápido."""
    if out_path.exists():
        return True
    r = subprocess.run([
        FFMPEG, "-y", "-ss", "2", "-i", str(src_path),
        "-t", str(duration),
        "-vf", "scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2",
        "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        str(out_path)
    ], capture_output=True, timeout=30)
    return r.returncode == 0

@app.route("/api/hook_timeline")
def api_hook_timeline():
    """Devuelve los segmentos del hook en orden: flow y youtube mezclados."""
    hook_file = VIDEO_FOLDER / "hook_timeline.json"
    if not hook_file.exists():
        return jsonify({"segments": []})

    all_segs = json.loads(hook_file.read_text()).get("visual_timeline", [])
    hook_dir = VIDEO_FOLDER / "hook_images"
    flow_imgs = sorted(hook_dir.glob("hook_[0-9]*_zp.mp4")) if hook_dir.exists() else []
    # Mapeo posición flow (1-indexed) → archivo
    flow_map = {i+1: f for i, f in enumerate(flow_imgs)}

    yt_state = load_hook_yt_state()
    # Asignar clips YT a los segmentos que no tienen uno aún
    yt_segs = [s for s in all_segs if s.get("type") == "youtube"]
    used_paths = list(yt_state.values())
    for seg in yt_segs:
        sid = str(seg["segment_id"])
        if sid not in yt_state:
            clip = pick_yt_clip_for_artist(seg["icloud_folder"], used_paths)
            if clip:
                yt_state[sid] = str(clip)
                used_paths.append(str(clip))
    save_hook_yt_state(yt_state)

    flow_idx = 0
    result = []
    for seg in all_segs:
        sid = str(seg["segment_id"])
        if seg.get("type", "flow") == "flow":
            flow_idx += 1
            mp4 = flow_map.get(flow_idx)
            result.append({
                "segment_id": seg["segment_id"],
                "type": "flow",
                "duration": seg["duration"],
                "descripcion": seg.get("descripcion", ""),
                "media_url": f"/hook_flow_clip?n={flow_idx}" if mp4 else None,
                "has_media": mp4 is not None,
            })
        else:
            clip_path = yt_state.get(sid)
            clip_file = pathlib.Path(clip_path) if clip_path else None
            result.append({
                "segment_id": seg["segment_id"],
                "type": "youtube",
                "duration": seg["duration"],
                "artist": seg.get("artist", ""),
                "icloud_folder": seg.get("icloud_folder", ""),
                "descripcion": seg.get("descripcion", ""),
                "clip_path": clip_path,
                "media_url": f"/hook_yt_clip?seg={sid}" if clip_path else None,
                "has_media": clip_file.exists() if clip_file else False,
            })
    return jsonify({"segments": result})

@app.route("/hook_flow_clip")
def serve_hook_flow_clip():
    from flask import redirect
    n = int(request.args.get("n", 1))
    hook_dir = VIDEO_FOLDER / "hook_images"
    clips = sorted(hook_dir.glob("hook_[0-9]*_zp.mp4"))
    if n < 1 or n > len(clips):
        return "not found", 404
    p = clips[n-1]
    return redirect(f"http://localhost:{STATIC_PORT}/?p={urllib.parse.quote(str(p))}")

@app.route("/hook_yt_clip")
def serve_hook_yt_clip():
    from flask import redirect
    seg_id = request.args.get("seg")
    yt_state = load_hook_yt_state()
    clip_path = yt_state.get(str(seg_id))
    if not clip_path or not pathlib.Path(clip_path).exists():
        return "not found", 404
    return redirect(f"http://localhost:{STATIC_PORT}/?p={urllib.parse.quote(clip_path)}")

@app.route("/api/hook_yt_reject", methods=["POST"])
def api_hook_yt_reject():
    """Rechaza el clip YT de un segmento y asigna otro del mismo artista."""
    data = request.json
    seg_id = str(data.get("segment_id"))
    icloud_folder = data.get("icloud_folder", "")

    yt_state = load_hook_yt_state()
    rejected = yt_state.get(seg_id)
    used_paths = [v for k, v in yt_state.items() if k != seg_id]

    new_clip = pick_yt_clip_for_artist(icloud_folder, used_paths + ([rejected] if rejected else []))
    if not new_clip:
        return jsonify({"error": f"Sin más clips para {icloud_folder}"}), 404

    yt_state[seg_id] = str(new_clip)
    save_hook_yt_state(yt_state)
    return jsonify({"ok": True, "new_clip": new_clip.name, "media_url": f"/hook_yt_clip?seg={seg_id}"})

# ─── Hook images API ──────────────────────────────────────────────────────────

@app.route("/api/hook_images")
def api_hook_images():
    imgs   = get_hook_images()
    state  = load_hook_state()
    result = []
    for i, img in enumerate(imgs):
        fname  = img.name
        media  = get_hook_media(img)
        mfname = media.name
        result.append({
            "filename":  fname,
            "index":     i,
            "estado":    state.get(fname, "pendiente"),
            "is_video":  media.suffix == ".mp4",
            "media_url": f"/hook_media?filename={urllib.parse.quote(mfname)}",
            "thumb_url": f"/hook_thumb?filename={urllib.parse.quote(fname)}",
        })
    return jsonify({
        "total":    len(result),
        "images":   result,
        "aprobados":  sum(1 for r in result if r["estado"] == "aprobado"),
        "rechazados": sum(1 for r in result if r["estado"] == "rechazado"),
    })


@app.route("/api/hook_approve", methods=["POST"])
def api_hook_approve():
    data   = request.json
    fname  = data.get("filename")
    estado = data.get("estado")
    if not fname or not estado:
        return jsonify({"error": "faltan parámetros"}), 400
    state = load_hook_state()
    state[fname] = estado
    save_hook_state(state)
    return jsonify({"ok": True})


@app.route("/api/hook_approve_all", methods=["POST"])
def api_hook_approve_all():
    estado = request.json.get("estado", "aprobado")
    imgs   = get_hook_images()
    state  = load_hook_state()
    for img in imgs:
        state[img.name] = estado
    save_hook_state(state)
    return jsonify({"ok": True, "updated": len(imgs)})


@app.route("/audio")
def serve_audio():
    mp3 = VIDEO_FOLDER / "audio.mp3"
    if not mp3.exists():
        return "No audio.mp3", 404
    return send_file(str(mp3), mimetype="audio/mpeg", conditional=True)

@app.route("/hook_media")
def serve_hook_media():
    fname    = request.args.get("filename", "")
    hook_dir = VIDEO_FOLDER / "hook_images"
    path     = hook_dir / fname
    if not path.exists() or path.suffix.lower() not in ('.jpg', '.jpeg', '.png', '.mp4'):
        return "not found", 404
    mime = "video/mp4" if path.suffix.lower() == ".mp4" else "image/jpeg"
    return send_file(str(path), mimetype=mime)


@app.route("/hook_thumb")
def serve_hook_thumb():
    fname      = request.args.get("filename", "")
    hook_dir   = VIDEO_FOLDER / "hook_images"
    src_path   = hook_dir / fname
    thumb_path = thumbs_dir() / "_hook" / (pathlib.Path(fname).stem + "_th.jpg")
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    make_thumbnail(str(src_path), str(thumb_path))
    if thumb_path.exists():
        return send_file(str(thumb_path), mimetype="image/jpeg")
    if src_path.exists():
        return send_file(str(src_path), mimetype="image/jpeg")
    return "not found", 404


# ─── API ──────────────────────────────────────────────────────────────────────

@app.route("/api/reorder", methods=["POST"])
def api_reorder():
    """Guarda el nuevo orden de clips. Body: {label, order: [filename, ...]}"""
    data  = request.json
    label = data.get("label")
    order = data.get("order", [])
    if not label or not order:
        return jsonify({"error": "faltan parámetros"}), 400
    meta  = load_meta()
    clips = meta.get(label, {}).get("clips", {})
    for new_slot, fname in enumerate(order):
        if fname in clips:
            clips[fname]["slot"] = new_slot
    save_meta(meta)
    return jsonify({"ok": True})


@app.route("/api/refresh_meta", methods=["POST"])
def api_refresh_meta():
    """Purga del meta todos los clips cuyo archivo ya no existe en disco."""
    meta = load_meta()
    removed = []
    for label, section in meta.items():
        clips = section.get("clips", {})
        to_del = [f for f, info in clips.items()
                  if not pathlib.Path(info.get("path","")).exists()]
        for f in to_del:
            del clips[f]
            removed.append({"label": label, "filename": f})
    if removed:
        save_meta(meta)
    return jsonify({"ok": True, "removed": len(removed), "detail": removed})


@app.route("/api/preflight")
def api_preflight():
    """Verifica déficit de clips por artista ANTES del render."""
    meta = load_meta()
    ts_file = VIDEO_FOLDER / "timestamps.json" if VIDEO_FOLDER else None
    _ts_raw = json.loads(ts_file.read_text()) if ts_file and ts_file.exists() else {}
    # Normalizar: puede ser lista [{label, ...}] o dict {label: {...}}
    if isinstance(_ts_raw, list):
        timestamps = {item["label"]: item for item in _ts_raw if "label" in item}
    else:
        timestamps = _ts_raw
    MAX_CLIP_DUR = 8.0
    issues = []
    for label, info in meta.items():
        if label == "00_HOOK":
            continue
        nombre = info.get("nombre", label)
        dur = timestamps.get(label, {}).get("duration", 0) if isinstance(timestamps.get(label), dict) else 0
        if not dur:
            # buscar por nombre
            for k, v in timestamps.items():
                if isinstance(v, dict) and nombre.lower() in k.lower():
                    dur = v.get("duration", 0)
                    break
        clips = info.get("clips", {})
        aprobados = [c for c in clips.values() if c.get("estado") != "rechazado"]
        tiene = len(aprobados)
        necesita = math.ceil(dur / MAX_CLIP_DUR) if dur else 0
        if necesita > tiene:
            issues.append({
                "artista": nombre,
                "duracion": round(dur),
                "necesita": necesita,
                "tiene": tiene,
                "deficit": necesita - tiene,
            })
    return jsonify({"ok": len(issues) == 0, "issues": issues})


# ── Notificación render completado ───────────────────────────────────────────
_render_done = {"done": False, "size_mb": 0, "dur_min": 0}

@app.route("/api/render_done", methods=["POST"])
def api_render_done():
    data = request.json or {}
    _render_done.update({"done": True, "size_mb": data.get("size_mb", 0), "dur_min": data.get("dur_min", 0)})
    return jsonify({"ok": True})

@app.route("/api/render_status")
def api_render_status():
    return jsonify(_render_done)


@app.route("/api/sections")
def api_sections():
    meta = load_meta()
    sections = []
    for label, info in meta.items():
        if label == "00_HOOK":
            continue
        clips      = info.get("clips", {})
        total      = len(clips)
        aprobados  = sum(1 for c in clips.values() if c.get("estado") == "aprobado")
        rechazados = sum(1 for c in clips.values() if c.get("estado") == "rechazado")
        needs_flow = sum(1 for c in clips.values() if c.get("estado") == "needs_flow")
        import math as _math
        duration = info.get("duration", 0)
        needed   = _math.ceil(duration / 7.5) if duration else 0
        sections.append({
            "label":      label,
            "nombre":     info.get("nombre", label),
            "is_hook":    info.get("is_hook", False),
            "total":      total,
            "needed":     needed,
            "aprobados":  aprobados,
            "rechazados": rechazados,
            "needs_flow": needs_flow,
            "pendientes": total - aprobados - rechazados - needs_flow,
        })
    return jsonify(sections)


@app.route("/api/clips/<path:label>")
def api_clips(label):
    meta = load_meta()
    section = meta.get(label)
    if not section:
        return jsonify({"error": "sección no encontrada"}), 404
    clips_list = []
    for fname, info in section["clips"].items():
        clips_list.append({
            "filename":   fname,
            "orig_name":  info.get("orig_name", fname),
            "reciclado":  info.get("reciclado", False),
            "estado":     info.get("estado", "pendiente"),
            "tipo":       info.get("tipo", "video"),
            "duration":   info.get("duration", 0),
            "width":      info.get("width", 0),
            "height":     info.get("height", 0),
            "slot":       info.get("slot", 999),
            "slot_start": info.get("slot_start", 0),
            "slot_end":   info.get("slot_end", 0),
            "srt_text":   info.get("srt_text", ""),
            "fuente":     info.get("fuente", "icloud"),
            "thumb_url":  f"/thumb?label={urllib.parse.quote(label)}&filename={urllib.parse.quote(fname)}",
            "media_url":  f"/media?label={urllib.parse.quote(label)}&filename={urllib.parse.quote(fname)}",
            "path":       info.get("path", ""),
        })
    clips_list.sort(key=lambda c: c["slot"])
    return jsonify({
        "label":    label,
        "nombre":   section["nombre"],
        "duration": section.get("duration", 0),
        "clips":    clips_list,
    })


@app.route("/api/approve", methods=["POST"])
def api_approve():
    data     = request.json
    label    = data.get("label")
    filename = data.get("filename")
    estado   = data.get("estado")
    if not label or not filename or not estado:
        return jsonify({"error": "faltan parámetros"}), 400
    meta = load_meta()
    if label not in meta or filename not in meta[label]["clips"]:
        return jsonify({"error": "clip no encontrado"}), 404
    meta[label]["clips"][filename]["estado"] = estado
    save_meta(meta)
    return jsonify({"ok": True})


@app.route("/api/approve_all", methods=["POST"])
def api_approve_all():
    data   = request.json
    label  = data.get("label")  # None = todos los artistas
    estado = data.get("estado", "aprobado")
    meta   = load_meta()
    total  = 0
    labels = [label] if label else list(meta.keys())
    for lbl in labels:
        if lbl not in meta:
            continue
        for fname in meta[lbl]["clips"]:
            meta[lbl]["clips"][fname]["estado"] = estado
            total += 1
    save_meta(meta)
    return jsonify({"ok": True, "updated": total})


@app.route("/api/reject_and_replace", methods=["POST"])
def api_reject_and_replace():
    """
    Rechaza un clip: borra físicamente de disco (incluyendo iCloud), busca un
    reemplazo que NO esté ya en ningún card del dashboard, lo agrega al meta
    y lo devuelve al frontend para actualizar la tarjeta en lugar de eliminarla.
    """
    data     = request.json
    label    = data.get("label")
    filename = data.get("filename")
    if not label or not filename:
        return jsonify({"error": "faltan parámetros"}), 400

    meta      = load_meta()
    section   = meta.get(label, {})
    clip_info = section.get("clips", {}).get(filename)
    if not clip_info:
        return jsonify({"error": "clip no encontrado"}), 404

    clip_path = pathlib.Path(clip_info.get("path", ""))

    # Borrar archivo físicamente
    if clip_path.exists():
        try:
            clip_path.unlink()
            print(f"  🗑  Borrado: {clip_path.name}")
        except Exception as e:
            print(f"  ⚠ No se pudo borrar {clip_path}: {e}")

    # Borrar thumbnail
    thumb_path = thumbs_dir() / label.replace(" ", "_") / (pathlib.Path(filename).stem + ".jpg")
    thumb_path.unlink(missing_ok=True)

    # Eliminar del meta
    del meta[label]["clips"][filename]

    # ── Buscar reemplazo ────────────────────────────────────────────────────
    # Recopilar TODOS los paths ya usados en TODAS las secciones del meta
    todos_usados = set()
    for sec_data in meta.values():
        for ci in sec_data.get("clips", {}).values():
            p = ci.get("path", "")
            if p:
                todos_usados.add(str(pathlib.Path(p).resolve()))

    replacement = None

    # Determinar carpeta fuente (misma que el clip rechazado)
    source_dir = clip_path.parent if clip_path.parent.exists() else None

    if source_dir and source_dir.exists():
        # Preferir raw MP4, si no hay usar _zp (imágenes ya convertidas a zoompan)
        raw_cands = [f for f in source_dir.glob("*.mp4")
                     if "_zp" not in f.stem
                     and not f.stem.startswith(("tmp", "flow"))
                     and str(f.resolve()) not in todos_usados
                     and f.exists()]
        zp_cands  = [f for f in source_dir.glob("*_zp.mp4")
                     if str(f.resolve()) not in todos_usados and f.exists()]
        candidatos = raw_cands if raw_cands else zp_cands
        import random as _rnd
        _rnd.shuffle(candidatos)

        if candidatos:
            repl_path = candidatos[0]
            # Heredar el slot del clip rechazado para mantener el orden en el dashboard
            orig_slot = clip_info.get("slot", len(section.get("clips", {})))
            repl_key  = f"slot{orig_slot:03d}_repl_{repl_path.name}"
            repl_info = {
                "path":       str(repl_path),
                "estado":     "pendiente",
                "slot":       orig_slot,
                "slot_start": clip_info.get("slot_start", 0),
                "slot_end":   clip_info.get("slot_end", 0),
                "label":      label,
                "tipo":       "video",
                "orig_name":  repl_path.name,
                "fuente":     "icloud",
                "reciclado":  False,
            }
            meta[label]["clips"][repl_key] = repl_info
            replacement = {
                "filename":   repl_key,
                "orig_name":  repl_path.name,
                "media_url":  f"/media?label={urllib.parse.quote(label)}&filename={urllib.parse.quote(repl_key)}",
                "thumb_url":  f"/thumb?label={urllib.parse.quote(label)}&filename={urllib.parse.quote(repl_key)}",
                "estado":     "pendiente",
                "tipo":       "video",
                "slot":       orig_slot,
                "slot_start": clip_info.get("slot_start", 0),
                "slot_end":   clip_info.get("slot_end", 0),
                "reciclado":  False,
                "fuente":     "icloud",
                "srt_text":   clip_info.get("srt_text", ""),
                "duration":   0,
                "width":      0,
                "height":     0,
                "path":       str(repl_path),
                "label":      label,
            }
            print(f"  ✓ Reemplazo: {repl_path.name}")

    save_meta(meta)

    if replacement:
        return jsonify({"ok": True, "replacement": replacement})
    else:
        return jsonify({"ok": True, "replacement": None, "msg": "pool agotado"})


@app.route("/api/remove_card", methods=["POST"])
def api_remove_card():
    """Elimina la tarjeta del dashboard sin borrar el archivo del disco."""
    data     = request.json
    label    = data.get("label")
    filename = data.get("filename")
    if not label or not filename:
        return jsonify({"error": "faltan parámetros"}), 400

    meta    = load_meta()
    section = meta.get(label, {})
    if filename not in section.get("clips", {}):
        return jsonify({"error": "clip no encontrado"}), 404

    del meta[label]["clips"][filename]
    save_meta(meta)
    return jsonify({"ok": True})


def buscar_pexels(query, count=20):
    try:
        key = PEXELS_KEY_FILE.read_text().strip()
    except Exception:
        return []
    url = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(query)}&per_page={min(count,80)}"
    req = urllib.request.Request(url, headers={"Authorization": key})
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read())
        results = []
        for p in data.get("photos", []):
            results.append({
                "url":    p["src"]["large"],
                "thumb":  p["src"]["medium"],
                "source": "pexels",
                "credit": p.get("photographer", ""),
            })
        return results
    except Exception:
        return []


def buscar_pixabay(query, count=20):
    try:
        key = PIXABAY_KEY_FILE.read_text().strip()
    except Exception:
        return []
    url = (f"https://pixabay.com/api/?key={key}"
           f"&q={urllib.parse.quote(query)}&image_type=photo"
           f"&per_page={min(count,200)}&safesearch=true")
    try:
        with urllib.request.urlopen(url, timeout=12) as r:
            data = json.loads(r.read())
        results = []
        for p in data.get("hits", []):
            results.append({
                "url":    p.get("largeImageURL", p.get("webformatURL", "")),
                "thumb":  p.get("webformatURL", ""),
                "source": "pixabay",
                "credit": p.get("user", ""),
            })
        return results
    except Exception:
        return []


@app.route("/api/search_images", methods=["GET"])
def api_search_images():
    """Busca imágenes. source=brave|pexels|pixabay|photos (pexels+pixabay combinados)."""
    q      = request.args.get("q", "")
    source = request.args.get("source", "brave")
    count  = int(request.args.get("count", 20))
    if not q:
        return jsonify({"results": []})

    if source == "pexels":
        results = buscar_pexels(q, count)
    elif source == "pixabay":
        results = buscar_pixabay(q, count)
    elif source == "photos":
        # Combinar Pexels + Pixabay intercalados
        px = buscar_pexels(q, count // 2 + 2)
        pi = buscar_pixabay(q, count // 2 + 2)
        results = [x for pair in zip(px, pi) for x in pair][:count]
        if len(px) > len(pi):
            results += px[len(pi):]
        elif len(pi) > len(px):
            results += pi[len(px):]
    else:
        results = buscar_brave(q, count=count)

    return jsonify({"results": results})


def buscar_pexels_videos(query, count=12):
    try:
        key = PEXELS_KEY_FILE.read_text().strip()
        url = f"https://api.pexels.com/videos/search?query={urllib.parse.quote(query)}&per_page={min(count,80)}"
        req = urllib.request.Request(url, headers={"Authorization": key})
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read())
        results = []
        for v in data.get("videos", []):
            # Elegir archivo de mejor resolución SD (≤1080p)
            files = sorted(v.get("video_files", []),
                           key=lambda f: f.get("width", 0), reverse=True)
            best = next((f for f in files if f.get("width", 9999) <= 1920), files[0] if files else None)
            if not best:
                continue
            dur = v.get("duration", 0)
            results.append({
                "url": best.get("link", ""),
                "thumb": v.get("image", ""),
                "duration": dur,
                "source": "pexels",
            })
        return results
    except Exception as e:
        print(f"[pexels_videos] {e}", flush=True)
        return []


def buscar_pixabay_videos(query, count=12):
    try:
        key = PIXABAY_KEY_FILE.read_text().strip()
        url = (f"https://pixabay.com/api/videos/?key={key}"
               f"&q={urllib.parse.quote(query)}&per_page={min(count,200)}&video_type=film")
        with urllib.request.urlopen(url, timeout=12) as r:
            data = json.loads(r.read())
        results = []
        for v in data.get("hits", []):
            videos = v.get("videos", {})
            # Preferir medium > small > tiny
            fobj = videos.get("medium") or videos.get("small") or videos.get("tiny")
            if not fobj:
                continue
            results.append({
                "url": fobj.get("url", ""),
                "thumb": v.get("userImageURL") or v.get("previewURL", ""),
                "duration": v.get("duration", 0),
                "source": "pixabay",
            })
        return results
    except Exception as e:
        print(f"[pixabay_videos] {e}", flush=True)
        return []


@app.route("/api/search_videos", methods=["GET"])
def api_search_stock_videos():
    """Busca videos en Pexels + Pixabay (source=stock) o YouTube (source=youtube/omitido)."""
    q      = request.args.get("q", "")
    source = request.args.get("source", "youtube")
    count  = int(request.args.get("count", 12))
    if not q:
        return jsonify({"results": []})

    if source == "stock":
        half = count // 2 + 2
        px = buscar_pexels_videos(q, half)
        pi = buscar_pixabay_videos(q, half)
        results = [x for pair in zip(px, pi) for x in pair][:count]
        if len(px) > len(pi): results += px[len(pi):]
        elif len(pi) > len(px): results += pi[len(px):]
        return jsonify({"results": results})

    # Fallback: búsqueda YouTube vía Brave (comportamiento original)
    api_key = leer_brave_key()
    if not api_key:
        return jsonify({"results": [], "error": "Sin API key Brave"})
    url = (f"https://api.search.brave.com/res/v1/videos/search"
           f"?q={urllib.parse.quote(q)}&count={count}&safesearch=off")
    req = urllib.request.Request(url, headers={
        "Accept": "application/json", "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    })
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            raw = r.read()
            try: raw = gzip.decompress(raw)
            except Exception: pass
            data = json.loads(raw)
        results = [{"url": i.get("url",""), "title": i.get("title",""),
                    "thumb": i.get("thumbnail",{}).get("src",""),
                    "duration": i.get("video",{}).get("duration",""),
                    "source": "youtube"} for i in data.get("results",[])]
        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"results": [], "error": str(e)})


@app.route("/api/search_youtube", methods=["GET"])
def api_search_youtube():
    """Busca videos en YouTube con yt-dlp y devuelve título, thumb, duración, video_id."""
    q     = request.args.get("q", "")
    count = int(request.args.get("count", 10))
    if not q:
        return jsonify({"results": []})
    try:
        cmd = [
            "/opt/homebrew/bin/yt-dlp",
            "--cookies-from-browser", "brave",
            f"ytsearch{count}:{q}",
            "--print", '{"id":"%(id)s","title":"%(title)s","duration":%(duration)s,"thumb":"%(thumbnail)s"}',
            "--no-playlist", "--skip-download", "--quiet",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        results = []
        for line in r.stdout.strip().splitlines():
            try:
                item = json.loads(line)
                if item.get("id"):
                    results.append({
                        "video_id": item["id"],
                        "title":    item.get("title", ""),
                        "duration": item.get("duration", 0),
                        "thumb":    item.get("thumb", f"https://i.ytimg.com/vi/{item['id']}/mqdefault.jpg"),
                        "url":      f"https://www.youtube.com/watch?v={item['id']}",
                    })
            except Exception:
                continue
        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"results": [], "error": str(e)})


ZOOMPAN_MOVES = [
    ("zoom_in_center",   "min(zoom+0.0015,1.5)", "iw/2-(iw/zoom/2)",                        "ih/2-(ih/zoom/2)"),
    ("pan_left_right",   "1.4",                   "iw*0.1*(on/225)",                          "ih/2-(ih/zoom/2)"),
    ("pan_right_left",   "1.4",                   "iw*0.1*(1-on/225)",                        "ih/2-(ih/zoom/2)"),
    ("pan_top_bottom",   "1.4",                   "iw/2-(iw/zoom/2)",                         "ih*0.1*(on/225)"),
    ("pan_bottom_top",   "1.4",                   "iw/2-(iw/zoom/2)",                         "ih*0.1*(1-on/225)"),
    ("ken_burns_tl",     "min(zoom+0.0012,1.4)",  "iw*0.05*(1-on/225)",                       "ih*0.05*(1-on/225)"),
    ("ken_burns_br",     "min(zoom+0.0012,1.4)",  "iw/2-(iw/zoom/2)+iw*0.05*(on/225)",       "ih/2-(ih/zoom/2)+ih*0.05*(on/225)"),
]

def imagen_a_zoompan(src_path, dst_path, move_idx=0):
    """Convierte imagen a clip zoompan 640x360. Portrait → blur de fondo."""
    w, h = get_dims(src_path)
    if w == 0:
        return False
    ratio = w / h
    _, z, x, y = ZOOMPAN_MOVES[move_idx % len(ZOOMPAN_MOVES)]
    zp = f"zoompan=z='{z}':x='{x}':y='{y}':d=225:s=1920x1080:fps=30"

    if ratio < 0.9:  # portrait → blur bg + imagen centrada sin estirar
        fg  = f"scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black@0"
        bg  = f"scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,boxblur=20:5"
        vf  = f"[0:v]{bg}[bg];[0:v]{fg}[fg];[bg][fg]overlay=0:0,{zp},scale=640:360"
        cmd = [FFMPEG, "-y", "-loop", "1", "-i", str(src_path),
               "-filter_complex", vf]
    else:
        vf  = f"scale=8000:-1,{zp},scale=640:360"
        cmd = [FFMPEG, "-y", "-loop", "1", "-i", str(src_path), "-vf", vf]

    cmd += ["-t", "7.5", "-c:v", "libx264", "-profile:v", "baseline",
            "-level", "3.0", "-pix_fmt", "yuv420p", "-an",
            "-movflags", "+faststart", str(dst_path)]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    return dst_path.exists() and dst_path.stat().st_size > 50_000


def _run_add_job(job_id, label, items, carpeta):
    """Corre en hilo de fondo. Actualiza _JOBS[job_id] con progreso."""
    total = len(items)
    with _JOBS_LOCK:
        _JOBS[job_id].update({"status": "running", "total": total, "done": 0, "added": 0})

    meta2    = load_meta()
    section2 = meta2.get(label, {})
    clips     = section2.get("clips", {})
    usados    = {v["path"] for v in clips.values()}
    next_slot = max((v.get("slot", 0) for v in clips.values()), default=-1) + 1
    move_idx  = sum(1 for f in carpeta.glob("*_zp.mp4"))
    thumb_dir = thumbs_dir() / label.replace(" ", "_")
    thumb_dir.mkdir(parents=True, exist_ok=True)

    added_count = 0
    for i, itm in enumerate(items):
        src_url = itm.get("url", "")
        if not src_url:
            with _JOBS_LOCK:
                _JOBS[job_id]["done"] = i + 1
            continue

        h_id   = abs(hash(src_url)) % 99999
        src    = itm.get("source", "web")
        tipo   = itm.get("tipo", "imagen")
        prefix = "pexels" if src == "pexels" else "pixabay" if src == "pixabay" else "web"

        if tipo == "video":
            # Video de stock → descargar y cortar 8s desde el inicio
            raw_vid = carpeta / f"{prefix}_{h_id:05d}_raw.mp4"
            zp      = carpeta / f"{prefix}_{h_id:05d}_zp.mp4"

            if str(zp) in usados:
                with _JOBS_LOCK:
                    _JOBS[job_id].update({"done": i+1, "msg": f"duplicado {i+1}/{total}"})
                continue

            with _JOBS_LOCK:
                _JOBS[job_id].update({"done": i+1, "msg": f"descargando video {i+1}/{total}…"})
            if not raw_vid.exists():
                r = subprocess.run(
                    ["curl", "-sL", "--max-time", "60", "-A", "Mozilla/5.0",
                     "-o", str(raw_vid), src_url],
                    capture_output=True, timeout=65
                )
                if not raw_vid.exists() or raw_vid.stat().st_size < 10000:
                    raw_vid.unlink(missing_ok=True)
                    with _JOBS_LOCK:
                        _JOBS[job_id]["msg"] = f"❌ {i+1}/{total} falló descarga video"
                    continue

            with _JOBS_LOCK:
                _JOBS[job_id]["msg"] = f"cortando 8s {i+1}/{total}…"
            if not zp.exists():
                r = subprocess.run(
                    [FFMPEG, "-y", "-i", str(raw_vid),
                     "-t", "8", "-vf", "scale=640:360:force_original_aspect_ratio=decrease,"
                     "pad=640:360:(ow-iw)/2:(oh-ih)/2:color=black",
                     "-c:v", "libx264", "-profile:v", "baseline", "-level", "3.0",
                     "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", str(zp)],
                    capture_output=True, timeout=60
                )
                if not zp.exists() or zp.stat().st_size < 10000:
                    zp.unlink(missing_ok=True)
                    raw_vid.unlink(missing_ok=True)
                    with _JOBS_LOCK:
                        _JOBS[job_id]["msg"] = f"❌ {i+1}/{total} falló corte"
                    continue
            raw_vid.unlink(missing_ok=True)

        else:
            # Imagen → descargar + zoompan
            img  = carpeta / f"{prefix}_{h_id:05d}.jpg"
            zp   = carpeta / f"{prefix}_{h_id:05d}_zp.mp4"

            if str(zp) in usados:
                with _JOBS_LOCK:
                    _JOBS[job_id].update({"done": i+1, "msg": f"duplicado {i+1}/{total}"})
                continue

            with _JOBS_LOCK:
                _JOBS[job_id].update({"done": i+1, "msg": f"descargando {i+1}/{total}…"})
            if not img.exists():
                ok = descargar_imagen_brave(src_url, img)
                if not ok:
                    print(f"[job {job_id}] ❌ descarga fallida: {src_url[:80]}", flush=True)
                    with _JOBS_LOCK:
                        _JOBS[job_id]["msg"] = f"❌ {i+1}/{total} falló descarga"
                    continue
            if img.stat().st_size < 5000:
                img.unlink(missing_ok=True)
                with _JOBS_LOCK:
                    _JOBS[job_id]["msg"] = f"❌ {i+1}/{total} imagen inválida"
                continue

            with _JOBS_LOCK:
                _JOBS[job_id]["msg"] = f"zoompan {i+1}/{total}…"
            if not zp.exists():
                ok = imagen_a_zoompan(img, zp, move_idx)
                if not ok:
                    print(f"[job {job_id}] ❌ zoompan fallido: {img}", flush=True)
                    img.unlink(missing_ok=True)
                    with _JOBS_LOCK:
                        _JOBS[job_id]["msg"] = f"❌ {i+1}/{total} falló zoompan"
                    continue
            img.unlink(missing_ok=True)
            move_idx += 1

        w2, h2 = get_dims(zp)
        fname  = zp.name
        clips[fname] = {
            "slot": next_slot, "estado": "pendiente", "tipo": "video",
            "path": str(zp), "duration": 7.5, "slot_start": 0, "slot_end": 0,
            "srt_text": "", "search_query": "", "ia_prompt": "",
            "width": w2, "height": h2, "fuente": "web",
        }
        make_thumbnail(str(zp), thumb_dir / (pathlib.Path(fname).stem + ".jpg"))
        added_count += 1
        next_slot += 1
        usados.add(str(zp))
        with _JOBS_LOCK:
            _JOBS[job_id].update({"done": i + 1, "added": added_count,
                                   "msg": f"✅ {i+1}/{total} listo"})

    section2["clips"] = clips
    meta2[label] = section2
    save_meta(meta2)
    with _JOBS_LOCK:
        _JOBS[job_id].update({"status": "done", "done": total, "added": added_count,
                               "msg": f"✅ {added_count} de {total} completadas"})


@app.route("/api/add_to_section", methods=["POST"])
def api_add_to_section():
    """Lanza descarga+zoompan en background. Devuelve job_id inmediatamente."""
    data  = request.json
    label = data.get("label")
    items = data.get("items", [])
    if not label or not items:
        return jsonify({"error": "faltan parámetros"}), 400

    meta    = load_meta()
    section = meta.get(label, {})
    if not section:
        return jsonify({"error": "sección no encontrada"}), 404

    nombre  = section.get("nombre", "")
    carpeta = buscar_carpeta_icloud(nombre)
    if not carpeta:
        carpeta = ICLOUD / nombre
        carpeta.mkdir(parents=True, exist_ok=True)

    job_id = hashlib.md5(f"{label}{time.time()}".encode()).hexdigest()[:10]
    with _JOBS_LOCK:
        _JOBS[job_id] = {"status": "pending", "done": 0, "total": len(items),
                         "added": 0, "msg": "Iniciando…", "label": label}

    t = threading.Thread(target=_run_add_job, args=(job_id, label, items, carpeta), daemon=True)
    t.start()
    return jsonify({"ok": True, "job_id": job_id, "total": len(items)})


@app.route("/api/job_status/<job_id>")
def api_job_status(job_id):
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if not job:
        return jsonify({"error": "job no encontrado"}), 404
    return jsonify(job)


@app.route("/api/scan_upload_folder", methods=["GET"])
def api_scan_upload_folder():
    """Lista archivos en ~/Downloads/Upload listos para procesar."""
    IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp'}
    VIDEO_EXTS = {'.mp4'}
    files = []
    for f in sorted(UPLOAD_DIR.iterdir()):
        if f.suffix.lower() in IMAGE_EXTS | VIDEO_EXTS and f.is_file():
            files.append({"name": f.name, "size": f.stat().st_size,
                          "tipo": "video" if f.suffix.lower() in VIDEO_EXTS else "imagen",
                          "preview_url": f"/api/upload_folder_file/{f.name}"})
    return jsonify({"ok": True, "files": files, "total": len(files)})


@app.route("/api/upload_folder_file/<filename>")
def api_upload_folder_file(filename):
    """Sirve un archivo de ~/Downloads/Upload para preview."""
    p = UPLOAD_DIR / filename
    if not p.exists() or not p.is_file():
        return "not found", 404
    mime = "video/mp4" if p.suffix.lower() == ".mp4" else "image/jpeg"
    return send_file(str(p), mimetype=mime)


@app.route("/api/process_upload_folder", methods=["POST"])
def api_process_upload_folder():
    """Procesa archivos de ~/Downloads/Upload para el artista dado y los borra al terminar."""
    data  = request.get_json(force=True)
    label = data.get("label", "")
    if not label:
        return jsonify({"error": "falta label"}), 400

    meta    = load_meta()
    section = meta.get(label, {})
    if not section:
        return jsonify({"error": "sección no encontrada"}), 404

    nombre  = section.get("nombre", "")
    carpeta = buscar_carpeta_icloud(nombre)
    if not carpeta:
        carpeta = ICLOUD / nombre
        carpeta.mkdir(parents=True, exist_ok=True)

    IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp'}
    VIDEO_EXTS = {'.mp4'}
    archivos = [f for f in sorted(UPLOAD_DIR.iterdir())
                if f.suffix.lower() in IMAGE_EXTS | VIDEO_EXTS and f.is_file()]

    if not archivos:
        return jsonify({"ok": True, "total": 0, "msg": "No hay archivos en la carpeta Upload"})

    clips     = section.get("clips", {})
    next_slot = max((v.get("slot", 0) for v in clips.values()), default=-1) + 1
    move_idx  = sum(1 for f in carpeta.glob("*_zp.mp4"))
    thumb_dir = thumbs_dir() / label.replace(" ", "_")
    thumb_dir.mkdir(parents=True, exist_ok=True)

    imgs = [(f, move_idx + i) for i, f in enumerate(archivos) if f.suffix.lower() in IMAGE_EXTS]
    vids = [f for f in archivos if f.suffix.lower() in VIDEO_EXTS]

    # MP4s → copiar a iCloud y registrar directo
    for f in vids:
        h_id  = abs(hash(f.name + str(time.time()))) % 99999
        dest  = carpeta / f"upload_{h_id:05d}.mp4"
        import shutil; shutil.copy2(f, dest)
        w, h_dim = get_dims(dest)
        dur = get_duration(dest)
        fname = dest.name
        clips[fname] = {
            "slot": next_slot, "estado": "pendiente", "tipo": "video",
            "path": str(dest), "duration": dur, "slot_start": 0, "slot_end": 0,
            "srt_text": "", "search_query": "", "ia_prompt": "",
            "width": w, "height": h_dim, "fuente": "upload",
        }
        make_thumbnail(str(dest), thumb_dir / (pathlib.Path(fname).stem + ".jpg"))
        next_slot += 1
        f.unlink(missing_ok=True)  # borrar de Upload

    section["clips"] = clips
    meta[label] = section
    save_meta(meta)

    if not imgs:
        return jsonify({"ok": True, "added": len(vids), "total": len(archivos)})

    # Imágenes → zoompan en background, borrar de Upload al terminar
    items = [{"_local_path": str(src), "_move_idx": mi, "_upload_src": str(src)}
             for src, mi in imgs]

    def _run_folder_job(job_id, lbl, img_list, carp):
        total = len(img_list)
        with _JOBS_LOCK:
            _JOBS[job_id].update({"status": "running", "total": total})
        meta2 = load_meta()
        section2 = meta2.get(lbl, {})
        clips2   = section2.get("clips", {})
        ns   = max((v.get("slot", 0) for v in clips2.values()), default=-1) + 1
        td   = thumbs_dir() / lbl.replace(" ", "_")
        td.mkdir(parents=True, exist_ok=True)
        added = 0
        for i, itm in enumerate(img_list):
            src  = pathlib.Path(itm["_local_path"])
            midx = itm["_move_idx"]
            h_id = abs(hash(src.name + str(time.time()))) % 99999
            # Copiar imagen a iCloud primero
            import shutil
            icloud_img = carp / f"upload_{h_id:05d}{src.suffix.lower()}"
            shutil.copy2(src, icloud_img)
            zp = carp / f"upload_{h_id:05d}_zp.mp4"
            with _JOBS_LOCK:
                _JOBS[job_id].update({"done": i+1, "msg": f"zoompan {i+1}/{total}…"})
            ok2 = imagen_a_zoompan(icloud_img, zp, midx)
            icloud_img.unlink(missing_ok=True)  # borrar copia temporal en iCloud
            if ok2:
                src.unlink(missing_ok=True)  # borrar de ~/Downloads/Upload
                w2, h2 = get_dims(zp)
                fname2 = zp.name
                clips2[fname2] = {
                    "slot": ns, "estado": "pendiente", "tipo": "video",
                    "path": str(zp), "duration": 7.5, "slot_start": 0, "slot_end": 0,
                    "srt_text": "", "search_query": "", "ia_prompt": "",
                    "width": w2, "height": h2, "fuente": "upload",
                }
                make_thumbnail(str(zp), td / (pathlib.Path(fname2).stem + ".jpg"))
                ns += 1
                added += 1
            else:
                print(f"[folder job] ❌ zoompan falló: {src}", flush=True)
        section2["clips"] = clips2
        meta2[lbl] = section2
        save_meta(meta2)
        with _JOBS_LOCK:
            _JOBS[job_id].update({"status": "done", "done": total, "added": added,
                                  "msg": f"✅ {added}/{total} listas"})

    job_id = hashlib.md5(f"folder{label}{time.time()}".encode()).hexdigest()[:10]
    with _JOBS_LOCK:
        _JOBS[job_id] = {"status": "pending", "done": 0, "total": len(imgs),
                         "added": 0, "msg": "Iniciando…", "label": label}
    threading.Thread(target=_run_folder_job,
                     args=(job_id, label, items, carpeta), daemon=True).start()
    return jsonify({"ok": True, "added": len(vids), "job_id": job_id,
                    "total": len(imgs), "has_job": True})


@app.route("/api/upload_clip", methods=["POST"])
def api_upload_clip():
    """Recibe archivo(s) subidos. MP4 → directo al meta. Imágenes → zoompan en background."""
    label = request.form.get("label", "")
    if not label:
        return jsonify({"error": "falta label"}), 400

    meta    = load_meta()
    section = meta.get(label, {})
    if not section:
        return jsonify({"error": "sección no encontrada"}), 404

    nombre   = section.get("nombre", "")
    carpeta  = buscar_carpeta_icloud(nombre)
    if not carpeta:
        carpeta = ICLOUD / nombre
        carpeta.mkdir(parents=True, exist_ok=True)

    # Guardar archivos recibidos en la carpeta iCloud del artista
    saved_imgs = []  # (Path img, move_idx)
    saved_vids = []  # Path mp4

    clips     = section.get("clips", {})
    next_slot = max((v.get("slot", 0) for v in clips.values()), default=-1) + 1
    move_idx  = sum(1 for f in carpeta.glob("*_zp.mp4"))
    thumb_dir = thumbs_dir() / label.replace(" ", "_")
    thumb_dir.mkdir(parents=True, exist_ok=True)

    for f in request.files.getlist("files"):
        orig_ext = pathlib.Path(f.filename).suffix.lower() or ".jpg"
        h_id     = abs(hash(f.filename + str(time.time()))) % 99999
        dest     = carpeta / f"upload_{h_id:05d}{orig_ext}"
        f.save(str(dest))

        if orig_ext == ".mp4":
            # MP4 directo → registrar en meta sin zoompan
            w, h = get_dims(dest)
            dur  = get_duration(dest)
            fname = dest.name
            clips[fname] = {
                "slot": next_slot, "estado": "pendiente", "tipo": "video",
                "path": str(dest), "duration": dur, "slot_start": 0, "slot_end": 0,
                "srt_text": "", "search_query": "", "ia_prompt": "",
                "width": w, "height": h, "fuente": "upload",
            }
            make_thumbnail(str(dest), thumb_dir / (pathlib.Path(fname).stem + ".jpg"))
            next_slot += 1
            saved_vids.append(dest)
        else:
            saved_imgs.append((dest, move_idx))
            move_idx += 1

    section["clips"] = clips
    meta[label] = section
    save_meta(meta)

    # Lanzar zoompan en background para las imágenes
    if saved_imgs:
        items_fake = [{"url": f"file://{p}", "_local_path": str(p), "_move_idx": mi}
                      for p, mi in saved_imgs]

        def _run_upload_job(job_id, lbl, img_list, carp):
            total = len(img_list)
            with _JOBS_LOCK:
                _JOBS[job_id].update({"status": "running", "total": total})
            meta2    = load_meta()
            section2 = meta2.get(lbl, {})
            clips2   = section2.get("clips", {})
            ns       = max((v.get("slot", 0) for v in clips2.values()), default=-1) + 1
            td       = thumbs_dir() / lbl.replace(" ", "_")
            td.mkdir(parents=True, exist_ok=True)
            added = 0
            for i, itm in enumerate(img_list):
                src  = pathlib.Path(itm["_local_path"])
                midx = itm["_move_idx"]
                zp   = carp / (src.stem + "_zp.mp4")
                with _JOBS_LOCK:
                    _JOBS[job_id].update({"done": i+1, "msg": f"zoompan {i+1}/{total}…"})
                ok = imagen_a_zoompan(src, zp, midx)
                if ok:
                    src.unlink(missing_ok=True)
                    w2, h2 = get_dims(zp)
                    fname2 = zp.name
                    clips2[fname2] = {
                        "slot": ns, "estado": "pendiente", "tipo": "video",
                        "path": str(zp), "duration": 7.5, "slot_start": 0, "slot_end": 0,
                        "srt_text": "", "search_query": "", "ia_prompt": "",
                        "width": w2, "height": h2, "fuente": "upload",
                    }
                    make_thumbnail(str(zp), td / (pathlib.Path(fname2).stem + ".jpg"))
                    ns += 1
                    added += 1
                else:
                    print(f"[upload job] ❌ zoompan falló: {src}", flush=True)
            section2["clips"] = clips2
            meta2[lbl] = section2
            save_meta(meta2)
            with _JOBS_LOCK:
                _JOBS[job_id].update({"status": "done", "done": total, "added": added,
                                      "msg": f"✅ {added}/{total} listas"})

        job_id = hashlib.md5(f"upload{label}{time.time()}".encode()).hexdigest()[:10]
        with _JOBS_LOCK:
            _JOBS[job_id] = {"status": "pending", "done": 0, "total": len(saved_imgs),
                             "added": 0, "msg": "Iniciando zoompan…", "label": label}
        threading.Thread(target=_run_upload_job,
                         args=(job_id, label, items_fake, carpeta), daemon=True).start()
        return jsonify({"ok": True, "added": len(saved_vids), "job_id": job_id,
                        "total": len(saved_imgs), "has_job": True})

    return jsonify({"ok": True, "added": len(saved_vids), "has_job": False})


@app.route("/api/add_youtube_clips", methods=["POST"])
def api_add_youtube_clips():
    """
    Llama a extraer_clips_video.py para descargar y extraer clips a la carpeta
    iCloud del artista, luego sincroniza el meta con lo que quedó en disco.
    """
    data    = request.json
    label   = data.get("label", "")
    url     = data.get("url", "")
    n_clips = int(data.get("n_clips", 20))
    if not label or not url:
        return jsonify({"error": "faltan parámetros"}), 400

    meta    = load_meta()
    section = meta.get(label, {})
    if not section:
        return jsonify({"error": "sección no encontrada"}), 404

    nombre  = section.get("nombre", "")
    carpeta = buscar_carpeta_icloud(nombre)
    if not carpeta:
        # Crear carpeta si no existe
        carpeta = ICLOUD / nombre
        carpeta.mkdir(parents=True, exist_ok=True)

    # Snapshots de archivos ANTES para detectar los nuevos
    antes = set(carpeta.glob("*.mp4")) | set(carpeta.glob("*.jpg")) | \
            set(carpeta.glob("*.png")) | set(carpeta.glob("*.webp"))

    # Llamar extraer_clips_video.py
    script = HOME / "Downloads/Canales/extraer_clips_video.py"
    proc = subprocess.run(
        ["python3", str(script), url, str(carpeta), "--clips", str(n_clips), "--no-color", "--force-reencode"],
        capture_output=True, text=True, timeout=600
    )

    if proc.returncode != 0 and not any(carpeta.glob("*.mp4")):
        app.logger.error("extraer_clips_video stderr: %s", proc.stderr[-1200:])
        app.logger.error("extraer_clips_video stdout: %s", proc.stdout[-400:])
        return jsonify({
            "error": "extraer_clips_video.py falló",
            "stderr": proc.stderr[-800:]
        }), 500

    # Detectar archivos nuevos
    despues  = set(carpeta.glob("*.mp4")) | set(carpeta.glob("*.jpg")) | \
               set(carpeta.glob("*.png")) | set(carpeta.glob("*.webp"))
    nuevos   = sorted(despues - antes)

    # Agregar solo los nuevos al meta
    clips     = section.get("clips", {})
    usados    = {v["path"] for v in clips.values()}
    next_slot = max((v.get("slot", 0) for v in clips.values()), default=-1) + 1
    added     = []

    thumb_dir = thumbs_dir() / label.replace(" ", "_")
    thumb_dir.mkdir(parents=True, exist_ok=True)

    for p in nuevos:
        if str(p) in usados:
            continue
        fname = p.name
        tipo  = "video" if p.suffix == ".mp4" else "imagen"
        dur   = get_duration(p) if tipo == "video" else 0
        w, h  = get_dims(p)
        clips[fname] = {
            "slot": next_slot, "estado": "pendiente", "tipo": tipo,
            "path": str(p), "duration": dur, "slot_start": 0, "slot_end": 0,
            "srt_text": "", "search_query": "", "ia_prompt": "",
            "width": w, "height": h, "fuente": "icloud",
        }
        make_thumbnail(str(p), thumb_dir / (pathlib.Path(fname).stem + ".jpg"))
        added.append({
            "filename": fname, "slot": next_slot,
            "thumb_url": f"/thumb?label={urllib.parse.quote(label)}&filename={urllib.parse.quote(fname)}",
            "media_url": f"/media?label={urllib.parse.quote(label)}&filename={urllib.parse.quote(fname)}",
        })
        next_slot += 1
        usados.add(str(p))

    section["clips"] = clips
    save_meta(meta)
    return jsonify({"ok": True, "added": len(added), "clips": added, "log": proc.stdout[-400:]})


@app.route("/api/mark_flow", methods=["POST"])
def api_mark_flow():
    """Marca un clip directamente para generar con Flow (sin buscar en iCloud ni Brave)."""
    data     = request.json
    label    = data.get("label")
    filename = data.get("filename")
    if not label or not filename:
        return jsonify({"error": "faltan parámetros"}), 400
    meta = load_meta()
    if label not in meta or filename not in meta[label]["clips"]:
        return jsonify({"error": "clip no encontrado"}), 404
    meta[label]["clips"][filename]["estado"] = "needs_flow"
    save_meta(meta)
    return jsonify({"ok": True, "estado": "needs_flow"})


@app.route("/api/duplicados")
def api_duplicados():
    """
    Devuelve un dict {path → [label, fname, ...]} de todos los paths
    que aparecen en MÁS DE UNA slot activa del timeline completo.
    """
    meta  = load_meta()
    path_to_slots = {}
    for lbl, section in meta.items():
        for fname, info in section.get("clips", {}).items():
            if info.get("estado") == "rechazado":
                continue
            p = str(info.get("path", ""))
            if not p:
                continue
            if p not in path_to_slots:
                path_to_slots[p] = []
            path_to_slots[p].append({"label": lbl, "fname": fname})
    duplicados = {p: slots for p, slots in path_to_slots.items() if len(slots) > 1}
    return jsonify(duplicados)


@app.route("/api/flow_count")
def api_flow_count():
    """Cuántos slots needs_flow hay en total."""
    meta  = load_meta()
    items = []
    for label, section in meta.items():
        for fname, info in section.get("clips", {}).items():
            if info.get("estado") == "needs_flow":
                items.append({
                    "label":      label,
                    "nombre":     section.get("nombre", ""),
                    "filename":   fname,
                    "slot":       info.get("slot", 0),
                    "slot_start": info.get("slot_start", 0),
                    "srt_text":   info.get("srt_text", ""),
                })
    return jsonify({"count": len(items), "items": items})


@app.route("/api/send_to_flow", methods=["POST"])
def api_send_to_flow():
    """
    Recoge todos los slots needs_flow y los manda a Baserow en batch.
    Genera ia_prompt y veo_prompt por artista + contexto SRT.
    """
    meta  = load_meta()
    pendientes = []
    for label, section in meta.items():
        nombre = section.get("nombre", "")
        for fname, info in section.get("clips", {}).items():
            if info.get("estado") == "needs_flow":
                srt       = info.get("srt_text", "")
                slot      = info.get("slot", 0)
                nombre_d  = nombre.title()
                # Usar ia_prompt específico del slot (generado en el harvester)
                ia_prompt = info.get("ia_prompt") or (
                    f"Photorealistic scene of Mexican TV entertainer {nombre_d}, "
                    f"1980s Televisa Mexico studio, no text, cinematic lighting"
                )
                veo_prompt = f"Slow cinematic zoom in, {nombre_d} on Mexican television"
                pendientes.append({
                    "label":      label,
                    "nombre":     nombre,
                    "filename":   fname,
                    "slot":       slot,
                    "ia_prompt":  ia_prompt,
                    "veo_prompt": veo_prompt,
                    "srt_text":   srt,
                })

    if not pendientes:
        return jsonify({"ok": False, "error": "No hay slots needs_flow"})

    # Limpiar Baserow
    borrados = limpiar_baserow()

    # Crear filas en batch
    items = []
    for p in pendientes:
        items.append({
            "Image Prompt": p["ia_prompt"],
            "VEO Prompt":   p["veo_prompt"],
            "Mode":         "Imagegen",
            "Status":       "pending",
            "segment_id":   str(p["slot"]),
        })

    result  = _baserow_curl('POST',
        f'/database/rows/table/{BASEROW_TABLE_ID}/batch/?user_field_names=true',
        {'items': items})
    created = result.get('items', [])

    # Guardar mapeo row_id → slot en meta
    for i, row in enumerate(created):
        if i >= len(pendientes): break
        p = pendientes[i]
        meta[p["label"]]["clips"][p["filename"]]["estado"]       = "flow_sent"
        meta[p["label"]]["clips"][p["filename"]]["baserow_row"]  = row.get("id")
        meta[p["label"]]["clips"][p["filename"]]["ia_prompt"]    = p["ia_prompt"]

    save_meta(meta)

    return jsonify({
        "ok":      True,
        "enviados": len(created),
        "borrados": borrados,
        "message": f"{len(created)} filas en Baserow — corre la extensión VEO y avisa cuando termines",
    })


@app.route("/api/check_flow_downloads", methods=["POST"])
def api_check_flow_downloads():
    """
    Revisa Baserow: si hay Video_URL llena para alguna fila flow_sent,
    descarga el clip con yt-dlp y actualiza el slot.
    """
    meta = load_meta()

    # Obtener filas de Baserow
    data = _baserow_curl('GET', f'/database/rows/table/{BASEROW_TABLE_ID}/?user_field_names=true&size=200')
    rows = {r['id']: r for r in data.get('results', [])}

    descargados = 0
    pendientes  = 0

    for label, section in meta.items():
        nombre = section.get("nombre", "")
        for fname, info in section.get("clips", {}).items():
            if info.get("estado") != "flow_sent":
                continue
            row_id = info.get("baserow_row")
            if not row_id or row_id not in rows:
                pendientes += 1
                continue

            row = rows[row_id]
            sv  = row.get('Status', '')
            if isinstance(sv, dict): sv = sv.get('value', '')

            if sv == 'completed':
                url = row.get('Video_URL', '')
                if url and url.startswith('http'):
                    # Descargar clip de Flow
                    flow_dir = VIDEO_FOLDER / "_flow_reemplazos"
                    flow_dir.mkdir(exist_ok=True)
                    slot = info.get("slot", 0)
                    dest = flow_dir / f"flow_{label[:8].replace(' ','_')}_{slot:03d}.mp4"
                    r = subprocess.run(
                        [YTDLP, '--cookies-from-browser', 'brave',
                         '-o', str(dest), '--no-playlist', '-q', url],
                        capture_output=True, timeout=120
                    )
                    if dest.exists() and dest.stat().st_size > 5000:
                        w, h = get_dims(dest)
                        dur  = get_duration(dest)
                        meta[label]["clips"][fname]["estado"] = "aprobado"
                        meta[label]["clips"][fname]["path"]   = str(dest)
                        meta[label]["clips"][fname]["tipo"]   = "video"
                        meta[label]["clips"][fname]["width"]  = w
                        meta[label]["clips"][fname]["height"] = h
                        meta[label]["clips"][fname]["duration"] = dur
                        meta[label]["clips"][fname]["fuente"] = "flow"
                        descargados += 1
                    else:
                        pendientes += 1
                else:
                    pendientes += 1
            else:
                pendientes += 1

    save_meta(meta)
    return jsonify({"ok": True, "descargados": descargados, "pendientes": pendientes})


@app.route("/thumb")
def serve_thumb():
    label    = request.args.get("label", "")
    filename = request.args.get("filename", "")
    meta     = load_meta()
    section  = meta.get(label, {})
    clip     = section.get("clips", {}).get(filename)
    if not clip:
        return "not found", 404
    src_path = pathlib.Path(clip.get("path", ""))
    if not src_path.is_absolute():
        src_path = VIDEO_FOLDER.parent / src_path
    thumb_path = thumbs_dir() / label.replace(" ", "_") / (pathlib.Path(filename).stem + ".jpg")
    make_thumbnail(str(src_path), thumb_path)
    if thumb_path.exists():
        return send_file(str(thumb_path), mimetype="image/jpeg")
    return "no thumb", 404


@app.route("/media")
def serve_media():
    label    = request.args.get("label", "")
    filename = request.args.get("filename", "")
    meta     = load_meta()
    section  = meta.get(label, {})
    clip     = section.get("clips", {}).get(filename)
    if not clip:
        return "not found", 404
    path = pathlib.Path(clip.get("path", ""))
    if not path.is_absolute():
        path = VIDEO_FOLDER.parent / path
    if not path.exists():
        return "file not found", 404
    # Redirigir al servidor estático (ThreadingMixIn) para no bloquear Flask
    from flask import redirect
    return redirect(f"http://localhost:{STATIC_PORT}/?p={urllib.parse.quote(str(path))}")


@app.route("/api/trim_clip", methods=["POST"])
def api_trim_clip():
    data     = request.json
    label    = data.get("label", "")
    filename = data.get("filename", "")
    start    = float(data.get("start", 0))
    end      = float(data.get("end", 0))
    if end <= start:
        return jsonify({"error": "end debe ser mayor que start"}), 400

    meta    = load_meta()
    section = meta.get(label, {})
    clip    = section.get("clips", {}).get(filename)
    if not clip:
        return jsonify({"error": "clip no encontrado"}), 404

    path = pathlib.Path(clip.get("path", ""))
    if not path.is_absolute():
        path = VIDEO_FOLDER.parent / path
    if not path.exists():
        return jsonify({"error": "archivo no existe"}), 404

    tmp = path.with_suffix(".trim_tmp.mp4")
    r = subprocess.run([
        FFMPEG, "-y",
        "-ss", str(round(start, 3)),
        "-to", str(round(end, 3)),
        "-i", str(path),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-an",
        str(tmp)
    ], capture_output=True, timeout=120)

    if r.returncode != 0:
        return jsonify({"error": r.stderr.decode()[-200:]}), 500

    tmp.replace(path)  # reemplaza el original atómicamente

    # Actualizar duración en meta
    new_dur = end - start
    meta[label]["clips"][filename]["duration"] = round(new_dur, 2)
    save_meta(meta)

    return jsonify({"ok": True, "new_duration": new_dur})


# ─── Pre-generar thumbnails en background ─────────────────────────────────────

def purgar_fantasmas():
    """Al arrancar, elimina del meta cualquier clip cuyo archivo ya no existe en disco."""
    meta = load_meta()
    total = 0
    for label, section in meta.items():
        clips = section.get("clips", {})
        to_del = [f for f, info in clips.items() if not pathlib.Path(info.get("path","")).exists()]
        for f in to_del:
            del clips[f]
            total += 1
    if total:
        save_meta(meta)
        print(f"  ✓ {total} entradas fantasma purgadas del meta")

purgar_fantasmas()

def pregen_thumbnails():
    """Genera todos los thumbnails en segundo plano al arrancar."""
    import time as _time
    _time.sleep(1)  # esperar que Flask arranque
    meta = load_meta()
    total = 0
    for label, section in meta.items():
        lbl_dir = thumbs_dir() / label.replace(" ", "_")
        lbl_dir.mkdir(parents=True, exist_ok=True)
        for fname, info in section.get("clips", {}).items():
            src = info.get("path", "")
            thumb = lbl_dir / (pathlib.Path(fname).stem + ".jpg")
            if not thumb.exists() and src:
                make_thumbnail(src, thumb)
                total += 1
    print(f"  ✓ {total} thumbnails pre-generados")

threading.Thread(target=pregen_thumbnails, daemon=True).start()

# ─── HTML ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return HTML_PAGE


HTML_PAGE = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Farandula — Aprobación de Clips</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0e0e16; color: #e0e0e0; font-family: system-ui, sans-serif; min-height: 100vh; }

.topbar { background: #15151f; border-bottom: 1px solid #2a2a3a; padding: 12px 20px;
          display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
          position: sticky; top: 0; z-index: 100; }
.topbar h1 { font-size: 1.1rem; color: #d4af37; font-weight: 700; white-space: nowrap; }
.section-pills { display: flex; gap: 7px; flex-wrap: wrap; flex: 1; }
.pill { padding: 5px 12px; border-radius: 20px; border: 1px solid #333; background: #1a1a2a;
        cursor: pointer; font-size: 0.78rem; color: #aaa; transition: all .15s; white-space: nowrap; }
.pill:hover { border-color: #d4af37; color: #d4af37; }
.pill.active { background: #d4af37; color: #0e0e16; border-color: #d4af37; font-weight: 700; }
.pill .ok  { color: #00cc66; font-size: 0.7rem; }
.pill .bad { color: #ff4455; font-size: 0.7rem; }
.pill .flow-badge { color: #a78bfa; font-size: 0.7rem; }

.flow-bar { background: #12101e; border-bottom: 1px solid #2a1a4a; padding: 8px 20px;
            display: flex; align-items: center; gap: 12px; }
.flow-count { color: #a78bfa; font-size: 0.85rem; font-weight: 600; }
.btn-flow { padding: 6px 16px; border-radius: 6px; border: none; cursor: pointer;
            background: #6d28d9; color: #fff; font-size: 0.82rem; font-weight: 700; transition: opacity .15s; }
.btn-flow:hover { opacity: 0.85; }
.btn-flow:disabled { opacity: 0.4; cursor: default; }
.btn-check-flow { padding: 6px 14px; border-radius: 6px; border: 1px solid #6d28d9;
                  cursor: pointer; background: transparent; color: #a78bfa; font-size: 0.82rem; }
.flow-msg { font-size: 0.78rem; color: #888; }

.statsbar { background: #12121a; padding: 8px 20px; display: flex; gap: 20px; flex-wrap: wrap; font-size: 0.8rem; }
.stat { display: flex; align-items: center; gap: 5px; }
.dot { width: 7px; height: 7px; border-radius: 50%; }
.dot.pend { background: #555; } .dot.apro { background: #00cc66; }
.dot.rech { background: #ff4455; } .dot.flow { background: #a78bfa; }

.toolbar { padding: 10px 20px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.btn { padding: 6px 12px; border-radius: 6px; border: none; cursor: pointer;
       font-size: 0.8rem; font-weight: 600; transition: opacity .15s; }
.btn:hover { opacity: 0.85; }
.btn-green { background: #00cc66; color: #000; }
.btn-red   { background: #ff4455; color: #fff; }
.btn-gray  { background: #2a2a3a; color: #ccc; }
.filter-btns { display: flex; gap: 5px; margin-left: auto; }
.filter-btn { padding: 4px 9px; border-radius: 4px; border: 1px solid #333;
              background: #1a1a2a; cursor: pointer; font-size: 0.75rem; color: #aaa; }
.filter-btn.active { border-color: #d4af37; color: #d4af37; }

.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
        gap: 10px; padding: 14px 20px; }
.card { background: #16161e; border: 2px solid #2a2a3a; border-radius: 8px; overflow: hidden;
        display: flex; flex-direction: column; transition: border-color .15s; }
.card.aprobado   { border-color: #00cc66; }
.card.rechazado  { border-color: #ff4455; opacity: 0.45; }
.card.needs_flow { border-color: #a78bfa; }
.card.duplicado  { border-color: #ff3333; box-shadow: 0 0 8px rgba(255,50,50,0.5); }
.card.flow_sent  { border-color: #6d28d9; }
.card:hover { border-color: #d4af37; }

.card-media { position: relative; width: 100%; aspect-ratio: 16/9; background: #050508;
              overflow: hidden; cursor: pointer; }
.card-media img   { width: 100%; height: 100%; object-fit: cover; display: block; }
.card-placeholder { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;
                    font-size: 2rem; opacity: 0.25; }
.card-media .play { position: absolute; inset: 0; display: flex; align-items: center;
                    justify-content: center; font-size: 2rem; opacity: 0; transition: opacity .2s; pointer-events: none; }
.card-media:hover .play { opacity: 0.7; }
.tipo-badge { position: absolute; top: 4px; right: 4px; font-size: 0.6rem; padding: 2px 5px;
              border-radius: 3px; background: rgba(0,0,0,0.7); color: #aaa; }
.fuente-badge { position: absolute; top: 4px; left: 4px; font-size: 0.6rem; padding: 2px 5px;
                border-radius: 3px; }
.fuente-icloud { background: rgba(0,80,200,0.7); color: #6af; }
.fuente-brave  { background: rgba(200,80,0,0.7);  color: #fa8; }
.fuente-flow   { background: rgba(100,40,180,0.7); color: #c9b; }
.dur-badge { position: absolute; bottom: 4px; right: 4px; font-size: 0.6rem; padding: 2px 5px;
             border-radius: 3px; background: rgba(0,0,0,0.7); color: #ddd; }
.flow-status-overlay { position: absolute; inset: 0; background: rgba(109,40,217,0.35);
                       display: flex; align-items: center; justify-content: center;
                       font-size: 0.75rem; color: #c4b5fd; font-weight: 700; }

.card-info { padding: 7px 9px; flex: 1; }
.card-slot { font-size: 0.68rem; color: #d4af37; font-weight: 700; margin-bottom: 1px; }
.card-filename { font-size: 0.62rem; color: #555; word-break: break-all; margin-bottom: 3px; }
.card-srt { font-size: 0.65rem; color: #889; line-height: 1.3; font-style: italic;
            display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; margin-bottom: 3px; }
.card-dims { font-size: 0.6rem; color: #444; }

.card-actions { display: flex; gap: 0; border-top: 1px solid #222; }
.card-actions button { flex: 1; padding: 7px; border: none; cursor: pointer;
                       font-size: 0.75rem; font-weight: 600; transition: background .15s; }
.btn-rechazar { background: #2a0a0e; color: #ff4455; }
.btn-eliminar { background: #1a1a1a; color: #888; border-left: 1px solid #2a2a2a; padding: 0 8px; font-size: 0.85rem; }
.btn-flow-card { background: #1a0e2e; color: #a78bfa; border-left: 1px solid #2a1a4a; }
.btn-rechazar:hover  { background: #ff4455; color: #fff; }
.btn-eliminar:hover  { background: #333; color: #fff; }
.btn-flow-card:hover { background: #6d28d9; color: #fff; }
.btn-replacing { background: #1a1a2a; color: #888; font-size: 0.7rem; }

.replacing-overlay { position: absolute; inset: 0; background: rgba(14,14,22,0.85);
                     display: flex; align-items: center; justify-content: center;
                     font-size: 0.8rem; color: #d4af37; }

.loading { text-align: center; padding: 60px; color: #555; }
.toast { position: fixed; bottom: 20px; right: 20px; padding: 10px 18px; border-radius: 8px;
         font-size: 0.85rem; font-weight: 600; z-index: 9999; transition: opacity .3s; }
.toast.success { background: #00cc66; color: #000; }
.toast.error   { background: #ff4455; color: #fff; }
.toast.info    { background: #6d28d9; color: #fff; }

/* Drag & drop */
.card { cursor: grab; }
.card.dragging { opacity: .35; cursor: grabbing; transform: scale(.97); }
.card.drag-over { border-color: #d4af37 !important; border-style: dashed !important; }
.drag-ghost { position: fixed; pointer-events: none; z-index: 9990; opacity: .85;
              border-radius: 8px; box-shadow: 0 8px 30px rgba(0,0,0,.6); }
</style>
</head>
<body>

<div class="topbar">
  <h1>🎬 Farandula</h1>
  <div class="section-pills" id="pills"></div>

  <div id="audio-player" style="display:flex;align-items:center;gap:8px;flex-shrink:0;background:#0d0d1a;border:1px solid #333;border-radius:8px;padding:6px 12px;">
    <button id="ap-playpause" onclick="apToggle()" title="Play / Pausa"
      style="width:32px;height:32px;border-radius:50%;border:none;background:#5566ff;color:#fff;font-size:14px;cursor:pointer;flex-shrink:0;">▶</button>
    <span id="ap-cur" style="font-size:11px;color:#aaa;min-width:36px;text-align:right;">0:00</span>
    <input id="ap-seek" type="range" min="0" max="100" value="0" step="0.1"
      style="width:180px;accent-color:#5566ff;cursor:pointer;"
      oninput="apSeek(this.value)" />
    <span id="ap-dur" style="font-size:11px;color:#666;min-width:36px;">0:00</span>
    <input id="ap-vol" type="range" min="0" max="1" value="0.8" step="0.01"
      style="width:60px;accent-color:#5566ff;cursor:pointer;"
      oninput="apVol(this.value)" title="Volumen" />
    <span style="font-size:11px;color:#555;">🔊</span>
  </div>

  <button id="btn-refresh" onclick="refreshMeta()" title="Sincronizar con iCloud — elimina clips borrados"
    style="padding:6px 14px;border-radius:6px;border:1px solid #444;background:#1a1a2a;color:#aaa;cursor:pointer;font-size:0.8rem;white-space:nowrap;flex-shrink:0;">
    ↺ Sync iCloud
  </button>
</div>

<div class="flow-bar" id="flow-bar" style="display:none">
  <span class="flow-count" id="flow-count">0 slots necesitan Flow</span>
  <button class="btn-flow" id="btn-send-flow" onclick="sendToFlow()">→ Enviar a Flow (Baserow)</button>
  <button class="btn-check-flow" id="btn-check-flow" onclick="checkFlowDownloads()" style="display:none">↓ Revisar descargas</button>
  <span class="flow-msg" id="flow-msg"></span>
</div>

<div style="margin:6px 0 2px;display:flex;align-items:center;gap:8px;">
  <button onclick="checkPreflight()" style="padding:5px 14px;border-radius:6px;border:1px solid #555;background:#1a1a2e;color:#aaa;font-size:0.8rem;cursor:pointer;">🔍 Verificar déficit antes de render</button>
</div>
<div id="preflight-banner" style="display:none;background:#3a1a1a;border:1px solid #cc3333;border-radius:6px;padding:12px 16px;margin:4px 0 8px;color:#ff6666;font-size:13px;"></div>

<div class="statsbar" id="statsbar"></div>

<div class="toolbar">
  <button class="btn btn-green" onclick="approveAll()">✓ Aprobar todos</button>
  <button class="btn btn-red"   onclick="rejectAll()">✗ Rechazar todos</button>
  <button class="btn btn-gray"  onclick="resetAll()">↺ Resetear</button>
  <div class="filter-btns">
    <button class="filter-btn active" id="f-todos"      onclick="setFilter('todos')">Todos</button>
    <button class="filter-btn"        id="f-pendiente"  onclick="setFilter('pendiente')">Pendientes</button>
    <button class="filter-btn"        id="f-aprobado"   onclick="setFilter('aprobado')">Aprobados</button>
    <button class="filter-btn"        id="f-rechazado"  onclick="setFilter('rechazado')">Rechazados</button>
    <button class="filter-btn"        id="f-needs_flow" onclick="setFilter('needs_flow')">Flow</button>
  </div>
</div>

<div id="grid" class="grid"><div class="loading">Selecciona una sección arriba</div></div>

<!-- Botón Agregar flotante -->
<div id="agregar-bar" style="display:none;position:sticky;bottom:0;background:#0e0e16;border-top:1px solid #2a2a3a;padding:10px 20px;z-index:50;">
  <button onclick="openAgregar()" style="padding:9px 22px;border-radius:8px;border:none;cursor:pointer;background:#d4af37;color:#0e0e16;font-size:0.9rem;font-weight:700;letter-spacing:.3px;">+ Agregar clips a esta sección</button>
</div>

<!-- Modal Agregar -->
<div id="modal-agregar" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.88);z-index:9998;overflow:auto;">
  <div style="max-width:780px;margin:40px auto;background:#16161e;border-radius:14px;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,.8);">
    <!-- Header del modal -->
    <div style="padding:16px 20px;border-bottom:1px solid #2a2a3a;display:flex;align-items:center;gap:12px;">
      <div id="search-bar-wrap" style="flex:1;display:flex;background:#0e0e16;border:1px solid #333;border-radius:8px;overflow:hidden;">
        <span style="padding:10px 12px;color:#888;font-size:1rem;">🔍</span>
        <input id="agregar-search-input" type="text" placeholder="Buscar..." onkeydown="if(event.key==='Enter')doSearch()"
          style="flex:1;background:transparent;border:none;outline:none;color:#e0e0e0;font-size:0.95rem;padding:10px 0;">
      </div>
      <button id="search-bar-btn" onclick="doSearch()" style="padding:10px 20px;border-radius:8px;border:none;cursor:pointer;background:#6d28d9;color:#fff;font-size:0.9rem;font-weight:700;">Buscar</button>
      <button onclick="closeAgregar()" style="padding:10px 14px;border-radius:8px;border:1px solid #444;background:transparent;color:#aaa;cursor:pointer;font-size:0.9rem;">✕</button>
    </div>

    <!-- Tabs -->
    <div style="display:flex;gap:0;border-bottom:1px solid #2a2a3a;padding:0 20px;">
      <button class="ag-tab active" id="tab-uploads" onclick="setTab('uploads')">📤 Subir</button>
      <button class="ag-tab"        id="tab-web"     onclick="setTab('web')">🌐 Web search</button>
      <button class="ag-tab"        id="tab-stock"   onclick="setTab('stock')">🎨 Stock</button>
      <button class="ag-tab"        id="tab-youtube" onclick="setTab('youtube')">▶ YouTube</button>
    </div>

    <!-- Panel Uploads -->
    <div id="panel-uploads" class="ag-panel" style="padding:24px 20px;">
      <!-- Carpeta ~/Downloads/Upload -->
      <div style="background:#0d0d1a;border:1px solid #2a2a3a;border-radius:10px;padding:16px 20px;margin-bottom:16px;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
          <div>
            <span style="font-size:1rem;color:#ccc;font-weight:600;">📂 ~/Downloads/Upload</span>
            <span style="font-size:0.78rem;color:#555;margin-left:8px;">Coloca imágenes o MP4 ahí y haz clic en Escanear</span>
          </div>
          <button onclick="escanearUploadFolder()" style="background:#1e1e3a;border:1px solid #3a3a5a;color:#aaa;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:0.82rem;">🔍 Escanear</button>
        </div>
        <div id="upload-folder-list" style="display:flex;align-items:center;gap:6px;min-height:28px;margin-bottom:10px;"></div>
        <div id="upload-folder-preview" style="display:flex;flex-wrap:wrap;gap:6px;"></div>
      </div>
      <!-- Drag & drop -->
      <label style="display:block;border:2px dashed #3a3a4a;border-radius:10px;padding:28px;text-align:center;cursor:pointer;color:#888;transition:border-color .2s;" id="drop-zone">
        <input type="file" multiple accept="image/*,video/mp4" id="file-input" style="display:none" onchange="handleFileSelect(event)">
        <div style="font-size:2rem;margin-bottom:6px">📁</div>
        <div style="font-size:0.9rem;margin-bottom:4px">O arrastra archivos aquí</div>
        <div style="font-size:0.78rem;color:#555">Imágenes (JPG, PNG, WEBP) o videos MP4</div>
      </label>
      <div id="upload-preview" style="margin-top:14px;display:flex;flex-wrap:wrap;gap:8px;"></div>
      <div id="upload-btn-row" style="margin-top:12px;display:none;"></div>
    </div>

    <!-- Panel Web search -->
    <div id="panel-web" class="ag-panel" style="display:none;padding:0;">
      <div id="search-grid" style="display:grid;grid-template-columns:repeat(4,1fr);gap:3px;padding:12px;min-height:200px;max-height:480px;overflow-y:auto;"></div>
    </div>

    <!-- Panel Stock (Pexels + Pixabay con subtabs Fotos / Videos) -->
    <div id="panel-stock" class="ag-panel" style="display:none;padding:0;flex-direction:column;">
      <div style="display:flex;gap:0;border-bottom:1px solid #1a1a2a;padding:0 12px;background:#0a0a12;">
        <button class="ag-subtab active" id="subtab-photos" onclick="setStockSubtab('photos')" style="padding:8px 16px;background:none;border:none;color:#aaa;cursor:pointer;font-size:0.82rem;border-bottom:2px solid #6d28d9;">🖼 Fotos</button>
        <button class="ag-subtab"        id="subtab-stockvideos" onclick="setStockSubtab('stockvideos')" style="padding:8px 16px;background:none;border:none;color:#666;cursor:pointer;font-size:0.82rem;border-bottom:2px solid transparent;">🎬 Videos</button>
      </div>
      <div id="photos-grid"      style="display:grid;grid-template-columns:repeat(4,1fr);gap:3px;padding:12px;min-height:200px;max-height:440px;overflow-y:auto;"></div>
      <div id="stockvideos-grid" style="display:none;grid-template-columns:repeat(3,1fr);gap:6px;padding:12px;min-height:200px;max-height:440px;overflow-y:auto;"></div>
    </div>

    <!-- Panel YouTube -->
    <div id="panel-youtube" class="ag-panel" style="display:none;padding:0;flex-direction:column;">
      <!-- URL directa -->
      <div style="padding:10px 16px 0;display:flex;gap:8px;align-items:center;">
        <input type="text" id="yt-url-input" placeholder="Pega URL de YouTube directamente..."
          style="flex:1;padding:8px 14px;background:#0e0e16;border:1px solid #555;border-radius:8px;color:#e0e0e0;font-size:0.85rem;outline:none;"
          onkeydown="if(event.key==='Enter')doYtUrl()">
        <button onclick="doYtUrl()" style="padding:8px 14px;border-radius:8px;border:none;cursor:pointer;background:#1a7a3a;color:#fff;font-weight:700;white-space:nowrap;">▶ Usar URL</button>
      </div>
      <div style="padding:4px 16px 8px;color:#555;font-size:0.72rem;">— o busca por término —</div>
      <!-- Búsqueda por término -->
      <div style="padding:0 16px 12px;border-bottom:1px solid #1a1a2a;display:flex;gap:8px;">
        <input type="text" id="yt-search-input" placeholder="Buscar en YouTube..."
          style="flex:1;padding:9px 14px;background:#0e0e16;border:1px solid #333;border-radius:8px;color:#e0e0e0;font-size:0.9rem;outline:none;"
          onkeydown="if(event.key==='Enter')doYtSearch()">
        <button onclick="doYtSearch()" style="padding:9px 18px;border-radius:8px;border:none;cursor:pointer;background:#ff0000;color:#fff;font-weight:700;">🔍 Buscar</button>
      </div>
      <!-- Grid resultados + mini player lado a lado -->
      <div style="display:flex;flex:1;overflow:hidden;min-height:380px;">
        <!-- Grid de resultados -->
        <div id="yt-results-grid" style="flex:1;overflow-y:auto;padding:10px;display:grid;grid-template-columns:repeat(2,1fr);gap:8px;align-content:start;">
          <div style="grid-column:1/-1;text-align:center;padding:40px;color:#555;font-size:0.85rem;">Escribe un término y busca</div>
        </div>
        <!-- Mini player -->
        <div id="yt-player-panel" style="width:340px;border-left:1px solid #1a1a2a;display:flex;flex-direction:column;background:#07070f;">
          <div id="yt-player-wrap" style="position:relative;width:100%;padding-top:56.25%;background:#000;">
            <iframe id="yt-iframe" style="position:absolute;inset:0;width:100%;height:100%;border:none;" allow="autoplay;encrypted-media" allowfullscreen></iframe>
          </div>
          <div id="yt-player-title" style="padding:10px 12px;font-size:0.78rem;color:#aaa;line-height:1.4;"></div>
          <div style="padding:0 12px 10px;display:flex;align-items:center;gap:8px;">
            <label style="color:#888;font-size:0.8rem;">Clips:</label>
            <input type="number" id="yt-nclips" value="50" min="5" max="200"
              style="width:55px;padding:5px;background:#0e0e16;border:1px solid #333;border-radius:6px;color:#e0e0e0;text-align:center;font-size:0.85rem;">
          </div>
          <div id="yt-status" style="padding:0 12px 10px;color:#888;font-size:0.75rem;"></div>
        </div>
      </div>
    </div>

    <!-- Footer de selección -->
    <div id="agregar-footer" style="padding:12px 20px;border-top:1px solid #2a2a3a;display:flex;align-items:center;justify-content:space-between;">
      <span style="font-size:0.8rem;color:#666" id="images-source-note">Imágenes via Web Search</span>
      <div style="display:flex;gap:8px;">
        <button onclick="closeAgregar()" style="padding:8px 18px;border-radius:8px;border:1px solid #444;background:transparent;color:#aaa;cursor:pointer;">Cancelar</button>
        <button id="btn-confirm-selection" onclick="confirmSelection()" disabled
          style="padding:8px 20px;border-radius:8px;border:none;cursor:pointer;background:#6d28d9;color:#fff;font-weight:700;opacity:.5;">
          ⬆ Subir archivos
        </button>
      </div>
    </div>
  </div>
</div>

<style>
.ag-tab { padding:10px 16px;border:none;background:transparent;cursor:pointer;color:#888;font-size:0.82rem;border-bottom:2px solid transparent;transition:all .15s; }
.ag-tab.active { color:#d4af37;border-bottom-color:#d4af37; }
.ag-tab:hover { color:#ddd; }
.ag-panel { display:block; }
.ag-img-item { position:relative;aspect-ratio:16/9;overflow:hidden;cursor:pointer;border-radius:4px;border:2px solid transparent;background:#050508;transition:border-color .15s; }
.ag-img-item img { width:100%;height:100%;object-fit:cover;display:block; }
.ag-img-item:hover { border-color:#888; }
.ag-img-item.selected { border-color:#6d28d9; }
.ag-img-item .sel-badge { display:none;position:absolute;inset:0;background:rgba(109,40,217,0.5);align-items:center;justify-content:center;font-size:1.5rem;color:#fff; }
.ag-img-item.selected .sel-badge { display:flex; }
.ag-label-tag { position:absolute;bottom:3px;right:3px;font-size:0.6rem;padding:1px 5px;border-radius:3px;background:rgba(0,0,0,.7);color:#aaa; }
.ag-video-item { background:#16161e;border:1px solid #2a2a3a;border-radius:8px;overflow:hidden;cursor:pointer;transition:border-color .15s; }
.ag-video-item:hover { border-color:#888; }
.ag-video-item.selected { border-color:#6d28d9; }
.ag-video-item img { width:100%;aspect-ratio:16/9;object-fit:cover;display:block; }
.ag-video-item .v-info { padding:8px; }
.ag-video-item .v-title { font-size:0.78rem;color:#ccc;line-height:1.3;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden; }
.ag-video-item .v-dur { font-size:0.7rem;color:#666;margin-top:3px; }
</style>

<script>
function fmt(s) {
  const m = Math.floor(s / 60), sec = Math.round(s % 60);
  return m > 0 ? `${m}m${sec}s` : `${sec}s`;
}
function toast(msg, type='success', ms=3000) {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 300); }, ms);
}

let currentLabel = null;
let currentClips = [];
let currentFilter = 'todos';
let sections = [];
let duplicadosGlobal = {};

// ── Agregar Modal ─────────────────────────────────────────────────────────────
let agTab = 'uploads';
let agSelected = []; // [{url, tipo, source}]
let agPendingFiles = [];

function openAgregar() {
  document.getElementById('modal-agregar').style.display = 'block';
  setTab('uploads');
}
function closeAgregar() {
  document.getElementById('modal-agregar').style.display = 'none';
  agSelected = [];
  agPendingFiles = [];
  updateConfirmBtn();
}

let agStockSubtab = 'photos';

function setTab(tab) {
  agTab = tab;
  document.querySelectorAll('.ag-tab').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + tab).classList.add('active');
  document.querySelectorAll('.ag-panel').forEach(p => p.style.display = 'none');
  document.getElementById('panel-' + tab).style.display = (tab === 'stock' || tab === 'youtube') ? 'flex' : 'block';
  const showSearch = tab === 'web' || tab === 'stock';
  document.getElementById('search-bar-wrap').style.display = showSearch ? 'flex' : 'none';
  document.getElementById('search-bar-btn').style.display  = showSearch ? 'block' : 'none';
  updateConfirmBtn();
}

function setStockSubtab(sub) {
  agStockSubtab = sub;
  document.querySelectorAll('.ag-subtab').forEach(b => {
    b.style.color = '#666';
    b.style.borderBottomColor = 'transparent';
  });
  const active = document.getElementById('subtab-' + sub);
  active.style.color = '#e0e0e0';
  active.style.borderBottomColor = '#6d28d9';
  document.getElementById('photos-grid').style.display      = sub === 'photos'      ? 'grid' : 'none';
  document.getElementById('stockvideos-grid').style.display = sub === 'stockvideos' ? 'grid' : 'none';
  updateConfirmBtn();
}

function updateConfirmBtn() {
  const btn = document.getElementById('btn-confirm-selection');
  if (agTab === 'uploads') {
    const n = agPendingFiles.length;
    btn.textContent   = n > 0 ? `⬆ Subir ${n} archivo(s)` : '⬆ Subir archivos';
    btn.disabled      = n === 0;
    btn.style.opacity = n > 0 ? '1' : '0.5';
  } else if (agTab === 'youtube') {
    const n = Object.keys(ytSelected || {}).length;
    btn.textContent   = n > 0 ? `▶ Extraer clips de ${n} video(s)` : '▶ Selecciona videos';
    btn.disabled      = n === 0;
    btn.style.opacity = n > 0 ? '1' : '0.5';
  } else {
    const n    = agSelected.length;
    const tipo = (agTab === 'stock' && agStockSubtab === 'stockvideos') ? 'video(s)' : 'imagen(es)';
    btn.textContent   = n > 0 ? `✓ Agregar ${n} ${tipo}` : `Selecciona ${tipo}`;
    btn.disabled      = n === 0;
    btn.style.opacity = n > 0 ? '1' : '0.5';
  }
}

// ── Web / Photos search ───────────────────────────────────────────────────────
async function doSearch() {
  const q = document.getElementById('agregar-search-input').value.trim();
  if (!q) return;

  const isStock      = agTab === 'stock';
  const isStockVideo = isStock && agStockSubtab === 'stockvideos';
  const source = isStockVideo ? 'stockvideos' : isStock ? 'photos' : 'brave';
  const gridId = isStockVideo ? 'stockvideos-grid' : isStock ? 'photos-grid' : 'search-grid';

  const grid = document.getElementById(gridId);
  const label = isStockVideo ? 'Pexels + Pixabay Videos' : isStock ? 'Pexels + Pixabay Fotos' : 'Web';
  grid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:40px;color:#666;">Buscando en ${label}...</div>`;

  const endpoint = isStockVideo ? `/api/search_videos?q=${encodeURIComponent(q)}&source=stock&count=18`
                                : `/api/search_images?q=${encodeURIComponent(q)}&source=${source}&count=24`;
  const res  = await fetch(endpoint);
  const data = await res.json();
  grid.innerHTML = '';

  if (!data.results || !data.results.length) {
    grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:40px;color:#555;">Sin resultados</div>';
    return;
  }

  if (isStockVideo) {
    // Grid de videos con preview
    grid.style.gridTemplateColumns = 'repeat(3,1fr)';
    data.results.forEach(item => {
      const div = document.createElement('div');
      div.className = 'ag-img-item';
      div.dataset.url = item.url;
      const srcColor = item.source === 'pexels' ? '#05a081' : '#1c83c4';
      div.innerHTML = `
        <video src="${item.url}" muted loop style="width:100%;height:100%;object-fit:cover;"
          onmouseenter="this.play()" onmouseleave="this.pause();this.currentTime=0"></video>
        <span class="ag-label-tag" style="background:${srcColor}99;color:#fff">${item.source}</span>
        ${item.duration ? `<span style="position:absolute;top:3px;right:3px;font-size:0.6rem;padding:1px 4px;border-radius:2px;background:rgba(0,0,0,.7);color:#fff">${item.duration}s</span>` : ''}
        <div class="sel-badge">✓ Selected</div>`;
      div.onclick = () => toggleImgSel(div, item.url, 'video', item.source);
      grid.appendChild(div);
    });
  } else {
    data.results.forEach(item => {
      const div = document.createElement('div');
      div.className = 'ag-img-item';
      div.dataset.url = item.url;
      const srcColor = item.source === 'pexels' ? '#05a081' : item.source === 'pixabay' ? '#1c83c4' : '#e65c00';
      let domain = '';
      if (item.page) { try { domain = new URL(item.page).hostname.replace('www.',''); } catch(e){} }
      div.innerHTML = `
        <img src="${item.thumb || item.url}" loading="lazy" onerror="this.parentElement.style.display='none'">
        <span class="ag-label-tag" style="background:${srcColor}99;color:#fff">${item.source || 'web'}</span>
        ${domain ? `<span style="position:absolute;bottom:3px;left:3px;right:3px;font-size:0.55rem;padding:1px 4px;border-radius:2px;background:rgba(0,0,0,.75);color:#ccc;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${domain}</span>` : ''}
        <div class="sel-badge">✓ Selected</div>`;
      div.onclick = () => toggleImgSel(div, item.url, 'imagen', item.source || 'web');
      grid.appendChild(div);
    });
  }
}

// ── Videos search ─────────────────────────────────────────────────────────────
async function doVideoSearch() {
  const q = document.getElementById('agregar-search-input').value.trim();
  if (!q) return;
  const grid = document.getElementById('videos-grid');
  grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:40px;color:#666;">Buscando videos...</div>';
  setTab('videos');
  const res  = await fetch('/api/search_videos?q=' + encodeURIComponent(q));
  const data = await res.json();
  grid.innerHTML = '';
  if (!data.results?.length) {
    grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:40px;color:#555;">Sin resultados</div>';
    return;
  }
  data.results.forEach(item => {
    const div = document.createElement('div');
    div.className = 'ag-video-item';
    div.dataset.url = item.url;
    div.innerHTML = `
      <img src="${item.thumb}" loading="lazy" onerror="this.src=''" style="background:#111">
      <div class="v-info">
        <div class="v-title">${item.title || 'Video'}</div>
        <div class="v-dur">${item.duration || ''}</div>
      </div>`;
    div.onclick = () => toggleVideoSel(div, item.url, item.title);
    grid.appendChild(div);
  });
}

// Bind search button para cada tab
document.addEventListener('keydown', e => {
  if (e.key === 'Enter' && document.getElementById('modal-agregar').style.display !== 'none') {
    if (agTab === 'videos') doVideoSearch();
    else doSearch();
  }
});

function toggleImgSel(el, url, tipo, source) {
  const i = agSelected.findIndex(s => s.url === url);
  if (i >= 0) { agSelected.splice(i, 1); el.classList.remove('selected'); }
  else { agSelected.push({url, tipo, source}); el.classList.add('selected'); }
  updateConfirmBtn();
}

function toggleVideoSel(el, url, title) {
  const i = agSelected.findIndex(s => s.url === url);
  if (i >= 0) { agSelected.splice(i, 1); el.classList.remove('selected'); }
  else { agSelected.push({url, tipo:'video', source:'youtube_video', title}); el.classList.add('selected'); }
  updateConfirmBtn();
}

// ── Uploads ───────────────────────────────────────────────────────────────────
async function escanearUploadFolder() {
  const res  = await fetch('/api/scan_upload_folder');
  const data = await res.json();
  const list = document.getElementById('upload-folder-list');
  const preview = document.getElementById('upload-folder-preview');
  if (!data.files || data.files.length === 0) {
    list.innerHTML = '<span style="color:#555;font-size:0.82rem;">Carpeta vacía — agrega imágenes o MP4 en ~/Downloads/Upload</span>';
    preview.innerHTML = '';
    return;
  }
  list.innerHTML =
    `<span style="color:#aaa;font-size:0.82rem;">${data.total} archivo(s) encontrado(s)</span>
     <button onclick="procesarUploadFolder()" style="margin-left:10px;background:#6d28d9;border:none;color:#fff;padding:5px 16px;border-radius:6px;cursor:pointer;font-size:0.82rem;font-weight:600;">
       ⬆ Procesar ${data.total} archivo(s)
     </button>`;
  preview.innerHTML = data.files.map(f => {
    const media = f.tipo === 'video'
      ? `<video src="${f.preview_url}" muted loop style="width:100%;height:100%;object-fit:cover;" onmouseenter="this.play()" onmouseleave="this.pause()"></video>`
      : `<img src="${f.preview_url}" style="width:100%;height:100%;object-fit:cover;" loading="lazy">`;
    return `<div style="position:relative;width:120px;height:90px;border-radius:6px;overflow:hidden;border:1px solid #2a2a3a;flex-shrink:0;">
      ${media}
      <div style="position:absolute;bottom:0;left:0;right:0;background:rgba(0,0,0,.6);font-size:0.65rem;color:#ccc;padding:2px 4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${f.name}</div>
    </div>`;
  }).join('');
}

async function procesarUploadFolder() {
  const label = currentLabel;
  if (!label) { alert('Abre el modal desde una sección'); return; }
  closeAgregar();
  const res  = await fetch('/api/process_upload_folder', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({label})
  });
  const data = await res.json();
  if (data.job_id) {
    _startJobPolling(data.job_id, label, data.total);
  } else {
    showToast(data.msg || `${data.added || 0} clips agregados`);
    await refresh_meta();
    loadSections();
    loadSection(label);
  }
}

function handleFileSelect(event) {
  agPendingFiles = Array.from(event.target.files);
  const preview = document.getElementById('upload-preview');
  preview.innerHTML = '';
  agPendingFiles.forEach(f => {
    const div = document.createElement('div');
    div.style.cssText = 'position:relative;width:90px;height:60px;border-radius:6px;overflow:hidden;border:1px solid #333;background:#111;';
    const url = URL.createObjectURL(f);
    if (f.type.startsWith('video')) {
      div.innerHTML = `<video src="${url}" muted style="width:100%;height:100%;object-fit:cover;display:block;"></video>`;
    } else {
      div.innerHTML = `<img src="${url}" style="width:100%;height:100%;object-fit:cover;display:block;">`;
    }
    div.innerHTML += `<span style="position:absolute;bottom:2px;left:2px;right:2px;font-size:0.55rem;color:#ccc;background:rgba(0,0,0,.7);padding:1px 3px;border-radius:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${f.name}</span>`;
    preview.appendChild(div);
  });
  document.getElementById('upload-btn-row').style.display = agPendingFiles.length ? 'block' : 'none';
  updateConfirmBtn();
}

// Drag & drop
// ── Audio Player ────────────────────────────────────────────────────────────
const _aud = new Audio('/audio');
_aud.preload = 'metadata';
_aud.volume = 0.8;
function apFmt(s) {
  s = Math.floor(s || 0);
  return Math.floor(s/60) + ':' + String(s%60).padStart(2,'0');
}
_aud.addEventListener('loadedmetadata', () => {
  document.getElementById('ap-dur').textContent = apFmt(_aud.duration);
});
_aud.addEventListener('timeupdate', () => {
  const cur = document.getElementById('ap-cur');
  const seek = document.getElementById('ap-seek');
  cur.textContent = apFmt(_aud.currentTime);
  if (!_aud.seeking) seek.value = (_aud.currentTime / (_aud.duration || 1)) * 100;
});
_aud.addEventListener('ended', () => {
  document.getElementById('ap-playpause').textContent = '▶';
});
function apToggle() {
  const btn = document.getElementById('ap-playpause');
  if (_aud.paused) { _aud.play(); btn.textContent = '⏸'; }
  else { _aud.pause(); btn.textContent = '▶'; }
}
function apSeek(val) { _aud.currentTime = (val / 100) * (_aud.duration || 0); }
function apVol(val)  { _aud.volume = val; }
// ─────────────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  const dz = document.getElementById('drop-zone');
  if (!dz) return;
  dz.addEventListener('dragover', e => { e.preventDefault(); dz.style.borderColor = '#d4af37'; });
  dz.addEventListener('dragleave', () => { dz.style.borderColor = '#3a3a4a'; });
  dz.addEventListener('drop', e => {
    e.preventDefault(); dz.style.borderColor = '#3a3a4a';
    const fi = document.getElementById('file-input');
    const dt = new DataTransfer();
    Array.from(e.dataTransfer.files).forEach(f => dt.items.add(f));
    fi.files = dt.files;
    handleFileSelect({target: fi});
  });
});

async function doUpload() {
  if (!agPendingFiles.length) return;
  const fd = new FormData();
  fd.append('label', currentLabel);
  agPendingFiles.forEach(f => fd.append('files', f));
  toast('Subiendo archivos…', 'info', 60000);
  const res  = await fetch('/api/upload_clip', {method:'POST', body:fd});
  const data = await res.json();
  closeAgregar();
  if (data.has_job) {
    _startJobPolling(data.job_id, currentLabel, data.total);
    if (data.added) toast(`✓ ${data.added} video(s) agregado(s)`, 'success');
  } else {
    toast(`✓ ${data.added} archivo(s) agregado(s)`, 'success');
    await loadSection(currentLabel);
  }
}

// ── YouTube ───────────────────────────────────────────────────────────────────
// ── YouTube search & player ──────────────────────────────────────────────────
let ytSelected = {}; // {video_id: {url, title}}

function extractYtId(url) {
  const m = url.match(new RegExp('(?:v=|youtu\\.be/|/shorts/)([a-zA-Z0-9_-]{11})'));
  return m ? m[1] : null;
}

async function doYtUrl() {
  const raw = document.getElementById('yt-url-input').value.trim();
  if (!raw) return;
  const video_id = extractYtId(raw);
  if (!video_id) { toast('URL de YouTube no válida', 'error'); return; }

  // Limpiar URL params (timestamp etc.) → URL limpia
  const url = `https://www.youtube.com/watch?v=${video_id}`;

  // Obtener título via yt-dlp (endpoint search con el id directamente)
  const grid = document.getElementById('yt-results-grid');
  grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:20px;color:#666;">Cargando video...</div>';
  ytSelected = {};

  let title = url; // fallback
  try {
    const res  = await fetch('/api/search_youtube?q=' + encodeURIComponent(url) + '&count=1&direct=1');
    const data = await res.json();
    if (data.results && data.results[0]) title = data.results[0].title;
  } catch(e) {}

  // Mostrar como única card seleccionada
  grid.innerHTML = '';
  const card = document.createElement('div');
  card.id = 'ytcard-' + video_id;
  card.style.cssText = 'position:relative;background:#0e0e16;border-radius:8px;overflow:hidden;cursor:pointer;border:2px solid #6d28d9;';
  card.innerHTML = `
    <img src="https://img.youtube.com/vi/${video_id}/mqdefault.jpg" style="width:100%;display:block;aspect-ratio:16/9;object-fit:cover;">
    <div style="padding:6px 8px;font-size:0.75rem;color:#ccc;line-height:1.3;">${title}</div>
    <div id="ytcheck-${video_id}" style="position:absolute;top:4px;left:4px;width:20px;height:20px;border-radius:50%;background:#6d28d9;display:flex;align-items:center;justify-content:center;font-size:0.7rem;color:#fff;font-weight:900;">✓</div>`;
  card.onclick = () => ytLoadPlayer(video_id, title);
  const selBtn = document.createElement('button');
  selBtn.textContent = '✕ Quitar';
  selBtn.style.cssText = 'position:absolute;bottom:6px;right:6px;padding:3px 8px;font-size:0.7rem;border-radius:5px;border:none;background:#7f1d1d;color:#fff;cursor:pointer;';
  selBtn.onclick = (e) => { e.stopPropagation(); ytSelected = {}; grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:40px;color:#555;font-size:0.85rem;">Pega otra URL o busca por término</div>'; updateConfirmBtn(); };
  card.appendChild(selBtn);
  grid.appendChild(card);

  ytSelected[video_id] = {url, title};
  ytLoadPlayer(video_id, title);
  updateConfirmBtn();
}

function fmtDur(s) {
  if (!s) return '';
  s = parseInt(s);
  const m = Math.floor(s/60), sec = s%60;
  return `${m}:${sec.toString().padStart(2,'0')}`;
}

async function doYtSearch() {
  const q = document.getElementById('yt-search-input').value.trim();
  if (!q) return;
  const grid = document.getElementById('yt-results-grid');
  grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:40px;color:#666;">Buscando...</div>';
  ytSelected = {};
  updateConfirmBtn();

  const res  = await fetch('/api/search_youtube?q=' + encodeURIComponent(q) + '&count=10');
  const data = await res.json();
  grid.innerHTML = '';

  if (!data.results || !data.results.length) {
    grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:40px;color:#555;">Sin resultados</div>';
    return;
  }

  data.results.forEach(item => {
    const sel = ytSelected[item.video_id];
    const card = document.createElement('div');
    card.id = 'ytcard-' + item.video_id;
    card.style.cssText = 'position:relative;background:#0e0e16;border-radius:8px;overflow:hidden;cursor:pointer;border:2px solid transparent;transition:border-color .15s;';
    card.innerHTML = `
      <img src="${item.thumb}" style="width:100%;display:block;aspect-ratio:16/9;object-fit:cover;">
      <div style="position:absolute;top:4px;right:4px;background:rgba(0,0,0,.75);color:#fff;font-size:0.65rem;padding:2px 5px;border-radius:3px">${fmtDur(item.duration)}</div>
      <div style="padding:6px 8px;font-size:0.75rem;color:#ccc;line-height:1.3;max-height:2.6em;overflow:hidden">${item.title}</div>
      <div id="ytcheck-${item.video_id}" style="position:absolute;top:4px;left:4px;width:20px;height:20px;border-radius:50%;background:#6d28d9;display:none;align-items:center;justify-content:center;font-size:0.7rem;color:#fff;font-weight:900;">✓</div>`;
    card.onclick = (e) => {
      // Click izquierdo → preview; también toggle selección con checkbox
      ytLoadPlayer(item.video_id, item.title);
    };
    // Checkbox de selección en esquina superior izquierda
    card.ondblclick = (e) => { e.stopPropagation(); ytToggleSelect(item.video_id, item.url, item.title, card); };
    // Botón seleccionar visible al hover
    const selBtn = document.createElement('button');
    selBtn.textContent = '＋ Seleccionar';
    selBtn.style.cssText = 'position:absolute;bottom:6px;right:6px;padding:3px 8px;font-size:0.7rem;border-radius:5px;border:none;background:#6d28d9;color:#fff;cursor:pointer;';
    selBtn.onclick = (e) => { e.stopPropagation(); ytToggleSelect(item.video_id, item.url, item.title, card); };
    card.appendChild(selBtn);
    grid.appendChild(card);
  });
  // Cargar primer video automáticamente
  if (data.results[0]) ytLoadPlayer(data.results[0].video_id, data.results[0].title);
}

function ytLoadPlayer(video_id, title) {
  document.getElementById('yt-iframe').src = `https://www.youtube.com/embed/${video_id}?autoplay=1&mute=1`;
  document.getElementById('yt-player-title').textContent = title || '';
}

function ytToggleSelect(video_id, url, title, card) {
  if (ytSelected[video_id]) {
    delete ytSelected[video_id];
    card.style.borderColor = 'transparent';
    const chk = document.getElementById('ytcheck-' + video_id);
    if (chk) chk.style.display = 'none';
  } else {
    ytSelected[video_id] = {url, title};
    card.style.borderColor = '#6d28d9';
    const chk = document.getElementById('ytcheck-' + video_id);
    if (chk) { chk.style.display = 'flex'; }
  }
  updateConfirmBtn();
}

async function doYouTube() {
  const n      = parseInt(document.getElementById('yt-nclips').value) || 50;
  const urls   = Object.values(ytSelected).map(v => v.url);
  if (!urls.length) { toast('Selecciona al menos un video', 'error'); return; }
  const label  = currentLabel; // capturar antes de cerrar
  closeAgregar();
  toast(`⏳ Extrayendo clips de ${urls.length} video(s)... puede tardar 1-3 min`, 'info', 180000);

  // Lanzar extracción en paralelo para cada URL seleccionada
  const promises = urls.map(url =>
    fetch('/api/add_youtube_clips', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({label, url, n_clips: n})
    }).then(r => r.json())
  );
  const results = await Promise.all(promises);
  const total   = results.reduce((s, d) => s + (d.added || 0), 0);
  const errors  = results.filter(d => d.error);
  if (errors.length) {
    const msg = errors.map(d => d.stderr || d.error).join(' | ').slice(0, 300);
    toast(`⚠ ${errors.length} URL(s) fallaron: ${msg}`, 'error', 10000);
  }
  if (total > 0)
    toast(`✅ ${total} clips extraídos`, 'success', 5000);
  else if (!errors.length)
    toast('⚠ Se procesó el video pero no se generaron clips. Intenta con otra URL.', 'error', 8000);
  await fetch('/api/refresh_meta', {method:'POST'});
  await loadSections();
  await loadSection(label);
  ytSelected = {};
}

// ── Progreso global de job activo (persiste aunque se cierre el modal) ────────
let _activeJobId   = null;
let _activeJobLabel = null;
let _jobPollTimer  = null;

function _startJobPolling(job_id, label, total) {
  _activeJobId    = job_id;
  _activeJobLabel = label;
  if (_jobPollTimer) clearInterval(_jobPollTimer);

  // Toast con barra de progreso flotante (fuera del modal)
  let bar = document.getElementById('job-float-bar');
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'job-float-bar';
    bar.style.cssText = 'position:fixed;bottom:20px;right:20px;background:#1e1b4b;color:#fff;' +
      'border-radius:12px;padding:14px 18px;min-width:260px;z-index:9999;box-shadow:0 4px 20px rgba(0,0,0,.5);';
    document.body.appendChild(bar);
  }
  const renderBar = (done, tot, msg) => {
    const pct = tot ? Math.round(done/tot*100) : 0;
    bar.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
        <span style="font-size:0.85rem;font-weight:700">📥 Procesando imágenes</span>
        <span style="font-size:1rem;font-weight:900;color:#a78bfa">${done} / ${tot}</span>
      </div>
      <div style="background:#333;border-radius:4px;height:8px;overflow:hidden;margin-bottom:6px">
        <div style="height:100%;width:${pct}%;background:#7c3aed;transition:width .3s"></div>
      </div>
      <div style="font-size:0.75rem;color:#a78bfa">${msg || ''}</div>`;
    bar.style.display = 'block';
  };
  renderBar(0, total, 'Iniciando…');

  _jobPollTimer = setInterval(async () => {
    try {
      const r   = await fetch('/api/job_status/' + job_id);
      const job = await r.json();
      renderBar(job.done, job.total, job.msg);
      if (job.status === 'done') {
        clearInterval(_jobPollTimer);
        _jobPollTimer = null;
        _activeJobId  = null;
        bar.style.display = 'none';
        toast(`✅ ${job.added} de ${job.total} imagen(es) convertidas a zoompan`, 'success', 5000);
        const lbl = _activeJobLabel;
        _activeJobLabel = null;
        await fetch('/api/refresh_meta', {method:'POST'});
        await loadSections();
        if (lbl) await loadSection(lbl);
      }
    } catch(e) { /* ignorar errores de red transitorios */ }
  }, 1500);
}

// ── Confirm images from web ───────────────────────────────────────────────────
async function confirmSelection() {
  if (agTab === 'uploads')  { await doUpload();  return; }
  if (agTab === 'youtube')  { await doYouTube(); return; }
  if (!agSelected.length) return;
  const btn   = document.getElementById('btn-confirm-selection');
  const total = agSelected.length;
  btn.disabled = true;

  const res  = await fetch('/api/add_to_section', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({label: currentLabel, items: agSelected})
  });
  const data = await res.json();

  if (!data.ok) {
    toast('Error: ' + (data.error || 'desconocido'), 'error');
    btn.disabled = false;
    btn.textContent = `Confirmar selección (${total})`;
    return;
  }

  // Lanzar polling en background — el modal se puede cerrar libremente
  _startJobPolling(data.job_id, currentLabel, data.total);
  closeAgregar();
  btn.disabled = false;
  btn.textContent = 'Confirmar selección (0)';
}
</script>

<script>
async function refreshDuplicados() {
  const res = await fetch('/api/duplicados');
  duplicadosGlobal = await res.json();
}

// ── Hook Images ──────────────────────────────────────────────────────────────
let hookImages = [];
let currentSection = 'clips'; // 'clips' | 'hook'

let hookSegments = [];

async function loadHookImages() {
  currentSection = 'hook';
  currentLabel   = null;
  document.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
  const hookPill = document.getElementById('pill-hook');
  if (hookPill) hookPill.classList.add('active');
  document.getElementById('grid').innerHTML = '<div class="loading">Cargando hook...</div>';
  const res  = await fetch('/api/hook_timeline');
  const data = await res.json();
  hookSegments = data.segments || [];
  // Compat con código antiguo que lee hookImages
  hookImages = [];
  renderHookMixedGrid();
  updateStats();
}

function buildHookFlowCard(seg, n) {
  const card = document.createElement('div');
  card.className = 'card aprobado';
  card.id = 'hseg-' + seg.segment_id;
  const url = seg.media_url || '';
  card.innerHTML = `
    <div class="card-media" style="cursor:pointer" onclick="previewClip('${url}','clip','flow_${seg.segment_id}')">
      <video data-src="${url}" muted loop playsinline style="width:100%;height:100%;object-fit:cover;display:block;"></video>
      <span class="tipo-badge">flow</span>
      <span class="fuente-badge fuente-flow">hook</span>
    </div>
    <div class="card-info">
      <div class="card-slot">#${n} Flow · ${seg.duration}s</div>
      <div class="card-filename" style="font-size:10px;opacity:.7">${seg.descripcion ? seg.descripcion.substring(0,60)+'…' : ''}</div>
    </div>`;
  return card;
}

function buildHookYTCard(seg, n) {
  const card = document.createElement('div');
  card.className = 'card pendiente';
  card.id = 'hseg-' + seg.segment_id;
  const url = seg.media_url || '';
  card.innerHTML = `
    <div class="card-media" style="cursor:pointer" onclick="previewClip('${url}','clip','yt_${seg.segment_id}')">
      ${url
        ? `<video data-src="${url}" muted loop playsinline style="width:100%;height:100%;object-fit:cover;display:block;"></video>`
        : `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#888;font-size:12px;">Sin clip</div>`}
      <span class="tipo-badge" style="background:#c0392b">YT</span>
      <span class="fuente-badge" style="background:#1a1a3a;color:#7eb3ff">${seg.artist}</span>
    </div>
    <div class="card-info">
      <div class="card-slot">#${n} YT · ${seg.duration}s · ${seg.artist}</div>
    </div>
    <div class="card-actions">
      <button class="btn-rechazar" onclick="hookYTReject(${seg.segment_id},'${seg.icloud_folder}','${seg.artist}')">↺ Cambiar clip</button>
    </div>`;
  return card;
}

function renderHookMixedGrid() {
  const grid = document.getElementById('grid');
  if (!hookSegments.length) {
    grid.innerHTML = '<div class="loading">Sin datos en hook_timeline.json</div>';
    return;
  }
  grid.innerHTML = '';
  hookSegments.forEach((seg, i) => {
    const n = i + 1;
    const card = seg.type === 'youtube' ? buildHookYTCard(seg, n) : buildHookFlowCard(seg, n);
    grid.appendChild(card);
  });
  // Activar lazy autoplay con IntersectionObserver
  if (window._hookObserver) window._hookObserver.disconnect();
  window._hookObserver = new IntersectionObserver(entries => {
    entries.forEach(e => {
      const v = e.target.querySelector('video[data-src]');
      if (!v) return;
      if (e.isIntersecting) {
        if (!v.src && v.dataset.src) { v.src = v.dataset.src; }
        v.play().catch(()=>{});
      } else { v.pause(); }
    });
  }, {threshold: 0.1});
  grid.querySelectorAll('.card').forEach(c => window._hookObserver.observe(c));

  const nFlow = hookSegments.filter(s=>s.type==='flow').length;
  const nYT   = hookSegments.filter(s=>s.type==='youtube').length;
  document.getElementById('statsbar').innerHTML = `
    <div class="stat"><span class="dot apro"></span> Flow: ${nFlow}</div>
    <div class="stat"><span class="dot pend" style="background:#c0392b"></span> YT: ${nYT}</div>
    <div class="stat" style="color:#666">Total: ${hookSegments.length} segmentos</div>`;
}

async function hookYTReject(segmentId, icloudFolder, artist) {
  const card = document.getElementById('hseg-' + segmentId);
  if (card) card.style.opacity = '0.5';
  const res = await fetch('/api/hook_yt_reject', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({segment_id: segmentId, icloud_folder: icloudFolder})});
  const data = await res.json();
  if (data.error) { if(card) card.style.opacity='1'; return; } // sin más clips → nada
  await loadHookImages();
}

async function hookApproveAll() {
  if (currentSection !== 'hook') return;
  // Para el hook mixto no hay aprobación individual, los Flow ya están aprobados
  alert('Hook listo — los clips Flow y YT están configurados.');
}
// ─────────────────────────────────────────────────────────────────────────────

async function checkPreflight() {
  const res = await fetch('/api/preflight');
  const data = await res.json();
  const banner = document.getElementById('preflight-banner');
  if (!data.ok && data.issues.length > 0) {
    let html = '⚠️ <strong>DÉFICIT DE CLIPS — el render fallará si no se corrige:</strong><br>';
    data.issues.forEach(i => {
      html += `&nbsp;&nbsp;• <strong>${i.artista}</strong>: tiene ${i.tiene} clips, necesita ${i.necesita} (faltan <strong>${i.deficit}</strong>, duración ${i.duracion}s)<br>`;
    });
    banner.innerHTML = html;
    banner.style.display = 'block';
  } else {
    banner.style.display = 'none';
  }
}

async function loadSections(autoFirst = false) {
  const res = await fetch('/api/sections');
  sections  = await res.json();
  const pills = document.getElementById('pills');
  pills.innerHTML = '';
  let totalFlow = 0;

  // Hook pill (siempre primero)
  const hookRes  = await fetch('/api/hook_images');
  const hookData = await hookRes.json();
  if (hookData.total > 0) {
    const hookPill = document.createElement('button');
    hookPill.id        = 'pill-hook';
    hookPill.className = 'pill' + (currentSection === 'hook' ? ' active' : '');
    const hAp = hookData.aprobados  > 0 ? `<span class="ok"> ✓${hookData.aprobados}</span>`  : '';
    const hRe = hookData.rechazados > 0 ? `<span class="bad"> ✗${hookData.rechazados}</span>` : '';
    hookPill.innerHTML = `🖼 Hook (${hookData.total})${hAp}${hRe}`;
    hookPill.onclick   = loadHookImages;
    pills.appendChild(hookPill);
  }

  sections.forEach(s => {
    totalFlow += s.needs_flow || 0;
    const pill = document.createElement('button');
    pill.className = 'pill' + (s.label === currentLabel ? ' active' : '');
    pill.id = 'pill-' + s.label;
    const ap = s.aprobados > 0 ? `<span class="ok"> ✓${s.aprobados}</span>` : '';
    const re = s.rechazados > 0 ? `<span class="bad"> ✗${s.rechazados}</span>` : '';
    const fl = s.needs_flow > 0 ? `<span class="flow-badge"> ◈${s.needs_flow}</span>` : '';
    const hook = s.is_hook ? '🎬 ' : '';
    const countColor = s.total >= s.needed ? '#00ffaa' : '#ff6b6b';
    const counter = s.needed > 0
      ? ` <span style="font-size:0.7rem;color:${countColor};font-weight:700;background:rgba(0,0,0,0.4);padding:1px 5px;border-radius:4px">${s.total}/${s.needed}</span>`
      : '';
    pill.innerHTML = `${hook}${s.nombre}${counter}${ap}${re}${fl}`;
    pill.onclick = () => { currentSection = 'clips'; loadSection(s.label); };
    pills.appendChild(pill);
  });
  // Flow bar
  const flowBar = document.getElementById('flow-bar');
  document.getElementById('flow-count').textContent = `${totalFlow} slot(s) necesitan Flow`;
  flowBar.style.display = totalFlow > 0 ? 'flex' : 'none';

  if (autoFirst) {
    if (hookData.total > 0) loadHookImages();
    else if (sections.length > 0) { currentSection = 'clips'; loadSection(sections[0].label); }
  }
}

async function loadSection(label) {
  currentLabel = label;
  document.getElementById('agregar-bar').style.display = 'block';
  document.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
  const pill = document.getElementById('pill-' + label);
  if (pill) pill.classList.add('active');
  document.getElementById('grid').innerHTML = '<div class="loading">Cargando...</div>';
  const [res, _] = await Promise.all([
    fetch('/api/clips/' + encodeURIComponent(label)),
    refreshDuplicados()
  ]);
  const data = await res.json();
  currentClips = data.clips || [];
  renderGrid();
  updateStats();
}

function setFilter(f) {
  currentFilter = f;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('f-' + f).classList.add('active');
  renderGrid();
}

function buildCard(clip) {
  const card = document.createElement('div');
  card.className = 'card ' + clip.estado;
  card.id = 'card-' + clip.filename;

  const dur    = clip.duration > 0 ? clip.duration.toFixed(1) + 's' : '';
  const dims   = clip.width ? `${clip.width}×${clip.height}` : '';
  const slotTs = `${fmt(clip.slot_start)} → ${fmt(clip.slot_end)}`;
  const fuente = clip.fuente || 'icloud';
  const isFlow = clip.estado === 'flow_sent' || clip.estado === 'needs_flow';

  const flowOverlay = clip.estado === 'flow_sent'
    ? `<div class="flow-status-overlay">⏳ Esperando Flow...</div>` : '';
  const needsFlowOverlay = clip.estado === 'needs_flow'
    ? `<div class="flow-status-overlay">◈ Pendiente Flow</div>` : '';
  const recBadge = clip.reciclado
    ? `<span style="position:absolute;bottom:4px;left:4px;font-size:0.6rem;padding:2px 5px;border-radius:3px;background:rgba(180,120,0,0.8);color:#ffe;">♻ reciclado</span>` : '';
  const isDup = clip.path && duplicadosGlobal[clip.path] && duplicadosGlobal[clip.path].length > 1;
  const dupCount = isDup ? duplicadosGlobal[clip.path].length : 0;
  const dupBadge = isDup
    ? `<span style="position:absolute;top:4px;left:4px;font-size:0.6rem;padding:2px 5px;border-radius:3px;background:rgba(220,30,30,0.9);color:#fff;font-weight:700;">⚠ DUPLICADO ×${dupCount}</span>` : '';
  if (isDup) card.classList.add('duplicado');

  const mediaTag = clip.tipo === 'video'
    ? `<video data-src="${clip.media_url}" muted loop playsinline style="width:100%;height:100%;object-fit:cover;display:block;" onclick="previewClip('${clip.media_url}','${clip.tipo}','${clip.filename}')"></video>`
    : `<img src="${clip.media_url}" style="width:100%;height:100%;object-fit:cover;display:block;" onclick="previewClip('${clip.media_url}','${clip.tipo}','${clip.filename}')">`;

  card.innerHTML = `
    <div class="card-media" id="media-${clip.filename}">
      ${mediaTag}
      <span class="tipo-badge">${clip.tipo}</span>
      <span class="fuente-badge fuente-${fuente}">${fuente}</span>
      ${dur ? `<span class="dur-badge">${dur}</span>` : ''}
      ${recBadge}
      ${dupBadge}
      ${flowOverlay}${needsFlowOverlay}
      <div class="play">▶</div>
    </div>
    <div class="card-info">
      <div class="card-slot">#${clip.slot + 1} <span style="font-weight:400;color:#666;font-size:0.62rem">${slotTs}</span>${clip.reciclado ? ' <span style="color:#b87400;font-size:0.6rem">♻</span>' : ''}</div>
      <div class="card-filename">${clip.orig_name || clip.filename}</div>
      ${clip.srt_text ? `<div class="card-srt">"${clip.srt_text}"</div>` : ''}
      ${dims ? `<div class="card-dims">${dims}</div>` : ''}
    </div>
    <div class="card-actions">
      <button class="btn-rechazar"  id="btn-rech-${clip.filename}" onclick="rejectAndReplace('${clip.filename}')">✗ Rechazar</button>
      <button class="btn-eliminar"  onclick="removeCard('${clip.filename}')">🗑</button>
      <button class="btn-flow-card" onclick="markFlow('${clip.filename}')">🎬 Flow</button>
    </div>`;
  enableDrag(card);
  return card;
}

function renderGrid() {
  const grid = document.getElementById('grid');
  let clips = currentClips;
  if (currentFilter !== 'todos') {
    if (currentFilter === 'needs_flow') {
      clips = clips.filter(c => c.estado === 'needs_flow' || c.estado === 'flow_sent');
    } else {
      clips = clips.filter(c => c.estado === currentFilter);
    }
  }
  if (!clips.length) { grid.innerHTML = '<div class="loading">Sin clips en esta vista</div>'; return; }
  grid.innerHTML = '';
  clips.forEach(clip => grid.appendChild(buildCard(clip)));
  initVideoObserver();
}

function renderHookGridAndObserve() {
  renderHookMixedGrid();
}

// IntersectionObserver: carga y reproduce videos solo cuando son visibles
let _videoObserver = null;
function initVideoObserver() {
  if (_videoObserver) _videoObserver.disconnect();
  _videoObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      const v = entry.target;
      if (entry.isIntersecting) {
        if (!v.src && v.dataset.src) {
          v.src = v.dataset.src;
          v.load();
        }
        const tryPlay = () => v.play().catch(() => {});
        if (v.readyState >= 3) {
          tryPlay();
        } else {
          v.addEventListener('canplay', tryPlay, { once: true });
        }
      } else {
        v.pause();
      }
    });
  }, { rootMargin: '100px' });
  document.querySelectorAll('video[data-src], video[src]').forEach(v => {
    if (v.closest('#grid, #hook-grid')) _videoObserver.observe(v);
  });
}

async function setClipState(filename, estado) {
  await fetch('/api/approve', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({label: currentLabel, filename, estado})
  });
  const clip = currentClips.find(c => c.filename === filename);
  if (clip) clip.estado = estado;
  const card = document.getElementById('card-' + filename);
  if (card) {
    card.className = 'card ' + estado;
    if (currentFilter !== 'todos' && currentFilter !== estado) card.style.display = 'none';
  }
  updateStats();
  loadSections();
}

async function removeCard(filename) {
  const sec = sections.find(s => s.label === currentLabel);
  if (sec && sec.needed > 0 && sec.total <= sec.needed) {
    toast(`⚠ Mínimo alcanzado — necesitas ${sec.needed} clips para esta sección`, 'error', 3000);
    return;
  }
  const card = document.getElementById('card-' + filename);
  const res  = await fetch('/api/remove_card', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({label: currentLabel, filename})
  });
  const data = await res.json();
  if (data.ok) {
    currentClips = currentClips.filter(c => c.filename !== filename);
    if (card) {
      card.style.transition = 'opacity .2s';
      card.style.opacity = '0';
      setTimeout(() => card.remove(), 200);
    }
    updateStats();
    loadSections();
  }
}

async function rejectAndReplace(filename) {
  // Rechazar = swap con reemplazo, nunca baja el conteo → sin chequeo de mínimo
  const btn  = document.getElementById('btn-rech-' + filename);
  const card = document.getElementById('card-' + filename);
  if (btn) { btn.textContent = '⏳'; btn.disabled = true; }

  const res  = await fetch('/api/reject_and_replace', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({label: currentLabel, filename})
  });
  const data = await res.json();

  if (data.ok) {
    if (data.replacement) {
      const r = data.replacement;
      // Actualizar lista local en la misma posición
      const idx = currentClips.findIndex(c => c.filename === filename);
      if (idx !== -1) currentClips[idx] = r;
      else currentClips.push(r);

      // Reemplazar el card completo usando buildCard (misma lógica que el render normal)
      const newCard = buildCard(r);
      if (card && card.parentNode) {
        card.parentNode.replaceChild(newCard, card);
        // Arrancar el observer de lazy-load en el nuevo card
        const vid = newCard.querySelector('video[data-src]');
        if (vid && _videoObserver) _videoObserver.observe(vid);
        // Flash verde para indicar reemplazo
        newCard.style.outline = '3px solid #4ade80';
        setTimeout(() => newCard.style.outline = '', 1400);
      }
      toast('Clip reemplazado ✓', 'success', 1800);
    } else {
      // Sin reemplazo disponible — eliminar tarjeta
      currentClips = currentClips.filter(c => c.filename !== filename);
      if (card) {
        card.style.transition = 'opacity .2s';
        card.style.opacity = '0';
        setTimeout(() => card.remove(), 200);
      }
      toast('Clip eliminado (pool agotado)', 'warning', 2000);
    }
  } else {
    if (btn) { btn.textContent = '✗ Rechazar'; btn.disabled = false; }
    toast('Error al eliminar clip', 'error');
  }

  updateStats();
  loadSections();
}

async function markFlow(filename) {
  await fetch('/api/mark_flow', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({label: currentLabel, filename})
  });
  const clip = currentClips.find(c => c.filename === filename);
  if (clip) clip.estado = 'needs_flow';
  const card = document.getElementById('card-' + filename);
  if (card) card.className = 'card needs_flow';
  updateStats();
  loadSections();
  toast('Marcado para Flow ◈', 'info', 2000);
}

async function approveAll() {
  if (currentSection === 'hook') { await hookApproveAll(); return; }

  // Verificar que ningún artista esté vacío antes de aprobar
  const vacios = sections.filter(s => (s.total || 0) === 0);
  if (vacios.length) {
    const nombres = vacios.map(s => s.nombre || s.label).join(', ');
    toast(`⚠ Sin clips: ${nombres} — agrega clips antes de aprobar`, 'error', 8000);
    return;
  }

  await fetch('/api/approve_all', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({label: null, estado: 'aprobado'})});
  currentClips.forEach(c => c.estado = 'aprobado');
  renderGrid(); updateStats(); loadSections();
  toast('✅ Todos los clips de todos los artistas aprobados', 'success', 4000);
}
async function rejectAll() {
  if (currentSection === 'hook') return;
  await fetch('/api/approve_all', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({label: currentLabel, estado: 'rechazado'})});
  currentClips.forEach(c => c.estado = 'rechazado');
  renderGrid(); updateStats(); loadSections();
}
async function resetAll() {
  if (currentSection === 'hook') return;
  await fetch('/api/approve_all', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({label: currentLabel, estado: 'pendiente'})});
  currentClips.forEach(c => c.estado = 'pendiente');
  renderGrid(); updateStats(); loadSections();
}

async function sendToFlow() {
  const btn = document.getElementById('btn-send-flow');
  btn.disabled = true;
  btn.textContent = '⏳ Enviando a Baserow...';
  document.getElementById('flow-msg').textContent = '';
  const res  = await fetch('/api/send_to_flow', {method:'POST'});
  const data = await res.json();
  if (data.ok) {
    toast(`${data.enviados} filas enviadas a Baserow`, 'info', 5000);
    document.getElementById('flow-msg').textContent = data.message;
    document.getElementById('btn-check-flow').style.display = 'inline-block';
  } else {
    toast(data.error || 'Error enviando a Baserow', 'error');
  }
  btn.disabled = false;
  btn.textContent = '→ Enviar a Flow (Baserow)';
  loadSections();
}

async function checkFlowDownloads() {
  const btn = document.getElementById('btn-check-flow');
  btn.textContent = '⏳ Revisando...';
  const res  = await fetch('/api/check_flow_downloads', {method:'POST'});
  const data = await res.json();
  toast(`Descargados: ${data.descargados} | Pendientes: ${data.pendientes}`, 'info', 4000);
  btn.textContent = '↓ Revisar descargas';
  loadSections();
  if (currentLabel) loadSection(currentLabel);
}

function updateStats() {
  const total = currentClips.length;
  const apro  = currentClips.filter(c => c.estado === 'aprobado').length;
  const rech  = currentClips.filter(c => c.estado === 'rechazado').length;
  const flow  = currentClips.filter(c => c.estado === 'needs_flow' || c.estado === 'flow_sent').length;
  const pend  = total - apro - rech - flow;
  document.getElementById('statsbar').innerHTML = `
    <div class="stat"><span class="dot pend"></span> Pendientes: ${pend}</div>
    <div class="stat"><span class="dot apro"></span> Aprobados: ${apro}</div>
    <div class="stat"><span class="dot rech"></span> Rechazados: ${rech}</div>
    <div class="stat"><span class="dot flow"></span> Flow: ${flow}</div>
    <div class="stat" style="color:#666">Total: ${total}</div>`;
}

// Primer click → muestra thumbnail en la card; segundo click → abre modal
function toggleThumb(el, thumbUrl, mediaUrl, tipo, filename) {
  const existing = el.querySelector('img, video');
  if (!existing) {
    const ph = el.querySelector('.card-placeholder');
    let media;
    if (tipo === 'video') {
      media = document.createElement('video');
      media.src = mediaUrl;
      media.muted = true;
      media.autoplay = true;
      media.loop = true;
      media.playsInline = true;
      media.style.cssText = 'width:100%;height:100%;object-fit:cover;display:block;';
    } else {
      media = document.createElement('img');
      media.src = mediaUrl;
      media.style.cssText = 'width:100%;height:100%;object-fit:cover;display:block;';
    }
    if (ph) ph.replaceWith(media);
    else el.prepend(media);
    return;
  }
  // Segunda vez: abrir modal completo
  previewClip(mediaUrl, tipo, filename);
}

let modalEl = null;
function previewClip(url, tipo, filename) {
  if (modalEl) { modalEl.remove(); modalEl = null; }
  const m = document.createElement('div');
  m.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.93);z-index:9999;display:flex;flex-direction:column;align-items:center;justify-content:center;';

  if (tipo === 'imagen') {
    m.innerHTML = `<img src="${url}" style="max-width:90vw;max-height:85vh;object-fit:contain;">
      <div style="position:absolute;top:14px;right:22px;font-size:1.4rem;color:#fff;cursor:pointer;" onclick="this.closest('div[style]').remove()">✕</div>`;
    m.onclick = e => { if(e.target===m){m.remove();modalEl=null;} };
    document.body.appendChild(m); modalEl = m; return;
  }

  // ── Video con trimmer ──
  m.innerHTML = `
    <div style="position:absolute;top:14px;right:22px;font-size:1.4rem;color:#fff;cursor:pointer;z-index:10;" id="pm-close">✕</div>
    <video id="pm-video" src="${url}" style="max-width:90vw;max-height:72vh;background:#000;" preload="metadata"></video>
    <div id="pm-trim-ui" style="width:min(90vw,800px);margin-top:14px;user-select:none;">
      <!-- barra de tiempo -->
      <div id="pm-bar-wrap" style="position:relative;height:36px;background:#1a1a2e;border-radius:6px;cursor:crosshair;overflow:hidden;">
        <div id="pm-played" style="position:absolute;top:0;left:0;height:100%;background:#3a3a6a;pointer-events:none;"></div>
        <div id="pm-trim-range" style="position:absolute;top:0;height:100%;background:rgba(212,175,55,0.25);border:2px solid #d4af37;box-sizing:border-box;pointer-events:none;"></div>
        <div id="pm-handle-start" style="position:absolute;top:0;width:10px;height:100%;background:#d4af37;cursor:ew-resize;border-radius:3px 0 0 3px;z-index:3;"></div>
        <div id="pm-handle-end"   style="position:absolute;top:0;width:10px;height:100%;background:#d4af37;cursor:ew-resize;border-radius:0 3px 3px 0;z-index:3;right:0;"></div>
      </div>
      <!-- info + botones -->
      <div style="display:flex;align-items:center;gap:12px;margin-top:10px;flex-wrap:wrap;">
        <span style="color:#aaa;font-size:0.82rem;" id="pm-info">▶ 0.0s &nbsp;|&nbsp; ✂ 0.0s → 0.0s &nbsp;(0.0s)</span>
        <button id="pm-btn-trim" style="background:#d4af37;color:#0e0e16;border:none;padding:7px 18px;border-radius:6px;cursor:pointer;font-weight:700;font-size:0.88rem;">✂ Recortar y guardar</button>
        <button id="pm-btn-preview-trim" style="background:#1a2e1a;color:#00cc66;border:1px solid #00cc66;padding:7px 14px;border-radius:6px;cursor:pointer;font-size:0.85rem;">▶ Ver recorte</button>
        <button id="pm-btn-reset" style="background:#1a1a3a;color:#aaa;border:1px solid #3a3a5a;padding:7px 14px;border-radius:6px;cursor:pointer;font-size:0.85rem;">↺ Reset</button>
        <span id="pm-status" style="color:#aaa;font-size:0.82rem;"></span>
      </div>
    </div>`;

  document.body.appendChild(m);
  modalEl = m;

  document.getElementById('pm-close').onclick = () => { m.remove(); modalEl = null; };

  const vid     = document.getElementById('pm-video');
  const bar     = document.getElementById('pm-bar-wrap');
  const played  = document.getElementById('pm-played');
  const trimRng = document.getElementById('pm-trim-range');
  const hStart  = document.getElementById('pm-handle-start');
  const hEnd    = document.getElementById('pm-handle-end');
  const info    = document.getElementById('pm-info');
  const status  = document.getElementById('pm-status');

  let dur = 0, trimStart = 0, trimEnd = 0;

  function pct(t) { return dur > 0 ? (t / dur) * 100 : 0; }
  function fromPct(p) { return Math.max(0, Math.min(dur, (p / 100) * dur)); }

  function updateUI() {
    played.style.width  = pct(vid.currentTime) + '%';
    hStart.style.left   = pct(trimStart) + '%';
    hEnd.style.right    = (100 - pct(trimEnd)) + '%';
    trimRng.style.left  = pct(trimStart) + '%';
    trimRng.style.width = (pct(trimEnd) - pct(trimStart)) + '%';
    info.innerHTML = `▶ ${vid.currentTime.toFixed(1)}s &nbsp;|&nbsp; ✂ ${trimStart.toFixed(1)}s → ${trimEnd.toFixed(1)}s &nbsp;<b style="color:#d4af37">(${(trimEnd-trimStart).toFixed(1)}s)</b>`;
  }

  vid.addEventListener('loadedmetadata', () => {
    dur = vid.duration; trimStart = 0; trimEnd = dur;
    vid.play(); updateUI();
  });
  vid.addEventListener('timeupdate', updateUI);

  // Drag handles
  function makeDraggable(handle, isStart) {
    handle.addEventListener('mousedown', e => {
      e.stopPropagation();
      const rect = bar.getBoundingClientRect();
      const onMove = ev => {
        const p = Math.max(0, Math.min(100, (ev.clientX - rect.left) / rect.width * 100));
        if (isStart) { trimStart = Math.min(fromPct(p), trimEnd - 0.2); }
        else         { trimEnd   = Math.max(fromPct(p), trimStart + 0.2); }
        updateUI();
      };
      const onUp = () => { document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp); };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
  }
  makeDraggable(hStart, true);
  makeDraggable(hEnd, false);

  // Click en barra → seek
  bar.addEventListener('click', e => {
    const rect = bar.getBoundingClientRect();
    const p = (e.clientX - rect.left) / rect.width;
    vid.currentTime = p * dur;
  });

  // Botón: ver solo el recorte
  document.getElementById('pm-btn-preview-trim').onclick = () => {
    vid.currentTime = trimStart;
    vid.play();
    const check = setInterval(() => {
      if (vid.currentTime >= trimEnd) { vid.pause(); clearInterval(check); }
    }, 100);
  };

  // Botón: reset
  document.getElementById('pm-btn-reset').onclick = () => {
    trimStart = 0; trimEnd = dur; updateUI();
  };

  // Botón: recortar y guardar
  document.getElementById('pm-btn-trim').onclick = async () => {
    if (trimStart === 0 && trimEnd === dur) { status.textContent = 'Sin cambios (mueve los handles)'; return; }
    if (!filename || filename.startsWith('flow_') || filename.startsWith('yt_')) {
      status.textContent = '⚠ Solo se pueden recortar clips de artistas'; return;
    }
    if ((trimEnd - trimStart) < 2.0) { status.textContent = '⚠ Mínimo 2 segundos de duración'; return; }
    status.textContent = '⏳ Recortando...';
    document.getElementById('pm-btn-trim').disabled = true;
    const res = await fetch('/api/trim_clip', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({label: currentLabel, filename, start: trimStart, end: trimEnd})
    });
    const data = await res.json();
    if (data.ok) {
      status.innerHTML = `<span style="color:#00cc66">✓ Guardado (${data.new_duration.toFixed(1)}s)</span>`;
      // Recargar video con el clip recortado
      vid.src = url + '?t=' + Date.now();
      vid.load(); vid.play();
    } else {
      status.innerHTML = `<span style="color:#e55">❌ ${data.error}</span>`;
      document.getElementById('pm-btn-trim').disabled = false;
    }
  };
}

// ── Drag & Drop reorder ───────────────────────────────────────────────────────
let dragSrc = null;
let saveReorderTimer = null;

function enableDrag(card) {
  card.setAttribute('draggable', 'true');

  card.addEventListener('dragstart', e => {
    dragSrc = card;
    card.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', card.id);
  });

  card.addEventListener('dragend', () => {
    card.classList.remove('dragging');
    document.querySelectorAll('.card.drag-over').forEach(c => c.classList.remove('drag-over'));
    dragSrc = null;
  });

  card.addEventListener('dragover', e => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    if (dragSrc && dragSrc !== card) {
      document.querySelectorAll('.card.drag-over').forEach(c => c.classList.remove('drag-over'));
      card.classList.add('drag-over');
    }
  });

  card.addEventListener('dragleave', () => {
    card.classList.remove('drag-over');
  });

  card.addEventListener('drop', e => {
    e.preventDefault();
    card.classList.remove('drag-over');
    if (!dragSrc || dragSrc === card) return;

    const grid = document.getElementById('grid');
    const cards = [...grid.querySelectorAll('.card')];
    const srcIdx = cards.indexOf(dragSrc);
    const dstIdx = cards.indexOf(card);

    // Reordenar en el DOM
    if (srcIdx < dstIdx) {
      card.after(dragSrc);
    } else {
      card.before(dragSrc);
    }

    // Actualizar currentClips según nuevo orden DOM y guardar
    scheduleReorderSave();
  });
}

function scheduleReorderSave() {
  clearTimeout(saveReorderTimer);
  saveReorderTimer = setTimeout(saveReorder, 600);
}

async function saveReorder() {
  const grid  = document.getElementById('grid');
  const cards = [...grid.querySelectorAll('.card[id^="card-"]')];
  const order = cards.map(c => c.id.replace('card-', ''));

  // Actualizar slots en currentClips localmente
  order.forEach((fname, i) => {
    const clip = currentClips.find(c => c.filename === fname);
    if (clip) clip.slot = i;
  });

  await fetch('/api/reorder', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({label: currentLabel, order})
  });
  toast('Orden guardado', 'success', 1200);
}

async function refreshMeta() {
  const btn = document.getElementById('btn-refresh');
  btn.textContent = '⏳ Sincronizando...';
  btn.disabled = true;
  const res  = await fetch('/api/refresh_meta', {method:'POST'});
  const data = await res.json();
  btn.textContent = '↺ Sync iCloud';
  btn.disabled = false;
  if (data.removed > 0) {
    toast(`${data.removed} clip(s) eliminados del dashboard`, 'info', 3000);
  } else {
    toast('Todo sincronizado ✓', 'success', 2000);
  }
  await loadSections();
  if (currentLabel) await loadSection(currentLabel);
}

loadSections(true);

// ── Polling de estado de render ───────────────────────────────────────────
(function pollRender() {
  fetch('/api/render_status').then(r => r.json()).then(d => {
    if (d.done) {
      // Notificación grande en pantalla
      const el = document.createElement('div');
      el.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:9999;background:#0d2e0d;border:2px solid #00cc66;border-radius:16px;padding:32px 48px;text-align:center;color:#00cc66;font-size:1.4rem;font-weight:700;box-shadow:0 0 60px rgba(0,200,100,0.4);';
      el.innerHTML = '✅ RENDER COMPLETADO<br><span style="font-size:1rem;color:#aaa">' + d.size_mb + 'MB &nbsp;·&nbsp; ' + d.dur_min + ' min</span><br><button onclick="this.parentElement.remove()" style="margin-top:16px;padding:8px 24px;border-radius:8px;border:none;background:#00cc66;color:#000;font-weight:700;cursor:pointer;font-size:0.9rem;">OK</button>';
      document.body.appendChild(el);
      // Notificación del sistema si el tab está en segundo plano
      if (Notification && Notification.permission === 'granted')
        new Notification('Farandula — Render listo', {body: d.size_mb + 'MB, ' + d.dur_min + ' min'});
    } else {
      setTimeout(pollRender, 10000);
    }
  }).catch(() => setTimeout(pollRender, 15000));
})();

// Pedir permiso de notificación del sistema al cargar
if (typeof Notification !== 'undefined' && Notification.permission === 'default')
  Notification.requestPermission();
</script>
</body>
</html>"""


if __name__ == "__main__":
    if not VIDEO_FOLDER or not VIDEO_FOLDER.exists():
        print("Uso: python3 dashboard_farandula.py 'VIVIENDO DE FAVOR TELEVISA/'")
        sys.exit(1)
    if not META_FILE.exists():
        print("✗ No existe dashboard_meta.json. Corre primero harvester_clips_farandula.py")
        sys.exit(1)
    print(f"\n  Dashboard Farandula — {VIDEO_FOLDER.name}")
    print(f"  http://localhost:5002\n")
    app.run(host="0.0.0.0", port=5002, debug=False)
