#!/usr/bin/env python3
"""
dashboard.py — Panel de control para canales YouTube
Uso: python3 dashboard.py
     Abre http://localhost:5000
"""

import json, os, subprocess, datetime, pathlib, threading, time, sys
import gzip, hashlib, unicodedata, math, urllib.request, urllib.parse, random
from flask import Flask, jsonify, request, send_file, Response, make_response

BASE_DIR  = pathlib.Path(__file__).parent
LOGS_DIR  = BASE_DIR / "_logs"
LOGS_DIR.mkdir(exist_ok=True)

app = Flask(__name__)

# Cola nocturna
from night_queue_module import register_night_queue_routes
register_night_queue_routes(app, BASE_DIR, render_script="render.py")
upload_procs = {}   # personaje → {"proc": Popen, "log": path}
regen_procs  = {}   # "personaje|num" → {"proc": Popen, "log": path}
rerun_procs  = {}   # personaje → {"proc": Popen, "log": path}
yt_dl_jobs   = {}   # job_id → {"done": bool, "added": int, "error": str, "log": [str], "clips_antes": int, "clips_dir": Path}

PIPELINE_STEPS = ["titulo", "guion", "audio", "subtitulos", "imagenes", "video", "miniaturas", "youtube"]

HOME            = pathlib.Path.home()
FFMPEG          = "/opt/homebrew/bin/ffmpeg"
FFPROBE         = "/opt/homebrew/bin/ffprobe"
BRAVE_KEY_FILE  = HOME / ".brave_key"
PEXELS_KEY_FILE = HOME / ".pexels_key"
PIXABAY_KEY_FILE= HOME / ".pixabay_key"
MIN_W, MIN_H    = 400, 300
_JOBS: dict     = {}
_JOBS_LOCK      = threading.Lock()

ZOOMPAN_MOVES = [
    ("zoom_in_center", "min(zoom+0.0012,1.4)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    ("pan_lr",  "1.4", "iw*0.04*(on/225)",       "ih/2-(ih/zoom/2)"),
    ("pan_rl",  "1.4", "iw*0.04*(1-on/225)",     "ih/2-(ih/zoom/2)"),
    ("pan_tb",  "1.4", "iw/2-(iw/zoom/2)",      "ih*0.04*(on/225)"),
    ("pan_bt",  "1.4", "iw/2-(iw/zoom/2)",      "ih*0.04*(1-on/225)"),
    ("ken_tl",  "min(zoom+0.0010,1.4)", "iw*0.02*(1-on/225)",                 "ih*0.02*(1-on/225)"),
    ("ken_br",  "min(zoom+0.0010,1.4)", "iw/2-(iw/zoom/2)+iw*0.02*(on/225)", "ih/2-(ih/zoom/2)+ih*0.02*(on/225)"),
]

def _flow_clip(img_dir, seg_id):
    """Devuelve (clip_name, clip_path) priorizando VEO animado sobre zoompan."""
    import pathlib as _pl
    img_dir = _pl.Path(img_dir)
    veo = img_dir / f"flow_{seg_id:04d}.mp4"
    if veo.exists():
        return f"flow_{seg_id:04d}.mp4", veo
    zp = img_dir / f"flow_{seg_id:04d}_zp.mp4"
    return f"flow_{seg_id:04d}_zp.mp4", zp

def _get_dims(path):
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=10)
        w, h = r.stdout.strip().split(",")
        return int(w), int(h)
    except Exception:
        return 0, 0

def _make_thumbnail(src, thumb):
    src = pathlib.Path(src); thumb = pathlib.Path(thumb)
    if thumb.exists(): return True
    thumb.parent.mkdir(parents=True, exist_ok=True)
    ext = src.suffix.lower()
    if ext in ('.jpg','.jpeg','.png','.webp'):
        try:
            from PIL import Image
            img = Image.open(src).convert("RGB"); img.thumbnail((320,180))
            img.save(str(thumb), "JPEG", quality=70); return True
        except Exception: pass
    elif ext == '.mp4':
        subprocess.run([FFMPEG,"-hide_banner","-loglevel","error","-nostdin","-y",
            "-ss","1","-i",str(src),"-vframes","1",
            "-vf","scale=320:180:force_original_aspect_ratio=decrease,pad=320:180:(ow-iw)/2:(oh-ih)/2",
            str(thumb)], capture_output=True, timeout=15)
        return thumb.exists()
    return False

def _imagen_a_zoompan(src, dst, move_idx=0):
    w, h = _get_dims(src)
    if w == 0: return False
    _, z, x, y = ZOOMPAN_MOVES[move_idx % len(ZOOMPAN_MOVES)]
    # d=225 @ fps=30 = 7.5s de duración — generar a 1920x1080 directo (no 640x360)
    zp = f"zoompan=z='{z}':x='{x}':y='{y}':d=225:s=1920x1080:fps=30"
    if (w/h) < 0.9:
        fg = f"scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black@0"
        bg = f"scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,boxblur=20:5"
        vf = f"[0:v]{bg}[bg];[0:v]{fg}[fg];[bg][fg]overlay=0:0,{zp}"
        cmd = [FFMPEG, "-y", "-loop", "1", "-i", str(src), "-filter_complex", vf]
    else:
        vf = f"scale=8000:-1,{zp}"
        cmd = [FFMPEG, "-y", "-loop", "1", "-i", str(src), "-vf", vf]
    cmd += ["-t","7.5","-c:v","libx264","-preset","ultrafast","-crf","28",
            "-pix_fmt","yuv420p","-an","-movflags","+faststart",str(dst)]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    return pathlib.Path(dst).exists() and pathlib.Path(dst).stat().st_size > 50_000

def _buscar_brave(query, count=10):
    try: api_key = BRAVE_KEY_FILE.read_text().strip()
    except Exception: return []
    url = (f"https://api.search.brave.com/res/v1/images/search"
           f"?q={urllib.parse.quote(query)}&count={count}&safesearch=off")
    req = urllib.request.Request(url, headers={"Accept":"application/json","Accept-Encoding":"gzip","X-Subscription-Token":api_key})
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            raw = r.read()
            try: raw = gzip.decompress(raw)
            except Exception: pass
            data = json.loads(raw)
        items = []
        for item in data.get("results",[]):
            props = item.get("properties",{}) or {}
            img_url = props.get("url") or item.get("url","")
            if not img_url: continue
            iw = props.get("width") or 0; ih = props.get("height") or 0
            if iw and ih and (iw < MIN_W or ih < MIN_H): continue
            thumb = (item.get("thumbnail",{}) or {}).get("src") or img_url
            items.append({"url":img_url,"thumb":thumb,"source":"brave"})
        return items
    except Exception: return []

def _buscar_pexels_imgs(query, count=20):
    try: key = PEXELS_KEY_FILE.read_text().strip()
    except Exception: return []
    url = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(query)}&per_page={min(count,80)}"
    try:
        req = urllib.request.Request(url, headers={"Authorization": key})
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read())
        return [{"url":p["src"]["large"],"thumb":p["src"]["medium"],"source":"pexels"} for p in data.get("photos",[])]
    except Exception: return []

def _buscar_pixabay_imgs(query, count=20):
    try: key = PIXABAY_KEY_FILE.read_text().strip()
    except Exception: return []
    url = (f"https://pixabay.com/api/?key={key}&q={urllib.parse.quote(query)}"
           f"&image_type=photo&per_page={min(count,200)}&safesearch=true")
    try:
        with urllib.request.urlopen(url, timeout=12) as r:
            data = json.loads(r.read())
        return [{"url":p.get("largeImageURL",""),"thumb":p.get("webformatURL",""),"source":"pixabay"} for p in data.get("hits",[])]
    except Exception: return []

def _buscar_pexels_vids(query, count=12):
    try: key = PEXELS_KEY_FILE.read_text().strip()
    except Exception: return []
    url = f"https://api.pexels.com/videos/search?query={urllib.parse.quote(query)}&per_page={min(count,80)}"
    try:
        req = urllib.request.Request(url, headers={"Authorization": key})
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read())
        out = []
        for v in data.get("videos",[]):
            files = sorted(v.get("video_files",[]), key=lambda f: f.get("width",0), reverse=True)
            best  = next((f for f in files if f.get("width",9999) <= 1920), files[0] if files else None)
            if best: out.append({"url":best.get("link",""),"thumb":v.get("image",""),"duration":v.get("duration",0),"source":"pexels"})
        return out
    except Exception: return []

def _buscar_pixabay_vids(query, count=12):
    try: key = PIXABAY_KEY_FILE.read_text().strip()
    except Exception: return []
    url = (f"https://pixabay.com/api/videos/?key={key}&q={urllib.parse.quote(query)}"
           f"&per_page={min(count,200)}&video_type=film")
    try:
        with urllib.request.urlopen(url, timeout=12) as r:
            data = json.loads(r.read())
        out = []
        for v in data.get("hits",[]):
            vids = v.get("videos",{})
            fo = vids.get("medium") or vids.get("small") or vids.get("tiny")
            if fo: out.append({"url":fo.get("url",""),"thumb":v.get("userImageURL",""),"duration":v.get("duration",0),"source":"pixabay"})
        return out
    except Exception: return []

ICLOUD_ARTISTAS = HOME / "Library/Mobile Documents/com~apple~CloudDocs/Artistas"

def _norm_nombre(s):
    s = unicodedata.normalize("NFD", s.lower().replace("_"," "))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")

def _buscar_icloud_artista(nombre):
    """Busca carpeta en iCloud/Artistas por nombre normalizado."""
    if not ICLOUD_ARTISTAS.exists():
        return None
    n = _norm_nombre(nombre)
    for d in ICLOUD_ARTISTAS.iterdir():
        if d.is_dir() and _norm_nombre(d.name) == n:
            return d
    # Búsqueda parcial por apellido
    partes = n.split()
    apellido = partes[-1] if partes else n
    if len(apellido) > 3:
        for d in ICLOUD_ARTISTAS.iterdir():
            if d.is_dir() and apellido in _norm_nombre(d.name):
                return d
    return None

def _copiar_clips_a_icloud_bg(nombre, clips_dir):
    """Copia clips a iCloud automáticamente.
    - Si no existe la carpeta → crea y copia todo.
    - Si existe pero tiene MENOS clips que clips_dir → borra y reemplaza con los nuevos.
    - Si existe con igual o más clips → no toca nada.
    """
    import shutil
    clips_locales = sorted(pathlib.Path(clips_dir).glob("*.mp4"))
    n_locales = len(clips_locales)
    if n_locales == 0:
        return {"skipped": True, "reason": "sin clips locales"}

    carpeta_icloud = _buscar_icloud_artista(nombre)
    if carpeta_icloud:
        n_icloud = len(list(carpeta_icloud.glob("*.mp4")))
        if n_icloud >= n_locales:
            print(f"[iCloud] {nombre}: iCloud tiene {n_icloud} clips ≥ {n_locales} locales — omitiendo", flush=True)
            return {"skipped": True, "reason": "iCloud ya tiene suficientes", "folder": str(carpeta_icloud)}
        # iCloud tiene menos — borrar y reemplazar
        print(f"[iCloud] {nombre}: iCloud tiene {n_icloud} clips < {n_locales} locales — reemplazando", flush=True)
        shutil.rmtree(carpeta_icloud)
        nueva = carpeta_icloud
    else:
        nueva = ICLOUD_ARTISTAS / nombre.replace("_", " ").upper()

    nueva.mkdir(parents=True, exist_ok=True)
    copiados = 0
    for f in clips_locales:
        shutil.copy2(f, nueva / f.name)
        copiados += 1
    print(f"[iCloud] {nombre} → {nueva.name}: {copiados} clips copiados", flush=True)
    return {"skipped": False, "folder": str(nueva), "copiados": copiados}

def _descargar_imagen(url, dest, timeout=20):
    try:
        subprocess.run(["curl","-sL","--max-time",str(timeout),"-A","Mozilla/5.0","-o",str(dest),url],
                       capture_output=True, timeout=timeout+5)
        if not dest.exists() or dest.stat().st_size < 5000: dest.unlink(missing_ok=True); return False
        w, h = _get_dims(dest)
        if w < MIN_W or h < MIN_H: dest.unlink(missing_ok=True); return False
        return True
    except Exception: dest.unlink(missing_ok=True); return False

CANAL_COLORS = [
    "#00ff88", "#ff6b35", "#4ecdc4", "#ffe66d", "#a8e6cf",
    "#dda0dd", "#87ceeb", "#f0e68c", "#98fb98", "#ff69b4",
]


# ── helpers ──────────────────────────────────────────────────────────────────

def log(canal, personaje, accion, resultado):
    entry = {
        "fecha":     datetime.datetime.now().isoformat(timespec="seconds"),
        "canal":     canal,
        "video":     personaje,
        "accion":    accion,
        "resultado": resultado,
    }
    log_file = LOGS_DIR / f"{datetime.date.today()}.jsonl"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


_meta_lock = {}  # path → threading.Lock()
_meta_lock_mu = __import__("threading").Lock()

def _save_meta(meta_path, meta):
    """Escritura atómica de metadata.json: temp file → os.replace para evitar corrupción en writes concurrentes."""
    import threading, tempfile, os
    path_str = str(meta_path)
    with _meta_lock_mu:
        if path_str not in _meta_lock:
            _meta_lock[path_str] = threading.Lock()
    lock = _meta_lock[path_str]
    with lock:
        tmp = pathlib.Path(str(meta_path) + ".tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, meta_path)


def scan_videos():
    """Lee todos los metadata.json del árbol de carpetas (hasta 3 niveles)."""
    videos = []
    patterns = ["*/metadata.json", "*/*/metadata.json", "*/*/*/metadata.json"]
    seen = set()
    all_paths = []
    for pat in patterns:
        all_paths.extend(BASE_DIR.glob(pat))
    for meta_path in sorted(set(all_paths)):
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            carpeta = meta_path.parent
            if str(carpeta) in seen:
                continue
            seen.add(str(carpeta))
            # _carpeta es la ruta relativa desde BASE_DIR para las rutas de API
            rel = carpeta.relative_to(BASE_DIR)
            meta["_carpeta"] = str(rel)   # ej: "riqueza/victoria_ruffo"
            meta["_path"]    = str(carpeta)
            # Archivos presentes
            meta["_has_mp4"] = bool(list(carpeta.glob("*_final.mp4")))
            meta["_miniaturas_files"] = [
                f"miniatura_{i}" for i in [1, 2, 3]
                if (carpeta / f"miniatura_{i}.jpg").exists()
            ]
            # Estado de upload en proceso
            if carpeta.name in upload_procs:
                proc_info = upload_procs[carpeta.name]
                if proc_info["proc"].poll() is None:
                    meta["_uploading"] = True
                else:
                    meta["_uploading"] = False
            else:
                meta["_uploading"] = False
            videos.append(meta)
        except Exception:
            continue
    return videos


def group_by_canal(videos):
    canales = {}
    for v in videos:
        canal = v.get("canal", "sin_canal")
        canales.setdefault(canal, []).append(v)
    return canales


# ── API routes ────────────────────────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    videos  = scan_videos()
    canales = group_by_canal(videos)
    canal_list = []
    for idx, (canal, vids) in enumerate(canales.items()):
        pendientes = sum(1 for v in vids if v.get("estado") != "subido")
        subidos    = [v for v in vids if v.get("youtube_id")]
        ultimo     = max(subidos, key=lambda v: v.get("fecha_subida", ""), default=None)
        canal_list.append({
            "nombre":    canal,
            "color":     CANAL_COLORS[idx % len(CANAL_COLORS)],
            "videos":    vids,
            "pendientes": pendientes,
            "ultimo":    ultimo,
        })
    return jsonify(canal_list)


@app.route("/api/approve_thumbnail", methods=["POST"])
def approve_thumbnail():
    data      = request.json
    personaje = data["personaje"]   # puede ser "riqueza/victoria_ruffo"
    num       = data["num"]
    carpeta   = BASE_DIR / personaje
    meta_path = carpeta / "metadata.json"
    if not meta_path.exists():
        return jsonify({"ok": False, "error": "No metadata.json"}), 404
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    meta.setdefault("miniaturas", {})[f"miniatura_{num}"] = "aprobada"
    _save_meta(meta_path, meta)
    log(meta.get("canal", "?"), personaje, f"aprobar miniatura_{num}", "ok")
    return jsonify({"ok": True})


@app.route("/api/reject_thumbnail", methods=["POST"])
def reject_thumbnail():
    data      = request.json
    personaje = data["personaje"]
    num       = data["num"]
    carpeta   = BASE_DIR / personaje
    meta_path = carpeta / "metadata.json"
    if not meta_path.exists():
        return jsonify({"ok": False, "error": "No metadata.json"}), 404
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    meta.setdefault("miniaturas", {})[f"miniatura_{num}"] = "rechazada"
    _save_meta(meta_path, meta)
    log(meta.get("canal", "?"), personaje, f"rechazar miniatura_{num}", "ok")
    return jsonify({"ok": True})


@app.route("/api/upload/<path:personaje>", methods=["POST"])
def trigger_upload(personaje):
    data      = request.json or {}
    canal_json = data.get("canal_json", "Canal1FotosImpresionantes.json")
    privacidad = data.get("privacidad", "private")
    carpeta    = BASE_DIR / personaje

    if not carpeta.is_dir():
        return jsonify({"ok": False, "error": "Carpeta no existe"}), 404

    if personaje in upload_procs and upload_procs[personaje]["proc"].poll() is None:
        return jsonify({"ok": False, "error": "Upload ya en proceso"}), 409

    log_path = LOGS_DIR / f"upload_{personaje}_{datetime.date.today()}.log"
    log_file = open(log_path, "w")
    proc = subprocess.Popen(
        [
            sys.executable, str(BASE_DIR / "youtube_upload.py"),
            str(carpeta),
            "--headless",
            "--canal",      canal_json,
            "--privacidad", privacidad,
        ],
        stdout=log_file, stderr=subprocess.STDOUT,
    )
    upload_procs[personaje] = {"proc": proc, "log": str(log_path)}
    log("?", personaje, "iniciar upload", f"PID {proc.pid}")
    return jsonify({"ok": True, "pid": proc.pid, "log": str(log_path)})


@app.route("/api/upload_status/<path:personaje>")
def upload_status(personaje):
    if personaje not in upload_procs:
        return jsonify({"running": False, "returncode": None})
    info = upload_procs[personaje]
    rc   = info["proc"].poll()
    # Leer últimas 20 líneas del log
    lines = []
    try:
        with open(info["log"], encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()[-20:]
    except Exception:
        pass
    return jsonify({"running": rc is None, "returncode": rc, "log_tail": lines})


@app.route("/api/upload_all/<canal>", methods=["POST"])
def upload_all(canal):
    videos   = scan_videos()
    pending  = [v for v in videos if v.get("canal") == canal and v.get("estado") != "subido"]
    launched = []
    for v in pending:
        personaje = v["_carpeta"]
        r = trigger_upload.__wrapped__(personaje) if hasattr(trigger_upload, "__wrapped__") else None
        # Call directly
        data = request.json or {}
        canal_json = data.get("canal_json", "Canal1FotosImpresionantes.json")
        privacidad = data.get("privacidad", "private")
        carpeta    = BASE_DIR / personaje
        log_path   = LOGS_DIR / f"upload_{personaje}_{datetime.date.today()}.log"
        log_file   = open(log_path, "w")
        proc = subprocess.Popen(
            [sys.executable, str(BASE_DIR / "youtube_upload.py"),
             str(carpeta), "--headless", "--canal", canal_json, "--privacidad", privacidad],
            stdout=log_file, stderr=subprocess.STDOUT,
        )
        upload_procs[personaje] = {"proc": proc, "log": str(log_path)}
        launched.append(personaje)
        time.sleep(2)  # Pequeño gap entre subidas
    return jsonify({"ok": True, "launched": launched})


@app.route("/video/<path:personaje>/preview")
def video_preview(personaje):
    carpeta = BASE_DIR / personaje
    mp4s    = list(carpeta.glob("*_final.mp4"))
    if not mp4s:
        return "No video", 404
    return send_file(mp4s[0], mimetype="video/mp4", conditional=True)

@app.route("/audio/<path:personaje>/guion")
def audio_guion(personaje):
    carpeta = BASE_DIR / personaje
    mp3s = sorted([f for f in carpeta.glob("*.mp3") if "_test" not in f.name and "_src" not in f.name])
    if not mp3s:
        return "No audio", 404
    return send_file(mp3s[0], mimetype="audio/mpeg", conditional=True)


@app.route("/video/<path:personaje>/miniatura/<int:num>")
def miniatura_img(personaje, num):
    path = BASE_DIR / personaje / f"miniatura_{num}.jpg"
    if not path.exists():
        return "No image", 404
    return send_file(path, mimetype="image/jpeg")


@app.route("/api/regen_thumbnail/<path:personaje>", methods=["POST"])
def regen_thumbnail(personaje):
    data    = request.json or {}
    num     = int(data.get("num", 1))
    edad    = str(data.get("edad", "50"))
    cifra   = data.get("cifra", "")
    mujer   = bool(data.get("mujer", False))
    carpeta = BASE_DIR / personaje

    if not carpeta.is_dir():
        return jsonify({"ok": False, "error": "Carpeta no existe"}), 404

    key = f"{personaje}|{num}"
    if key in regen_procs and regen_procs[key]["proc"].poll() is None:
        return jsonify({"ok": False, "error": "Regeneración ya en proceso"}), 409

    cmd = [sys.executable, str(BASE_DIR / "miniatura.py"), str(carpeta),
           "--edad", edad, "--solo", str(num)]
    if cifra:
        cmd += ["--cifra", cifra]
    if mujer:
        cmd.append("--mujer")

    log_path = LOGS_DIR / f"regen_{personaje.replace('/', '_')}_{num}_{datetime.date.today()}.log"
    log_file = open(log_path, "w")
    proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)
    regen_procs[key] = {"proc": proc, "log": str(log_path)}
    log(personaje, personaje, f"regen miniatura_{num}", f"PID {proc.pid}")
    return jsonify({"ok": True, "pid": proc.pid})


@app.route("/api/regen_status/<path:personaje>/<int:num>")
def regen_status(personaje, num):
    key = f"{personaje}|{num}"
    if key not in regen_procs:
        return jsonify({"running": False, "returncode": None})
    info = regen_procs[key]
    rc   = info["proc"].poll()
    lines = []
    try:
        with open(info["log"], encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()[-10:]
    except Exception:
        pass
    return jsonify({"running": rc is None, "returncode": rc, "log_tail": lines})


@app.route("/api/canales_json")
def api_canales_json():
    jsons = sorted((BASE_DIR / "_jsonytapi").glob("*.json"))
    return jsonify([f.name for f in jsons])


# ── FOOTAGE — Aprobación visual antes del render ──────────────────────────────

@app.route("/api/footage/<path:personaje>")
def footage_list(personaje):
    """Lista todos los clips/imágenes de footage con su estado."""
    carpeta   = BASE_DIR / personaje
    meta_path = carpeta / "metadata.json"
    img_dir   = carpeta / "03-imagenes"
    if not meta_path.exists():
        return jsonify({"footage": {}, "stats": {}})
    meta    = json.loads(meta_path.read_text(encoding="utf-8"))
    footage = meta.get("footage", {})
    COSTO_POR_FUENTE = {"ia": 0.003, "pexels": 0.0, "pixabay": 0.0, "brave": 0.0}
    costo_total = sum(COSTO_POR_FUENTE.get(v.get("fuente","ia"), 0.003)
                      for v in footage.values() if v.get("estado") != "error")
    # Total esperado desde timeline.json (seduccion) o conteo del footage (riqueza)
    timeline_f = carpeta / "05-montaje" / "timeline.json"
    # Enriquecer footage con descripción en español y duración desde timeline.json
    if timeline_f.exists():
        tdata = json.loads(timeline_f.read_text(encoding="utf-8"))
        tl_by_ts = {}
        for seg in tdata.get("visual_timeline", []):
            key = round(float(seg.get("start_seconds", 0)), 1)
            tl_by_ts[key] = seg
        for info in footage.values():
            try:
                ts_key = round(float(info.get("timestamp", 0)), 1)
            except (ValueError, TypeError):
                continue
            seg = tl_by_ts.get(ts_key) or tl_by_ts.get(round(ts_key + 0.1, 1)) or tl_by_ts.get(round(ts_key - 0.1, 1))
            if seg:
                info["descripcion_es"] = seg.get("scene_description_es", "")
                info["duration_s"]     = round(seg.get("duration", 0), 1)
                info["ia_prompt"]      = seg.get("ia_prompt", "")
                info["segment_id"]     = seg.get("segment_id", 0)
    if timeline_f.exists():
        tdata = json.loads(timeline_f.read_text(encoding="utf-8"))
        total_esperado = len(tdata.get("visual_timeline", []))
    else:
        total_esperado = len(footage)
    generadas   = sum(1 for v in footage.values() if v.get("estado") != "error")
    faltantes   = max(0, total_esperado - generadas)
    SEGS_POR_IMG = 32  # ~30s generación + 2s overhead
    eta_segs    = faltantes * SEGS_POR_IMG
    eta_min     = eta_segs // 60
    eta_seg_rem = eta_segs % 60
    eta_str     = f"{eta_min}m {eta_seg_rem:02d}s" if faltantes > 0 else "Completo"
    stats   = {
        "total":          len(footage),
        "total_esperado": total_esperado,
        "generadas":      generadas,
        "faltantes":      faltantes,
        "eta":            eta_str,
        "aprobado":    sum(1 for v in footage.values() if v.get("estado") == "aprobado"),
        "pendiente":   sum(1 for v in footage.values() if v.get("estado") == "pendiente"),
        "rechazado":   sum(1 for v in footage.values() if v.get("estado") == "rechazado"),
        "error":       sum(1 for v in footage.values() if v.get("estado") == "error"),
        "costo_total": round(costo_total, 4),
    }
    return jsonify({"footage": footage, "stats": stats})


def _serve_video(path):
    """Sirve un MP4 con soporte correcto de HTTP Range requests para el browser."""
    path = pathlib.Path(path)
    file_size = path.stat().st_size
    range_header = request.headers.get("Range")
    if range_header:
        # Parsear "bytes=start-end"
        byte_range = range_header.replace("bytes=", "").split("-")
        start = int(byte_range[0])
        end   = int(byte_range[1]) if byte_range[1] else file_size - 1
        length = end - start + 1
        def generate():
            with open(path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(524288, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk
        resp = Response(generate(), 206, mimetype="video/mp4", direct_passthrough=True)
        resp.headers["Content-Range"]  = f"bytes {start}-{end}/{file_size}"
        resp.headers["Accept-Ranges"]  = "bytes"
        resp.headers["Content-Length"] = str(length)
        return resp
    # Sin Range: servir completo
    resp = Response(open(path, "rb"), 200, mimetype="video/mp4", direct_passthrough=True)
    resp.headers["Accept-Ranges"]  = "bytes"
    resp.headers["Content-Length"] = str(file_size)
    return resp


@app.route("/footage/<path:personaje>/<clip_name>")
def footage_clip(personaje, clip_name):
    """Sirve un clip de footage para preview con soporte de Range requests."""
    for subdir in ("footage", "03-imagenes"):
        clip_path = BASE_DIR / personaje / subdir / clip_name
        if clip_path.exists():
            return _serve_video(clip_path)
    return "Not found", 404


@app.route("/api/yt_clips/<path:personaje>")
def yt_clips_list(personaje):
    """Lista clips de YouTube (clips/yt/ o clips/). Devuelve todos para que el front pueda reemplazar rechazados."""
    carpeta   = BASE_DIR / personaje
    clips_dir = carpeta / "clips"
    # Preferir subcarpeta yt/ si existe
    yt_dir = clips_dir / "yt"
    search_dir = yt_dir if yt_dir.exists() else clips_dir
    meta_path = carpeta / "metadata.json"
    if not search_dir.exists():
        return jsonify({"clips": [], "total": 0, "total_10min": 0})
    import re as _re
    def _clip_index(f):
        m = _re.search(r"(\d+)", f.stem)
        return int(m.group(1)) if m else 0
    files = sorted(
        [f for f in search_dir.glob("*.mp4") if _re.search(r"\d+", f.stem)],
        key=_clip_index
    )
    rejected = {}
    saved_order = []
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        rejected = meta.get("rejected_yt_clips", {})
        saved_order = meta.get("clips_order", [])

    # Si hay clips_order guardado, respetar ese orden en el grid
    files_by_name = {f.name: f for f in files}
    if saved_order:
        ordered_files = [files_by_name[n] for n in saved_order if n in files_by_name]
        # Agregar al final cualquier clip no incluido en el orden guardado
        ordered_names = set(saved_order)
        ordered_files += [f for f in files if f.name not in ordered_names]
    else:
        ordered_files = files

    clips = []
    for f in ordered_files:
        name = f.name
        start_s = _clip_index(f) * 5
        clips.append({
            "name":    name,
            "start_s": start_s,
            "estado":  rejected.get(name, "pendiente"),
        })
    return jsonify({"clips": clips, "total": len(ordered_files), "total_10min": min(120, len(ordered_files))})


@app.route("/yt_clip/<path:personaje>/<clip_name>")
def serve_yt_clip(personaje, clip_name):
    """Sirve clip del pool: clips/yt/, clips/google/, clips/ o 03-imagenes/ (fallback YT)."""
    base = BASE_DIR / personaje / "clips"
    for sub in ["yt", "google", ""]:
        p = (base / sub / clip_name) if sub else (base / clip_name)
        if p.exists():
            return _serve_video(p)
    # Fallback: clips YT guardados en 03-imagenes (cuando no había imagen en ZIP)
    p2 = BASE_DIR / personaje / "03-imagenes" / clip_name
    if p2.exists():
        return _serve_video(p2)
    return "Not found", 404


@app.route("/flow_poster/<path:personaje>/<clip_name>")
def serve_flow_poster(personaje, clip_name):
    """Sirve poster JPG de un clip Flow (primer frame). Genera al vuelo si no existe."""
    stem       = pathlib.Path(clip_name).stem
    img_dir    = BASE_DIR / personaje / "03-imagenes"
    poster_dir = img_dir / ".posters"
    poster_path = poster_dir / f"{stem}.jpg"
    if not poster_path.exists():
        clip_path = img_dir / clip_name
        if not clip_path.exists():
            return "Not found", 404
        poster_dir.mkdir(exist_ok=True)
        for seek in ["0.1", "0"]:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", seek, "-i", str(clip_path),
                 "-vframes", "1", "-q:v", "5", "-vf", "scale=320:-1", str(poster_path)],
                capture_output=True, timeout=8
            )
            if poster_path.exists():
                break
    if not poster_path.exists():
        return "Not found", 404
    return send_file(poster_path, mimetype="image/jpeg")


@app.route("/yt_poster/<path:personaje>/<clip_name>")
def serve_yt_poster(personaje, clip_name):
    """Sirve poster JPG de un clip YT (generado por ffmpeg). Si no existe, genera al vuelo."""
    stem      = pathlib.Path(clip_name).stem
    base_clips = BASE_DIR / personaje / "clips"
    poster_dir = base_clips / ".posters"
    poster_path = poster_dir / f"{stem}.jpg"
    if not poster_path.exists():
        clip_path = None
        for sub in ["yt", "google", ""]:
            p = (base_clips / sub / clip_name) if sub else (base_clips / clip_name)
            if p.exists():
                clip_path = p
                break
        if not clip_path:
            return "Not found", 404
        poster_dir.mkdir(exist_ok=True)
        # Intentar en 0.5s primero; si falla (clip muy corto), usar frame 0
        for seek in ["0.5", "0"]:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", seek, "-i", str(clip_path),
                 "-vframes", "1", "-q:v", "5", "-vf", "scale=320:-1", str(poster_path)],
                capture_output=True, timeout=8
            )
            if poster_path.exists():
                break
    if not poster_path.exists():
        return "Not found", 404
    from flask import send_file
    return send_file(poster_path, mimetype="image/jpeg")


@app.route("/api/trim_clip/<path:personaje>", methods=["POST"])
def trim_clip(personaje):
    """Re-encodea un clip con start/end y reemplaza en disco."""
    data = request.get_json(force=True)
    clip_name = data.get("clip")
    t_start   = float(data.get("start", 0))
    t_end     = float(data.get("end", 0))
    clip_type = data.get("type", "yt")  # "yt" o "footage"

    if not clip_name:
        return jsonify({"ok": False, "error": "clip requerido"}), 400

    if clip_type == "footage":
        clip_path = BASE_DIR / personaje / "03-imagenes" / clip_name
    else:
        clip_path = BASE_DIR / personaje / "clips" / clip_name

    if not clip_path.exists():
        return jsonify({"ok": False, "error": "clip no encontrado"}), 404

    duration = t_end - t_start
    if duration < 2.5:
        return jsonify({"ok": False, "error": "duración mínima 2.5s"}), 400

    tmp_path = clip_path.with_suffix(".trimming.mp4")
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", str(t_start), "-to", str(t_end),
        "-i", str(clip_path),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-an", str(tmp_path)
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        return jsonify({"ok": False, "error": result.stderr.decode()[:300]}), 500

    tmp_path.replace(clip_path)
    return jsonify({"ok": True, "clip": clip_name, "duration": round(duration, 2)})


@app.route("/api/yt_clip_action/<path:personaje>", methods=["POST"])
def yt_clip_action(personaje):
    """Aprueba o rechaza un clip de YouTube."""
    body   = request.json or {}
    clip   = body.get("clip")
    accion = body.get("accion")  # "aprobado" | "rechazado"
    if not clip or accion not in ("aprobado", "rechazado"):
        return jsonify({"ok": False, "error": "clip y accion requeridos"}), 400
    meta_path = BASE_DIR / personaje / "metadata.json"
    if not meta_path.exists():
        return jsonify({"ok": False, "error": "metadata.json no encontrado"}), 404
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if accion == "rechazado":
        meta.setdefault("rejected_yt_clips", {})[clip] = "rechazado"
    else:
        meta.setdefault("rejected_yt_clips", {}).pop(clip, None)
    _save_meta(meta_path, meta)
    return jsonify({"ok": True})


@app.route("/api/footage_approve/<path:personaje>", methods=["POST"])
def footage_approve(personaje):
    """Aprueba o rechaza un clip de footage."""
    body      = request.json or {}
    clip_name = body.get("clip")
    accion    = body.get("accion")  # "aprobado" | "rechazado"
    if not clip_name or accion not in ("aprobado", "rechazado"):
        return jsonify({"ok": False, "error": "clip y accion requeridos"}), 400
    meta_path = BASE_DIR / personaje / "metadata.json"
    if not meta_path.exists():
        return jsonify({"ok": False, "error": "metadata.json no encontrado"}), 404
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.setdefault("footage", {}).setdefault(clip_name, {})["estado"] = accion
    _save_meta(meta_path, meta)
    log("?", personaje, f"footage_{accion}", clip_name)

    return jsonify({"ok": True, "clip": clip_name, "estado": accion})


@app.route("/api/prompts/<path:personaje>", methods=["GET"])
def prompts_get(personaje):
    """Lee el CSV de prompts de imagen."""
    carpeta = BASE_DIR / personaje
    csvs = list(carpeta.glob("*_prompts.csv"))
    if not csvs:
        return jsonify({"prompts": []})
    import csv as csvmod
    rows = []
    with open(csvs[0], encoding="utf-8", newline="") as f:
        reader = csvmod.DictReader(f)
        for r in reader:
            rows.append({"seg_inicio": r.get("seg_inicio", ""), "prompt": r.get("prompt", "")})
    return jsonify({"prompts": rows, "csv_path": str(csvs[0].relative_to(BASE_DIR))})


@app.route("/api/prompts/<path:personaje>", methods=["PUT"])
def prompts_save(personaje):
    """Guarda el CSV de prompts editado desde el dashboard."""
    carpeta = BASE_DIR / personaje
    csvs = list(carpeta.glob("*_prompts.csv"))
    if not csvs:
        return jsonify({"ok": False, "error": "CSV no encontrado"}), 404
    data = request.json or {}
    rows = data.get("prompts", [])
    import csv as csvmod
    with open(csvs[0], "w", encoding="utf-8", newline="") as f:
        writer = csvmod.DictWriter(f, fieldnames=["seg_inicio", "prompt"])
        writer.writeheader()
        for r in rows:
            writer.writerow({"seg_inicio": r["seg_inicio"], "prompt": r["prompt"]})
    log("?", personaje, "prompts_guardados", f"{len(rows)} prompts")
    return jsonify({"ok": True, "guardados": len(rows)})


@app.route("/api/rerun_status/<path:personaje>")
def rerun_status(personaje):
    if personaje not in rerun_procs:
        return jsonify({"running": False})
    rc = rerun_procs[personaje]["proc"].poll()
    return jsonify({"running": rc is None})


render_procs: dict = {}  # personaje → {"proc": Popen, "log": str}

@app.route("/api/render_launch/<path:personaje>", methods=["POST"])
def render_launch(personaje):
    """Lanza render.py en background para el personaje dado."""
    carpeta = BASE_DIR / personaje
    if not carpeta.is_dir():
        return jsonify({"ok": False, "error": "Carpeta no existe"}), 404
    if personaje in render_procs and render_procs[personaje]["proc"].poll() is None:
        return jsonify({"ok": False, "error": "Render ya en proceso"}), 409
    log_path = LOGS_DIR / f"render_{personaje.replace('/', '_')}.log"
    log_file = open(log_path, "w")
    proc = subprocess.Popen(
        [sys.executable, str(BASE_DIR / "render.py"), str(carpeta)],
        stdout=log_file, stderr=subprocess.STDOUT,
    )
    render_procs[personaje] = {"proc": proc, "log": str(log_path)}
    log("?", personaje, "render_launch", f"PID {proc.pid}")
    return jsonify({"ok": True, "pid": proc.pid, "log": str(log_path)})


@app.route("/api/render_launch_status/<path:personaje>")
def render_launch_status(personaje):
    if personaje not in render_procs:
        return jsonify({"running": False, "returncode": None})
    info = render_procs[personaje]
    rc = info["proc"].poll()
    lines = []
    try:
        with open(info["log"], encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()[-10:]
    except Exception:
        pass
    return jsonify({"running": rc is None, "returncode": rc, "log_tail": lines})


@app.route("/api/footage_approve_all/<path:personaje>", methods=["POST"])
def footage_approve_all(personaje):
    """Aprueba todos los clips pendientes de un video y congela el orden del grid."""
    meta_path = BASE_DIR / personaje / "metadata.json"
    if not meta_path.exists():
        return jsonify({"ok": False}), 404
    meta    = json.loads(meta_path.read_text(encoding="utf-8"))
    footage = meta.get("footage", {})
    count   = 0
    for clip, info in footage.items():
        if info.get("estado") == "pendiente":
            info["estado"] = "aprobado"
            count += 1
    # Guardar el orden del grid — siempre sobrescribir con lo que manda el frontend
    body = request.json or {}
    clips_order = body.get("clips_order", [])
    if clips_order:
        meta["clips_order"] = clips_order
    _save_meta(meta_path, meta)
    log("?", personaje, "footage_approve_all", f"{count} clips aprobados, orden guardado: {len(clips_order)} clips")
    return jsonify({"ok": True, "aprobados": count})


@app.route("/api/cola_auto_approve/<path:personaje>", methods=["POST"])
def cola_auto_approve(personaje):
    """Auto-aprobación para cola_videos.py — NO usar desde el dashboard manual."""
    import re as _re
    carpeta   = BASE_DIR / personaje
    meta_path = carpeta / "metadata.json"
    _m2 = {}
    if meta_path.exists():
        try:
            _m2 = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            _m2 = {}

    # Aprobar todos los clips de footage pendientes
    footage = _m2.get("footage", {})
    for clip, info in footage.items():
        if info.get("estado") == "pendiente":
            info["estado"] = "aprobado"

    # Generar clips_order shuffleado si no existe
    if not _m2.get("clips_order"):
        clips_dir = carpeta / "clips"
        deleted_yt = set(_m2.get("deleted_yt_clips", {}).keys()) | set(_m2.get("rejected_yt_clips", {}).keys())
        def _ci(f):
            m = _re.search(r"(\d+)", f.stem)
            return int(m.group(1)) if m else 0
        # Buscar en yt/ y google/ además de raíz
        all_files = []
        for sub in ["yt", "google", ""]:
            d = clips_dir / sub if sub else clips_dir
            if d.exists():
                all_files.extend(f for f in d.glob("*.mp4") if f.name not in deleted_yt and not any(x.name == f.name for x in all_files))
        clip_files = sorted(all_files, key=_ci)
        names = [f.name for f in clip_files]
        random.shuffle(names)
        _m2["clips_order"] = names

    _save_meta(meta_path, _m2)
    log("🤖", personaje, "cola_auto_approve", f"auto-aprobado por cola_videos.py")
    return jsonify({"ok": True, "clips_order": len(_m2["clips_order"])})


@app.route("/api/flow_replace_with_yt", methods=["POST"])
def flow_replace_with_yt():
    """Registra que un clip Flow fue rechazado y reemplazado por un clip YT. Borra el archivo físico."""
    data = request.json or {}
    personaje = data.get("personaje", "")
    flow_clip  = data.get("flow_clip", "")
    yt_clip    = data.get("yt_clip", "")
    if not (personaje and flow_clip and yt_clip):
        return jsonify({"ok": False, "error": "faltan parámetros"})
    # Mover a _backup/ en vez de borrar — por si se necesita recuperar
    flow_path = BASE_DIR / personaje / "03-imagenes" / flow_clip
    deleted = False
    if flow_path.exists():
        backup_dir = BASE_DIR / personaje / "03-imagenes" / "_backup"
        backup_dir.mkdir(exist_ok=True)
        shutil.move(str(flow_path), str(backup_dir / flow_clip))
        deleted = True
    meta_path = BASE_DIR / personaje / "metadata.json"
    meta = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    rechazados = meta.setdefault("flow_replaced_by_yt", {})
    rechazados[flow_clip] = yt_clip
    _save_meta(meta_path, meta)
    return jsonify({"ok": True, "deleted_flow": deleted})


@app.route("/api/update_baserow_prompt", methods=["POST"])
def update_baserow_prompt():
    """
    Actualiza una o varias filas en Baserow: status=pending + nuevo Image Prompt.
    Body: { "updates": [ {"clip": "flow_0001_zp.mp4", "prompt": "...", "personaje": "riqueza/luis_de_alba"}, ... ] }
    """
    import subprocess as _sp, json as _json
    BASEROW_TOKEN    = '4QrZH5MkTLHKtGqTG97Gz2yQTAIhknMq'
    BASEROW_TABLE_ID = '1100194'
    BASEROW_API_BASE = 'https://api.baserow.io/api'

    def _br_curl(method, path, data=None):
        url = BASEROW_API_BASE + path
        cmd = ['curl', '-s', '-X', method, url,
               '-H', f'Authorization: Token {BASEROW_TOKEN}',
               '-H', 'Content-Type: application/json']
        if data:
            cmd += ['-d', _json.dumps(data)]
        r = _sp.run(cmd, capture_output=True, text=True)
        try:
            return _json.loads(r.stdout) if r.stdout.strip() else {}
        except Exception:
            return {}

    body    = request.json or {}
    updates = body.get("updates", [])
    if not updates:
        return jsonify({"ok": False, "error": "updates requerido"}), 400

    # Obtener todas las filas actuales de Baserow para mapear segment_id → row_id
    rows_data = _br_curl('GET', f'/database/rows/table/{BASEROW_TABLE_ID}/?user_field_names=true&size=200')
    rows = rows_data.get('results', [])

    # Construir mapa: segment_id → row_id  (el segment_id va en el prefijo "[N] " del campo VEO Prompt)
    seg_to_rowid = {}
    for row in rows:
        veo = row.get('VEO Prompt', '') or ''
        if veo.startswith('['):
            try:
                seg_id = int(veo.split(']')[0][1:])
                seg_to_rowid[seg_id] = row['id']
            except (ValueError, IndexError):
                pass

    results = []
    errors  = []
    for upd in updates:
        clip     = upd.get('clip', '')
        new_prompt = upd.get('prompt', '').strip()
        personaje  = upd.get('personaje', '')

        # Extraer segment_id del nombre del clip: flow_0001_zp.mp4 → 1
        try:
            seg_id = int(clip.replace('flow_', '').replace('_zp.mp4', '').replace('img_', '').replace('.mp4', ''))
        except ValueError:
            errors.append({"clip": clip, "error": "no se pudo extraer segment_id"})
            continue

        row_id = seg_to_rowid.get(seg_id)
        if not row_id:
            errors.append({"clip": clip, "error": f"segment_id {seg_id} no encontrado en Baserow"})
            continue

        patch = {'Image Prompt': new_prompt, 'Status': 'pending'}
        resp  = _br_curl('PATCH', f'/database/rows/table/{BASEROW_TABLE_ID}/{row_id}/?user_field_names=true', patch)
        results.append({"clip": clip, "seg_id": seg_id, "row_id": row_id, "ok": bool(resp.get('id'))})

        # Actualizar metadata.json local si se provee personaje
        if personaje:
            meta_path = BASE_DIR / personaje / "metadata.json"
            if meta_path.exists():
                meta = _json.loads(meta_path.read_text(encoding="utf-8"))
                meta.setdefault("footage", {}).setdefault(clip, {})["estado"] = "rechazado"
                meta.setdefault("footage", {})[clip]["ia_prompt"] = new_prompt
                _save_meta(meta_path, meta)

    log("?", "batch", "update_baserow_prompt", f"{len(results)} actualizados, {len(errors)} errores")
    return jsonify({"ok": True, "results": results, "errors": errors})


@app.route("/api/render_preview/<path:personaje>")
def render_preview_api(personaje):
    """Simula la timeline de los primeros 10 min: clips YT intercalados con Flow images."""
    import random as _rnd
    carpeta = BASE_DIR / personaje

    # Leer clips de YT
    clips_dir = carpeta / "clips"
    tl_path_check = carpeta / "05-montaje" / "timeline.json"
    # Si existe timeline.json → canal con footage IA; usar ese path siempre
    if tl_path_check.exists():
        # Canal 100% IA — construir segmentos directo del timeline + footage
        tl_path = carpeta / "05-montaje" / "timeline.json"
        if not tl_path.exists():
            return jsonify({"segments": [], "error": "No hay clips"})
        tl = json.load(open(tl_path))
        meta_path = carpeta / "metadata.json"
        footage = {}
        if meta_path.exists():
            footage = json.loads(meta_path.read_text(encoding="utf-8")).get("footage", {})
        segments = []
        for seg in tl.get("visual_timeline", []):
            # Solo incluir segmentos con source=flow/brave/ia/hyperframe/yt_clip
            if seg.get("source", "flow") not in ("flow", "brave", "ia", "hyperframe", "yt_clip"):
                continue
            seg_id    = seg.get("segment_id", seg.get("segmento_id", 0))
            clip_name, clip_path = _flow_clip(carpeta / "03-imagenes", seg_id)
            info      = footage.get(clip_name, {})
            t_start   = seg.get("start_seconds", seg.get("inicio_segundos", 0))
            t_end     = seg.get("end_seconds",   seg.get("fin_segundos", t_start + seg.get("duration", seg.get("duracion", 6.0))))
            dur       = round(t_end - t_start, 2)
            meta_fuente = info.get("fuente", seg.get("source", "flow"))
            seg_type  = "flow" if meta_fuente in ("flow", "brave", "ia", "hyperframe") else "yt_clip"
            segments.append({
                "type":        seg_type,
                "clip":        clip_name,
                "t_start":     round(t_start, 2),
                "t_end":       round(t_end, 2),
                "duration":    dur,
                "description": seg.get("scene_description_es") or seg.get("scene_description", ""),
                "label":       seg.get("ia_prompt") or seg.get("image_prompt", ""),
                "estado":      info.get("estado", "pendiente") if clip_path.exists() else "faltante",
                "exists":      clip_path.exists(),
                "recycled":    False,
            })
        # Incluir también clips del pool: clips/yt/, clips/google/, clips/
        recycled_count_ia = 0
        _audio_dur = 0.0
        extra_clips_dir = carpeta / "clips"
        deleted_extra   = set((footage.get("deleted_yt_clips") or {}).keys()) | \
                          set((footage.get("rejected_yt_clips") or {}).keys())
        if extra_clips_dir.exists():
            import re as _re2
            def _cidx(f):
                m = _re2.search(r"(\d+)", f.stem); return int(m.group(1)) if m else 0
            def _extra_sort(f):
                name = f.name
                if name.startswith("clip_"): group = 2
                elif name.startswith("added_"): group = 0
                else: group = 1  # img_*
                return (group, _cidx(f))
            # Buscar en subcarpetas yt/ y google/ además de la raíz
            raw_files = []
            for sub in ["yt", "google", ""]:
                d = extra_clips_dir / sub if sub else extra_clips_dir
                if d.is_dir():
                    raw_files.extend(f for f in d.glob("*.mp4") if "_raw" not in f.name and not f.name.startswith("source_"))
            # Todos los clips disponibles (sin borrados)
            available = {f.name: f for f in raw_files if f.name not in deleted_extra}
            # Respetar clips_order guardado si existe
            saved_order = footage.get("clips_order", [])
            if saved_order:
                # Clips en el orden guardado (solo los que aún existen)
                ordered_names = [n for n in saved_order if n in available]
                # Clips nuevos no incluidos en el orden guardado → al final
                new_names = sorted([f for f in available.values() if f.name not in set(saved_order)],
                                   key=_extra_sort)
                extra = [available[n] for n in ordered_names] + new_names
            else:
                extra = sorted(available.values(), key=_extra_sort)
            # Calcular duración del audio para saber hasta dónde llegar
            import math as _math2
            _mp3s = sorted([f for f in carpeta.glob("*.mp3") if "_test" not in f.name and "_src" not in f.name])
            _audio_dur = 0.0
            if _mp3s:
                try:
                    _rp = subprocess.run(
                        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                         "-of", "default=noprint_wrappers=1:nokey=1", str(_mp3s[0])],
                        capture_output=True, text=True, timeout=5)
                    _audio_dur = float(_rp.stdout.strip())
                except Exception:
                    _audio_dur = 0.0
            _MAX_T = _audio_dur if _audio_dur > 0 else 1800.0

            extra_cycle = list(extra)
            ei = 0
            recycled_count_ia = 0  # conteo clips YT reciclados

            def _yt_seg(ef, t0, dur, is_rec):
                info_e = footage.get(ef.name, {})
                return {
                    "type":        "yt_clip",
                    "clip":        ef.name,
                    "t_start":     round(t0, 2),
                    "t_end":       round(t0 + dur, 2),
                    "duration":    round(dur, 2),
                    "description": info_e.get("descripcion_es", ""),
                    "label":       ef.name,
                    "estado":      info_e.get("estado", "pendiente"),
                    "exists":      True,
                    "recycled":    is_rec,
                }

            # Riqueza/fútbol: intercalar YT cronológicamente entre los Flow
            if extra_cycle:
                flow_queue = list(segments)   # ya ordenados por t_start
                segments = []
                cursor_t = 0.0
                for flow_seg in flow_queue:
                    flow_start = flow_seg["t_start"]
                    while cursor_t < flow_start - 0.1 and extra_cycle:
                        ef = extra_cycle[ei % len(extra_cycle)]
                        ei += 1
                        is_recycled = ei > len(extra_cycle)
                        if is_recycled:
                            recycled_count_ia += 1
                        dur_e = min(5.0, flow_start - cursor_t, _MAX_T - cursor_t)
                        if dur_e < 0.5:
                            break
                        segments.append(_yt_seg(ef, cursor_t, dur_e, is_recycled))
                        cursor_t += dur_e
                    segments.append(flow_seg)
                    cursor_t = flow_seg["t_end"]
                # Llenar el resto con YT clips
                while cursor_t < _MAX_T and extra_cycle:
                    ef = extra_cycle[ei % len(extra_cycle)]
                    ei += 1
                    is_recycled = ei > len(extra_cycle)
                    if is_recycled:
                        recycled_count_ia += 1
                    dur_e = min(5.0, _MAX_T - cursor_t)
                    segments.append(_yt_seg(ef, cursor_t, dur_e, is_recycled))
                    cursor_t += dur_e
        return jsonify({"segments": segments, "recycled_count": recycled_count_ia, "recycled_names": [], "clips_order_saved": bool(footage.get("clips_order")), "audio_dur": round(_audio_dur, 1)})

    import re as _re
    def _clip_index(f):
        m = _re.search(r"(\d+)", f.stem)
        return int(m.group(1)) if m else 0

    # Excluir clips marcados como borrados en metadata
    meta_path = carpeta / "metadata.json"
    _m = {}
    if meta_path.exists():
        try:
            _m = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            _m = {}
    else:
        # Crear metadata mínimo para que el dashboard funcione
        _m = {
            "personaje": carpeta.name,
            "nicho": carpeta.parent.name,
            "estado": "pendiente",
            "deleted_yt_clips": {},
            "rejected_yt_clips": {},
            "clips_order": [],
        }
        _save_meta(meta_path, _m)
    deleted_yt = set(_m.get("deleted_yt_clips", {}).keys()) | set(_m.get("removed_yt_cards", {}).keys())
    clips_order = _m.get("clips_order", [])

    all_files = {f.name: f for f in clips_dir.glob("*.mp4")}
    # Respetar orden guardado por drag & drop si existe
    if clips_order:
        ordered = [all_files[n] for n in clips_order if n in all_files and n not in deleted_yt]
        remaining = [f for n, f in sorted(all_files.items(), key=lambda x: _clip_index(x[1]))
                     if n not in deleted_yt and n not in clips_order]
        clip_files = ordered + remaining
    else:
        clip_files = sorted([f for f in all_files.values() if f.name not in deleted_yt], key=_clip_index)

    if not clip_files:
        return jsonify({"segments": [], "error": "No hay clips"})

    # Leer timeline de Flow images
    tl_path = carpeta / "05-montaje" / "timeline.json"
    flow_inserts = {}  # timestamp_inicio -> segmento
    if tl_path.exists():
        tl = json.load(open(tl_path))
        for seg in tl.get("visual_timeline", []):
            if seg.get("source", "flow") not in ("flow", "brave", "ia", "hyperframe", "yt_clip"):
                continue
            ts = float(seg.get("start_seconds", seg.get("start_time", 0)))
            flow_inserts[ts] = seg

    # Obtener duración real de clips con ffprobe
    def clip_dur(path):
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                capture_output=True, text=True, timeout=3
            )
            return float(r.stdout.strip())
        except Exception:
            return 5.0

    MAX_T = 1800.0  # 30 min cubre cualquier video

    name_to_idx = {f.name: i for i, f in enumerate(clip_files)}

    if clips_order:
        # Respetar exactamente el orden guardado (incluye reciclados en su posición)
        pool = [name_to_idx[n] for n in clips_order if n in name_to_idx]
        recycled_start_pool_idx = len(clip_files)
        # Si el pool guardado no cubre MAX_T, extender con el mismo orden
        indices = list(range(len(clip_files)))
        clips_necesarios = int(MAX_T / 5) + 10
        while len(pool) < clips_necesarios:
            pool.extend(indices)
    else:
        indices = list(range(len(clip_files)))
        _rnd.shuffle(indices)
        first_pass = list(indices)
        # Guardar orden inmediatamente para que refrescos futuros lo respeten
        _m["clips_order"] = [clip_files[i].name for i in first_pass]
        _save_meta(meta_path, _m)
        clips_necesarios = int(MAX_T / 5) + 10
        second_pass = []
        while len(first_pass) + len(second_pass) < clips_necesarios:
            second_pass.extend(indices)
        recycled_start_pool_idx = len(first_pass)
        pool = first_pass + second_pass

    # Construir timeline hasta MAX_T
    flow_ts_sorted = sorted(flow_inserts.keys())
    cursor = 0.0
    segments = []
    clip_idx = 0

    while cursor < MAX_T and clip_idx < len(pool):
        # ¿Hay un Flow insert cuyo timestamp ya llegó?
        next_flow = None
        for ts in flow_ts_sorted:
            if ts <= cursor + 5.0:  # dentro del siguiente clip
                next_flow = ts
                break

        if next_flow is not None:
            seg = flow_inserts[next_flow]
            seg_id = seg.get("segment_id", 0)
            dur = float(seg.get("duration", 8.0))
            flow_clip_name, flow_clip_path = _flow_clip(carpeta / "03-imagenes", seg_id)
            segments.append({
                "type": "flow",
                "t_start": round(next_flow, 1),
                "t_end": round(next_flow + dur, 1),
                "duration": round(dur, 1),
                "label": seg.get("scene_description_es") or seg.get("ia_prompt", f"Flow {seg_id}"),
                "clip": flow_clip_name,
                "url": f"/footage/{personaje}/{flow_clip_name}",
                "exists": flow_clip_path.exists(),
                "seg_id": seg_id,
            })
            cursor = next_flow + dur
            flow_ts_sorted = [t for t in flow_ts_sorted if t > next_flow]
        else:
            is_recycled = clip_idx >= recycled_start_pool_idx
            ci = pool[clip_idx % len(pool)]
            clip_idx += 1
            cf = clip_files[ci]
            dur = 5.0
            if cursor + dur > MAX_T:
                dur = MAX_T - cursor
            segments.append({
                "type": "yt_clip",
                "t_start": round(cursor, 1),
                "t_end": round(cursor + dur, 1),
                "duration": round(dur, 1),
                "label": cf.name,
                "clip": cf.name,
                "url": f"/yt_clip/{personaje}/{cf.name}",
                "exists": True,
                "recycled": is_recycled,
            })
            cursor += dur

    # Contar clips reciclados
    recycled_count = sum(1 for s in segments if s.get("recycled"))
    recycled_names = list({s["clip"] for s in segments if s.get("recycled")})

    # Calcular clips necesarios: duración del MP3 / 5s por clip
    import math as _math
    mp3s = sorted([f for f in carpeta.glob("*.mp3") if "_test" not in f.name and "_src" not in f.name])
    audio_dur = 0.0
    if mp3s:
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(mp3s[0])],
                capture_output=True, text=True, timeout=5
            )
            audio_dur = float(r.stdout.strip())
        except Exception:
            audio_dur = 0.0
    clips_needed = _math.ceil(audio_dur / 5) if audio_dur > 0 else 0
    # Total real de clips disponibles en la carpeta (todos, no solo los del preview)
    all_clips_count = len([f for f in clips_dir.glob("*.mp4")
                           if f.name not in deleted_yt
                           and f.name not in set(_m.get("removed_yt_cards", {}).keys())])

    return jsonify({
        "segments": segments,
        "total_clips": all_clips_count,
        "flow_count": len(flow_inserts),
        "recycled_count": recycled_count,
        "recycled_names": recycled_names,
        "clips_order_saved": bool(clips_order),
        "clips_needed": clips_needed,
        "audio_dur": round(audio_dur, 1),
    })


@app.route("/preview/<path:personaje>")
def render_preview_page(personaje):
    """Página: primeros 10 min del render intercalando clips YT y Flow images."""
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Preview Render (10 min) — {personaje}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: #0d0d0d; color: #eee; font-family: system-ui, sans-serif; padding: 20px; }}
h1 {{ font-size: 17px; margin-bottom: 4px; color: #fff; }}
.sub {{ color: #777; font-size: 12px; margin-bottom: 20px; }}
.legend {{ display: flex; gap: 16px; margin-bottom: 16px; font-size: 12px; }}
.leg {{ display: flex; align-items: center; gap: 6px; }}
.dot {{ width: 12px; height: 12px; border-radius: 3px; }}
.dot-yt {{ background: #1976d2; }}
.dot-flow {{ background: #7c3aed; }}
.timeline {{ display: flex; flex-direction: column; gap: 4px; }}
.seg {{ display: flex; align-items: stretch; border-radius: 6px; overflow: hidden; cursor: pointer; border: 2px solid transparent; transition: border-color .15s; }}
.seg:hover {{ border-color: #fff4; }}
.seg.yt {{ background: #0d2137; border-left: 4px solid #1976d2; }}
.seg.flow {{ background: #1a0d2e; border-left: 4px solid #7c3aed; }}
.seg.flow.missing {{ background: #2d1a00; border-left-color: #ff9800; opacity:.7; }}
.thumb {{ width: 120px; min-width: 120px; height: 68px; object-fit: cover; background: #222; }}
.info {{ padding: 6px 10px; flex: 1; display: flex; flex-direction: column; justify-content: center; gap: 3px; }}
.ts {{ font-size: 11px; color: #aaa; font-variant-numeric: tabular-nums; }}
.lbl {{ font-size: 12px; color: #ddd; line-height: 1.3; max-height: 2.6em; overflow: hidden; }}
.badge {{ font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 3px; align-self: flex-start; }}
.badge-yt {{ background: #1976d2; color: #fff; }}
.badge-flow {{ background: #7c3aed; color: #fff; }}
.badge-miss {{ background: #ff9800; color: #000; }}
.loading {{ color: #777; padding: 40px; text-align: center; }}
.header-actions {{ display: flex; gap: 10px; align-items: center; margin-bottom: 16px; }}
.btn {{ padding: 7px 14px; border: none; border-radius: 6px; cursor: pointer; font-size: 12px; font-weight: 600; }}
.btn-blue {{ background: #1565c0; color: #fff; }}
.btn-back {{ background: #333; color: #ccc; }}
.modal {{ display: none; position: fixed; inset: 0; background: #000a; z-index: 100; align-items: center; justify-content: center; }}
.modal.open {{ display: flex; }}
.modal-inner {{ background: #111; border-radius: 10px; padding: 12px; max-width: 90vw; }}
.modal-inner video {{ max-width: 80vw; max-height: 70vh; border-radius: 6px; }}
.modal-close {{ float: right; background: #333; border: none; color: #fff; padding: 4px 10px; border-radius: 4px; cursor: pointer; margin-bottom: 8px; }}
</style>
</head>
<body>
<h1>🎬 Preview de Render — Primeros 10 minutos</h1>
<p class="sub">{personaje} · Haz clic en cualquier segmento para ver el clip</p>

<div class="header-actions">
  <button class="btn btn-back" onclick="location.href='/aprobar/{personaje}'">← Volver al dashboard</button>
  <button class="btn btn-blue" onclick="loadTimeline()">↻ Recargar</button>
  <span id="meta" style="font-size:12px;color:#777;"></span>
</div>

<div class="legend">
  <div class="leg"><div class="dot dot-yt"></div> Clip YouTube</div>
  <div class="leg"><div class="dot dot-flow"></div> Imagen Flow (inserción exacta)</div>
</div>

<div class="timeline" id="tl"><div class="loading">Cargando timeline...</div></div>

<div class="modal" id="modal" onclick="closeModal()">
  <div class="modal-inner" onclick="event.stopPropagation()">
    <button class="modal-close" onclick="closeModal()">✕ Cerrar</button><br>
    <video id="modal-video" controls autoplay muted></video>
    <p id="modal-label" style="font-size:12px;color:#aaa;margin-top:6px;"></p>
  </div>
</div>

<script>
function fmt(s){{
  const m = Math.floor(s/60), sec = Math.round(s%60);
  return m + ':' + String(sec).padStart(2,'0');
}}

function openModal(url, label, dur){{
  // Añadir #t=0,dur para que el browser recorte el zoompan a la duración real del segmento
  const src = dur ? url + '#t=0,' + dur : url;
  document.getElementById('modal-video').src = src;
  document.getElementById('modal-label').textContent = label;
  document.getElementById('modal').classList.add('open');
}}
function closeModal(){{
  const v = document.getElementById('modal-video');
  v.pause(); v.src = '';
  document.getElementById('modal').classList.remove('open');
}}

async function loadTimeline(){{
  document.getElementById('tl').innerHTML = '<div class="loading">Cargando...</div>';
  const r = await fetch('/api/render_preview/{personaje}');
  const d = await r.json();
  const needed   = d.clips_needed  || 0;
  const total_yt = d.total_clips   || 0;
  _clipsNeeded   = needed;
  const okColor  = total_yt >= needed ? "#00ffaa" : "#ff6b6b";
  const pillHtml = needed > 0
    ? `<span data-counter="1" style="background:rgba(0,0,0,0.4);color:${{okColor}};font-weight:700;font-size:13px;
         padding:2px 10px;border-radius:12px;border:1px solid ${{okColor}};margin-left:8px">
         ${{total_yt}}/${{needed}}</span>`
    : "";
  document.getElementById('meta').innerHTML =
    `${{total_yt}} clips YT · ${{d.flow_count}} inserciones Flow${{pillHtml}}`;

  const tl = document.getElementById('tl');
  tl.innerHTML = '';
  for(const seg of d.segments){{
    const isFlow = seg.type === 'flow';
    const missing = isFlow && !seg.exists;
    const div = document.createElement('div');
    div.className = 'seg ' + (isFlow ? 'flow' : 'yt') + (missing ? ' missing' : '');
    div.onclick = () => openModal(seg.url, seg.label);

    const badge = isFlow
      ? (missing ? '<span class="badge badge-miss">⚠ FALTANTE</span>' : '<span class="badge badge-flow">FLOW</span>')
      : '<span class="badge badge-yt">YT CLIP</span>';

    div.innerHTML = `
      <img class="thumb" src="${{seg.url}}" onerror="this.style.background='#222';this.removeAttribute('src')">
      <div class="info">
        <div class="ts">${{fmt(seg.t_start)}} → ${{fmt(seg.t_end)}} &nbsp;(${{seg.duration}}s)</div>
        <div class="lbl">${{seg.label}}</div>
        ${{badge}}
      </div>`;
    tl.appendChild(div);
  }}
}}

loadTimeline();
</script>
</body>
</html>"""


@app.route("/mobile/<path:personaje>")
def mobile_page(personaje):
    """Página de aprobación optimizada para celular."""
    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>📱 {personaje.split('/')[-1].replace('_',' ').title()}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}}
  body{{background:#0d0d0d;color:#eee;font-family:system-ui,sans-serif;padding:10px;padding-bottom:90px}}
  h1{{font-size:16px;font-weight:700;color:#fff;margin-bottom:4px;text-transform:capitalize}}
  .sub{{color:#888;font-size:12px;margin-bottom:14px}}
  .stats{{display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap}}
  .stat{{background:#1a1a1a;border:1px solid #333;border-radius:8px;padding:8px 14px;font-size:12px;text-align:center}}
  .stat span{{font-size:18px;font-weight:bold;display:block}}
  .stat.ap span{{color:#4caf50}}.stat.pe span{{color:#ffc107}}.stat.re span{{color:#f44336}}
  /* Grid 2 columnas */
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}
  .card{{background:#1a1a1a;border:2px solid #333;border-radius:8px;overflow:hidden;position:relative;transition:border-color .2s}}
  .card.selected{{border-color:#00bcd4!important;box-shadow:0 0 0 2px #00bcd4}}
  .card.aprobado{{border-color:#4caf50}}.card.rechazado{{border-color:#f44336;opacity:.5}}
  .card-label{{position:absolute;top:0;left:0;font-size:9px;font-weight:700;padding:2px 5px;border-radius:0 0 4px 0;z-index:2;color:#fff}}
  video,img.thumb{{width:100%;height:90px;object-fit:cover;background:#111;display:block}}
  .card-body{{padding:6px}}
  .card-name{{font-size:9px;color:#888;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:4px}}
  .card-time{{font-size:10px;color:#9c9;font-weight:700;margin-bottom:5px}}
  .btn-reject{{width:100%;background:#7f1d1d;color:#fca5a5;border:none;border-radius:5px;padding:6px;font-size:12px;font-weight:700;cursor:pointer}}
  .btn-reject:active{{background:#991b1b}}
  /* Swap hint */
  .swap-hint{{background:#1a3a4a;border:1px solid #00bcd4;color:#7dd3fc;font-size:11px;text-align:center;padding:6px;border-radius:6px;margin-bottom:10px;display:none}}
  /* FAB aprobar */
  #fab{{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);background:#22c55e;color:#fff;border:none;border-radius:50px;padding:16px 40px;font-size:16px;font-weight:800;cursor:pointer;box-shadow:0 4px 20px rgba(0,0,0,.6);z-index:9999;width:90%;max-width:360px}}
  #fab:active{{background:#16a34a}}
  .toast{{position:fixed;top:14px;left:50%;transform:translateX(-50%);background:#1e293b;color:#fff;padding:8px 18px;border-radius:20px;font-size:13px;z-index:99999;opacity:0;transition:opacity .3s;pointer-events:none;white-space:nowrap}}
  .toast.show{{opacity:1}}
  .section-title{{font-size:11px;font-weight:700;color:#666;text-transform:uppercase;letter-spacing:.5px;margin:12px 0 6px}}
</style>
</head>
<body>
<h1>📱 {personaje.split('/')[-1].replace('_',' ').title()}</h1>
<div class="sub">{personaje}</div>
<div class="stats" id="stats"></div>
<div class="swap-hint" id="swap-hint">👆 Toca otra card para intercambiar posición</div>
<div id="grid-main" class="grid"></div>
<button id="fab" onclick="aprobarTodos()">✓ Aprobar todos y render</button>
<div class="toast" id="toast"></div>

<script>
const PERSONAJE = '{personaje}';
let _footage = {{}};
let _ytAll = [];        // todos los clips YT disponibles
let _ytGrid = [];       // orden actual en el grid
let _selectedCard = null; // {{el, name, idx}} para swap

function toast(msg, color) {{
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.background = color || '#1e293b';
  t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'), 2200);
}}

// ── Carga inicial ──────────────────────────────────────────
async function cargar() {{
  const [fRes, pRes, yRes] = await Promise.all([
    fetch(`/api/footage/${{PERSONAJE}}`),
    fetch(`/api/render_preview/${{PERSONAJE}}`),
    fetch(`/api/yt_clips/${{PERSONAJE}}`)
  ]);
  const fData = await fRes.json();
  const pData = await pRes.json();
  const yData = await yRes.json();

  _footage = fData.footage || {{}};
  const segments = pData.segments || [];
  _ytAll  = yData.clips || [];

  renderStats(fData.stats || {{}});
  renderGrid(segments);
}}

function renderStats(s) {{
  const el = document.getElementById('stats');
  el.innerHTML = `
    <div class="stat ap"><span>${{s.aprobado||0}}</span>aprobados</div>
    <div class="stat pe"><span>${{s.pendiente||0}}</span>pendientes</div>
    <div class="stat re"><span>${{s.rechazado||0}}</span>rechazados</div>
  `;
}}

// ── Render grid unificado (orden del render) ───────────────
function renderGrid(segments) {{
  const grid = document.getElementById('grid-main');
  grid.innerHTML = '';

  // Extraer orden YT para swap
  _ytGrid = segments.filter(s => s.type !== 'flow' && !s.clip?.startsWith('flow_')).map(s => s.clip);

  segments.forEach((seg, i) => {{
    const isFlow = seg.type === 'flow' || seg.clip?.startsWith('flow_');
    const num = i + 1;
    grid.appendChild(isFlow ? buildFlowCard(seg, num) : buildYTCard(seg, i, num));
  }});

  setTimeout(observeVideos, 100);
}}

// ── Media helper: poster estático, tap carga video ─────────
function buildMedia(posterUrl, videoUrl, eager) {{
  const wrap = document.createElement('div');
  wrap.className = 'media-wrap';
  wrap.style.cssText = 'position:relative;width:100%;height:90px;background:#111;overflow:hidden;cursor:pointer';
  const img = document.createElement('img');
  img.src = posterUrl;
  img.style.cssText = 'width:100%;height:90px;object-fit:cover;display:block';
  img.loading = 'eager';
  img.onerror = () => {{
    img.style.display = 'none';
    wrap.style.background = '#1a1a2e';
    const ph = document.createElement('div');
    ph.style.cssText = 'width:100%;height:90px;display:flex;align-items:center;justify-content:center;color:#444;font-size:11px';
    ph.textContent = '🎬 sin preview';
    wrap.insertBefore(ph, icon);
  }};
  const icon = document.createElement('div');
  icon.textContent = '▶';
  icon.style.cssText = 'position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);color:#fff;font-size:22px;text-shadow:0 0 8px #000;pointer-events:none';
  wrap.appendChild(img); wrap.appendChild(icon);
  wrap.addEventListener('click', e => {{
    e.stopPropagation();
    const vid = wrap.querySelector('video');
    if (vid) {{ vid.paused ? vid.play() : vid.pause(); return; }}
    img.remove(); icon.remove();
    const v = document.createElement('video');
    v.src = videoUrl; v.muted = true; v.loop = true;
    v.setAttribute('playsinline', ''); v.autoplay = true;
    v.style.cssText = 'width:100%;height:90px;object-fit:cover;display:block';
    wrap.appendChild(v);
    v.play().catch(()=>{{}});
  }});
  return wrap;
}}

// ── Flow card ──────────────────────────────────────────────
function buildFlowCard(seg, num) {{
  const clip   = seg.clip || '';
  const estado = (_footage[clip]?.estado) || 'pendiente';
  const div    = document.createElement('div');
  div.className = `card ${{estado}}`;
  div.id = `fc-${{clip}}`;
  div.innerHTML = `<div class="card-label" style="background:#7c3aed">#${{num}} FLOW</div>`;
  div.appendChild(buildMedia(`/flow_poster/${{PERSONAJE}}/${{clip}}`, `/footage/${{PERSONAJE}}/${{clip}}?t=${{Date.now()}}`));
  const body = document.createElement('div');
  body.className = 'card-body';
  body.innerHTML = `
    <div class="card-name">${{clip}}</div>
    <div class="card-time">⏱ ${{fmtT(seg.t_start)}}→${{fmtT(seg.t_start+seg.duration)}}</div>
    <div style="color:#555;font-size:10px;text-align:center;padding:2px 0">🔒 Flow — no editable</div>`;
  div.appendChild(body);
  return div;
}}

// ── YT card ────────────────────────────────────────────────
function buildYTCard(seg, i, num) {{
  const name = seg.clip || '';
  const div  = document.createElement('div');
  div.className = 'card';
  div.id = `yc-${{name}}`;
  div.dataset.idx  = i;
  div.dataset.name = name;
  div.innerHTML = `<div class="card-label" style="background:#ff6b35">#${{num}} YT</div>`;
  div.appendChild(buildMedia(`/yt_poster/${{PERSONAJE}}/${{name}}`, `/yt_clip/${{PERSONAJE}}/${{name}}?t=${{Date.now()}}`));
  const body = document.createElement('div');
  body.className = 'card-body';
  body.innerHTML = `
    <div class="card-name">${{name}}</div>
    <div class="card-time">⏱ ${{fmtT(seg.t_start)}}→${{fmtT(seg.t_start+seg.duration)}}</div>
    <div style="display:flex;gap:4px;margin-top:2px">
      <button class="btn-reject" style="flex:1" onclick="rechazarYT('${{name}}', ${{i}}, ${{num}})">✗</button>
      <button class="btn-move" style="flex:1;background:#1a3a4a;color:#7dd3fc;border:none;border-radius:5px;padding:6px;font-size:14px;cursor:pointer" onclick="seleccionarParaSwap(document.getElementById('yc-${{name}}'),'${{name}}',${{i}})">↕</button>
    </div>`;
  div.appendChild(body);
  return div;
}}

// ── Swap por tap ───────────────────────────────────────────
function seleccionarParaSwap(el, name, idx) {{
  const hint = document.getElementById('swap-hint');
  if (_selectedCard && _selectedCard.name !== name) {{
    // Intercambiar posiciones
    const a = _selectedCard;
    const b = {{el, name, idx}};
    _swapDOM(a.el, b.el);
    // Actualizar orden en memoria
    const oi = _ytGrid.indexOf(a.name);
    const oj = _ytGrid.indexOf(b.name);
    if (oi >= 0 && oj >= 0) {{ [_ytGrid[oi], _ytGrid[oj]] = [_ytGrid[oj], _ytGrid[oi]]; }}
    // Guardar orden en servidor
    fetch(`/api/riq/save_order/${{PERSONAJE}}`, {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{order: _ytGrid, force: true}})
    }});
    toast('↕ Posiciones intercambiadas', '#0e7490');
    _selectedCard = null;
    hint.style.display = 'none';
    document.querySelectorAll('.card.selected').forEach(c => c.classList.remove('selected'));
  }} else {{
    // Primera selección
    document.querySelectorAll('.card.selected').forEach(c => c.classList.remove('selected'));
    _selectedCard = {{el, name, idx}};
    el.classList.add('selected');
    hint.style.display = '';
  }}
}}

function _swapDOM(a, b) {{
  // Intercambiar contenido visual: poster/video + nombre + botones
  // (más confiable en mobile que mover nodos)
  const aWrap = a.querySelector('.media-wrap');
  const bWrap = b.querySelector('.media-wrap');
  const aName = a.querySelector('.card-name');
  const bName = b.querySelector('.card-name');
  const aTime = a.querySelector('.card-time');
  const bTime = b.querySelector('.card-time');

  // Clonar wraps para intercambiar
  const aWrapClone = aWrap.cloneNode(true);
  const bWrapClone = bWrap.cloneNode(true);
  aWrap.replaceWith(bWrapClone);
  bWrap.replaceWith(aWrapClone);

  // Volver a conectar eventos de tap-to-play en los nuevos wraps
  [aWrapClone, bWrapClone].forEach(wrap => {{
    wrap.addEventListener('click', e => {{
      e.stopPropagation();
      const vid = wrap.querySelector('video');
      if (vid) {{ vid.paused ? vid.play() : vid.pause(); return; }}
      const img = wrap.querySelector('img');
      const src = img ? img.src.replace('/yt_poster/', '/yt_clip/').replace('/flow_poster/', '/footage/') + '?t=' + Date.now() : '';
      if (img) img.remove();
      const icon = wrap.querySelector('div');
      if (icon) icon.remove();
      const v = document.createElement('video');
      v.src = src; v.muted = true; v.loop = true;
      v.setAttribute('playsinline',''); v.autoplay = true;
      v.style.cssText = 'width:100%;height:90px;object-fit:cover;display:block';
      wrap.appendChild(v); v.play().catch(()=>{{}});
    }});
  }});

  // Intercambiar texto nombre y tiempo
  const tmpName = aName.textContent;
  const tmpTime = aTime.innerHTML;
  aName.textContent = bName.textContent;
  aTime.innerHTML   = bTime.innerHTML;
  bName.textContent = tmpName;
  bTime.innerHTML   = tmpTime;

  // Intercambiar IDs, data-name y botones
  const aId   = a.id; const bId   = b.id;
  const aData = a.dataset.name; const bData = b.dataset.name;
  a.id = bId; a.dataset.name = bData;
  b.id = aId; b.dataset.name = aData;

  // Actualizar onclick de botones con los nuevos nombres
  const aBtns = a.querySelectorAll('button');
  const bBtns = b.querySelectorAll('button');
  aBtns.forEach(btn => {{
    const oc = btn.getAttribute('onclick') || '';
    if (oc.includes('rechazarYT'))    btn.setAttribute('onclick', oc.replace(/rechazarYT\('[^']*'/, `rechazarYT('${{bData}}'`));
    if (oc.includes('seleccionarPara')) btn.setAttribute('onclick', oc.replace(/getElementById\('[^']*'\),'[^']*'/, `getElementById('${{bId}}'),'${{bData}}'`));
  }});
  bBtns.forEach(btn => {{
    const oc = btn.getAttribute('onclick') || '';
    if (oc.includes('rechazarYT'))    btn.setAttribute('onclick', oc.replace(/rechazarYT\('[^']*'/, `rechazarYT('${{aData}}'`));
    if (oc.includes('seleccionarPara')) btn.setAttribute('onclick', oc.replace(/getElementById\('[^']*'\),'[^']*'/, `getElementById('${{aId}}'),'${{aData}}'`));
  }});
}}

// ── Rechazar YT ────────────────────────────────────────────
function rechazarYT(name, idx, num) {{
  const cardEl = document.getElementById(`yc-${{name}}`);
  if (!cardEl) return;

  // _ytAll es array de objetos {{name, estado, ...}} — extraer nombres
  const enGrid = new Set(_ytGrid);
  const pool   = _ytAll.filter(c => c.name !== name && c.estado !== 'rechazado' && !enGrid.has(c.name));
  const nuevo  = pool.length ? pool[Math.floor(Math.random()*pool.length)] : null;

  // Marcar rechazado en servidor
  fetch(`/api/riq/delete_yt_clip/${{PERSONAJE}}`, {{
    method:'POST', headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{clip: name}})
  }});
  // Marcar en memoria
  const ri = (_ytAll||[]).findIndex(c => c.name === name);
  if (ri >= 0) _ytAll[ri].estado = 'rechazado';

  if (nuevo) {{
    const nuevoNombre = nuevo.name;
    // Actualizar _ytGrid
    const gi = _ytGrid.indexOf(name);
    if (gi >= 0) _ytGrid[gi] = nuevoNombre;

    // Reemplazar el media wrap (poster + video)
    const oldWrap = cardEl.querySelector('.media-wrap');
    const newWrap = buildMedia(
      `/yt_poster/${{PERSONAJE}}/${{nuevoNombre}}`,
      `/yt_clip/${{PERSONAJE}}/${{nuevoNombre}}?t=${{Date.now()}}`,
      true
    );
    if (oldWrap) oldWrap.replaceWith(newWrap);

    // Actualizar metadatos de la card
    cardEl.id = `yc-${{nuevoNombre}}`;
    cardEl.dataset.name = nuevoNombre;
    cardEl.querySelector('.card-name').textContent = nuevoNombre;
    cardEl.querySelector('.btn-reject').setAttribute('onclick', `rechazarYT('${{nuevoNombre}}',${{idx}},${{num}})`);

    // Guardar orden
    fetch(`/api/riq/save_order/${{PERSONAJE}}`, {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{order: _ytGrid, force: true}})
    }});
    toast(`#${{num}} → ${{nuevoNombre}}`, '#166634');
  }} else {{
    cardEl.style.opacity = '.4';
    toast('⚠ Sin clips disponibles', '#b45309');
  }}
}}

// ── Rechazar Flow ──────────────────────────────────────────
function rechazarFlow(clip, num) {{
  fetch('/api/flow_replace_with_yt', {{
    method:'POST', headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{personaje: PERSONAJE, clip}})
  }}).then(r=>r.json()).then(d=>{{
    if (d.ok) toast(`#${{num}} reemplazado con YT`, '#166634');
    else toast('Error al rechazar', '#991b1b');
    cargar();
  }});
}}

// ── Aprobar todos y lanzar render ─────────────────────────
async function aprobarTodos() {{
  const btn = document.getElementById('fab');
  btn.disabled = true;
  btn.textContent = '⏳ Aprobando...';
  try {{
    // 1. Aprobar todos los clips — enviar orden actual del grid
    await fetch(`/api/footage_approve_all/${{PERSONAJE}}`, {{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{clips_order: _ytGrid}})
    }});
    btn.textContent = '⏳ Lanzando render...';
    toast('✓ Aprobado — lanzando render...', '#166634');
    // 2. Lanzar render en background
    const rr = await fetch(`/api/render_launch/${{PERSONAJE}}`, {{method:'POST'}});
    const rd = await rr.json();
    if (rd.ok) {{
      toast(`🎬 Render iniciado (PID ${{rd.pid}})`, '#166634', 5000);
      btn.textContent = '🎬 Render en progreso...';
      // Polling cada 10s para saber si terminó
      const poll = setInterval(async () => {{
        const s = await fetch(`/api/render_launch_status/${{PERSONAJE}}`).then(r=>r.json());
        if (!s.running) {{
          clearInterval(poll);
          if (s.returncode === 0) {{
            toast('✅ Render completado', '#166634', 6000);
            btn.textContent = '✅ Render listo';
          }} else {{
            toast(`⚠ Render terminó con código ${{s.returncode}}`, '#991b1b', 8000);
            btn.textContent = '⚠ Render con error';
            btn.disabled = false;
          }}
        }}
      }}, 10000);
    }} else {{
      toast(`Error render: ${{rd.error || 'desconocido'}}`, '#991b1b');
      btn.textContent = '✓ Aprobar todos y render';
      btn.disabled = false;
    }}
  }} catch(e) {{
    toast('Error al aprobar/render', '#991b1b');
    btn.disabled = false;
    btn.textContent = '✓ Aprobar todos y render';
  }}
}}

// ── Lazy load videos ───────────────────────────────────────
const _obs = new IntersectionObserver(entries => {{
  entries.forEach(e => {{
    if (!e.isIntersecting) return;
    const v = e.target;
    const src = v.getAttribute('data-src');
    if (src && !v.getAttribute('src')) {{
      v.setAttribute('src', src);
      v.load();
    }}
    _obs.unobserve(v);
  }});
}}, {{rootMargin: '300px', threshold: 0}});

function observeVideos() {{
  document.querySelectorAll('video.lazy-video').forEach(v => {{
    if (!v._mobObs) {{ v._mobObs = true; _obs.observe(v); }}
  }});
}}

function fmtT(s) {{
  if (!s && s!==0) return '?';
  const m=Math.floor(s/60),sec=Math.floor(s%60);
  return `${{m}}:${{String(sec).padStart(2,'0')}}`;
}}

cargar();
</script>
</body>
</html>"""
    return make_response(html, 200)


@app.route("/aprobar/<path:personaje>")
def footage_page(personaje):
    """Página de aprobación visual de footage."""
    ua = request.headers.get("User-Agent", "")
    if any(x in ua for x in ("iPhone", "Android", "Mobile", "iPad")):
        from flask import redirect
        return redirect(f"/mobile/{personaje}/")
    parts = personaje.split("/")
    siblings_html = ""
    _tl_path = BASE_DIR / personaje / "05-montaje" / "timeline.json"
    timeline_exists = "true" if _tl_path.exists() else "false"
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Aprobar Footage — {personaje}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0d0d0d; color: #eee; font-family: system-ui, sans-serif; padding: 24px; }}
  h1 {{ font-size: 18px; margin-bottom: 6px; color: #fff; }}
  .sub {{ color: #888; font-size: 13px; margin-bottom: 20px; }}
  .stats {{ display: flex; gap: 12px; margin-bottom: 24px; flex-wrap: wrap; }}
  .stat {{ background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 10px 18px; font-size: 13px; }}
  .stat span {{ font-size: 20px; font-weight: bold; display: block; }}
  .stat.ap span {{ color: #4caf50; }}
  .stat.pe span {{ color: #ffc107; }}
  .stat.re span {{ color: #f44336; }}
  .actions-top {{ display: flex; gap: 10px; margin-bottom: 20px; }}
  #fab-aprobar {{ position:fixed; bottom:28px; right:28px; z-index:9999; background:#22c55e; color:#fff; border:none; border-radius:50px; padding:14px 24px; font-size:15px; font-weight:700; cursor:pointer; box-shadow:0 4px 18px rgba(0,0,0,0.5); display:none; align-items:center; gap:8px; }}
  #fab-aprobar:hover {{ background:#16a34a; }}
  .btn {{ padding: 8px 16px; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 600; }}
  .btn-green  {{ background: #2e7d32; color: #fff; }}
  .btn-green:hover {{ background: #388e3c; }}
  .btn-gray   {{ background: #333; color: #ccc; }}
  .btn-gray:hover {{ background: #444; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }}
  @media (max-width: 600px) {{
    .grid {{ grid-template-columns: repeat(2, 1fr) !important; gap: 8px; }}
    video {{ height: 100px !important; }}
    .card-body {{ padding: 6px; }}
    .card-desc-es {{ display: none; }}
    textarea {{ display: none; }}
  }}
  .card {{ background: #1a1a1a; border: 2px solid #333; border-radius: 10px; overflow: hidden; position: relative; }}
  .card.aprobado {{ border-color: #4caf50; }}
  .card.rechazado {{ border-color: #f44336; opacity: 0.5; }}
  .card.error {{ border-color: #ff9800; opacity: 0.6; }}
  .card.drag-over {{ outline: 2px dashed #4ecdc4; opacity: 0.85; }}
  video {{ width: 100%; height: 158px; object-fit: cover; background: #000; display: block; }}
  .card-body {{ padding: 10px; }}
  .card-id {{ font-size: 11px; color: #666; margin-bottom: 4px; display:flex; align-items:center; gap:8px; }}
  .card-dur {{ background:#1e2a1e; color:#66bb6a; font-size:11px; font-weight:700; padding:1px 7px; border-radius:4px; border:1px solid #2e4a2e; }}
  .card-desc-es {{ font-size: 13px; color: #fff; font-weight:600; margin-bottom: 5px; line-height: 1.4; }}
  .card-desc {{ font-size: 11px; color: #666; margin-bottom: 8px; line-height: 1.4; font-style:italic; }}
  .card-fuente {{ font-size: 11px; color: #888; margin-bottom: 8px; }}
  .fuente-ia {{ color: #9c27b0; }} .fuente-pexels {{ color: #2196f3; }} .fuente-pixabay {{ color: #4caf50; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }}
  .badge-pendiente {{ background: #3a2f00; color: #ffc107; }}
  .badge-aprobado  {{ background: #1b3d1b; color: #4caf50; }}
  .badge-rechazado {{ background: #3d1b1b; color: #f44336; }}
  .badge-error     {{ background: #3d2500; color: #ff9800; }}
  .card-btns {{ display: flex; gap: 6px; margin-top: 8px; }}
  .btn-ap {{ background: #2e7d32; color: #fff; flex: 1; font-size: 12px; padding: 6px; border-radius: 5px; border: none; cursor: pointer; }}
  .btn-re {{ background: #7f1d1d; color: #fff; flex: 1; font-size: 12px; padding: 6px; border-radius: 5px; border: none; cursor: pointer; }}
  .btn-eliminar {{ background: #1a1a2e; color: #888; font-size: 14px; padding: 6px 8px; border-radius: 5px; border: 1px solid #333; cursor: pointer; flex-shrink: 0; }}
  .btn-eliminar:hover {{ background: #2a0a0a; color: #f87171; border-color: #7f1d1d; }}
  .btn-ap:hover {{ background: #388e3c; }} .btn-re:hover {{ background: #b91c1c; }}
  #toast {{ position: fixed; bottom: 24px; right: 24px; background: #333; color: #fff; padding: 10px 18px; border-radius: 8px; font-size: 13px; opacity: 0; transition: opacity 0.3s; pointer-events: none; }}
  #toast.show {{ opacity: 1; }}
  .render-block {{ background: #3d1b00; border: 1px solid #f44336; border-radius: 8px; padding: 12px 16px; margin-bottom: 20px; font-size: 13px; color: #ff9800; display: none; }}
  .render-ok {{ background: #1b3d1b; border-color: #4caf50; color: #4caf50; }}
</style>
</head>
<body>
{siblings_html}
<h1>Aprobación de Footage — {personaje}</h1>
<p class="sub">Aprobá cada imagen antes de renderizar. El render se bloquea si hay pendientes.</p>

<!-- Audio player del guion -->
<div id="audio-player-wrap" style="background:#111;border:1px solid #2a2a2a;border-radius:10px;padding:14px 18px;margin-bottom:18px;display:flex;align-items:center;gap:14px;flex-wrap:wrap">
  <span style="font-size:12px;color:#888;white-space:nowrap;font-weight:600">🎙 GUION</span>
  <audio id="guion-audio" controls preload="metadata" style="flex:1;min-width:260px;height:36px;accent-color:#9c27b0;"
    src="/audio/{personaje}/guion">
    Tu browser no soporta audio.
  </audio>
  <div style="display:flex;align-items:center;gap:8px;white-space:nowrap">
    <span style="font-size:11px;color:#555">Tiempo:</span>
    <span id="audio-time" style="font-size:13px;font-weight:700;color:#9c27b0;font-family:monospace;min-width:80px">0:00 / --:--</span>
  </div>
</div>

<div id="progress-bar-wrap" style="display:none;background:#1a1a1a;border:1px solid #333;border-radius:8px;padding:12px 16px;margin-bottom:16px"></div>

<div id="render-status" class="render-block"></div>

<div class="stats" id="stats"></div>

<button id="fab-aprobar" onclick="aprobarTodos()">✓ Aprobar todos</button>

<div class="actions-top" id="actions-top-header" style="flex-wrap:wrap;align-items:center">
  <button class="btn btn-green" onclick="aprobarTodos()">✓ Aprobar todos</button>
  <button class="btn btn-gray" onclick="location.reload()">↻ Actualizar</button>
  <button class="btn btn-gray" onclick="location.href='/'">← Dashboard</button>
  <button class="btn" style="background:#1a1a3a;color:#4ecdc4;border:1px solid #4ecdc4" onclick="abrirModalAgregar()">＋ Agregar clips</button>
  <span id="clips-counter-pill" style="margin-left:auto;background:rgba(0,0,0,0.4);padding:4px 14px;border-radius:20px;font-size:13px;font-weight:700;border:1px solid #333"></span>
</div>

<!-- Banner déficit de clips -->
<div id="deficit-banner" style="display:none;margin:8px 0 4px;padding:12px 16px;border-radius:10px;font-size:13px;font-weight:600;line-height:1.5"></div>

<!-- Modal preview clip -->
<div id="modal-preview" onclick="cerrarPreview()" style="display:none;position:fixed;inset:0;background:#000d;z-index:300;align-items:center;justify-content:center">
  <div onclick="event.stopPropagation()" style="position:relative;width:min(900px,94vw);background:#0a0a0a;border:1px solid #444;border-radius:12px;overflow:hidden;box-shadow:0 0 60px #000">
    <button onclick="cerrarPreview()" style="position:absolute;top:10px;right:12px;z-index:10;background:#222;border:1px solid #555;color:#fff;border-radius:6px;padding:4px 12px;cursor:pointer;font-size:14px">✕</button>
    <div id="preview-label" style="position:absolute;top:10px;left:12px;z-index:10;background:#0009;color:#fff;font-size:12px;padding:3px 10px;border-radius:5px;font-family:monospace"></div>
    <video id="preview-video" controls autoplay style="width:100%;height:auto !important;max-height:72vh;object-fit:contain !important;display:block;background:#000"></video>
    <!-- Trimmer -->
    <div id="trim-bar-wrap" style="padding:10px 14px 14px;background:#111;border-top:1px solid #222">
      <div id="trim-bar" style="position:relative;height:28px;background:#1a2035;border-radius:6px;cursor:pointer;user-select:none;margin-bottom:8px">
        <!-- zona activa -->
        <div id="trim-zone" style="position:absolute;top:0;bottom:0;left:0;right:0;background:#f5b93366;border-radius:6px;pointer-events:none"></div>
        <!-- handle start -->
        <div id="trim-handle-start" style="position:absolute;top:0;bottom:0;left:0;width:14px;background:#f5b933;border-radius:6px 0 0 6px;cursor:ew-resize;z-index:2"></div>
        <!-- handle end -->
        <div id="trim-handle-end" style="position:absolute;top:0;bottom:0;right:0;width:14px;background:#f5b933;border-radius:0 6px 6px 0;cursor:ew-resize;z-index:2"></div>
        <!-- playhead -->
        <div id="trim-playhead" style="position:absolute;top:0;bottom:0;width:2px;background:#fff8;pointer-events:none;z-index:3"></div>
      </div>
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
        <span id="trim-info" style="font-family:monospace;font-size:11px;color:#aaa;flex:1">▶ 0.0s &nbsp;|&nbsp; ✂ 0.0s → 0.0s &nbsp;(0.0s)</span>
        <button id="trim-save-btn" onclick="trimSave()" style="background:#f5b933;color:#000;border:none;border-radius:6px;padding:5px 14px;cursor:pointer;font-size:12px;font-weight:700">✂ Recortar y guardar</button>
        <button onclick="trimPreview()" style="background:#1b5e20;color:#fff;border:none;border-radius:6px;padding:5px 14px;cursor:pointer;font-size:12px">▶ Ver recorte</button>
        <button onclick="trimReset()" style="background:#333;color:#fff;border:none;border-radius:6px;padding:5px 10px;cursor:pointer;font-size:12px">↺ Reset</button>
      </div>
    </div>
  </div>
</div>

<!-- Modal agregar clips -->
<div id="modal-agregar" style="display:none;position:fixed;inset:0;background:#000a;z-index:200;align-items:center;justify-content:center">
  <div style="background:#111;border:1px solid #333;border-radius:12px;padding:0;width:min(700px,96vw);max-height:90vh;overflow:hidden;display:flex;flex-direction:column">
    <div style="display:flex;align-items:center;padding:14px 20px;border-bottom:1px solid #333;gap:10px">
      <span style="font-size:14px;font-weight:700;color:#fff;flex:1">＋ Agregar clips</span>
      <button onclick="cerrarModalAgregar()" style="background:#333;border:none;color:#fff;padding:4px 12px;border-radius:5px;cursor:pointer">✕</button>
    </div>
    <!-- Tabs -->
    <div style="display:flex;border-bottom:1px solid #333">
      <button class="ag-tab active" data-tab="img" onclick="switchTab('img')">🖼 Imágenes</button>
      <button class="ag-tab" data-tab="vid" onclick="switchTab('vid')">🎬 Videos stock</button>
      <button class="ag-tab" data-tab="yt" onclick="switchTab('yt')">▶ YouTube</button>
      <button class="ag-tab" data-tab="up" onclick="switchTab('up')">⬆ Subir</button>
    </div>
    <!-- Contenido tabs -->
    <div style="overflow-y:auto;flex:1;padding:16px">
      <!-- Tab imágenes -->
      <div id="tab-img" class="ag-tabcontent">
        <div style="display:flex;gap:8px;margin-bottom:10px">
          <input id="img-query" placeholder="Buscar imágenes…" style="flex:1;background:#1a1a1a;color:#eee;border:1px solid #444;border-radius:6px;padding:7px 10px;font-size:12px">
          <select id="img-source" style="background:#1a1a1a;color:#eee;border:1px solid #444;border-radius:6px;padding:7px 10px;font-size:12px">
            <option value="brave">Brave</option>
            <option value="pexels">Pexels</option>
            <option value="pixabay">Pixabay</option>
            <option value="photos">Pexels+Pixabay</option>
          </select>
          <button onclick="buscarImagenes()" style="background:#1565c0;color:#fff;border:none;border-radius:6px;padding:7px 14px;cursor:pointer;font-size:12px">Buscar</button>
        </div>
        <div id="img-results" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:6px;min-height:80px"></div>
        <div id="img-selected-count" style="font-size:11px;color:#aaa;margin-top:8px"></div>
        <button id="img-add-btn" onclick="agregarSeleccionadas('imagen')" style="display:none;margin-top:8px;background:#2e7d32;color:#fff;border:none;border-radius:6px;padding:8px 16px;cursor:pointer;font-size:12px">Agregar seleccionadas</button>
      </div>
      <!-- Tab videos stock -->
      <div id="tab-vid" class="ag-tabcontent" style="display:none">
        <div style="display:flex;gap:8px;margin-bottom:10px">
          <input id="vid-query" placeholder="Buscar videos…" style="flex:1;background:#1a1a1a;color:#eee;border:1px solid #444;border-radius:6px;padding:7px 10px;font-size:12px">
          <button onclick="buscarVideosStock()" style="background:#1565c0;color:#fff;border:none;border-radius:6px;padding:7px 14px;cursor:pointer;font-size:12px">Buscar</button>
        </div>
        <div id="vid-results" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:6px;min-height:80px"></div>
        <div id="vid-selected-count" style="font-size:11px;color:#aaa;margin-top:8px"></div>
        <button id="vid-add-btn" onclick="agregarSeleccionadas('video')" style="display:none;margin-top:8px;background:#2e7d32;color:#fff;border:none;border-radius:6px;padding:8px 16px;cursor:pointer;font-size:12px">Agregar seleccionados</button>
      </div>
      <!-- Tab YouTube -->
      <div id="tab-yt" class="ag-tabcontent" style="display:none">
        <div style="margin-bottom:12px">
          <div style="font-size:11px;color:#aaa;margin-bottom:6px">Pegar URL de YouTube</div>
          <div style="display:flex;gap:8px">
            <input id="yt-url" placeholder="https://youtube.com/watch?v=…" style="flex:1;background:#1a1a1a;color:#eee;border:1px solid #444;border-radius:6px;padding:7px 10px;font-size:12px">
            <input id="yt-url-nclips" type="number" value="20" min="5" max="60" style="width:60px;background:#1a1a1a;color:#eee;border:1px solid #444;border-radius:6px;padding:7px 8px;font-size:12px">
            <button onclick="agregarYouTubeURL()" style="background:#c62828;color:#fff;border:none;border-radius:6px;padding:7px 14px;cursor:pointer;font-size:12px">Extraer clips</button>
          </div>
        </div>
        <hr style="border-color:#333;margin:12px 0">
        <div style="font-size:11px;color:#aaa;margin-bottom:6px">Buscar en YouTube</div>
        <div style="display:flex;gap:8px;margin-bottom:10px">
          <input id="yt-query" placeholder="Buscar en YouTube…" style="flex:1;background:#1a1a1a;color:#eee;border:1px solid #444;border-radius:6px;padding:7px 10px;font-size:12px">
          <button onclick="buscarYouTube()" style="background:#1565c0;color:#fff;border:none;border-radius:6px;padding:7px 14px;cursor:pointer;font-size:12px">Buscar</button>
        </div>
        <div id="yt-results" style="display:flex;flex-direction:column;gap:8px;min-height:80px"></div>
      </div>
      <!-- Tab subir -->
      <div id="tab-up" class="ag-tabcontent" style="display:none">
        <div id="drop-zone"
             style="border:3px dashed #4ecdc4;border-radius:12px;padding:60px 20px;text-align:center;color:#4ecdc4;cursor:pointer;font-size:16px;font-weight:700;background:#0a2020;transition:background .2s"
             onclick="document.getElementById('file-input').click()">
          ⬆ Arrastrá fotos o videos aquí
          <div style="font-size:12px;color:#888;font-weight:400;margin-top:8px">JPG · PNG · WEBP · MP4 — o hacé click para elegir</div>
        </div>
        <input id="file-input" type="file" multiple accept=".mp4,.jpg,.jpeg,.png,.webp" style="display:none" onchange="handleFileInput(this.files)">
        <div id="upload-list" style="font-size:12px;color:#aaa;margin-top:8px"></div>
      </div>
    </div>
    <!-- Job progress -->
    <div id="ag-job-bar" style="display:none;padding:10px 16px;background:#0d1a0d;border-top:1px solid #2e4a2e;font-size:12px;color:#4caf50"></div>
  </div>
</div>

<style>
.ag-tab {{ background:none;border:none;color:#888;padding:10px 16px;cursor:pointer;font-size:12px;border-bottom:2px solid transparent;transition:color .15s,border-color .15s }}
.ag-tab:hover {{ color:#fff }}
.ag-tab.active {{ color:#4ecdc4;border-bottom-color:#4ecdc4 }}
.ag-thumb {{ width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:5px;cursor:pointer;border:2px solid transparent;transition:border-color .15s }}
.ag-thumb.sel {{ border-color:#4caf50 }}
.ag-thumb-wrap {{ position:relative }}
.ag-check {{ position:absolute;top:4px;right:4px;width:18px;height:18px;border-radius:50%;background:#4caf50;color:#fff;font-size:10px;display:none;align-items:center;justify-content:center;pointer-events:none }}
.ag-thumb-wrap.sel .ag-check {{ display:flex }}
</style>

<div id="toast"></div>
<!-- Barra de progreso global para uploads/jobs (fuera del modal) -->
<div id="global-job-bar" style="display:none;position:fixed;bottom:64px;right:24px;z-index:300;background:#0d2a0d;border:1px solid #2e7d32;border-radius:8px;padding:10px 16px;font-size:12px;color:#4caf50;max-width:380px;box-shadow:0 4px 20px #000a"></div>

<!-- ── Timeline unificado: Flow + YT en orden de render ── -->
<div style="margin-top:4px">
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #333">
    <span style="font-size:12px;color:#888">
      <span style="color:#ce93d8">■</span> Flow (imagen IA)&nbsp;&nbsp;
      <span style="color:#ff6b35">■</span> Clip YouTube
    </span>
    <span id="unified-count" style="font-size:12px;color:#666;margin-left:auto"></span>
  </div>
  <div id="unified-timeline" class="grid"></div>
  <div id="unified-loading" style="text-align:center;color:#666;padding:32px;font-size:13px">Cargando timeline…</div>
</div>

<script>
const PERSONAJE = "{personaje}";
const TIMELINE_EXISTS = {timeline_exists};

function toast(msg, color, ms) {{
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.style.background = color || "#333";
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), ms || 2500);
}}

function fuenteColor(f) {{
  if (f === "ia") return "fuente-ia";
  if (f === "pexels") return "fuente-pexels";
  if (f === "pixabay") return "fuente-pixabay";
  return "";
}}

const COSTO_FUENTE = {{ia: 0.003, pexels: 0, pixabay: 0, brave: 0}};

function _recycledBadgeHtml(recycledCount, recycledNames) {{
  if (recycledCount === 0) {{
    return `<div class="stat" style="border-color:#555"><span style="color:#888">0</span>Clips reciclados</div>`;
  }}
  const names = (recycledNames || []).slice(0, 8);
  const tooltip = names.map(n => `♻ ${{n}}`).join("\\n") + (recycledNames.length > 8 ? `\\n…+${{recycledNames.length-8}} más` : "");
  return `<div class="stat" style="border-color:#ff9800;cursor:pointer;position:relative" title="${{tooltip}}"
               onclick="toggleRecycledList()">
    <span style="color:#ffb74d">${{recycledCount}}</span>
    ♻ Reciclados
    <div id="recycled-list" style="display:none;position:absolute;top:100%;left:0;z-index:50;background:#1a1a1a;border:1px solid #ff9800;border-radius:6px;padding:8px 10px;min-width:220px;max-height:200px;overflow-y:auto;font-size:11px;color:#ffb74d;text-align:left;white-space:nowrap;box-shadow:0 4px 16px #000a;margin-top:4px">
      <div style="color:#fff;font-weight:700;margin-bottom:6px;font-size:12px">♻ Clips al final del video (anti-fingerprint)</div>
      ${{(recycledNames||[]).map(n=>`<div style="padding:2px 0;border-bottom:1px solid #333">${{n}}</div>`).join("")}}
    </div>
  </div>`;
}}
function toggleRecycledList() {{
  const el = document.getElementById("recycled-list");
  if (el) el.style.display = el.style.display === "none" ? "block" : "none";
}}

function renderStats(stats, recycledCount, recycledNames) {{
  recycledCount = recycledCount ?? 0;
  recycledNames = recycledNames || [];
  if (!stats || typeof stats !== 'object') return;
  const s = document.getElementById("stats");
  const costo = (stats.costo_total || 0).toFixed(3);
  const gen   = stats.generadas  ?? stats.total ?? 0;
  const total = stats.total_esperado ?? stats.total ?? 0;
  // Si todo es 0/undefined (riqueza sin metadata.json) ocultamos los stats de imágenes IA
  if (!gen && !total && !(stats.aprobado || stats.pendiente || stats.rechazado)) {{
    if (s) s.innerHTML = `<div id="stat-recycled-badge">${{_recycledBadgeHtml(recycledCount, recycledNames)}}</div>`;
    const pb = document.getElementById("progress-bar-wrap");
    if (pb) pb.style.display = "none";
    const rs = document.getElementById("render-status");
    if (rs) rs.style.display = "none";
    return;
  }}
  const pct   = total > 0 ? Math.round(gen / total * 100) : 100;
  const enCurso = gen < total;
  s.innerHTML = `
    <div class="stat"><span>${{stats.total}}</span>Generadas</div>
    <div class="stat ap"><span>${{stats.aprobado}}</span>Aprobadas</div>
    <div class="stat pe"><span>${{stats.pendiente}}</span>Pendientes</div>
    <div class="stat re"><span>${{stats.rechazado}}</span>Rechazadas</div>
    <div class="stat" style="border-color:#9c27b0"><span style="color:#ce93d8">$${{costo}}</span>Costo total</div>
    <div id="stat-recycled-badge">${{_recycledBadgeHtml(recycledCount, recycledNames)}}</div>
  `;
  // Barra de progreso
  const pb = document.getElementById("progress-bar-wrap");
  if (pb) {{
    const eta = stats.eta || "";
    const color = pct >= 100 ? "#4caf50" : "#ffc107";
    pb.style.display = "block";
    pb.innerHTML = `
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:6px">
        <span style="font-size:13px;font-weight:700;color:#fff">${{gen}} / ${{total}} clips Flow</span>
        <span style="font-size:12px;color:#888">${{pct}}%</span>
        ${{enCurso ? `<span style="font-size:12px;color:#ffc107">⏱ ETA: ${{eta}}</span>` : '<span style="font-size:12px;color:#4caf50">✓ Completo</span>'}}
        ${{enCurso ? '<span style="font-size:11px;color:#555;margin-left:auto">Actualiza automáticamente cada 15s</span>' : ''}}
      </div>
      <div style="background:#1a1a1a;border-radius:6px;height:8px;overflow:hidden">
        <div style="background:${{color}};height:100%;width:${{pct}}%;transition:width 0.4s;border-radius:6px"></div>
      </div>`;
    if (enCurso) setTimeout(refreshSoloStats, 15000);
  }}
  const rs = document.getElementById("render-status");
  if (stats.pendiente > 0) {{
    rs.style.display = "block";
    rs.className = "render-block";
    rs.textContent = `⛔ Render bloqueado — ${{stats.pendiente}} imagen(s) pendiente(s) de aprobación.`;
  }} else if (stats.total > 0 && !enCurso) {{
    rs.style.display = "block";
    rs.className = "render-block render-ok";
    rs.textContent = `✅ TODAS APROBADAS — podés lanzar el render.`;
    // También actualizar botón de forma permanente
    const btn = document.querySelector('button[onclick="aprobarTodos()"]');
    if (btn) {{
      btn.textContent = "✅ APROBADOS — listo para render";
      btn.style.background = "#2e7d32";
      btn.style.color = "#fff";
      btn.style.fontWeight = "bold";
      btn.style.cursor = "default";
      btn.onclick = null;
    }}
  }} else {{
    rs.style.display = "none";
  }}
  updateClipCounter();
}}

// ── Timeline Unificado ────────────────────────────────────

var _footageData = {{}};   // nombre→info de flow clips
var _ytAllClips = [];      // pool de yt clips
var _recycledCountRuntime = 0;   // reciclados añadidos dinámicamente por rechazos
var _recycledNamesRuntime = [];  // nombres de los clips reciclados añadidos
var _ytShown = {{}};        // nombre→índice_en_timeline (para reemplazar)
var _timelineSegments = []; // segmentos del render_preview

function fmtTime(s) {{
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${{m}}:${{sec.toString().padStart(2,'0')}}`;
}}

function buildFlowCard(seg, footage, num) {{
  const clip = seg.clip;
  const info = footage[clip] || {{}};
  const estado = info.estado || "pendiente";
  const fuente = info.fuente || "ia";
  const descEs   = seg.description || info.descripcion_es || info.descripcion || "";
  const iaPrompt = seg.label || info.ia_prompt || info.prompt || "";
  const costoRaw = fuente in COSTO_FUENTE ? COSTO_FUENTE[fuente] : 0.003;
  const costoLabel = costoRaw === 0 ? "GRATIS" : `$${{costoRaw.toFixed(3)}}`;
  const costoColor = costoRaw === 0 ? "#4caf50" : "#ce93d8";
  const promptId = `prompt-${{clip.replace(/[^a-z0-9]/gi,'_')}}`;
  const btnsId   = `btns-${{clip.replace(/[^a-z0-9]/gi,'_')}}`;

  const aprobadoBadge = estado === "aprobado"
    ? `<span style="color:#4caf50;font-size:11px;font-weight:600">✓ Aprobado</span>`
    : estado === "buscando"
    ? `<span style="color:#ffc107;font-size:11px">⏳ Baserow...</span>`
    : estado === "error"
    ? `<span style="color:#ff9800;font-size:11px">⚠ Error</span>`
    : `<span style="color:#ffc107;font-size:11px">⏳ Pendiente</span>`;
  const estadoBtns = `<div class="card-btns" id="${{btnsId}}" style="display:flex;gap:4px;align-items:center;margin-top:4px">
    ${{aprobadoBadge}}
  </div>`;

  return `
    <div class="card ${{estado}}" id="card-${{clip}}" data-num="${{num}}" data-type="flow" style="border-top:3px solid #7c3aed;cursor:pointer"
         onclick="abrirPreview(event, '/footage/${{PERSONAJE}}/${{clip}}?t=${{Date.now()}}', '#${{num}} FLOW · ${{clip}} · ${{seg.duration}}s', '${{clip}}', 'footage', PERSONAJE)">
      <div style="position:absolute;top:0;left:0;background:#7c3aed;color:#fff;font-size:9px;font-weight:700;padding:2px 6px;border-radius:0 0 4px 0;z-index:2">#${{num}} ${{fuente.toUpperCase()}} ${{fmtTime(seg.t_start)}}</div>
      <video data-src="/footage/${{PERSONAJE}}/${{clip}}?t=${{Date.now()}}" muted loop preload="none" class="lazy-video"
             onmouseenter="this.play()" onmouseleave="this.pause();this.currentTime=0;"
             style="width:100%;height:158px;object-fit:cover;background:#111;display:block"></video>
      <div class="card-body">
        <div class="card-id">
          ${{clip}}
          <span class="card-dur">${{seg.duration}}s</span>
        </div>
        <div style="font-size:12px;color:#fff;background:#2a1a3e;border:1px solid #7c3aed;border-radius:5px;padding:4px 8px;margin-bottom:6px;font-family:monospace;font-weight:700">
          ⏱ ${{fmtTime(seg.t_start)}} → ${{fmtTime(seg.t_end !== undefined ? seg.t_end : seg.t_start + seg.duration)}} &nbsp;<span style="color:#ce93d8">(${{seg.duration}}s)</span>
        </div>
        ${{descEs ? `<div class="card-desc-es">${{descEs}}</div>` : ""}}
        <textarea id="${{promptId}}" rows="2" disabled style="width:100%;margin:4px 0;font-size:10px;background:#1a1a1a;color:#666;border:1px solid #333;border-radius:4px;padding:4px;resize:vertical;font-family:monospace;cursor:not-allowed">${{iaPrompt.replace(/</g,'&lt;')}}</textarea>
        <div class="card-fuente">Fuente: <span class="${{fuenteColor(fuente)}}">${{fuente.toUpperCase()}}</span>
          &nbsp;·&nbsp;<span class="badge badge-${{estado}}">${{estado}}</span>
        </div>
        ${{estadoBtns}}
      </div>
    </div>`;
}}

function buildYTCard(seg, segIdx, num) {{
  const name = seg.clip;
  const isRecycled = !!seg.recycled;
  // Distinguir tipo: clip YT vs imagen zoompan
  const isZoompan = name.startsWith('img_') || name.startsWith('added_');
  const borderColor = isRecycled ? "#ff9800" : (isZoompan ? "#0ea5e9" : "#ff6b35");
  const tipoLabel   = isZoompan ? "🖼 ZOOMPAN" : "🎬 YT";
  const tipoColor   = isZoompan ? "#0ea5e9" : "#ff6b35";
  const recycledGlow = isRecycled ? "box-shadow:0 0 0 1px #ff9800 inset;" : "";
  return `
    <div class="card" id="ytrow-${{name}}" data-num="${{num}}" data-segidx="${{segIdx}}" data-type="yt" draggable="true"
         style="border-top:3px solid ${{borderColor}};cursor:pointer;${{recycledGlow}}"
         onclick="abrirPreview(event, '/yt_clip/${{PERSONAJE}}/${{name}}?t=${{Date.now()}}#t=0,${{seg.duration}}', '#${{num}} ${{tipoLabel}} · ${{name}} · ${{seg.duration}}s${{isRecycled ? " · ♻ RECICLADO" : ""}}', '${{name}}', 'yt', PERSONAJE)">
      <div style="position:absolute;top:0;left:0;background:${{borderColor}};color:#fff;font-size:9px;font-weight:700;padding:2px 6px;border-radius:0 0 4px 0;z-index:2"><span class="clip-num">#${{num}}</span> ${{tipoLabel}} ${{fmtTime(seg.t_start)}}</div>
      <video data-src="/yt_clip/${{PERSONAJE}}/${{name}}?t=${{Date.now()}}#t=0,${{seg.duration}}" muted loop preload="none" class="lazy-video"
             data-slot-dur="${{seg.duration}}"
             poster="/yt_poster/${{PERSONAJE}}/${{name}}"
             onmouseenter="this.play()" onmouseleave="this.pause();this.currentTime=0;"
             ontimeupdate="if(this.currentTime>=${{seg.duration}}){{this.currentTime=0;}}"
             style="width:100%;height:158px;object-fit:cover;background:#111;display:block"></video>
      <div class="card-body">
        <div class="card-id">
          <span class="clip-label" style="color:${{tipoColor}};font-weight:700;font-size:11px">${{name}}</span>
          <span class="card-dur">${{seg.duration}}s</span>
        </div>
        <div style="font-size:11px;color:#9c9;background:#0d1f0d;border:1px solid #2a4a2a;border-radius:4px;padding:2px 7px;margin:3px 0;font-family:monospace;font-weight:700">
          ⏱ ${{fmtTime(seg.t_start)}} → ${{fmtTime(seg.t_end !== undefined ? seg.t_end : seg.t_start + seg.duration)}}
        </div>
        ${{isRecycled ? `<div style="background:#7c2d00;color:#fed7aa;font-size:11px;font-weight:700;padding:2px 8px;border-radius:4px;margin:2px 0;text-align:center;letter-spacing:0.5px">♻ CLIP REPETIDO</div>` : ''}}
        <div class="card-btns" style="margin-top:6px;display:flex;gap:4px">
          <button class="btn-re" onclick="rechazarYTClipUnified('${{name}}', ${{segIdx}}, ${{num}})">✗ Rechazar</button>
          <button class="btn-eliminar" onclick="eliminarCard('${{name}}', event)" title="Eliminar card (no borra el archivo)">🗑</button>
        </div>
      </div>
    </div>`;
}}

var _pageSize = 9999;
var _pageShown = 0;

var _dragSrcEl = null;

function _addDragEvents(container) {{
  container.querySelectorAll(".card[draggable]").forEach(card => {{
    card.addEventListener("dragstart", e => {{
      _dragSrcEl = card;
      e.dataTransfer.effectAllowed = "move";
      card.style.opacity = "0.4";
    }});
    card.addEventListener("dragend", () => {{
      container.querySelectorAll(".card[draggable]").forEach(c => c.style.opacity = "");
      container.querySelectorAll(".card[draggable]").forEach(c => c.classList.remove("drag-over"));
    }});
    card.addEventListener("dragover", e => {{
      if (card.dataset.type === "flow") {{ e.dataTransfer.dropEffect = "none"; return; }}
      e.preventDefault(); e.dataTransfer.dropEffect = "move";
      card.classList.add("drag-over");
    }});
    card.addEventListener("dragleave", () => card.classList.remove("drag-over"));
    card.addEventListener("drop", e => {{
      e.stopPropagation(); e.preventDefault();
      card.classList.remove("drag-over");
      if (_dragSrcEl === card) return;
      // No permitir soltar sobre cards Flow — permanecen fijas
      if (card.dataset.type === "flow") return;
      // Reordenar en el DOM
      const allCards = [...container.querySelectorAll(".card[draggable]")];
      const fromIdx  = allCards.indexOf(_dragSrcEl);
      const toIdx    = allCards.indexOf(card);
      if (fromIdx < 0 || toIdx < 0) return;
      if (fromIdx < toIdx) card.after(_dragSrcEl);
      else card.before(_dragSrcEl);
      // Renumerar labels visibles
      container.querySelectorAll(".card[draggable] .clip-num").forEach((el, i) => {{
        el.textContent = "#" + (i + 1);
      }});
      // Reordenar _timelineSegments para que el render respete el nuevo orden
      const ytRejected = new Set(_ytAllClips.filter(c => c.estado==='rechazado').map(c=>c.name));
      const visible = _timelineSegments.filter(s => s.type==="flow" || !ytRejected.has(s.clip));
      const moved = visible.splice(fromIdx, 1)[0];
      visible.splice(toIdx, 0, moved);
      // Reconstruir _timelineSegments con nuevo orden
      _timelineSegments = visible;
      // Guardar orden en servidor
      const order = [...container.querySelectorAll(".card[draggable]")].map(c => c.id.replace("ytrow-",""));
      fetch(`/api/riq/save_order/${{PERSONAJE}}`, {{
        method: "POST",
        headers: {{"Content-Type":"application/json"}},
        body: JSON.stringify({{order, force: true}})
      }});
    }});
  }});
}}

function renderUnified(segments, footage, ytClipsAll) {{
  const container = document.getElementById("unified-timeline");
  const loading   = document.getElementById("unified-loading");
  const cnt       = document.getElementById("unified-count");
  if (!container) return;

  const ytRejected = new Set(ytClipsAll.filter(c => c.estado === 'rechazado').map(c => c.name));

  // Filtrar segmentos válidos
  const visible = segments.filter(s => s.type === "flow" || !ytRejected.has(s.clip));
  _pageShown = Math.min(_pageSize, visible.length);

  let html = "";
  for (let i = 0; i < _pageShown; i++) {{
    const seg = visible[i];
    const num = i + 1;
    const segIdx = _timelineSegments.indexOf(seg);
    html += seg.type === "flow" ? buildFlowCard(seg, footage, num) : buildYTCard(seg, segIdx, num);
  }}

  if (visible.length > _pageShown) {{
    html += `<button class="load-more-btn" onclick="mostrarMas()" style="width:100%;padding:12px;background:#1a1a2e;border:1px solid #333;color:#888;border-radius:8px;cursor:pointer;font-size:13px;margin-top:8px">↓ Mostrar más (${{visible.length - _pageShown}} restantes)</button>`;
  }}

  container.innerHTML = html;
  if (loading) loading.style.display = "none";

  const flowCount = segments.filter(s => s.type === "flow").length;
  const ytCount   = visible.filter(s => s.type === "yt_clip").length;
  if (cnt) cnt.textContent = `${{flowCount}} Flow · ${{ytCount}} YT clips`;
  _addDragEvents(container);
}}

function mostrarMas() {{
  _pageShown = Math.min(_pageShown + 40, _timelineSegments.length);
  const container = document.getElementById("unified-timeline");
  const loading   = document.getElementById("unified-loading");
  const ytRejected = new Set(_ytAllClips.filter(c => c.estado === 'rechazado').map(c => c.name));
  const visible = _timelineSegments.filter(s => s.type === "flow" || !ytRejected.has(s.clip));
  let html = "";
  for (let i = _pageShown - 40; i < Math.min(_pageShown, visible.length); i++) {{
    const seg = visible[i]; const num = i + 1;
    const segIdx = _timelineSegments.indexOf(seg);
    html += seg.type === "flow" ? buildFlowCard(seg, _footageData, num) : buildYTCard(seg, segIdx, num);
  }}
  // Quitar botón viejo y agregar nuevas cards
  const oldBtn = container.querySelector("button.load-more-btn");
  if (oldBtn) oldBtn.remove();
  container.insertAdjacentHTML("beforeend", html);
  if (visible.length > _pageShown) {{
    container.insertAdjacentHTML("beforeend", `<button class="load-more-btn" onclick="mostrarMas()" style="width:100%;padding:12px;background:#1a1a2e;border:1px solid #333;color:#888;border-radius:8px;cursor:pointer;font-size:13px;margin-top:8px">↓ Mostrar más (${{visible.length - _pageShown}} restantes)</button>`);
  }}
  if (loading) loading.style.display = "none";
  setTimeout(observeVideos, 100);
}}

function _swapCard(cardEl, nuevoClip, segIdx, num, recycled, videoUrl) {{
  if (!cardEl) return;
  // Si la card estaba vacante, limpiarla
  cardEl.classList.remove("vacant");
  cardEl.querySelector(".vacant-badge")?.remove();
  const clipUrl = videoUrl || `/yt_clip/${{PERSONAJE}}/${{nuevoClip}}?t=${{Date.now()}}`;
  const vid = cardEl.querySelector('video');
  if (vid) {{
    const tmpVid = document.createElement('video');
    tmpVid.muted = true;
    tmpVid.preload = 'auto';
    tmpVid.src = clipUrl;
    tmpVid.addEventListener('canplay', () => {{
      vid.setAttribute('src', tmpVid.src);
      vid.dataset.src = vid.getAttribute('src');
      vid.muted = true;
      if (!_isMobile) vid.play().catch(()=>{{}});
      tmpVid.remove();
    }}, {{once: true}});
    setTimeout(() => {{
      if (!vid.getAttribute('src') || !vid.getAttribute('src').includes(nuevoClip)) {{
        vid.setAttribute('src', clipUrl);
        vid.dataset.src = clipUrl;
        vid.load();
        if (!_isMobile) vid.play().catch(()=>{{}});
      }}
    }}, 1500);
    document.body.appendChild(tmpVid);
    tmpVid.load();
  }}
  const lbl = cardEl.querySelector('.clip-label');
  if (lbl) lbl.textContent = nuevoClip;
  cardEl.id = `ytrow-${{nuevoClip}}`;
  cardEl.querySelector('.btn-re')?.setAttribute('onclick',
    `rechazarYTClipUnified('${{nuevoClip}}',${{segIdx}},${{num}})`);
  cardEl.onclick = (e) => abrirPreview(e,
    `${{clipUrl}}`,
    `#${{num}} YT · ${{nuevoClip}}${{recycled ? ' · ♻ RECICLADO' : ''}}`,
    nuevoClip, 'yt', PERSONAJE);
  if (recycled) {{
    cardEl.style.borderTop = '3px solid #ff9800';
    cardEl.style.boxShadow = '0 0 0 1px #ff9800 inset';
    if (!cardEl.querySelector('.recycled-badge')) {{
      const b = document.createElement('span');
      b.className = 'recycled-badge';
      b.style.cssText = 'background:#e65100;color:#fff;font-size:9px;font-weight:700;padding:1px 5px;border-radius:3px;letter-spacing:0.5px;margin-left:4px';
      b.textContent = '♻ RECICLADO';
      if (lbl) lbl.after(b);
    }}
  }} else {{
    cardEl.style.outline = '2px solid #4ecdc4';
    setTimeout(() => cardEl.style.outline = '', 1200);
  }}
}}

function _limpiarAvisoCard(cardEl) {{
  cardEl.querySelector('.card-deficit-msg')?.remove();
}}

function _mostrarAvisoEnCard(cardEl, tipo) {{
  _limpiarAvisoCard(cardEl);
  const msg = document.createElement('div');
  msg.className = 'card-deficit-msg';
  msg.style.cssText = 'font-size:10px;font-weight:600;padding:4px 6px;border-radius:4px;margin-top:4px;line-height:1.4;text-align:center';
  if (tipo === 'pocos') {{
    msg.style.background = '#1a1f00'; msg.style.color = '#ccdd44'; msg.style.border = '1px solid #88aa00';
    msg.textContent = '📉 Pocos clips frescos — considera descargar más';
  }} else if (tipo === 'reciclado') {{
    msg.style.background = '#2d1500'; msg.style.color = '#ffb366'; msg.style.border = '1px solid #cc6600';
    msg.innerHTML = '♻ Clips frescos agotados<br>Descarga otro video o agrega imágenes Google';
  }} else if (tipo === 'sin_frescos') {{
    msg.style.background = '#2d1500'; msg.style.color = '#ffb366'; msg.style.border = '1px solid #cc6600';
    msg.innerHTML = '♻ Clips frescos agotados<br>Descarga otro video o agrega imágenes Google';
  }} else if (tipo === 'sin_clips') {{
    msg.style.background = '#3b0000'; msg.style.color = '#ff8888'; msg.style.border = '1px solid #cc0000';
    msg.innerHTML = '🚨 Sin clips disponibles<br>Descarga otro video: <code>clips.py &lt;url&gt;</code><br>o agrega imágenes Google en <code>03-imagenes/</code>';
  }}
  cardEl.appendChild(msg);
}}

async function rechazarYTClipUnified(clip, segIdx, num) {{
  const cardEl = document.getElementById(`ytrow-${{clip}}`);
  const visiblesSet = new Set(
    Array.from(document.querySelectorAll('#unified-timeline [id^="ytrow-"]'))
      .map(el => el.id.replace('ytrow-', ''))
  );

  // ── OPTIMISTA: elegir reemplazo al instante desde memoria ──
  const visiblesActuales = Array.from(document.querySelectorAll('#unified-timeline [id^="ytrow-"]'))
    .map(e => e.id.replace('ytrow-',''));
  const enGridSet = new Set(visiblesActuales);

  // Pool: todos los clips no rechazados (disponibles para reemplazo)
  const poolClips   = (_ytAllClips || []).filter(c => c.estado !== 'rechazado' && c.name !== clip);
  // "frescos" = disponibles que NO han sido ya puestos como reemplazo en esta sesión
  // Como el grid renderiza todos, usamos simplemente: total disponibles = poolClips
  const frescoTodos = poolClips;  // cualquier no-rechazado es candidato

  // Marcar el clip rechazado como tal en el pool para que no sea candidato
  const rejIdx = (_ytAllClips || []).findIndex(c => c.name === clip);
  if (rejIdx >= 0) _ytAllClips[rejIdx] = {{ ..._ytAllClips[rejIdx], estado: 'rechazado' }};

  let reemplazoFast = null;
  let recycledFast  = false;
  let reemplazoUrl  = null;

  if (frescoTodos.length) {{
    // 1) Clip fresco no visible en el grid
    reemplazoFast = frescoTodos[Math.floor(Math.random() * frescoTodos.length)].name;
    recycledFast  = false;
  }}

  // 2) Último recurso: reciclar clip YT ya visible en el grid
  if (!reemplazoFast && poolClips.length) {{
    const reciclables = poolClips.filter(c => c.name !== clip && c.estado !== 'rechazado');
    const recClips = reciclables.filter(c => c.name.startsWith('clip_'));
    const recImgs  = reciclables.filter(c => !c.name.startsWith('clip_'));
    const recPool  = recClips.length ? recClips : recImgs;
    if (recPool.length) {{
      reemplazoFast = recPool[Math.floor(Math.random() * recPool.length)].name;
      recycledFast  = true;
    }}
  }}

  // ── BANNER DÉFICIT (arriba, secundario) ──
  _actualizarBannerDeficit(frescoTodos.length, !!reemplazoFast);

  if (reemplazoFast && cardEl) {{
    _swapCard(cardEl, reemplazoFast, segIdx, num, recycledFast, reemplazoUrl);
    // Aviso inline en el card cuando se usan reciclados o no hay frescos
    if (frescoTodos.length === 0) {{
      _mostrarAvisoEnCard(cardEl, recycledFast ? 'reciclado' : 'sin_frescos');
    }} else if (frescoTodos.length <= 5) {{
      _mostrarAvisoEnCard(cardEl, 'pocos');
    }} else {{
      _limpiarAvisoCard(cardEl);
    }}
    toast(`#${{num}} reemplazado → ${{reemplazoFast}}`, '#166634');
  }} else if (cardEl) {{
    _marcarVacante(cardEl, segIdx, num);
    _mostrarAvisoEnCard(cardEl, 'sin_clips');
    toast(`⚠ #${{num}} sin más clips disponibles`, '#b45309');
  }}

  // Detectar duplicados del clip rechazado en otras cards y ponerlas en negro
  document.querySelectorAll(`#unified-timeline [id="ytrow-${{clip}}"]`).forEach(dupeCard => {{
    if (dupeCard === cardEl) return;  // ya procesada
    const dupeNum = parseInt(dupeCard.dataset.num || "0");
    const dupeIdx = parseInt(dupeCard.dataset.segidx || "0");
    _marcarVacante(dupeCard, dupeIdx, dupeNum);
    toast(`⬛ Card #${{dupeNum}} vaciada (clip duplicado)`, '#78350f');
  }});

  updateClipCounter();
  _autoSaveOrder();  // persistir orden nuevo antes del reload

  // ── BACKEND en paralelo (no bloqueante) ──
  fetch(`/api/riq/delete_yt_clip/${{PERSONAJE}}`, {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{clip, visible_clips: visiblesActuales}})
  }}).catch(() => {{}});  // fire-and-forget

}}

var _clipsNeeded = 0;  // se llena al cargar

function _actualizarBannerDeficit(frescos, hayReemplazo) {{
  const banner = document.getElementById('deficit-banner');
  if (!banner) return;
  // frescos aquí = clips disponibles (no rechazados); umbral de aviso: menos de 10
  if (frescos > 10) {{
    banner.style.display = 'none';
    return;
  }}
  if (!hayReemplazo) {{
    // sin reemplazo alguno — URGENTE
    banner.style.display  = 'block';
    banner.style.background = '#3b0000';
    banner.style.border     = '1.5px solid #ff4444';
    banner.style.color      = '#ffaaaa';
    banner.innerHTML = `🚨 <b>Sin clips disponibles</b> — no hay YT frescos ni reciclados.<br>
      Opciones: <b>1)</b> descarga otro video con <code>clips.py &lt;url&gt;</code> y reinicia el dashboard&nbsp;&nbsp;
      <b>2)</b> agrega imágenes de Google en <code>03-imagenes/</code> (se les aplica zoompan automático)`;
  }} else if (frescos === 0) {{
    // usando reciclados — ADVERTENCIA
    banner.style.display  = 'block';
    banner.style.background = '#2d1a00';
    banner.style.border     = '1.5px solid #f5b933';
    banner.style.color      = '#ffe0a0';
    banner.innerHTML = `⚠️ <b>Clips frescos agotados</b> — se están reutilizando clips ya visibles en el grid.<br>
      Para más variedad: descarga otro video con <code>clips.py &lt;url&gt;</code> y reinicia el dashboard,
      o agrega imágenes de Google en <code>03-imagenes/</code> para zoompan automático.`;
  }} else {{
    // pocos frescos — AVISO suave
    banner.style.display  = 'block';
    banner.style.background = '#1a1f00';
    banner.style.border     = '1.5px solid #aacc00';
    banner.style.color      = '#ddeea0';
    banner.innerHTML = `📉 <b>${{frescos}} clip${{frescos===1?'':'s'}} fresco${{frescos===1?'':'s'}} disponible${{frescos===1?'':'s'}}</b> — quedan pocos clips sin usar.
      Si sigues rechazando considera descargar más.`;
  }}
}}

async function updateClipCounter() {{
  try {{
    const r = await fetch(`/api/riq/clip_count/${{PERSONAJE}}`);
    const d = await r.json();
    const total  = d.total  || 0;
    const needed = d.needed || _clipsNeeded;
    _clipsNeeded = needed;
    if (!needed) return;
    // calcular frescos: clips en pool que no están en el grid actual
    const enGrid = new Set(
      Array.from(document.querySelectorAll('#unified-timeline [id^="ytrow-"]'))
           .map(e => e.id.replace('ytrow-',''))
    );
    const frescos = (_ytAllClips || []).filter(c => c.estado !== 'rechazado').length;
    const okColor = total >= needed ? "#00ffaa" : "#ff6b6b";
    const pill = document.getElementById('clips-counter-pill');
    if (!pill) return;
    pill.style.color  = okColor;
    pill.style.border = `1px solid ${{okColor}}`;
    const frescoLabel = frescos > 0 ? ` · ${{frescos}} frescos` : ` · ⚠ sin frescos`;
    const frescoColor = frescos > 5 ? '#aaffcc' : frescos > 0 ? '#f5b933' : '#ff6b6b';
    pill.innerHTML = `<span style="color:${{okColor}}">${{total}}/${{needed}} clips</span><span style="color:${{frescoColor}};font-size:11px;margin-left:4px">${{frescoLabel}}</span>`;
  }} catch(e) {{}}
}}

async function eliminarCard(name, evt) {{
  if (evt) evt.stopPropagation();
  const cardEl = document.getElementById(`ytrow-${{name}}`);
  if (!cardEl) return;
  // Detectar duplicados ANTES de eliminar esta card
  const dupes = [...document.querySelectorAll(`#unified-timeline [id="ytrow-${{name}}"]`)]
    .filter(c => c !== cardEl);
  dupes.forEach(dupeCard => {{
    const dupeNum = parseInt(dupeCard.dataset.num || "0");
    const dupeIdx = parseInt(dupeCard.dataset.segidx || "0");
    _marcarVacante(dupeCard, dupeIdx, dupeNum);
    toast(`⬛ Card #${{dupeNum}} vaciada (clip duplicado)`, '#78350f');
  }});
  await fetch(`/api/riq/remove_yt_card/${{PERSONAJE}}`, {{
    method: "POST",
    headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{ clip: name }})
  }});
  const ci = _ytAllClips.findIndex(c => c.name === name);
  if (ci >= 0) _ytAllClips.splice(ci, 1);
  cardEl.style.transition = "opacity 0.25s, transform 0.25s";
  cardEl.style.opacity    = "0";
  cardEl.style.transform  = "scale(0.9)";
  setTimeout(() => {{ cardEl.remove(); updateClipCounter(); }}, 280);
  toast(`🗑 ${{name}} eliminado del grid`, "#555");
}}

async function accion(clip, estado) {{
  const res  = await fetch(`/api/footage_approve/${{PERSONAJE}}`, {{
    method: "POST",
    headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{clip, accion: estado}})
  }});
  const data = await res.json();
  if (!data.ok) return;

  // Actualizar SOLO esa card, sin recargar el grid completo
  const card = document.getElementById(`card-${{clip}}`);
  if (estado === "aprobado") {{
    toast(`✓ #${{card ? card.dataset.num : clip}} aprobado`, "#2e7d32");
    if (card) {{
      card.className = "card aprobado";
      const btnsId = `btns-${{clip.replace(/[^a-z0-9]/gi,'_')}}`;
      const btns = document.getElementById(btnsId);
      if (btns) btns.innerHTML = `<div style="color:#4caf50;font-size:12px;padding:2px 0">✓ Aprobado</div>`;
      const badge = card.querySelector(".badge");
      if (badge) {{ badge.className = "badge badge-aprobado"; badge.textContent = "aprobado"; }}
    }}
    // Actualizar stats en background sin re-render
    fetch(`/api/footage/${{PERSONAJE}}`).then(r=>r.json()).then(d=>renderStats(d.stats));
  }} else {{
    toast(`⏳ #${{card ? card.dataset.num : clip}} rechazado — actualizá Baserow y generá desde la extensión`, "#7f1d1d");
    if (card) {{
      card.className = "card rechazado";
      const btnsId = `btns-${{clip.replace(/[^a-z0-9]/gi,'_')}}`;
      const btns = document.getElementById(btnsId);
      if (btns) btns.innerHTML = `<div style="color:#ffc107;font-size:12px;padding:2px 0">⏳ status=pending en Baserow</div>`;
      const badge = card.querySelector(".badge");
      if (badge) {{ badge.className = "badge badge-rechazado"; badge.textContent = "rechazado"; }}
    }}
  }}
}}

function confirmarRechazoFlow(clip, btnsId) {{
  const btns = document.getElementById(btnsId);
  if (btns) btns.innerHTML = `
    <div style="font-size:12px;color:#ffcdd2;margin-bottom:6px">¿Seguro quieres rechazar este clip de Flow?</div>
    <div style="display:flex;gap:6px">
      <button class="btn-ap" onclick="cancelarRechazoFlow('${{clip}}','${{btnsId}}')">← No, cancelar</button>
      <button class="btn-re" onclick="rechazarFlowConYT('${{clip}}','${{btnsId}}')">✓ Sí, reemplazar con YT</button>
    </div>`;
}}

function cancelarRechazoFlow(clip, btnsId) {{
  const btns = document.getElementById(btnsId);
  if (btns) btns.innerHTML = `
    <button class="btn-re" onclick="confirmarRechazoFlow('${{clip}}','${{btnsId}}')">✗ Rechazar</button>`;
}}

async function rechazarFlowConYT(clip, btnsId) {{
  const btns = document.getElementById(btnsId);
  if (btns) btns.innerHTML = `<div style="color:#ffc107;font-size:12px">⏳ Buscando clip YT de reemplazo…</div>`;

  // Buscar clips YT visibles en el grid para no repetir
  const visiblesEnGrid = new Set(
    Array.from(document.querySelectorAll('#unified-timeline [id^="ytrow-"]'))
         .map(el => el.id.replace('ytrow-', ''))
  );
  const poolFlow = _ytAllClips.filter(c => !visiblesEnGrid.has(c.name) && c.estado !== 'rechazado' && c.estado !== 'en_grid');
  // Prioridad: clip_* primero, img_* solo si no hay clips YT disponibles
  const frescoYT   = poolFlow.filter(c => c.name.startsWith('clip_'));
  const frescoImgs = poolFlow.filter(c => !c.name.startsWith('clip_'));
  const candidatos = frescoYT.length ? frescoYT : frescoImgs;
  if (!candidatos.length) {{
    toast("⚠ No hay clips YT disponibles para reemplazar", "#f59e0b");
    if (btns) btns.innerHTML = `<button class="btn-re" onclick="confirmarRechazoFlow('${{clip}}','${{btnsId}}')">✗ Rechazar</button>`;
    return;
  }}
  const nuevo = candidatos[Math.floor(Math.random() * candidatos.length)];

  // Registrar en backend como clip Flow rechazado → reemplazado por YT
  await fetch("/api/flow_replace_with_yt", {{
    method: "POST",
    headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{ personaje: PERSONAJE, flow_clip: clip, yt_clip: nuevo.name }})
  }});

  // Reemplazar la card Flow por una card YT visualmente
  const card = document.getElementById(`card-${{clip}}`);
  if (card) {{
    const segIdx = parseInt(card.dataset.num) - 1;
    card.outerHTML = buildYTCard({{
      type: "yt_clip", clip: nuevo.name,
      url: `/yt_clip/${{PERSONAJE}}/${{nuevo.name}}`,
      t_start: 0, duration: 5, exists: true
    }}, segIdx, parseInt(card.dataset.num || 0));
    // Marcar en el pool como "en_grid" para que no se repita en el próximo rechazo
    const idxNuevo = _ytAllClips.findIndex(c => c.name === nuevo.name);
    if (idxNuevo >= 0) _ytAllClips[idxNuevo] = {{ ...nuevo, estado: "en_grid" }};
  }}
  toast(`✓ Flow reemplazado por ${{nuevo.name}}`, "#4caf50");
}}

function iniciarRechazo(clip, promptId) {{
  const textarea = document.getElementById(promptId);
  const btnsId   = `btns-${{clip.replace(/[^a-z0-9]/gi,'_')}}`;
  const btns     = document.getElementById(btnsId);
  textarea.disabled = false;
  textarea.style.background = "#1a0a0a";
  textarea.style.color = "#ffcdd2";
  textarea.style.border = "1px solid #b91c1c";
  textarea.style.cursor = "text";
  textarea.focus();
  if (btns) btns.innerHTML = `
    <button class="btn-ap" onclick="cancelarRechazo('${{clip}}','${{promptId}}','${{btnsId}}')">← Cancelar</button>
    <button class="btn-re" onclick="rechazarConPrompt('${{clip}}','${{promptId}}')">✓ Confirmar rechazo</button>`;
}}

function cancelarRechazo(clip, promptId, btnsId) {{
  const textarea = document.getElementById(promptId);
  textarea.disabled = true;
  textarea.style.background = "#1a1a1a";
  textarea.style.color = "#666";
  textarea.style.border = "1px solid #333";
  textarea.style.cursor = "not-allowed";
  const btns = document.getElementById(btnsId);
  if (btns) btns.innerHTML = `
    <button class="btn-re" onclick="confirmarRechazoFlow('${{clip}}','${{btnsId}}')">✗ Rechazar</button>`;
}}

async function rechazarConPrompt(clip, promptId) {{
  const textarea = document.getElementById(promptId);
  const newPrompt = textarea ? textarea.value.trim() : "";
  if (!newPrompt) {{
    toast("⚠ Escribe un prompt antes de confirmar", "#f59e0b");
    return;
  }}
  const res = await fetch("/api/update_baserow_prompt", {{
    method: "POST",
    headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{ updates: [{{ clip, prompt: newPrompt, personaje: PERSONAJE }}] }})
  }});
  const data = await res.json();
  const ok = data.ok && data.results && data.results[0] && data.results[0].ok;
  if (ok) {{
    toast(`✓ Baserow actualizado — genera desde la extensión y avísame`, "#1565c0");
    const card = document.getElementById(`card-${{clip}}`);
    if (card) {{
      card.className = "card rechazado";
      const btnsId = `btns-${{clip.replace(/[^a-z0-9]/gi,'_')}}`;
      const btns   = document.getElementById(btnsId);
      if (btns) btns.innerHTML = `<div style="color:#ffc107;font-size:12px;padding:2px 0">⏳ status=pending en Baserow — esperando nueva generación</div>`;
      if (textarea) {{
        textarea.disabled = true;
        textarea.style.background = "#1a1a1a";
        textarea.style.color = "#888";
        textarea.style.border = "1px solid #444";
        textarea.style.cursor = "not-allowed";
      }}
    }}
  }} else {{
    const err = (data.errors && data.errors[0]) ? data.errors[0].error : "error desconocido";
    toast(`⚠ No se pudo actualizar Baserow: ${{err}}`, "#f59e0b");
  }}
}}

let rerunPoller = null;
function pollRerun() {{
  if (rerunPoller) clearInterval(rerunPoller);
  rerunPoller = setInterval(async () => {{
    const r = await fetch(`/api/rerun_status/${{PERSONAJE}}`);
    const d = await r.json();
    if (!d.running) {{
      clearInterval(rerunPoller);
      rerunPoller = null;
      await cargar();
      toast(`✓ Alternativa lista — revisá el tablero`, "#1565c0");
    }}
  }}, 4000);
}}

// Audio player — actualizar tiempo en pantalla
(function() {{
  const audio = document.getElementById('guion-audio');
  const timeEl = document.getElementById('audio-time');
  if (!audio || !timeEl) return;
  function fmt(s) {{
    const m = Math.floor(s / 60), sec = Math.floor(s % 60);
    return m + ':' + String(sec).padStart(2, '0');
  }}
  audio.addEventListener('timeupdate', () => {{
    const dur = isNaN(audio.duration) ? '--:--' : fmt(audio.duration);
    timeEl.textContent = fmt(audio.currentTime) + ' / ' + dur;
  }});
  audio.addEventListener('loadedmetadata', () => {{
    timeEl.textContent = '0:00 / ' + fmt(audio.duration);
  }});
}})();

function _currentYTOrder() {{
  // Extrae el orden actual de clips YT visibles en el grid
  return [...document.querySelectorAll('#unified-timeline [id^="ytrow-"]')]
    .map(el => el.id.replace("ytrow-", ""));
}}

function _autoSaveOrder() {{
  // Guarda el orden actual silenciosamente después de cada rechazo/swap
  // force:true para sobreescribir siempre — el usuario cambió explícitamente el orden
  const order = _currentYTOrder().filter(n => !n.startsWith('vacant-'));
  if (!order.length) return;
  fetch(`/api/riq/save_order/${{PERSONAJE}}`, {{
    method: "POST",
    headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{order, force: true}})
  }}).catch(() => {{}});
}}

function _vacantCards() {{
  // Devuelve las cards YT vacías (clase .vacant)
  return [...document.querySelectorAll('#unified-timeline .card.vacant')];
}}

async function aprobarTodos() {{
  // Avisar sobre cards vacías pero NO bloquear — se excluyen del orden automáticamente
  const vacantes = _vacantCards();
  if (vacantes.length > 0) {{
    toast(`ℹ ${{vacantes.length}} card(s) sin clip — se excluirán del render`, "#b45309", 4000);
    vacantes.forEach(c => {{
      c.style.outline = "2px solid #f59e0b";
      setTimeout(() => c.style.outline = "", 3000);
    }});
    // NO return — continuar con la aprobación
  }}
  // Capturar orden actual del grid — excluir vacantes y vacant-*
  const clips_order = _currentYTOrder().filter(n => !n.startsWith('vacant-'));
  let data;
  try {{
    const res = await fetch(`/api/footage_approve_all/${{PERSONAJE}}`, {{
      method: "POST",
      headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify({{clips_order}})
    }});
    data = await res.json();
  }} catch(e) {{
    alert("❌ Error al aprobar: " + e.message);
    return;
  }}
  if (data.ok) {{
    const msg = data.aprobados > 0
      ? `✓ ${{data.aprobados}} clips Flow aprobados · ${{clips_order.length}} YT guardados`
      : `✓ Orden guardado — ${{clips_order.length}} clips listos para render`;
    alert("✅ " + msg);
    toast(msg, "#2e7d32", 6000);
    // Cambio PERMANENTE del botón — queda verde para siempre
    const btn = document.querySelector('button[onclick="aprobarTodos()"]');
    if (btn) {{
      btn.textContent = "✅ APROBADOS — listo para render";
      btn.style.background = "#2e7d32";
      btn.style.color = "#fff";
      btn.style.fontWeight = "bold";
      btn.style.cursor = "default";
      btn.onclick = null;
      // Mostrar botón cola nocturna justo al aprobar
      const existingNQ = document.getElementById('btn-night-queue');
      if (!existingNQ) {{
        const nqBtn = document.createElement('button');
        nqBtn.id = 'btn-night-queue';
        nqBtn.textContent = '🌙 Cola nocturna';
        nqBtn.style.cssText = 'background:#1a1040;color:#b39ddb;border:1px solid #7c4dff;padding:8px 18px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;margin-left:8px';
        nqBtn.onclick = function() {{ toggleNightQueue(); }};
        btn.parentNode.insertBefore(nqBtn, btn.nextSibling);
      }}
    }}
    document.querySelectorAll('#unified-timeline .card[id^="card-"]').forEach(card => {{
      card.className = "card aprobado";
      const badge = card.querySelector(".badge");
      if (badge) {{ badge.className = "badge badge-aprobado"; badge.textContent = "aprobado"; }}
      const btnsId = card.id.replace("card-", "btns-");
      const btns = document.getElementById(btnsId);
      if (btns) btns.innerHTML = `<div style="color:#4caf50;font-size:12px;padding:2px 0">✓ Aprobado</div>`;
    }});
    fetch(`/api/footage/${{PERSONAJE}}`).then(r=>r.json()).then(d=>renderStats(d.stats));
  }}
}}

function _marcarVacante(cardEl, segIdx, num) {{
  // Pone la card en negro — SIN cambiar el ID para que los botones sigan funcionando
  cardEl.classList.add("vacant");
  cardEl.style.borderTop = "3px solid #444";
  cardEl.style.boxShadow = "none";
  const vid = cardEl.querySelector("video");
  if (vid) {{ vid.pause(); vid.src = ""; vid.style.background = "#111"; }}
  const lbl = cardEl.querySelector(".clip-label");
  if (!cardEl.querySelector(".vacant-badge")) {{
    const b = document.createElement("span");
    b.className = "vacant-badge";
    b.style.cssText = "background:#444;color:#aaa;font-size:9px;padding:1px 5px;border-radius:3px;margin-left:4px;display:inline-block";
    b.textContent = "⬛ SIN CLIP";
    if (lbl) lbl.after(b);
  }}
}}

async function cargar() {{
  // Carga footage stats + timeline unificado en paralelo
  const [footageRes, previewRes, ytRes] = await Promise.all([
    fetch(`/api/footage/${{PERSONAJE}}`),
    fetch(`/api/render_preview/${{PERSONAJE}}`),
    fetch(`/api/yt_clips/${{PERSONAJE}}`)
  ]);
  const footageData  = await footageRes.json();
  const previewData  = await previewRes.json();
  const ytData       = await ytRes.json();

  _footageData          = footageData.footage || {{}};
  _timelineSegments     = previewData.segments || [];
  _ytAllClips           = ytData.clips || [];
  _recycledCountRuntime = previewData.recycled_count ?? 0;
  _recycledNamesRuntime = previewData.recycled_names ?? [];

  renderStats(footageData.stats, previewData.recycled_count ?? 0, previewData.recycled_names ?? []);
  renderUnified(_timelineSegments, _footageData, _ytAllClips);
  updateClipCounter();
  setTimeout(observeVideos, 150);
  // Congelar orden del grid si aún no está guardado en el servidor
  if (!previewData.clips_order_saved) {{
    const clips_order = _currentYTOrder();
    if (clips_order.length > 0) {{
      fetch(`/api/riq/save_order/${{PERSONAJE}}`, {{
        method: "POST",
        headers: {{"Content-Type":"application/json"}},
        body: JSON.stringify({{order: clips_order}})
      }});
    }}
  }}
}}

// ── Prompts ──────────────────────────────────────────────
let promptsData = [];

function renderPrompts(prompts) {{
  const grid = document.getElementById("prompts-grid");
  const sec  = document.getElementById("prompts-section");
  const cnt  = document.getElementById("prompts-count");
  if (!prompts || !prompts.length) {{ sec.style.display = "none"; return; }}
  sec.style.display = "block";
  cnt.textContent = `${{prompts.length}} imágenes`;
  grid.innerHTML = prompts.map((p, i) => `
    <div style="background:#1a1a1a;border:1px solid #333;border-radius:8px;padding:12px">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
        <span style="font-size:11px;color:#9c27b0;font-weight:700;min-width:60px">IMG ${{i+1}}</span>
        <span style="font-size:11px;color:#666">⏱ ${{p.seg_inicio}}</span>
        <button onclick="copyPrompt(${{i}})" style="margin-left:auto;background:#1a1a3a;color:#4ecdc4;border:1px solid #4ecdc4;border-radius:4px;padding:2px 10px;font-size:11px;cursor:pointer">Copiar</button>
      </div>
      <textarea id="prompt-text-${{i}}"
        style="width:100%;background:#0d0d0d;color:#eee;border:1px solid #444;border-radius:6px;padding:8px;font-size:12px;font-family:monospace;resize:vertical;min-height:60px"
        onchange="promptsData[${{i}}].prompt=this.value"
      >${{p.prompt}}</textarea>
    </div>`).join("");
}}

function copyPrompt(i) {{
  const el = document.getElementById(`prompt-text-${{i}}`);
  const txt = el.value;
  if (navigator.clipboard && window.isSecureContext) {{
    navigator.clipboard.writeText(txt).then(() => toast("✓ Copiado", "#1565c0")).catch(() => fallbackCopy(el));
  }} else {{
    fallbackCopy(el);
  }}
}}
function fallbackCopy(el) {{
  el.select();
  el.setSelectionRange(0, 99999);
  document.execCommand("copy");
  toast("✓ Copiado", "#1565c0");
}}

async function cargarPrompts() {{
  const res  = await fetch(`/api/prompts/${{PERSONAJE}}`);
  const data = await res.json();
  promptsData = data.prompts || [];
  renderPrompts(promptsData);
}}

async function guardarPrompts() {{
  // Leer valores actuales de los textareas
  promptsData.forEach((p, i) => {{
    const el = document.getElementById(`prompt-text-${{i}}`);
    if (el) p.prompt = el.value;
  }});
  const res = await fetch(`/api/prompts/${{PERSONAJE}}`, {{
    method: "PUT",
    headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{prompts: promptsData}})
  }});
  const d = await res.json();
  if (d.ok) toast(`✓ ${{d.guardados}} prompts guardados`, "#2e7d32");
  else toast("Error al guardar", "#7f1d1d");
}}

async function aprobarPrompts() {{
  await guardarPrompts();
  toast("✓ Prompts aprobados — ya podés generar las imágenes", "#2e7d32");
}}

async function refreshSoloStats() {{
  // Solo actualiza estadísticas — NUNCA reconstruye el grid
  const res  = await fetch(`/api/footage/${{PERSONAJE}}`);
  const data = await res.json();
  renderStats(data.stats || {{}});
}}

cargar();
cargarPrompts();
setInterval(refreshSoloStats, 15000);

// ── Cola Nocturna ─────────────────────────────────────────────
window.toggleNightQueue = async function() {{
  const btn = document.getElementById('btn-night-queue');
  const inQueue = btn && btn.dataset.inQueue === '1';
  if (inQueue) {{
    if (!confirm('¿Quitar este video de la cola nocturna?')) return;
    const r = await fetch('/api/night_queue/remove', {{
      method: 'POST', headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify({{carpeta: PERSONAJE}})
    }});
    const d = await r.json();
    if (d.ok) {{
      toast('Removido de la cola nocturna', '#555');
      const b = document.getElementById('btn-night-queue');
      if (b) {{ b.textContent='🌙 Cola nocturna'; b.style.background='#1a1040'; b.style.color='#b39ddb'; b.style.border='1px solid #7c4dff'; b.dataset.inQueue='0'; }}
    }}
  }} else {{
    const nombre = document.title.replace('Dashboard — ','').trim() || PERSONAJE;
    const r = await fetch('/api/night_queue/add', {{
      method: 'POST', headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify({{personaje: PERSONAJE, nombre: nombre, carpeta: PERSONAJE}})
    }});
    const d = await r.json();
    if (d.ok) {{
      const msg = d.already ? d.msg : `🌙 En cola nocturna ✓ (${{d.total}} en total)`;
      toast(msg, '#1b5e20', 6000);
      const b = document.getElementById('btn-night-queue');
      if (b) {{ b.textContent='🌙 En cola nocturna ✓'; b.style.background='#0d2b0d'; b.style.color='#69f0ae'; b.style.border='1px solid #00c853'; b.dataset.inQueue='1'; }}
    }} else {{ alert('Error: ' + d.error); }}
  }}
}};

// FAB "Aprobar todos" — aparece cuando el header sale de vista
(function() {{
  const fab = document.getElementById('fab-aprobar');
  const header = document.getElementById('actions-top-header');
  if (!fab || !header) return;
  const obs = new IntersectionObserver(entries => {{
    fab.style.display = entries[0].isIntersecting ? 'none' : 'flex';
  }}, {{ threshold: 0 }});
  obs.observe(header);
}})();



// ── IntersectionObserver: lazy autoplay ──────────────────
const _isMobile = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0);

function _loadVideoSrc(v) {{
  // v.src devuelve URL absoluta aunque esté vacío; usar getAttribute
  if (!v.getAttribute('src') && v.dataset.src) {{
    v.setAttribute('src', v.dataset.src);
    v.load();
  }}
}}

const _videoObserver = new IntersectionObserver((entries) => {{
  entries.forEach(e => {{
    const v = e.target;
    if (e.isIntersecting) {{
      _loadVideoSrc(v);  // siempre cargar src al entrar viewport (mobile y desktop)
      if (!_isMobile && v.paused && !v._mouseOver) v.play().catch(()=>{{}});
    }} else {{
      if (!v.paused) {{ v.pause(); v.currentTime = 0; }}
    }}
  }});
}}, {{rootMargin: "400px", threshold: 0}});

function observeVideos() {{
  document.querySelectorAll("video.lazy-video").forEach(v => {{
    if (v._observed) return;
    v._observed  = true;
    v._mouseOver = false;
    if (_isMobile) {{
      // En mobile: tap para play/pause
      v.addEventListener("click", (e) => {{
        e.stopPropagation();
        _loadVideoSrc(v);
        if (v.paused) {{ v.play().catch(()=>{{}}); }} else {{ v.pause(); }}
      }});
    }} else {{
      v.addEventListener("mouseenter", () => {{ v._mouseOver = true; _loadVideoSrc(v); v.play().catch(()=>{{}}); }});
      v.addEventListener("mouseleave", () => {{ v._mouseOver = false; v.pause(); v.currentTime = 0; }});
    }}
    _videoObserver.observe(v);
  }});
}}

// ── Modal agregar clips ───────────────────────────────────
let _agSelected = {{}};  // url → item
let _agJobId    = null;
let _agJobPoller= null;


// ── Trimmer state ──────────────────────────────────────────────────────────
let _trimClipName = null;
let _trimClipType = "yt";   // "yt" o "footage"
let _trimPersonaje = null;
let _trimStart = 0;
let _trimEnd   = 0;

function abrirPreview(e, url, label, clipName, clipType, personaje) {{
  if (e.target.closest("button,textarea,input,select")) return;
  const modal = document.getElementById("modal-preview");
  const vid   = document.getElementById("preview-video");
  const lbl   = document.getElementById("preview-label");
  _trimClipName   = clipName   || null;
  _trimClipType   = clipType   || "yt";
  _trimPersonaje  = personaje  || PERSONAJE;
  vid.preload = "auto";
  vid.src = url;
  vid.load();
  lbl.textContent = label || "";
  modal.style.display = "flex";
  document.addEventListener("keydown", _previewEsc);
  vid.onloadedmetadata = () => {{
    _trimStart = 0;
    _trimEnd   = vid.duration;
    trimUpdateUI();
  }};
  vid.ontimeupdate = () => {{
    const bar = document.getElementById("trim-bar");
    const ph  = document.getElementById("trim-playhead");
    if (!bar || !ph || !vid.duration) return;
    ph.style.left = ((vid.currentTime / vid.duration) * bar.clientWidth) + "px";
    const info = document.getElementById("trim-info");
    if (info) {{
      const dur = (_trimEnd - _trimStart).toFixed(1);
      info.textContent = `▶ ${{vid.currentTime.toFixed(1)}}s  |  ✂ ${{_trimStart.toFixed(1)}}s → ${{_trimEnd.toFixed(1)}}s  (${{dur}}s)`;
    }}
  }};
  trimInitDrag();
}}

function trimUpdateUI() {{
  const vid = document.getElementById("preview-video");
  const bar = document.getElementById("trim-bar");
  if (!bar || !vid.duration) return;
  const w = bar.clientWidth;
  const pStart = (_trimStart / vid.duration) * w;
  const pEnd   = (_trimEnd   / vid.duration) * w;
  document.getElementById("trim-handle-start").style.left = pStart + "px";
  document.getElementById("trim-handle-end").style.right  = (w - pEnd) + "px";
  document.getElementById("trim-zone").style.left  = pStart + "px";
  document.getElementById("trim-zone").style.right = (w - pEnd) + "px";
  const info = document.getElementById("trim-info");
  if (info) {{
    const dur = (_trimEnd - _trimStart).toFixed(1);
    info.textContent = `▶ -  |  ✂ ${{_trimStart.toFixed(1)}}s → ${{_trimEnd.toFixed(1)}}s  (${{dur}}s)`;
  }}
}}

function trimInitDrag() {{
  const bar   = document.getElementById("trim-bar");
  const hs    = document.getElementById("trim-handle-start");
  const he    = document.getElementById("trim-handle-end");
  const vid   = document.getElementById("preview-video");
  const MIN_DUR = 2.5;
  function posToTime(px) {{
    return Math.max(0, Math.min(vid.duration, (px / bar.clientWidth) * vid.duration));
  }}
  function makeDrag(handle, isStart) {{
    handle.onmousedown = ev => {{
      ev.preventDefault();
      const rect = bar.getBoundingClientRect();
      function onMove(mv) {{
        const x = Math.max(0, Math.min(mv.clientX - rect.left, bar.clientWidth));
        const t = posToTime(x);
        if (isStart) {{
          _trimStart = Math.min(t, _trimEnd - MIN_DUR);
        }} else {{
          _trimEnd = Math.max(t, _trimStart + MIN_DUR);
        }}
        trimUpdateUI();
      }}
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", () => document.removeEventListener("mousemove", onMove), {{once:true}});
    }};
  }}
  makeDrag(hs, true);
  makeDrag(he, false);
}}

function trimPreview() {{
  const vid = document.getElementById("preview-video");
  vid.currentTime = _trimStart;
  vid.play();
  function stopAtEnd() {{
    if (vid.currentTime >= _trimEnd) {{ vid.pause(); vid.removeEventListener("timeupdate", stopAtEnd); }}
  }}
  vid.addEventListener("timeupdate", stopAtEnd);
}}

function trimReset() {{
  const vid = document.getElementById("preview-video");
  _trimStart = 0;
  _trimEnd   = vid.duration || 0;
  trimUpdateUI();
}}

async function trimSave() {{
  if (!_trimClipName) {{ alert("No hay clip seleccionado"); return; }}
  const dur = _trimEnd - _trimStart;
  if (dur < 2.5) {{ alert("Mínimo 2.5 segundos"); return; }}
  const btn = document.getElementById("trim-save-btn");
  btn.textContent = "Guardando…"; btn.disabled = true;
  try {{
    const r = await fetch(`/api/trim_clip/${{_trimPersonaje}}`, {{
      method: "POST",
      headers: {{"Content-Type":"application/json"}},
      body: JSON.stringify({{ clip: _trimClipName, start: _trimStart, end: _trimEnd, type: _trimClipType }})
    }});
    const d = await r.json();
    if (d.ok) {{
      btn.textContent = "✓ Guardado";
      setTimeout(() => {{ btn.textContent = "✂ Recortar y guardar"; btn.disabled = false; }}, 2000);
    }} else {{
      alert("Error: " + d.error);
      btn.textContent = "✂ Recortar y guardar"; btn.disabled = false;
    }}
  }} catch(err) {{
    alert("Error de red"); btn.textContent = "✂ Recortar y guardar"; btn.disabled = false;
  }}
}}

function cerrarPreview() {{
  const modal = document.getElementById("modal-preview");
  const vid   = document.getElementById("preview-video");
  vid.pause(); vid.src = "";
  modal.style.display = "none";
  document.removeEventListener("keydown", _previewEsc);
  _trimClipName = null;
}}
function _previewEsc(e) {{ if (e.key === "Escape") cerrarPreview(); }}

function abrirModalAgregar() {{
  _agSelected = {{}};
  document.getElementById("modal-agregar").style.display = "flex";
}}
function cerrarModalAgregar() {{
  document.getElementById("modal-agregar").style.display = "none";
  _agSelected = {{}};
}}
document.getElementById("modal-agregar").addEventListener("click", e => {{
  if (e.target === document.getElementById("modal-agregar")) cerrarModalAgregar();
}});

// Prevenir que el browser navegue a archivos soltados fuera del dropzone
document.addEventListener("dragover",  e => e.preventDefault());
document.addEventListener("drop",      e => e.preventDefault());

// Cuando estamos en tab-up, TODO el modal acepta el drop
const _modalAg = document.getElementById("modal-agregar");
_modalAg.addEventListener("dragover", e => {{
  e.preventDefault();
  const tabUp = document.getElementById("tab-up");
  if (tabUp && tabUp.style.display !== "none") {{
    const dz = document.getElementById("drop-zone");
    if (dz) dz.style.background = "#0d3030";
  }}
}});
_modalAg.addEventListener("dragleave", e => {{
  // Solo resetear si el cursor salió del modal completamente
  if (!_modalAg.contains(e.relatedTarget)) {{
    const dz = document.getElementById("drop-zone");
    if (dz) dz.style.background = "#0a2020";
  }}
}});
let _dropHandled = false;
_modalAg.addEventListener("drop", e => {{
  e.preventDefault();
  if (_dropHandled) return;
  _dropHandled = true;
  setTimeout(() => _dropHandled = false, 300);
  const tabUp = document.getElementById("tab-up");
  if (tabUp && tabUp.style.display !== "none") {{
    const dz = document.getElementById("drop-zone");
    if (dz) dz.style.background = "#0a2020";
    handleFileInput(e.dataTransfer.files);
  }}
}});

function switchTab(tab) {{
  document.querySelectorAll(".ag-tab").forEach(t => t.classList.toggle("active", t.dataset.tab===tab));
  document.querySelectorAll(".ag-tabcontent").forEach(t => t.style.display = t.id==="tab-"+tab ? "" : "none");
}}

// -- Imágenes --
async function buscarImagenes() {{
  const q   = document.getElementById("img-query").value.trim();
  const src = document.getElementById("img-source").value;
  if (!q) return;
  const r = await fetch(`/api/riq/search_images?q=${{encodeURIComponent(q)}}&source=${{src}}&count=24`);
  const d = await r.json();
  const res = document.getElementById("img-results");
  res.innerHTML = d.results.map(item => `
    <div class="ag-thumb-wrap ${{_agSelected[item.url]?'sel':''}}" onclick="toggleSelect(this,'${{item.url.replace(/'/g,"\\'")}}',${{JSON.stringify(JSON.stringify(item)).slice(1,-1)}})">
      <img class="ag-thumb ${{_agSelected[item.url]?'sel':''}}" src="${{item.thumb||item.url}}" loading="lazy" onerror="this.src=''">
      <div class="ag-check">✓</div>
    </div>`).join("");
  actualizarContador("img");
}}

function toggleSelect(wrap, url, itemJson) {{
  const item = JSON.parse(itemJson);
  if (_agSelected[url]) {{ delete _agSelected[url]; wrap.classList.remove("sel"); wrap.querySelector("img").classList.remove("sel"); }}
  else {{ _agSelected[url] = item; wrap.classList.add("sel"); wrap.querySelector("img").classList.add("sel"); }}
  actualizarContador("img"); actualizarContador("vid");
}}

function actualizarContador(tab) {{
  const n = Object.keys(_agSelected).length;
  const countEl = document.getElementById(tab+"-selected-count");
  const addBtn  = document.getElementById(tab+"-add-btn");
  if (countEl) countEl.textContent = n > 0 ? `${{n}} seleccionada(s)` : "";
  if (addBtn)  addBtn.style.display = n > 0 ? "" : "none";
}}

async function buscarVideosStock() {{
  const q = document.getElementById("vid-query").value.trim();
  if (!q) return;
  const r = await fetch(`/api/riq/search_videos?q=${{encodeURIComponent(q)}}&count=20`);
  const d = await r.json();
  const res = document.getElementById("vid-results");
  res.innerHTML = d.results.map(item => {{
    const sel = _agSelected[item.url] ? "sel" : "";
    const itemJ = JSON.stringify(JSON.stringify({{...item,tipo:"video"}})).slice(1,-1);
    return `<div class="ag-thumb-wrap ${{sel}}" onclick="toggleSelect(this,'${{item.url.replace(/'/g,"\\'")}}','${{itemJ}}')">
      <img class="ag-thumb ${{sel}}" src="${{item.thumb||''}}" loading="lazy" onerror="this.src=''">
      <div style="font-size:10px;color:#aaa;padding:2px 4px">${{item.duration||''}}s · ${{item.source}}</div>
      <div class="ag-check">✓</div>
    </div>`;
  }}).join("");
  actualizarContador("vid");
}}

async function agregarSeleccionadas(tipo) {{
  const items = Object.values(_agSelected).map(i => ({{...i, tipo: i.tipo||tipo}}));
  if (!items.length) return;
  const r = await fetch(`/api/riq/add_images/${{PERSONAJE}}`, {{
    method:"POST", headers:{{"Content-Type":"application/json"}},
    body: JSON.stringify({{items}})
  }});
  const d = await r.json();
  if (d.job_id) {{
    _agJobId = d.job_id;
    mostrarJobBar(`Procesando ${{d.total}} archivos…`);
    _agJobPoller = setInterval(pollJob, 2000);
  }}
  _agSelected = {{}};
  cerrarModalAgregar();
}}

// -- YouTube --
async function buscarYouTube() {{
  const q = document.getElementById("yt-query").value.trim();
  if (!q) return;
  const r = await fetch(`/api/riq/search_youtube?q=${{encodeURIComponent(q)}}&count=10`);
  const d = await r.json();
  const res = document.getElementById("yt-results");
  res.innerHTML = d.results.map(item => `
    <div style="display:flex;gap:10px;align-items:center;background:#1a1a1a;border-radius:8px;padding:8px;cursor:pointer"
         onclick="usarURLYoutube('${{item.url}}')">
      <img src="${{item.thumb}}" style="width:80px;height:45px;object-fit:cover;border-radius:5px" loading="lazy">
      <div style="flex:1;min-width:0">
        <div style="font-size:12px;color:#fff;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${{item.title}}</div>
        <div style="font-size:11px;color:#888">${{item.duration}}s</div>
      </div>
      <button style="background:#c62828;color:#fff;border:none;border-radius:5px;padding:5px 10px;font-size:11px;cursor:pointer;flex-shrink:0">Usar</button>
    </div>`).join("") || "<div style='color:#666;font-size:12px'>Sin resultados</div>";
}}

function usarURLYoutube(url) {{
  document.getElementById("yt-url").value = url;
}}

async function agregarYouTubeURL() {{
  const url     = document.getElementById("yt-url").value.trim();
  const n_clips = parseInt(document.getElementById("yt-url-nclips").value) || 20;
  if (!url) return;
  cerrarModalAgregar();
  mostrarJobBar("Iniciando descarga YouTube…");

  const r = await fetch(`/api/riq/add_youtube_url/${{PERSONAJE}}`, {{
    method:"POST", headers:{{"Content-Type":"application/json"}},
    body: JSON.stringify({{url, n_clips}})
  }});
  const d = await r.json();
  if (!d.ok || !d.job_id) {{
    if (bar) bar.textContent = "❌ Error al iniciar descarga";
    return;
  }}

  // Polling cada 3s hasta que termine
  const job_id = d.job_id;
  let dots = 0;
  const interval = setInterval(async () => {{
    try {{
      const sr = await fetch(`/api/riq/yt_dl_status/${{job_id}}`);
      const sd = await sr.json();
      dots = (dots + 1) % 4;
      const dotStr = ".".repeat(dots + 1);
      const lastLine = sd.last_log && sd.last_log.length ? sd.last_log[sd.last_log.length-1].replace(/\x1b\[[0-9;]*m/g,"") : "";
      const gbar = document.getElementById("global-job-bar");
      if (sd.done) {{
        clearInterval(interval);
        if (sd.error) {{
          if (gbar) gbar.textContent = `❌ Error: ${{sd.error}}`;
        }} else {{
          if (gbar) {{ gbar.textContent = `✅ ${{sd.added}} clips descargados`; ocultarJobBar(); }}
          setTimeout(() => location.reload(), 5000);
        }}
        toast(sd.error ? "❌ Error" : `✅ ${{sd.added}} clips agregados — recargando…`, sd.error?"#7f1d1d":"#2e7d32");
      }} else {{
        if (gbar) gbar.textContent = `⏳ Descargando${{dotStr}} ${{sd.added}} clips${{lastLine ? " — " + lastLine.slice(-60) : ""}}`;
      }}
    }} catch(e) {{ /* silenciar errores de red temporales */ }}
  }}, 3000);
}}

// -- Upload --
function handleDrop(e) {{
  e.preventDefault(); e.currentTarget.style.borderColor = "#555";
  handleFileInput(e.dataTransfer.files);
}}
function handleFileInput(files) {{
  const list = document.getElementById("upload-list");
  list.textContent = `${{files.length}} archivo(s): ${{Array.from(files).map(f=>f.name).join(", ")}}`;
  subirArchivos(files);
}}
async function subirArchivos(files) {{
  const fd = new FormData();
  Array.from(files).forEach(f => fd.append("files", f));
  cerrarModalAgregar();
  mostrarJobBar(`Subiendo ${{files.length}} archivo(s)…`);
  const r = await fetch(`/api/riq/upload_clips/${{PERSONAJE}}`, {{method:"POST", body:fd}});
  const d = await r.json();
  if (d.job_id) {{
    _agJobId = d.job_id;
    _agJobPoller = setInterval(pollJob, 2000);
  }} else {{
    const bar = document.getElementById("global-job-bar");
    if (bar) {{ bar.textContent = `✅ ${{d.added_mp4}} video(s) agregados`; ocultarJobBar(); }}
    toast(`✅ ${{d.added_mp4}} video(s) agregados — recargando…`, "#2e7d32");
    setTimeout(() => location.reload(), 3000);
  }}
}}

// -- Job polling --
function mostrarJobBar(msg) {{
  // Usar barra global (fuera del modal) para que persista cuando se cierra
  const bar = document.getElementById("global-job-bar");
  if (bar) {{ bar.style.display = ""; bar.textContent = "⏳ " + msg; }}
}}
function ocultarJobBar() {{
  const bar = document.getElementById("global-job-bar");
  if (bar) setTimeout(() => bar.style.display="none", 5000);
}}
async function pollJob() {{
  if (!_agJobId) return;
  const r = await fetch(`/api/riq/job_status/${{_agJobId}}`);
  const d = await r.json();
  const bar = document.getElementById("global-job-bar");
  if (bar) bar.textContent = `⏳ ${{d.msg}} (${{d.done}}/${{d.total}})`;
  if (d.status === "done") {{
    clearInterval(_agJobPoller); _agJobPoller = null; _agJobId = null;
    if (bar) {{ bar.textContent = `✅ ${{d.msg}}`; ocultarJobBar(); }}
    toast(`✅ ${{d.added}} clips agregados — recargá la página`, "#2e7d32");
    setTimeout(() => location.reload(), 5000);
  }}
}}
</script>
</body>
</html>"""


# ── Riqueza: búsqueda de imágenes ────────────────────────────────────────────

@app.route("/api/riq/search_images")
def riq_search_images():
    q      = request.args.get("q","")
    source = request.args.get("source","brave")
    count  = int(request.args.get("count",20))
    if not q: return jsonify({"results":[]})
    if source == "pexels":   results = _buscar_pexels_imgs(q, count)
    elif source == "pixabay": results = _buscar_pixabay_imgs(q, count)
    elif source == "photos":
        px = _buscar_pexels_imgs(q, count//2+2); pi = _buscar_pixabay_imgs(q, count//2+2)
        results = [x for pair in zip(px,pi) for x in pair][:count]
        if len(px)>len(pi): results += px[len(pi):]
        elif len(pi)>len(px): results += pi[len(px):]
    else: results = _buscar_brave(q, count)
    return jsonify({"results": results})


@app.route("/api/riq/search_youtube")
def riq_search_youtube():
    q     = request.args.get("q","")
    count = int(request.args.get("count",10))
    if not q: return jsonify({"results":[]})
    try:
        cmd = ["/opt/homebrew/bin/yt-dlp","--cookies-from-browser","brave",
               f"ytsearch{count}:{q}",
               "--print",'{"id":"%(id)s","title":"%(title)s","duration":%(duration)s,"thumb":"%(thumbnail)s"}',
               "--no-playlist","--skip-download","--quiet"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        results = []
        for line in r.stdout.strip().splitlines():
            try:
                item = json.loads(line)
                if item.get("id"):
                    results.append({"video_id":item["id"],"title":item.get("title",""),
                        "duration":item.get("duration",0),
                        "thumb":item.get("thumb",f"https://i.ytimg.com/vi/{item['id']}/mqdefault.jpg"),
                        "url":f"https://www.youtube.com/watch?v={item['id']}"})
            except Exception: continue
        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"results":[],"error":str(e)})


@app.route("/api/riq/search_videos")
def riq_search_videos():
    q      = request.args.get("q","")
    source = request.args.get("source","stock")
    count  = int(request.args.get("count",12))
    if not q: return jsonify({"results":[]})
    half = count//2+2
    px = _buscar_pexels_vids(q, half); pi = _buscar_pixabay_vids(q, half)
    results = [x for pair in zip(px,pi) for x in pair][:count]
    if len(px)>len(pi): results += px[len(pi):]
    elif len(pi)>len(px): results += pi[len(px):]
    return jsonify({"results": results})


_delete_yt_lock = threading.Lock()

@app.route("/api/riq/delete_yt_clip/<path:personaje>", methods=["POST"])
def riq_delete_yt_clip(personaje):
    """Rechaza clip YT: borra disco + marca metadata. Rápido — sin búsqueda iCloud."""
    body = request.json or {}
    clip = body.get("clip")
    if not clip:
        return jsonify({"ok": False, "error": "falta clip"}), 400
    carpeta   = BASE_DIR / personaje
    clips_dir = carpeta / "clips"

    def _do_delete():
        with _delete_yt_lock:
            import shutil as _sh
            clip_path = None
            for sub in ["yt", "google", ""]:
                p = (clips_dir / sub / clip) if sub else (clips_dir / clip)
                if p.exists():
                    clip_path = p
                    break
            if clip_path:
                borrados_dir = clips_dir / "borrados"
                borrados_dir.mkdir(exist_ok=True)
                _sh.move(str(clip_path), str(borrados_dir / clip))
            meta_path = carpeta / "metadata.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
            meta.setdefault("deleted_yt_clips", {})[clip] = True
            _save_meta(meta_path, meta)

    import threading
    threading.Thread(target=_do_delete, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/riq/clip_count/<path:personaje>")
def riq_clip_count(personaje):
    """Devuelve total de clips disponibles y cuántos se necesitan para el video."""
    import math as _math
    carpeta   = BASE_DIR / personaje
    clips_dir = carpeta / "clips"
    meta_path = carpeta / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    deleted  = set(meta.get("deleted_yt_clips", {}).keys()) | set(meta.get("removed_yt_cards", {}).keys())
    if clips_dir.exists():
        all_mp4 = list(clips_dir.glob("*.mp4"))
        for sub in ["yt", "google"]:
            d = clips_dir / sub
            if d.exists():
                all_mp4.extend(d.glob("*.mp4"))
        total = len([f for f in all_mp4 if f.name not in deleted])
    else:
        total = 0
    mp3s     = sorted([f for f in carpeta.glob("*.mp3") if "_test" not in f.name and "_src" not in f.name])
    audio_dur = 0.0
    if mp3s:
        try:
            r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                 "-of", "default=noprint_wrappers=1:nokey=1", str(mp3s[0])],
                               capture_output=True, text=True, timeout=5)
            audio_dur = float(r.stdout.strip())
        except Exception:
            pass
    needed = _math.ceil(audio_dur / 5) if audio_dur > 0 else 0
    return jsonify({"total": total, "needed": needed, "audio_dur": round(audio_dur, 1)})


@app.route("/api/riq/remove_yt_card/<path:personaje>", methods=["POST"])
def riq_remove_yt_card(personaje):
    """Elimina card del grid y mueve el archivo a clips/borrados/ para nunca reusar."""
    import shutil as _sh
    body = request.json or {}
    clip = body.get("clip")
    if not clip:
        return jsonify({"ok": False, "error": "falta clip"}), 400
    carpeta   = BASE_DIR / personaje
    clips_dir = carpeta / "clips"
    clip_path = clips_dir / clip
    # Mover a borrados/
    if clip_path.exists():
        borrados_dir = clips_dir / "borrados"
        borrados_dir.mkdir(exist_ok=True)
        _sh.move(str(clip_path), str(borrados_dir / clip))
    meta_path = carpeta / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    meta.setdefault("removed_yt_cards", {})[clip] = True
    meta.setdefault("deleted_yt_clips", {})[clip] = True
    grid = set(meta.get("clips_en_grid", []))
    grid.discard(clip)
    meta["clips_en_grid"] = list(grid)
    _save_meta(meta_path, meta)
    return jsonify({"ok": True})


@app.route("/api/riq/add_youtube_url/<path:personaje>", methods=["POST"])
def riq_add_youtube_url(personaje):
    """Lanza descarga de clips YouTube en background y devuelve job_id para polling."""
    data    = request.json or {}
    url     = data.get("url","")
    n_clips = int(data.get("n_clips",20))
    if not url: return jsonify({"error":"falta url"}), 400
    carpeta   = BASE_DIR / personaje
    clips_dir = carpeta / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    job_id = f"ytdl_{int(time.time()*1000)}"
    clips_antes = len(list(clips_dir.glob("*.mp4")))
    yt_dl_jobs[job_id] = {"done": False, "added": 0, "error": "", "log": [], "clips_antes": clips_antes, "clips_dir": clips_dir}

    def _run():
        script = BASE_DIR / "extraer_clips_video.py"
        try:
            proc = subprocess.Popen(
                ["python3", str(script), url, str(clips_dir), "--clips", str(n_clips), "--no-color", "--force-reencode"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    yt_dl_jobs[job_id]["log"].append(line)
                    yt_dl_jobs[job_id]["added"] = len(list(clips_dir.glob("*.mp4"))) - clips_antes
            proc.wait()
            yt_dl_jobs[job_id]["added"] = len(list(clips_dir.glob("*.mp4"))) - clips_antes
        except Exception as e:
            yt_dl_jobs[job_id]["error"] = str(e)
        finally:
            yt_dl_jobs[job_id]["done"] = True

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/riq/yt_dl_status/<job_id>")
def riq_yt_dl_status(job_id):
    """Polling de estado de descarga YouTube."""
    job = yt_dl_jobs.get(job_id)
    if not job: return jsonify({"error":"job no encontrado"}), 404
    last_lines = job["log"][-3:] if job["log"] else []
    return jsonify({"done": job["done"], "added": job["added"], "error": job["error"], "last_log": last_lines})


@app.route("/api/riq/upload_clips/<path:personaje>", methods=["POST"])
def riq_upload_clips(personaje):
    """Sube archivos directamente. MP4 → clips/. Imágenes → zoompan en background."""
    carpeta   = BASE_DIR / personaje
    clips_dir = carpeta / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    IMAGE_EXTS = {'.jpg','.jpeg','.png','.webp'}
    saved_vids = []; saved_imgs = []
    move_idx = sum(1 for f in clips_dir.glob("img_*_zp.mp4"))
    for f in request.files.getlist("files"):
        ext  = pathlib.Path(f.filename).suffix.lower() or ".jpg"
        h_id = abs(hash(f.filename + str(time.time()))) % 99999
        dest = clips_dir / f"added_{h_id:05d}{ext}"
        f.save(str(dest))
        if ext == '.mp4':
            saved_vids.append(dest)
        else:
            saved_imgs.append((dest, move_idx)); move_idx += 1
    # Zoompan imágenes en background — deduplicar por MD5 antes de procesar
    if saved_imgs:
        def _md5_file(p):
            h = hashlib.md5()
            with open(p,"rb") as fp:
                for chunk in iter(lambda: fp.read(65536), b""): h.update(chunk)
            return h.hexdigest()
        # MD5s de img_*_zp.mp4 ya existentes (para no duplicar)
        existing_hashes = set()
        for ef in clips_dir.glob("img_*_zp.mp4"):
            try: existing_hashes.add(_md5_file(ef))
            except Exception: pass
        # Deduplicar las nuevas entre sí y contra las existentes
        unique_imgs = []
        batch_hashes = set()
        for src, midx in saved_imgs:
            try: h = _md5_file(src)
            except Exception: h = None
            if h and (h in existing_hashes or h in batch_hashes):
                src.unlink(missing_ok=True)  # descartar duplicado
            else:
                if h: batch_hashes.add(h)
                unique_imgs.append((src, midx))
        job_id = hashlib.md5(f"riq_upload{personaje}{time.time()}".encode()).hexdigest()[:10]
        with _JOBS_LOCK:
            _JOBS[job_id] = {"status":"running","done":0,"total":len(unique_imgs),"added":0,"msg":"Iniciando…"}
        def _run(jid, items, cdir):
            added = 0
            for i,(src,midx) in enumerate(items):
                zp = cdir / f"img_{abs(hash(str(src)+str(time.time())))%99999:05d}_zp.mp4"
                with _JOBS_LOCK: _JOBS[jid].update({"done":i+1,"msg":f"zoompan {i+1}/{len(items)}…"})
                ok = _imagen_a_zoompan(src, zp, midx)
                if ok: src.unlink(missing_ok=True); added += 1
                else: src.unlink(missing_ok=True)
            with _JOBS_LOCK: _JOBS[jid].update({"status":"done","done":len(items),"added":added,"msg":f"✅ {added} listas"})
        threading.Thread(target=_run, args=(job_id, unique_imgs, clips_dir), daemon=True).start()
        return jsonify({"ok":True,"added_mp4":len(saved_vids),"job_id":job_id,"total_imgs":len(unique_imgs)})
    return jsonify({"ok":True,"added_mp4":len(saved_vids),"has_job":False})


@app.route("/api/riq/add_images/<path:personaje>", methods=["POST"])
def riq_add_images(personaje):
    """Descarga imágenes/videos de búsqueda y los convierte a zoompan en clips/."""
    data  = request.json or {}
    items = data.get("items",[])
    if not items: return jsonify({"error":"sin items"}), 400
    carpeta   = BASE_DIR / personaje
    clips_dir = carpeta / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    job_id = hashlib.md5(f"riq_imgs{personaje}{time.time()}".encode()).hexdigest()[:10]
    with _JOBS_LOCK:
        _JOBS[job_id] = {"status":"pending","done":0,"total":len(items),"added":0,"msg":"Iniciando…"}
    def _run(jid, itms, cdir):
        total = len(itms)
        move_idx = sum(1 for f in cdir.glob("img_*_zp.mp4"))
        added = 0
        with _JOBS_LOCK: _JOBS[jid]["status"] = "running"
        for i, itm in enumerate(itms):
            src_url = itm.get("url","")
            tipo    = itm.get("tipo","imagen")
            h_id    = abs(hash(src_url)) % 99999
            src_pfx = itm.get("source","web")
            with _JOBS_LOCK: _JOBS[jid].update({"done":i+1,"msg":f"descargando {i+1}/{total}…"})
            if tipo == "video":
                raw = cdir / f"vid_{src_pfx}_{h_id:05d}_raw.mp4"
                zp  = cdir / f"vid_{src_pfx}_{h_id:05d}_zp.mp4"
                if not raw.exists():
                    subprocess.run(["curl","-sL","--max-time","60","-A","Mozilla/5.0","-o",str(raw),src_url],
                                   capture_output=True, timeout=65)
                if not raw.exists() or raw.stat().st_size < 10000: raw.unlink(missing_ok=True); continue
                with _JOBS_LOCK: _JOBS[jid]["msg"] = f"cortando {i+1}/{total}…"
                if not zp.exists():
                    subprocess.run([FFMPEG,"-y","-i",str(raw),"-t","8",
                        "-vf","scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2:color=black",
                        "-c:v","libx264","-profile:v","baseline","-level","3.0","-pix_fmt","yuv420p",
                        "-an","-movflags","+faststart",str(zp)], capture_output=True, timeout=60)
                raw.unlink(missing_ok=True)
                if zp.exists() and zp.stat().st_size > 10000: added += 1
            else:
                img = cdir / f"img_{src_pfx}_{h_id:05d}.jpg"
                zp  = cdir / f"img_{src_pfx}_{h_id:05d}_zp.mp4"
                if not img.exists():
                    ok = _descargar_imagen(src_url, img)
                    if not ok: continue
                with _JOBS_LOCK: _JOBS[jid]["msg"] = f"zoompan {i+1}/{total}…"
                if not zp.exists():
                    ok = _imagen_a_zoompan(img, zp, move_idx)
                    if not ok: img.unlink(missing_ok=True); continue
                img.unlink(missing_ok=True); move_idx += 1; added += 1
            with _JOBS_LOCK: _JOBS[jid].update({"added":added,"msg":f"✅ {i+1}/{total}"})
        with _JOBS_LOCK: _JOBS[jid].update({"status":"done","done":total,"added":added,"msg":f"✅ {added}/{total} listos"})
    threading.Thread(target=_run, args=(job_id, items, clips_dir), daemon=True).start()
    return jsonify({"ok":True,"job_id":job_id,"total":len(items)})


@app.route("/api/riq/job_status/<job_id>")
def riq_job_status(job_id):
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if not job: return jsonify({"error":"job no encontrado"}), 404
    return jsonify(job)


@app.route("/api/riq/yt_clips/<path:personaje>")
def riq_yt_clips(personaje):
    """Lista clips de YouTube con conteo actualizado."""
    carpeta   = BASE_DIR / personaje
    clips_dir = carpeta / "clips"
    meta_path = carpeta / "metadata.json"
    deleted = {}
    if meta_path.exists():
        meta    = json.loads(meta_path.read_text(encoding="utf-8"))
        deleted = meta.get("deleted_yt_clips", {})
    if not clips_dir.exists(): return jsonify({"clips":[],"total":0})
    import re as _re
    def _idx(f):
        m = _re.search(r"(\d+)", f.stem); return int(m.group(1)) if m else 0
    files = sorted([f for f in clips_dir.glob("*.mp4") if f.name not in deleted], key=_idx)
    return jsonify({"clips":[f.name for f in files], "total":len(files)})


@app.route("/api/riq/save_order/<path:personaje>", methods=["POST"])
def riq_save_order(personaje):
    """Persiste el orden de clips YT tras drag & drop."""
    order = (request.json or {}).get("order", [])
    if not order: return jsonify({"ok": False})
    meta_path = BASE_DIR / personaje / "metadata.json"
    meta = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    # No sobreescribir si ya existe un orden guardado (shuffle previo o drag-drop explícito)
    force = (request.json or {}).get("force", False)
    if not meta.get("clips_order") or force:
        meta["clips_order"] = order
        _save_meta(meta_path, meta)
        return jsonify({"ok": True, "saved": True})
    return jsonify({"ok": True, "saved": False, "reason": "order already exists"})


@app.route("/api/riq/copy_to_icloud/<path:personaje>", methods=["POST"])
def riq_copy_to_icloud(personaje):
    nombre    = pathlib.Path(personaje).name
    clips_dir = BASE_DIR / personaje / "clips"
    if not clips_dir.exists():
        return jsonify({"ok": False, "error": "carpeta clips no existe"})
    existente = _buscar_icloud_artista(nombre)
    if existente:
        return jsonify({"ok": True, "skipped": True, "folder": str(existente)})
    def _run():
        res = _copiar_clips_a_icloud_bg(nombre, clips_dir)
        print(f"[iCloud backup] {nombre}: {res}", flush=True)
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "skipped": False, "started": True})


_render_done_state: dict = {}

@app.route("/api/render_done", methods=["POST"])
def api_render_done():
    data = request.json or {}
    _render_done_state.update(data)
    # Auto-copia a iCloud para personajes riqueza
    personaje = data.get("personaje", "")
    if personaje:
        nombre    = pathlib.Path(personaje).name
        clips_dir = BASE_DIR / personaje / "clips"
        if clips_dir.exists() and not _buscar_icloud_artista(nombre):
            def _run():
                res = _copiar_clips_a_icloud_bg(nombre, clips_dir)
                print(f"[render_done iCloud] {nombre}: {res}", flush=True)
            threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/logs")
def get_logs():
    entries = []
    for lf in sorted(LOGS_DIR.glob("*.jsonl"), reverse=True)[:3]:
        try:
            with open(lf, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entries.append(json.loads(line))
        except Exception:
            continue
    return jsonify(entries[-100:])


# ── Frontend embebido ─────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Canal Dashboard</title>
<style>
  :root {
    --bg: #0a0a0f;
    --surface: #12121a;
    --surface2: #1a1a26;
    --border: #2a2a3a;
    --text: #e0e0f0;
    --muted: #7070a0;
    --green: #00ff88;
    --yellow: #ffe66d;
    --red: #ff4466;
    --blue: #4ecdc4;
    --orange: #ff6b35;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: 'SF Mono', 'Courier New', monospace; font-size: 13px; }

  header { display: flex; align-items: center; justify-content: space-between; padding: 14px 24px;
    background: var(--surface); border-bottom: 1px solid var(--border); position: sticky; top: 0; z-index: 100; }
  header h1 { font-size: 16px; letter-spacing: 2px; color: var(--green); text-transform: uppercase; }
  .refresh-info { color: var(--muted); font-size: 11px; }

  .main { padding: 20px 24px; max-width: 1600px; margin: 0 auto; }

  .canal-section { margin-bottom: 40px; }
  .canal-header { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; padding-bottom: 10px; border-bottom: 1px solid var(--border); }
  .canal-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
  .canal-name { font-size: 15px; font-weight: bold; text-transform: uppercase; letter-spacing: 1px; }
  .canal-stats { color: var(--muted); font-size: 11px; }
  .badge-pending { background: var(--yellow); color: #000; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: bold; }

  .videos-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(460px, 1fr)); gap: 16px; }

  .video-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
  .video-card.estado-subido { border-color: #1a3a2a; }
  .video-card.estado-pendiente { border-color: #3a3a1a; }
  .video-card.estado-error { border-color: #3a1a1a; }

  .card-top { display: flex; gap: 10px; padding: 12px; }
  video.preview { width: 140px; height: 79px; object-fit: cover; border-radius: 6px; background: #000; flex-shrink: 0; }
  .card-meta { flex: 1; min-width: 0; }
  .card-title { font-size: 12px; font-weight: bold; line-height: 1.3; margin-bottom: 6px;
    overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
  .card-personaje { color: var(--muted); font-size: 11px; margin-bottom: 6px; }
  .estado-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 10px; font-weight: bold; text-transform: uppercase; }
  .estado-subido   .estado-badge { background: #0a3a1a; color: var(--green); border: 1px solid var(--green); }
  .estado-pendiente .estado-badge { background: #3a3a0a; color: var(--yellow); border: 1px solid var(--yellow); }
  .estado-error     .estado-badge { background: #3a0a0a; color: var(--red); border: 1px solid var(--red); }
  .yt-link { display: inline-block; margin-top: 4px; color: var(--red); font-size: 11px; text-decoration: none; }
  .yt-link:hover { color: #ff6688; }
  .subido-hace { display: block; margin-top: 4px; color: var(--muted); font-size: 10px; }

  .pipeline { display: flex; gap: 4px; padding: 8px 12px; background: var(--surface2); flex-wrap: wrap; }
  .step { padding: 2px 6px; border-radius: 4px; font-size: 10px; text-transform: uppercase; }
  .step.completado { background: #0a2a1a; color: var(--green); }
  .step.pendiente  { background: #2a2a0a; color: var(--yellow); }
  .step.error      { background: #2a0a0a; color: var(--red); }

  .thumbs { display: flex; gap: 8px; padding: 10px 12px; background: var(--surface2); overflow-x: auto; }
  .thumb-item { flex-shrink: 0; text-align: center; }
  .thumb-item img { width: 120px; height: 68px; object-fit: cover; border-radius: 4px;
    border: 2px solid var(--border); display: block; margin-bottom: 4px; cursor: pointer; transition: border-color 0.2s; }
  .thumb-item img:hover { border-color: var(--blue); }
  .thumb-item img.aprobada  { border-color: var(--green); }
  .thumb-item img.rechazada { border-color: var(--red); opacity: 0.5; }
  .thumb-btns { display: flex; gap: 4px; justify-content: center; flex-wrap: wrap; }
  .btn-mini { padding: 2px 6px; border-radius: 3px; font-size: 9px; cursor: pointer; border: none; font-family: inherit; }
  .btn-approve { background: #0a3a1a; color: var(--green); border: 1px solid var(--green); }
  .btn-reject  { background: #3a0a0a; color: var(--red); border: 1px solid var(--red); }
  .btn-regen   { background: #1a1a3a; color: var(--blue); border: 1px solid var(--blue); }
  .btn-regen.running { background: #0a0a2a; color: var(--muted); border-color: var(--muted); cursor: not-allowed; }
  .thumb-estado { font-size: 9px; color: var(--muted); margin-top: 2px; }

  .card-actions { display: flex; gap: 8px; padding: 10px 12px; border-top: 1px solid var(--border); }
  .btn { padding: 6px 14px; border-radius: 6px; font-size: 11px; cursor: pointer; border: none; font-family: inherit;
    text-transform: uppercase; letter-spacing: 0.5px; font-weight: bold; transition: opacity 0.2s; }
  .btn:hover { opacity: 0.8; }
  .btn-upload   { background: var(--green); color: #000; }
  .btn-uploading { background: var(--muted); color: #fff; cursor: not-allowed; }
  .btn-all { background: var(--orange); color: #000; font-size: 11px; }

  .uploading-bar { height: 3px; background: linear-gradient(90deg, var(--blue), var(--green));
    animation: slide 1.5s infinite; }
  @keyframes slide { 0%{transform:translateX(-100%)} 100%{transform:translateX(200%)} }

  .no-thumb { width: 120px; height: 68px; background: var(--surface2); border-radius: 4px;
    border: 1px dashed var(--border); display: flex; align-items: center; justify-content: center;
    color: var(--muted); font-size: 9px; }

  .empty { color: var(--muted); text-align: center; padding: 40px; }

  .logs-panel { position: fixed; bottom: 0; right: 0; width: 420px; max-height: 220px;
    background: var(--surface); border-top: 1px solid var(--border); border-left: 1px solid var(--border);
    overflow-y: auto; font-size: 10px; display: none; z-index: 200; }
  .logs-panel.open { display: block; }
  .log-entry { padding: 4px 10px; border-bottom: 1px solid var(--border); display: flex; gap: 8px; }
  .log-time  { color: var(--muted); flex-shrink: 0; }
  .log-canal { color: var(--blue); flex-shrink: 0; }
  .log-video { color: var(--yellow); flex-shrink: 0; max-width: 100px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .log-accion { color: var(--text); flex: 1; }
  .log-ok  { color: var(--green); }
  .log-err { color: var(--red); }

  .fab { position: fixed; bottom: 20px; right: 20px; background: var(--surface2); border: 1px solid var(--border);
    border-radius: 8px; padding: 8px 14px; cursor: pointer; font-size: 11px; color: var(--muted);
    z-index: 300; transition: color 0.2s; }
  .fab:hover { color: var(--text); }

  /* Modal selector de canal */
  .modal-overlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,0.7); z-index:500; align-items:center; justify-content:center; }
  .modal-overlay.open { display:flex; }
  .modal { background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:24px; min-width:320px; }
  .modal h3 { margin-bottom:16px; color:var(--blue); font-size:13px; text-transform:uppercase; letter-spacing:1px; }
  .modal select, .modal select option { background:var(--surface2); color:var(--text); border:1px solid var(--border); border-radius:6px; padding:6px 10px; width:100%; margin-bottom:10px; font-family:inherit; font-size:12px; }
  .modal-btns { display:flex; gap:8px; margin-top:16px; }
</style>
</head>
<body>

<header>
  <h1>⬡ Canal Dashboard</h1>
  <div class="refresh-info" id="refresh-info">Actualizando cada 30s</div>
</header>

<div class="main" id="main">
  <div class="empty">Cargando...</div>
</div>

<div class="logs-panel" id="logs-panel"></div>
<div class="fab" id="fab-logs" onclick="toggleLogs()">📋 Logs</div>

<!-- Modal selector de canal -->
<div class="modal-overlay" id="upload-modal">
  <div class="modal">
    <h3>Subir a YouTube</h3>
    <div style="font-size:11px;color:var(--muted);margin-bottom:12px" id="modal-personaje-label"></div>
    <label style="font-size:11px;color:var(--muted);display:block;margin-bottom:4px">Canal</label>
    <select id="modal-canal"></select>
    <label style="font-size:11px;color:var(--muted);display:block;margin-bottom:4px">Visibilidad</label>
    <select id="modal-privacidad">
      <option value="private">Privado</option>
      <option value="unlisted">No listado</option>
      <option value="public">Público</option>
    </select>
    <div class="modal-btns">
      <button class="btn btn-upload" onclick="confirmUpload()">Subir</button>
      <button class="btn" style="background:var(--surface2);color:var(--muted);border:1px solid var(--border)" onclick="closeModal()">Cancelar</button>
    </div>
  </div>
</div>

<!-- Modal regenerar miniatura -->
<div class="modal-overlay" id="regen-modal">
  <div class="modal">
    <h3>🔄 Regenerar Miniatura</h3>
    <div style="font-size:11px;color:var(--muted);margin-bottom:12px" id="regen-modal-label"></div>
    <label style="font-size:11px;color:var(--muted);display:block;margin-bottom:4px">Edad (años)</label>
    <input id="regen-edad" type="number" value="50" min="10" max="100"
      style="background:var(--surface2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:6px 10px;width:100%;margin-bottom:10px;font-family:inherit;font-size:12px">
    <label style="font-size:11px;color:var(--muted);display:block;margin-bottom:4px">Cifra (ej: 5 MILLONES)</label>
    <input id="regen-cifra" type="text" placeholder="5 MILLONES"
      style="background:var(--surface2);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:6px 10px;width:100%;margin-bottom:10px;font-family:inherit;font-size:12px">
    <label style="display:flex;align-items:center;gap:8px;font-size:11px;color:var(--muted);margin-bottom:4px;cursor:pointer">
      <input id="regen-mujer" type="checkbox" style="width:14px;height:14px"> Personaje mujer (--mujer)
    </label>
    <div class="modal-btns" style="margin-top:14px">
      <button class="btn btn-upload" onclick="confirmRegen()">Regenerar</button>
      <button class="btn" style="background:var(--surface2);color:var(--muted);border:1px solid var(--border)" onclick="closeRegenModal()">Cancelar</button>
    </div>
  </div>
</div>

<script>
const PIPELINE_LABELS = {
  titulo: "Título", guion: "Guion", audio: "Audio", subtitulos: "Subs",
  imagenes: "Imgs", video: "Video", miniaturas: "Minis", youtube: "YouTube"
};

let canalesData = [];
let uploadPollers = {};
let regenPollers  = {};
let canalesJson = [];
let modalPersonaje = null;
let regenTarget = null;  // {personaje, num}

async function loadCanalesJson() {
  const r = await fetch("/api/canales_json");
  canalesJson = await r.json();
  const sel = document.getElementById("modal-canal");
  sel.innerHTML = canalesJson.map(c => `<option value="${c}">${c.replace('.json','')}</option>`).join("");
}

let _lastStatusJson = null;
async function fetchStatus() {
  const r = await fetch("/api/status");
  const newData = await r.json();
  const newJson = JSON.stringify(newData);
  if (newJson !== _lastStatusJson) {
    _lastStatusJson = newJson;
    canalesData = newData;
    render();
  }
  document.getElementById("refresh-info").textContent = "Actualizado " + new Date().toLocaleTimeString("es");
}

function render() {
  const main = document.getElementById("main");
  if (!canalesData.length) { main.innerHTML = '<div class="empty">Sin videos con metadata.json</div>'; return; }
  main.innerHTML = canalesData.map((canal, ci) => renderCanal(canal, ci)).join("");
}

function renderCanal(canal, ci) {
  const vids = canal.videos.map(v => renderVideo(v, canal.color)).join("");
  return `
    <div class="canal-section">
      <div class="canal-header">
        <div class="canal-dot" style="background:${canal.color}"></div>
        <span class="canal-name" style="color:${canal.color}">${canal.nombre}</span>
        ${canal.pendientes > 0 ? `<span class="badge-pending">${canal.pendientes} pendientes</span>` : ""}
        ${canal.pendientes > 0 ? `
          <button class="btn btn-all" onclick="uploadAllModal('${canal.nombre}')">⬆ Subir todos los pendientes</button>
        ` : ""}
        <span class="canal-stats">${canal.videos.length} videos</span>
      </div>
      <div class="videos-grid">${vids}</div>
    </div>`;
}

function renderVideo(v, canalColor) {
  const estado    = v.estado || "pendiente";
  const personaje = v._carpeta;
  const uploading = v._uploading;

  // Pipeline
  const pipeline = v.pipeline || {};
  const pipelineHtml = Object.entries(PIPELINE_LABELS).map(([k, label]) => {
    const st = pipeline[k] || "pendiente";
    return `<span class="step ${st}" title="${k}">${label}</span>`;
  }).join("");

  // Miniaturas
  const miniEstados = v.miniaturas || {};
  const thumbsHtml = [1, 2, 3].map(n => {
    const key = `miniatura_${n}`;
    const hasFile = v._miniaturas_files && v._miniaturas_files.includes(key);
    const est = miniEstados[key] || "pendiente";
    const imgClass = (est === "aprobada" || est === "rechazada") ? est : "";
    const regenKey = `${personaje}|${n}`;
    const isRegening = regenPollers[regenKey] !== undefined;
    const needsRegen = !hasFile || est === "pendiente" || est === "rechazada" || est === "error";
    const regenBtnHtml = needsRegen
      ? `<button class="btn-mini btn-regen ${isRegening ? 'running' : ''}"
           onclick="regenThumb('${personaje}', ${n})" title="Regenerar miniatura ${n}">
           ${isRegening ? '⏳' : '🔄'}
         </button>` : "";
    if (hasFile) {
      return `
        <div class="thumb-item" id="thumb-${personaje.replace(/\//g,'-')}-${n}">
          <img src="/video/${personaje}/miniatura/${n}?t=${Date.now()}"
               class="${imgClass}"
               onclick="previewThumb('${personaje}', ${n})"
               title="Miniatura ${n}" loading="lazy">
          <div class="thumb-btns">
            <button class="btn-mini btn-approve" onclick="approveThumb('${personaje}', ${n})">✓</button>
            <button class="btn-mini btn-reject"  onclick="rejectThumb('${personaje}', ${n})">✗</button>
            ${regenBtnHtml}
          </div>
          <div class="thumb-estado">${est}</div>
        </div>`;
    } else {
      return `
        <div class="thumb-item" id="thumb-${personaje.replace(/\//g,'-')}-${n}">
          <div class="no-thumb">sin miniatura ${n}</div>
          <div class="thumb-btns" style="margin-top:4px">${regenBtnHtml}</div>
        </div>`;
    }
  }).join("");

  // Botón upload
  let uploadBtn = "";
  if (estado !== "subido") {
    if (uploading) {
      uploadBtn = `<button class="btn btn-uploading">Subiendo...</button>`;
    } else {
      uploadBtn = `<button class="btn btn-upload" onclick="uploadVideo('${personaje}','${v.canal||''}')">Subir a YouTube</button>`;
    }
  }

  // Link YouTube + tiempo relativo
  function timeAgo(isoStr) {
    if (!isoStr) return "";
    const diff = (Date.now() - new Date(isoStr)) / 1000;
    if (diff < 60)   return "hace un momento";
    if (diff < 3600) return `hace ${Math.floor(diff/60)} min`;
    if (diff < 86400) return `hace ${Math.floor(diff/3600)} h`;
    if (diff < 2592000) return `hace ${Math.floor(diff/86400)} días`;
    return `hace ${Math.floor(diff/2592000)} meses`;
  }
  const subidoHace = v.fecha_subida ? `<span class="subido-hace">🕐 ${timeAgo(v.fecha_subida)}</span>` : "";
  const ytLink = v.youtube_url
    ? `<a class="yt-link" href="${v.youtube_url}" target="_blank">▶ Ver en YouTube</a>` : "";

  return `
    <div class="video-card estado-${estado}" id="card-${personaje}">
      ${uploading ? '<div class="uploading-bar"></div>' : ""}
      <div class="card-top">
        ${v._has_mp4 ? `<video class="preview" src="/video/${personaje}/preview" muted playsinline
          onmouseover="this.play()" onmouseout="this.pause();this.currentTime=0"></video>` :
          '<div class="preview" style="background:#111;display:flex;align-items:center;justify-content:center;color:#555;font-size:10px">sin video</div>'}
        <div class="card-meta">
          <div class="card-title">${v.titulo || personaje}</div>
          <div class="card-personaje">${personaje}</div>
          <span class="estado-badge">${estado}</span>
          ${subidoHace}
          ${ytLink}
        </div>
      </div>
      <div class="pipeline">${pipelineHtml}</div>
      <div class="thumbs">${thumbsHtml}</div>
      <div class="card-actions">
        ${uploadBtn}
        ${v.youtube_url ? `<button class="btn" style="background:#1a1a2a;color:#888;border:1px solid #333"
          onclick="navigator.clipboard.writeText('${v.youtube_url}')">Copiar URL</button>` : ""}
      </div>
    </div>`;
}

async function approveThumb(personaje, num) {
  await fetch("/api/approve_thumbnail", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({personaje, num})
  });
  fetchStatus();
}

async function rejectThumb(personaje, num) {
  await fetch("/api/reject_thumbnail", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({personaje, num})
  });
  fetchStatus();
}

function openUploadModal(personaje, canalSugerido) {
  modalPersonaje = personaje;
  document.getElementById("modal-personaje-label").textContent = personaje;
  // Pre-seleccionar el canal del video si existe
  const sel = document.getElementById("modal-canal");
  for (let i = 0; i < sel.options.length; i++) {
    if (sel.options[i].value.toLowerCase().includes((canalSugerido||"").toLowerCase().replace(" ",""))) {
      sel.selectedIndex = i; break;
    }
  }
  document.getElementById("upload-modal").classList.add("open");
}

function closeModal() {
  document.getElementById("upload-modal").classList.remove("open");
  modalPersonaje = null;
  uploadAllCanal = null;
  // Asegurar que el botón siempre vuelve al handler de video individual
  const btn = document.querySelector("#upload-modal .btn-upload");
  if (btn) btn.setAttribute("onclick", "confirmUpload()");
}

async function confirmUpload() {
  if (!modalPersonaje) return;
  const personaje   = modalPersonaje;   // guardar antes de closeModal()
  const canal_json  = document.getElementById("modal-canal").value;
  const privacidad  = document.getElementById("modal-privacidad").value;
  closeModal();
  const r = await fetch(`/api/upload/${personaje}`, {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({canal_json, privacidad})
  });
  const d = await r.json();
  if (d.ok) { pollUpload(personaje); fetchStatus(); }
  else alert("Error: " + d.error);
}

function uploadVideo(personaje, canalSugerido) {
  openUploadModal(personaje, canalSugerido);
}

// uploadAll usa el modal — guarda el canal destino para confirmUploadAll
let uploadAllCanal = null;

function uploadAllModal(canal) {
  uploadAllCanal = canal;
  document.getElementById("modal-personaje-label").textContent = `Todos los pendientes de "${canal}"`;
  // Pre-seleccionar el canal que coincida con el nombre
  const sel = document.getElementById("modal-canal");
  for (let i = 0; i < sel.options.length; i++) {
    if (sel.options[i].value.toLowerCase().replace('.json','').includes(canal.toLowerCase().replace(/\s/g,""))) {
      sel.selectedIndex = i; break;
    }
  }
  // Cambiar el botón del modal a confirmUploadAll
  document.querySelector("#upload-modal .btn-upload").setAttribute("onclick", "confirmUploadAll()");
  document.getElementById("upload-modal").classList.add("open");
}

async function confirmUploadAll() {
  const canal       = uploadAllCanal;
  const canal_json  = document.getElementById("modal-canal").value;
  const privacidad  = document.getElementById("modal-privacidad").value;
  // Restaurar onclick normal
  document.querySelector("#upload-modal .btn-upload").setAttribute("onclick", "confirmUpload()");
  closeModal();
  if (!canal) return;
  await fetch(`/api/upload_all/${canal}`, {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({canal_json, privacidad})
  });
  fetchStatus();
  uploadAllCanal = null;
}

async function uploadAll(canal) {  // mantener por compatibilidad
  uploadAllModal(canal);
}

function pollUpload(personaje) {
  if (uploadPollers[personaje]) clearInterval(uploadPollers[personaje]);
  uploadPollers[personaje] = setInterval(async () => {
    const r = await fetch(`/api/upload_status/${personaje}`);
    const d = await r.json();
    if (!d.running) {
      clearInterval(uploadPollers[personaje]);
      delete uploadPollers[personaje];
      fetchStatus();
    }
  }, 5000);
}

function previewThumb(personaje, num) {
  window.open(`/video/${personaje}/miniatura/${num}`, "_blank");
}

function regenThumb(personaje, num) {
  regenTarget = {personaje, num};
  document.getElementById("regen-modal-label").textContent = `${personaje} — Miniatura ${num}`;
  // Intentar pre-rellenar género del video en canalesData
  let mujer = false;
  for (const canal of canalesData) {
    const vid = canal.videos.find(v => v._carpeta === personaje);
    if (vid) { mujer = (vid._mujer === true); break; }
  }
  document.getElementById("regen-mujer").checked = mujer;
  document.getElementById("regen-modal").classList.add("open");
}

function closeRegenModal() {
  document.getElementById("regen-modal").classList.remove("open");
  regenTarget = null;
}

async function confirmRegen() {
  if (!regenTarget) return;
  const {personaje, num} = regenTarget;
  const edad  = document.getElementById("regen-edad").value || "50";
  const cifra = document.getElementById("regen-cifra").value.trim();
  const mujer = document.getElementById("regen-mujer").checked;
  closeRegenModal();

  const r = await fetch(`/api/regen_thumbnail/${personaje}`, {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({num, edad, cifra, mujer})
  });
  const d = await r.json();
  if (d.ok) {
    pollRegen(personaje, num);
    fetchStatus();
  } else {
    alert("Error al regenerar: " + d.error);
  }
}

function pollRegen(personaje, num) {
  const key = `${personaje}|${num}`;
  if (regenPollers[key]) clearInterval(regenPollers[key]);
  regenPollers[key] = setInterval(async () => {
    const r = await fetch(`/api/regen_status/${personaje}/${num}`);
    const d = await r.json();
    if (!d.running) {
      clearInterval(regenPollers[key]);
      delete regenPollers[key];
      fetchStatus();
    }
  }, 8000);
}

async function toggleLogs() {
  const panel = document.getElementById("logs-panel");
  if (panel.classList.toggle("open")) {
    const r = await fetch("/logs");
    const logs = await r.json();
    panel.innerHTML = logs.reverse().map(e => `
      <div class="log-entry">
        <span class="log-time">${e.fecha.slice(11,19)}</span>
        <span class="log-canal">${e.canal}</span>
        <span class="log-video">${e.video}</span>
        <span class="log-accion">${e.accion}</span>
        <span class="${e.resultado === 'ok' ? 'log-ok' : 'log-err'}">${e.resultado}</span>
      </div>`).join("") || "<div style='padding:10px;color:#555'>Sin logs</div>";
  }
}

// Init
loadCanalesJson();
fetchStatus();
setInterval(fetchStatus, 30000);

// Cerrar modales al hacer clic afuera
document.getElementById("upload-modal").addEventListener("click", function(e){
  if (e.target === this) closeModal();
});
document.getElementById("regen-modal").addEventListener("click", function(e){
  if (e.target === this) closeRegenModal();
});
</script>
</body>
</html>"""


@app.route("/")
def index():
    return Response(HTML, mimetype="text/html")


# ── run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from socketserver import ThreadingMixIn
    from wsgiref.simple_server import WSGIServer, make_server

    class ThreadedWSGI(ThreadingMixIn, WSGIServer):
        daemon_threads = True

    import argparse as _ap
    _parser = _ap.ArgumentParser()
    _parser.add_argument("--canal", default=None)
    _parser.add_argument("--puerto", type=int, default=None)
    _args, _ = _parser.parse_known_args()

    _puerto = _args.puerto
    if not _puerto and _args.canal:
        try:
            _cfg = json.loads((BASE_DIR.parent / "_config" / f"{_args.canal}.json").read_text())
            _puerto = _cfg.get("dashboard", {}).get("puerto", 5001)
        except Exception:
            _puerto = 5001
    if not _puerto:
        _puerto = 5001

    print(f"\n{'='*50}")
    print(f"  CANAL DASHBOARD  →  http://localhost:{_puerto}")
    print(f"{'='*50}\n")
    server = make_server("0.0.0.0", _puerto, app, server_class=ThreadedWSGI)
    server.serve_forever()
