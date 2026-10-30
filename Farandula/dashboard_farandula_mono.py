#!/usr/bin/env python3
"""
dashboard_farandula_mono.py — Dashboard Formato 2 (single-artista).

Una sola sección unificada y cronológica:
  • Slots de clips_ref/ cada 7.5 s
  • Imágenes Flow (hook_images/) insertadas en el segundo exacto del hook_timeline.json

Uso:
    python3 Farandula/dashboard_farandula_mono.py "Farandula/LUCHA VILLA/"
    → http://localhost:5002

Mejoras v2:
  1. Sin botón Aceptar individual — solo global
  2. Rechazar clip: borrado físico + reemplazo automático no usado
  3. Clips repetidos marcados con badge naranja (van al final en el build inicial)
  4. Drag & drop para reordenar cards
  5. Aprobar todos → copia clips_ref a iCloud si no existe
  6. Rechazar imagen Flow: confirmar → buscar clip YouTube
  7. Stats de clips repetidos en el header
"""

import json, math, pathlib, subprocess, sys, random, shutil, tempfile, os, re
import threading
_STATE_LOCK = threading.Lock()
from http.server import SimpleHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from flask import Flask, jsonify, request, send_file, Response

app = Flask(__name__)

STATIC_PORT = 5003

def _start_static_server(folder: pathlib.Path):
    """Servidor estático threaded para clips — maneja cientos de requests simultáneos sin cuello de botella."""
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(folder), **kw)
        def log_message(self, *a): pass  # silencio
        def end_headers(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "public, max-age=3600")
            super().end_headers()
    class ThreadedServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True
    srv = ThreadedServer(("127.0.0.1", STATIC_PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

VIDEO_FOLDER    = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
STATE_FILE      = VIDEO_FOLDER / "mono_state.json"    if VIDEO_FOLDER else None
REJECTED_FILE   = VIDEO_FOLDER / "rejected_clips.json" if VIDEO_FOLDER else None

FFMPEG  = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"
YTDLP   = "/opt/homebrew/bin/yt-dlp"
SHOT_DUR = 7.5   # default; se recalcula en _detect_shot_dur() con la duración real de clips_ref/

ICLOUD_ARTISTAS = pathlib.Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Artistas"

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
try:
    from zoompan_clip import make_zoompan
    _HAS_ZOOMPAN = True
except ImportError:
    _HAS_ZOOMPAN = False


# ─── helpers ──────────────────────────────────────────────────────────────────

def get_duration(path):
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nokey=1:noprint_wrappers=1", str(path)],
            capture_output=True, text=True, timeout=10
        )
        return round(float(r.stdout.strip()), 2)
    except Exception:
        return 5.0

def make_thumb(src: pathlib.Path, thumb: pathlib.Path) -> bool:
    if thumb.exists():
        return True
    thumb.parent.mkdir(parents=True, exist_ok=True)
    ext = src.suffix.lower()
    if ext in ('.jpg', '.jpeg', '.png'):
        try:
            subprocess.run(
                [FFMPEG, "-y", "-i", str(src),
                 "-vf", "scale=320:180:force_original_aspect_ratio=decrease,"
                        "pad=320:180:(ow-iw)/2:(oh-ih)/2",
                 str(thumb)],
                capture_output=True, timeout=15
            )
            return thumb.exists()
        except Exception:
            return False
    try:
        subprocess.run(
            [FFMPEG, "-y", "-ss", "0.5", "-i", str(src),
             "-frames:v", "1",
             "-vf", "scale=320:180:force_original_aspect_ratio=decrease,"
                    "pad=320:180:(ow-iw)/2:(oh-ih)/2",
             str(thumb)],
            capture_output=True, timeout=15
        )
        return thumb.exists()
    except Exception:
        return False


# ─── construir timeline unificado ─────────────────────────────────────────────

def build_unified_timeline():
    """Devuelve lista de items cronológicos — imágenes Flow en su segundo exacto,
    clips_ref llenando TODOS los gaps (antes del primer Flow, entre Flows, y después del último)."""
    clips_dir  = VIDEO_FOLDER / "clips_ref"
    hook_dir   = VIDEO_FOLDER / "hook_images"
    audio_path = VIDEO_FOLDER / "audio.mp3"
    tl_path    = VIDEO_FOLDER / "hook_timeline.json"

    audio_dur = get_duration(audio_path) if audio_path.exists() else 1714.0

    # 1. Leer segmentos Flow del hook_timeline
    flow_segs = []
    if tl_path.exists():
        data = json.loads(tl_path.read_text())
        for seg in data.get("visual_timeline", []):
            sid = seg['segment_id']
            img_path = hook_dir / f"hook_{sid:04d}_zp.mp4"
            if not img_path.exists():
                img_path = hook_dir / f"hook_{sid:04d}.jpg"
            if not img_path.exists():
                continue
            flow_segs.append({
                "tipo":       "imagen",
                "start":      seg["start_seconds"],
                "end":        seg["end_seconds"],
                "duration":   seg["duration"],
                "img_name":   img_path.name,
                "segment_id": sid,
                "estado":     "pendiente",
                "repetido":   False,
                "covers":     seg.get("scene_description", seg.get("covers_text", "")),
            })
    flow_segs.sort(key=lambda s: s["start"])

    # 2. Clips_ref pool — excluir video_ref.mp4 y rechazados
    rejected_path = VIDEO_FOLDER / "rejected_clips.json"
    rejected_set = set()
    if rejected_path.exists():
        try:
            rejected_set = set(json.loads(rejected_path.read_text()))
        except Exception:
            pass

    clips = [c for c in sorted(clips_dir.glob("clip_*.mp4"))
             if c.name != "video_ref.mp4" and str(c) not in rejected_set] if clips_dir.exists() else []
    if not clips:
        clips = [c for c in sorted(clips_dir.glob("*.mp4"))
                 if c.name != "video_ref.mp4" and str(c) not in rejected_set] if clips_dir.exists() else []
    n_unique = len(clips)

    def fill_gap(cursor, gap_end, pool_i, result):
        """Llena [cursor, gap_end) con clips_ref de duración SHOT_DUR."""
        while cursor < gap_end - 0.5 and clips:
            clip     = clips[pool_i % n_unique]
            is_rep   = pool_i >= n_unique
            end      = min(round(cursor + SHOT_DUR, 2), gap_end)
            result.append({
                "tipo":     "clip",
                "start":    round(cursor, 2),
                "end":      end,
                "duration": round(end - cursor, 2),
                "path":     str(clip),
                "filename": clip.name,
                "estado":   "pendiente",
                "repetido": is_rep,
            })
            cursor  = end
            pool_i += 1
        return cursor, pool_i

    items     = []
    cursor    = 0.0
    pool_i    = 0

    for seg in flow_segs:
        # Gap antes de este Flow segment
        cursor, pool_i = fill_gap(cursor, seg["start"], pool_i, items)
        # Insertar el Flow segment
        items.append(seg)
        cursor = seg["end"]

    # Gap final — desde el último Flow hasta el fin del audio
    cursor, pool_i = fill_gap(cursor, audio_dur, pool_i, items)

    # Ordenar y renumerar
    items.sort(key=lambda x: x["start"])
    for i, it in enumerate(items):
        it["idx"] = i

    n_flow = sum(1 for it in items if it["tipo"] == "imagen")
    n_clip = sum(1 for it in items if it["tipo"] == "clip")
    print(f"✓ Timeline: {len(items)} items ({n_clip} clips + {n_flow} imágenes Flow)")
    return items


# ─── estado persistente ────────────────────────────────────────────────────────

def load_state() -> list:
    if STATE_FILE and STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return []

def save_state(items: list):
    with _STATE_LOCK:
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2))
        tmp.replace(STATE_FILE)

def load_rejected() -> set:
    """Historial persistente de paths rechazados — nunca se reasignan."""
    if REJECTED_FILE and REJECTED_FILE.exists():
        try:
            return set(json.loads(REJECTED_FILE.read_text()))
        except Exception:
            pass
    return set()

def save_rejected(paths: set):
    tmp = REJECTED_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(sorted(paths), ensure_ascii=False, indent=2))
    tmp.replace(REJECTED_FILE)

def add_rejected(path: str):
    if not path:
        return
    rejected = load_rejected()
    rejected.add(path)
    save_rejected(rejected)

ICLOUD_ARTISTAS = pathlib.Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Artistas"

def delete_from_icloud(filename: str):
    """Borra el clip de iCloud/Artistas si existe."""
    if not filename or not VIDEO_FOLDER:
        return
    personaje = VIDEO_FOLDER.name
    for icloud_dir in [ICLOUD_ARTISTAS / personaje, ICLOUD_ARTISTAS]:
        candidate = icloud_dir / filename
        if candidate.exists():
            try:
                candidate.unlink()
                print(f"[iCloud] Borrado: {candidate}")
            except Exception as e:
                print(f"[WARN] No se pudo borrar de iCloud {candidate}: {e}")

def sanitize_state(items: list) -> tuple[list, int]:
    """Detecta clips cuyo archivo ya no existe y asigna reemplazo del pool."""
    fixed = 0
    clips_dir = VIDEO_FOLDER / "clips_ref"
    rejected_history = load_rejected()
    all_clips = sorted([c for c in clips_dir.glob("clip_*.mp4")
                        if c.name != "video_ref.mp4" and str(c) not in rejected_history]) if clips_dir.exists() else []
    pool_i = 0

    for it in items:
        if it.get("tipo") == "clip" and it.get("path"):
            if not pathlib.Path(it["path"]).exists():
                # Buscar reemplazo disponible
                replacement = None
                for _ in range(len(all_clips)):
                    candidate = all_clips[pool_i % len(all_clips)] if all_clips else None
                    pool_i += 1
                    if candidate and candidate.exists() and str(candidate) not in rejected_history:
                        replacement = candidate
                        break
                if replacement:
                    it["path"]     = str(replacement)
                    it["filename"] = replacement.name
                    it["estado"]   = "pendiente"
                else:
                    it["estado"]   = "rechazado"
                    it["path"]     = ""
                    it["filename"] = ""
                fixed += 1
    return items, fixed

def restore_flow_positions(items: list) -> list:
    """Ordena todos los items por start_seconds — mantiene Flow cards en su posición cronológica."""
    result = sorted(items, key=lambda x: x.get("start", 0))
    for i, it in enumerate(result):
        it["idx"] = i
    return result

def get_or_build_state() -> list:
    with _STATE_LOCK:
        existing = load_state()
        if existing:
            items, fixed = sanitize_state(existing)
            if fixed:
                print(f"[sanitize] {fixed} slots reparados (archivo faltante en disco)")
            items = restore_flow_positions(items)
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2))
            tmp.replace(STATE_FILE)
            return items
        items = build_unified_timeline()
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2))
        tmp.replace(STATE_FILE)
        return items

def active_paths(items):
    """Paths de clips actualmente en uso (no rechazados)."""
    return {it.get("path", "") for it in items
            if it.get("tipo") in ("clip", "clip_yt") and it.get("estado") != "rechazado"}


# ─── rutas de archivos ────────────────────────────────────────────────────────

def _stream_video(p: pathlib.Path) -> Response:
    """Sirve un MP4 con soporte de Range requests para que el browser pueda hacer seek y reproducir completo."""
    file_size = p.stat().st_size
    range_header = request.headers.get("Range")

    if range_header:
        m = re.search(r"bytes=(\d+)-(\d*)", range_header)
        if m:
            byte_start = int(m.group(1))
            byte_end   = int(m.group(2)) if m.group(2) else file_size - 1
            byte_end   = min(byte_end, file_size - 1)
            chunk_len  = byte_end - byte_start + 1

            def generate():
                with open(str(p), "rb") as f:
                    f.seek(byte_start)
                    remaining = chunk_len
                    while remaining:
                        data = f.read(min(65536, remaining))
                        if not data:
                            break
                        remaining -= len(data)
                        yield data

            rv = Response(generate(), 206, mimetype="video/mp4", direct_passthrough=True)
            rv.headers["Content-Range"]  = f"bytes {byte_start}-{byte_end}/{file_size}"
            rv.headers["Accept-Ranges"]  = "bytes"
            rv.headers["Content-Length"] = str(chunk_len)
            return rv

    rv = Response(open(str(p), "rb"), 200, mimetype="video/mp4", direct_passthrough=True)
    rv.headers["Accept-Ranges"]  = "bytes"
    rv.headers["Content-Length"] = str(file_size)
    return rv

@app.route("/audio")
def serve_audio():
    p = VIDEO_FOLDER / "audio.mp3"
    if not p.exists():
        return "not found", 404
    return _stream_video(p)

@app.route("/clip")
def serve_clip():
    path = request.args.get("path", "")
    p = pathlib.Path(path)
    if not p.exists() or p.suffix.lower() != ".mp4":
        return "not found", 404
    return _stream_video(p)

@app.route("/hook_img")
def serve_hook_img():
    filename = request.args.get("filename", "")
    p = VIDEO_FOLDER / "hook_images" / filename
    if not p.exists():
        return "not found", 404
    if p.suffix.lower() == ".mp4":
        return _stream_video(p)
    return send_file(str(p), mimetype="image/jpeg")

@app.route("/thumb")
def serve_thumb():
    path = request.args.get("path", "")
    src = pathlib.Path(path)
    if not src.exists():
        return "not found", 404
    thumbs = VIDEO_FOLDER / "_thumbs_mono"
    thumb  = thumbs / (src.stem + "_th.jpg")
    make_thumb(src, thumb)
    if thumb.exists():
        return send_file(str(thumb), mimetype="image/jpeg")
    return send_file(str(src), mimetype="image/jpeg")

@app.route("/hook_thumb")
def serve_hook_thumb():
    filename = request.args.get("filename", "")
    src = VIDEO_FOLDER / "hook_images" / filename
    if not src.exists():
        return "not found", 404
    thumbs = VIDEO_FOLDER / "_thumbs_mono" / "_hook"
    thumb  = thumbs / (pathlib.Path(filename).stem + "_th.jpg")
    make_thumb(src, thumb)
    if thumb.exists():
        return send_file(str(thumb), mimetype="image/jpeg")
    return send_file(str(src), mimetype="image/jpeg")


# ─── API ──────────────────────────────────────────────────────────────────────

@app.route("/api/items")
def api_items():
    page     = int(request.args.get("page", 1))
    per_page = int(request.args.get("per", 80))
    items    = get_or_build_state()
    total    = len(items)
    start    = (page - 1) * per_page
    end      = start + per_page
    return jsonify({
        "total":   total,
        "page":    page,
        "pages":   math.ceil(total / per_page),
        "items":   items[start:end],
    })

@app.route("/api/rechazar", methods=["POST"])
def api_rechazar():
    """Rechaza un clip, lo borra físicamente y lo reemplaza por uno no usado."""
    data  = request.get_json()
    idx   = data.get("idx")
    items = get_or_build_state()

    target = next((it for it in items if it["idx"] == idx), None)
    if not target:
        return jsonify({"ok": False, "error": "not found"}), 404

    if target["tipo"] == "imagen":
        return jsonify({"ok": False, "error": "usa /api/rechazar_imagen para imágenes Flow"}), 400

    # Borrar archivo físicamente de clips_ref/ y de iCloud
    old_path     = pathlib.Path(target.get("path", ""))
    old_filename = target.get("filename", "")
    if old_path.exists():
        try:
            old_path.unlink()
        except Exception as e:
            print(f"[WARN] No se pudo borrar {old_path}: {e}")
    delete_from_icloud(old_filename)

    # Registrar en historial permanente de rechazados
    add_rejected(str(old_path) if old_path.name else "")

    # Marcar rechazados TODOS los slots que compartían el mismo archivo (repetidos)
    duplicates_fixed = 0
    if old_filename:
        for it in items:
            if it["idx"] != idx and it.get("filename") == old_filename:
                it["estado"]   = "rechazado"
                it["path"]     = ""
                it["filename"] = ""
                it["repetido"] = False
                duplicates_fixed += 1
    if duplicates_fixed:
        print(f"[rechazar] {duplicates_fixed} slots duplicados marcados rechazados")

    # Buscar reemplazo — excluir los ya en uso Y el historial de rechazados
    rejected_history = load_rejected()
    used = active_paths(items)
    used.discard(target.get("path", ""))  # el rechazado ya no cuenta
    never_use = used | rejected_history

    clips_dir = VIDEO_FOLDER / "clips_ref"
    all_clips = sorted(clips_dir.glob("clip_*.mp4")) if clips_dir.exists() else []
    if not all_clips:
        all_clips = sorted(clips_dir.glob("*.mp4")) if clips_dir.exists() else []

    # Clips existentes en disco que nunca han sido rechazados
    existing_clips = [c for c in all_clips if c.exists() and str(c) not in rejected_history]
    available      = [c for c in existing_clips if str(c) not in used]

    if not existing_clips:
        target["estado"] = "rechazado"
        target["path"]   = ""
        target["filename"] = ""
        save_state(items)
        return jsonify({"ok": True, "replaced": False, "reload": True})

    if available:
        # Clips únicos disponibles → asignar directo, sin marcar repetido
        nuevo = random.choice(available)
        target["path"]     = str(nuevo)
        target["filename"] = nuevo.name
        target["estado"]   = "pendiente"
        target["repetido"] = False
        save_state(items)
        # Si había duplicados afectados → reload completo para reflejar todos los cambios
        needs_reload = duplicates_fixed > 0
        return jsonify({"ok": True, "replaced": True,
                        "new_path": str(nuevo), "new_filename": nuevo.name,
                        "repetido": False, "reload": needs_reload})

    # Pool agotado — estrategia "rotar al final":
    # Tomamos el clip del ÚLTIMO slot posterior en el timeline,
    # lo usamos aquí (no repetido), y el último slot recibe el reciclado.
    target_pos  = next(i for i, it in enumerate(items) if it["idx"] == idx)
    later_clips = [it for i, it in enumerate(items)
                   if i > target_pos
                   and it.get("tipo") == "clip"
                   and it.get("estado") != "rechazado"]

    if later_clips:
        last_item = later_clips[-1]
        # El slot actual toma el clip del último slot posterior (único allí)
        target["path"]        = last_item["path"]
        target["filename"]    = last_item["filename"]
        target["estado"]      = "pendiente"
        target["repetido"]    = False
        # El último slot recibe el clip reciclado (repetido al final)
        recycle_pool          = existing_clips if existing_clips else all_clips
        recycle               = random.choice(recycle_pool)
        last_item["path"]     = str(recycle)
        last_item["filename"] = recycle.name
        last_item["repetido"] = True
    else:
        # El target ya ES el último slot → aquí sí cabe el repetido
        recycle_pool       = existing_clips if existing_clips else all_clips
        recycle            = random.choice(recycle_pool)
        target["path"]     = str(recycle)
        target["filename"] = recycle.name
        target["estado"]   = "pendiente"
        target["repetido"] = True

    save_state(items)
    return jsonify({"ok": True, "replaced": True,
                    "new_path": target["path"], "new_filename": target["filename"],
                    "repetido": target["repetido"], "reload": True})

@app.route("/api/rechazar_imagen", methods=["POST"])
def api_rechazar_imagen():
    """Rechaza imagen Flow y la reemplaza con un clip de clips_ref/ no usado aún."""
    data  = request.get_json()
    idx   = data.get("idx")
    items = get_or_build_state()

    target = next((it for it in items if it["idx"] == idx), None)
    if not target or target.get("tipo") != "imagen":
        return jsonify({"ok": False, "error": "not found"}), 404

    clips_dir = VIDEO_FOLDER / "clips_ref"
    if not clips_dir.exists():
        return jsonify({"ok": False, "error": "clips_ref/ no encontrada"}), 500

    # Clips ya en uso o rechazados
    used = {it.get("clip_name", "") for it in items if it.get("tipo") == "clip"}
    rejected_set = load_rejected()

    all_clips = sorted(clips_dir.glob("clip_*.mp4"))
    replacement = None
    for c in all_clips:
        if c.name not in used and str(c) not in rejected_set:
            replacement = c
            break

    # Si todos usados, reciclar cualquier clip no rechazado
    if replacement is None:
        for c in all_clips:
            if str(c) not in rejected_set:
                replacement = c
                break

    if replacement is None:
        return jsonify({"ok": False, "error": "No quedan clips disponibles en clips_ref/"}), 500

    # Reemplazar item: imagen → clip
    target["tipo"]       = "clip"
    target["clip_name"]  = replacement.name
    target["path"]       = str(replacement)
    target["filename"]   = replacement.name
    target["img_name"]   = ""
    target["estado"]     = "pendiente"
    target["repetido"]   = False
    save_state(items)
    return jsonify({"ok": True, "clip": replacement.name})

@app.route("/api/aprobar_todos", methods=["POST"])
def api_aprobar_todos():
    items = get_or_build_state()
    for item in items:
        if item["estado"] == "pendiente":
            item["estado"] = "aprobado"
    save_state(items)
    aprobados = sum(1 for i in items if i["estado"] == "aprobado")

    # Copiar clips_ref a iCloud si no existe aún
    icloud_ok  = False
    icloud_msg = ""
    personaje  = VIDEO_FOLDER.name
    icloud_target = ICLOUD_ARTISTAS / personaje
    if not icloud_target.exists():
        clips_dir = VIDEO_FOLDER / "clips_ref"
        if clips_dir.exists():
            try:
                shutil.copytree(str(clips_dir), str(icloud_target))
                icloud_ok  = True
                icloud_msg = f"Clips copiados a iCloud/Artistas/{personaje}/"
            except Exception as e:
                icloud_msg = f"Error copiando a iCloud: {e}"
        else:
            icloud_msg = "clips_ref/ no encontrada"
    else:
        icloud_ok  = True
        icloud_msg = f"Ya existe en iCloud/Artistas/{personaje}/"

    return jsonify({"ok": True, "aprobados": aprobados,
                    "icloud": icloud_ok, "icloud_msg": icloud_msg})

@app.route("/api/reorder", methods=["POST"])
def api_reorder():
    """Mueve un item a la posición de otro (insert before drop)."""
    data     = request.get_json()
    drag_idx = data.get("drag_idx")
    drop_idx = data.get("drop_idx")
    items    = get_or_build_state()

    pos_drag = next((i for i, it in enumerate(items) if it["idx"] == drag_idx), None)
    pos_drop = next((i for i, it in enumerate(items) if it["idx"] == drop_idx), None)

    drag_item = next((it for it in items if it["idx"] == drag_idx), None)
    drop_item = next((it for it in items if it["idx"] == drop_idx), None)
    # Bloquear: no mover cards Flow, no dropar sobre cards Flow
    if (drag_item and drag_item.get("tipo") == "imagen") or \
       (drop_item and drop_item.get("tipo") == "imagen"):
        return jsonify({"ok": False, "error": "cards Flow son inmovibles"})

    if pos_drag is not None and pos_drop is not None and pos_drag != pos_drop:

        item_to_move = items.pop(pos_drag)
        pos_drop_new = next((i for i, it in enumerate(items) if it["idx"] == drop_idx), pos_drop)
        items.insert(pos_drop_new, item_to_move)
        save_state(items)

    return jsonify({"ok": True})

@app.route("/api/stats")
def api_stats():
    items     = get_or_build_state()
    total     = len(items)
    aprobados = sum(1 for i in items if i["estado"] == "aprobado")
    rechazados= sum(1 for i in items if i["estado"] == "rechazado")
    imagenes  = sum(1 for i in items if i["tipo"] == "imagen")
    repetidos = sum(1 for i in items
                    if i.get("repetido") and i["tipo"] == "clip" and i["estado"] != "rechazado")
    return jsonify({
        "total":        total,
        "aprobados":    aprobados,
        "rechazados":   rechazados,
        "pendientes":   total - aprobados - rechazados,
        "imagenes_flow": imagenes,
        "repetidos":    repetidos,
    })


# ─── UI ──────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Dashboard Mono — Farandula</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#111;color:#eee;font-family:sans-serif;font-size:13px}
  header{background:#1a1a2e;padding:12px 20px;display:flex;align-items:center;gap:14px;position:sticky;top:0;z-index:100;border-bottom:1px solid #333;flex-wrap:wrap}
  header h1{font-size:16px;color:#a78bfa;white-space:nowrap}
  .stats{display:flex;gap:10px;font-size:12px;flex-wrap:wrap}
  .stat{background:#222;padding:4px 10px;border-radius:20px;white-space:nowrap}
  .stat.ok{color:#4ade80}.stat.warn{color:#facc15}.stat.err{color:#f87171}
  .stat.flow{color:#818cf8}.stat.rep{color:#fb923c}
  .btn{cursor:pointer;padding:5px 14px;border:none;border-radius:6px;font-size:12px;font-weight:600}
  .btn-aprobar-todos{background:#4f46e5;color:#fff}
  .btn-aprobar-todos:hover{background:#4338ca}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;padding:16px}
  .card{background:#1e1e2e;border-radius:8px;overflow:hidden;border:2px solid #333;position:relative;transition:border-color .2s;cursor:grab}
  .card:active{cursor:grabbing}
  .card.drag-over{border-color:#818cf8;box-shadow:0 0 12px #818cf880}
  .card.dragging{opacity:.4}
  .card.aprobado{border-color:#4ade80}
  .card.rechazado{border-color:#f87171;opacity:.5}
  .card.imagen-flow{border-color:#818cf8}
  .card.imagen-flow.aprobado{border-color:#a5b4fc}
  .card.repetido-clip{border-color:#fb923c}
  .thumb-wrap{width:100%;aspect-ratio:16/9;background:#000;position:relative;overflow:hidden;cursor:zoom-in}
  .thumb-wrap img,.thumb-wrap video{width:100%;height:100%;object-fit:cover;display:block}
  .badge{position:absolute;top:4px;left:4px;font-size:10px;font-weight:700;padding:2px 6px;border-radius:4px;text-transform:uppercase}
  .badge-flow{background:#818cf8;color:#fff}
  .badge-clip{background:#374151;color:#aaa}
  .badge-rep{background:#fb923c;color:#fff;top:4px;left:4px}
  .ts{position:absolute;bottom:4px;right:4px;font-size:10px;background:rgba(0,0,0,.7);padding:2px 5px;border-radius:3px;color:#d1d5db}
  .card-body{padding:6px 8px}
  .trigger{font-size:10px;color:#a5b4fc;font-weight:700;text-transform:uppercase;margin-bottom:3px}
  .covers{font-size:10px;color:#9ca3af;line-height:1.3;max-height:32px;overflow:hidden}
  .card-actions{display:flex;gap:6px;padding:6px 8px;border-top:1px solid #2d2d3d}
  .btn-re{background:#ef4444;color:#fff;flex:1;padding:5px 10px;border:none;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer}
  .btn-re:hover{background:#dc2626}
  .pagination{display:flex;justify-content:center;gap:8px;padding:20px}
  .pg-btn{background:#374151;color:#eee;padding:6px 14px;border-radius:6px;border:none;cursor:pointer}
  .pg-btn:hover{background:#4b5563}
  .pg-btn.active{background:#4f46e5}
  .slot-num{font-size:10px;color:#6b7280;padding:3px 8px 0}
  #loading{position:fixed;inset:0;background:rgba(0,0,0,.8);display:flex;align-items:center;justify-content:center;font-size:20px;z-index:999}
  #modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.88);z-index:1000;align-items:center;justify-content:center;flex-direction:column;gap:12px}
  #modal.open{display:flex}
  #modal-video{max-width:90vw;max-height:80vh;border-radius:10px;outline:none;background:#000}
  #modal-close{position:absolute;top:16px;right:22px;font-size:28px;cursor:pointer;color:#fff;line-height:1;opacity:.7}
  #modal-close:hover{opacity:1}
  #modal-info{font-size:13px;color:#9ca3af;text-align:center}
  #yt-loading{display:none;position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:1100;align-items:center;justify-content:center;flex-direction:column;gap:16px}
  #yt-loading.open{display:flex}
  .spinner{width:48px;height:48px;border:5px solid #333;border-top-color:#818cf8;border-radius:50%;animation:spin .8s linear infinite}
  @keyframes spin{to{transform:rotate(360deg)}}
  .toast{position:fixed;bottom:24px;right:24px;background:#1f2937;border:1px solid #374151;border-radius:8px;padding:10px 18px;font-size:13px;z-index:2000;max-width:340px;transition:opacity .4s}
  .toast.ok{border-color:#4ade80;color:#4ade80}
  .toast.err{border-color:#f87171;color:#f87171}
  .toast.info{border-color:#818cf8;color:#818cf8}
</style>
</head>
<body>
<div id="loading">Cargando timeline...</div>

<div id="yt-loading">
  <div class="spinner"></div>
  <div style="color:#818cf8;font-size:15px">Buscando clip en YouTube...</div>
  <div style="color:#6b7280;font-size:12px">Esto puede tardar hasta 2 minutos</div>
</div>

<header>
  <h1>📽 Farandula Mono</h1>
  <div class="stats" id="stats"></div>
  <audio controls style="height:28px;min-width:220px;max-width:340px;flex-shrink:0" src="/audio">
    Tu browser no soporta audio.
  </audio>
  <button class="btn btn-aprobar-todos" onclick="aprobarTodos()">✓ Aprobar todos</button>
  <div style="margin-left:auto;font-size:12px;color:#6b7280" id="pg-info"></div>
</header>

<div id="modal" onclick="closeModal(event)">
  <span id="modal-close" onclick="closeModal()">✕</span>
  <video id="modal-video" controls autoplay muted loop playsinline></video>
  <div id="modal-info"></div>
</div>

<div class="grid" id="grid"></div>
<div class="pagination" id="pagination"></div>

<script>
const STATIC_BASE = '__STATIC_BASE__';
let currentPage = 1;
let totalPages  = 1;
const PER = 80;
let draggedIdx = null;

function fmt(s){
  const m=Math.floor(s/60), sec=Math.floor(s%60);
  return `${m}:${String(sec).padStart(2,'0')}`;
}

function showToast(msg, type='ok', ms=3000){
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => { t.style.opacity='0'; setTimeout(()=>t.remove(),400); }, ms);
}

async function loadStats(){
  const r = await fetch('/api/stats');
  const d = await r.json();
  let html = `
    <span class="stat">${d.total} slots</span>
    <span class="stat ok">✓ ${d.aprobados}</span>
    <span class="stat warn">⏳ ${d.pendientes}</span>
    <span class="stat err">✗ ${d.rechazados}</span>
    <span class="stat flow">🖼 ${d.imagenes_flow} Flow</span>`;
  if(d.repetidos > 0){
    html += `<span class="stat rep">🔁 ${d.repetidos} repetidos</span>`;
  }
  document.getElementById('stats').innerHTML = html;
}

async function loadPage(page){
  currentPage = page;
  const r = await fetch(`/api/items?page=${page}&per=${PER}`);
  const d = await r.json();
  totalPages = d.pages;
  document.getElementById('pg-info').textContent = `Pág ${page} / ${totalPages}`;
  renderGrid(d.items);
  renderPagination();
  document.getElementById('loading').style.display='none';
}

function renderGrid(items){
  const grid = document.getElementById('grid');
  grid.innerHTML = '';
  items.forEach(item => buildCard(item, grid));
}

function buildCard(item, grid){
  const isImagen  = item.tipo === 'imagen';
  const isClipYt  = item.tipo === 'clip_yt';
  const isRep     = item.repetido && !isImagen;

  const card = document.createElement('div');
  card.className = 'card'
    + (isImagen ? ' imagen-flow' : '')
    + (item.estado === 'aprobado' ? ' aprobado' : '')
    + (item.estado === 'rechazado' ? ' rechazado' : '')
    + (isRep ? ' repetido-clip' : '');
  card.id = `card-${item.idx}`;
  card.dataset.idx = item.idx;

  if(isImagen){
    // Cards Flow: bloqueados — no se pueden mover ni recibir drops
    card.draggable = false;
    card.style.cursor = 'default';
    card.title = 'Flow — posición fija en el render';
  } else {
    card.draggable = true;

    card.addEventListener('dragstart', e => {
      draggedIdx = item.idx;
      card.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
    });
    card.addEventListener('dragend', () => {
      card.classList.remove('dragging');
      draggedIdx = null;
      document.querySelectorAll('.drag-over').forEach(c => c.classList.remove('drag-over'));
    });
    card.addEventListener('dragover', e => {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      if(draggedIdx !== item.idx) card.classList.add('drag-over');
    });
    card.addEventListener('dragleave', () => card.classList.remove('drag-over'));
    card.addEventListener('drop', async e => {
      e.preventDefault();
      card.classList.remove('drag-over');
      if(draggedIdx === null || draggedIdx === item.idx) return;
      await fetch('/api/reorder', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({drag_idx: draggedIdx, drop_idx: item.idx})
      });
      draggedIdx = null;
      loadPage(currentPage);
    });
  } // fin else (no imagen)

  // Media
  let mediaHtml = '';
  let videoSrcForModal = '';
  let modalLabel = '';

  if(isImagen){
    const zpName = item.img_name.replace('.jpg','_zp.mp4');
    const zpSrc  = `${STATIC_BASE}/hook_images/${encodeURIComponent(zpName)}`;
    const jpgSrc = `${STATIC_BASE}/hook_images/${encodeURIComponent(item.img_name)}`;
    mediaHtml = `<video autoplay muted loop playsinline preload="auto" src="${zpSrc}" onerror="this.outerHTML='<img src=\\'${jpgSrc}\\'>'"></video>`;
    videoSrcForModal = zpSrc;
    modalLabel = `${item.trigger||'Flow'} · ${fmt(item.start)}–${fmt(item.end)}`;
  } else if(isClipYt){
    const src = `${STATIC_BASE}/clips_ref/${encodeURIComponent(item.filename)}`;
    mediaHtml = `<video autoplay muted loop playsinline preload="auto" src="${src}"></video>`;
    videoSrcForModal = src;
    modalLabel = `clip YT · ${fmt(item.start)}–${fmt(item.end)}`;
  } else {
    const src = `${STATIC_BASE}/clips_ref/${encodeURIComponent(item.filename)}`;
    mediaHtml = `<video autoplay muted loop playsinline preload="auto" src="${src}"></video>`;
    videoSrcForModal = src;
    modalLabel = `clip · ${fmt(item.start)}–${fmt(item.end)}`;
  }

  // Badge principal
  let badge = '';
  if(isRep){
    badge = `<span class="badge badge-rep">🔁 REPETIDO</span>`;
  } else if(isImagen){
    badge = `<span class="badge badge-flow">🖼 Flow</span>`;
  } else if(isClipYt){
    badge = `<span class="badge badge-flow" style="background:#22c55e">▶ YT</span>`;
  } else {
    badge = `<span class="badge badge-clip">clip</span>`;
  }
  const ts = `<span class="ts">${fmt(item.start)}–${fmt(item.end)}</span>`;

  // Body
  let bodyHtml = `<div class="slot-num">#${item.idx + 1}</div>`;
  if(isImagen){
    bodyHtml += `<div class="card-body">
      <div class="trigger">${item.trigger||''}</div>
      <div class="covers">${item.covers||''}</div>
    </div>`;
  }

  // Actions — sin botón Aprobar individual
  let actions = '';
  if(item.estado === 'rechazado' && !item.filename){
    // Slot vacío sin clip — mostrar botón para asignar reemplazo
    actions = `<div class="card-actions">
      <button class="btn-re" style="background:#f59e0b" onclick="rechazar(${item.idx})">↺ Asignar clip</button>
    </div>`;
  } else if(item.estado !== 'rechazado'){
    if(isImagen){
      actions = `<div class="card-actions">
        <button class="btn-re" onclick="rechazarImagen(${item.idx})">✗ Rechazar imagen</button>
      </div>`;
    } else {
      actions = `<div class="card-actions">
        <button class="btn-re" onclick="rechazar(${item.idx})">✗</button>
      </div>`;
    }
  }

  card.innerHTML = `
    <div class="thumb-wrap" onclick="openModal('${videoSrcForModal}','${modalLabel}')">${mediaHtml}${badge}${ts}</div>
    ${bodyHtml}
    ${actions}
  `;
  grid.appendChild(card);
}

function renderPagination(){
  const pg = document.getElementById('pagination');
  pg.innerHTML = '';
  const mkBtn = (label, page, active) => {
    const b = document.createElement('button');
    b.className = 'pg-btn' + (active ? ' active' : '');
    b.textContent = label;
    b.onclick = () => { loadPage(page); window.scrollTo(0,0); };
    return b;
  };
  if(currentPage > 1) pg.appendChild(mkBtn('‹ Anterior', currentPage-1));
  for(let p = Math.max(1,currentPage-2); p <= Math.min(totalPages, currentPage+2); p++){
    pg.appendChild(mkBtn(p, p, p === currentPage));
  }
  if(currentPage < totalPages) pg.appendChild(mkBtn('Siguiente ›', currentPage+1));
}

async function rechazar(idx){
  const r = await fetch('/api/rechazar', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({idx})
  });
  const d = await r.json();

  if(!d.replaced){
    showToast('No hay clips disponibles para reemplazar', 'err');
    const card = document.getElementById(`card-${idx}`);
    if(card) card.classList.add('rechazado');
    loadStats();
    return;
  }

  if(d.reload){
    // Hubo movimiento de dos cards (repetido empujado al final) → recargar
    await loadPage(currentPage);
  } else {
    // Reemplazo simple en el mismo slot → actualizar solo esa card
    const card = document.getElementById(`card-${idx}`);
    if(card){
      let video = card.querySelector('video');
      if(video && d.new_filename){
        const newSrc = `${STATIC_BASE}/clips_ref/${encodeURIComponent(d.new_filename)}?_t=${Date.now()}`;
        video.pause();
        video.src = newSrc;
        video.load();
        video.play().catch(()=>{});
        // Actualizar también el onclick del thumb-wrap para que el modal abra el clip correcto
        const tw = card.querySelector('.thumb-wrap');
        if(tw) tw.setAttribute('onclick', `openModal('${newSrc}','clip · reemplazado')`);
      }
      card.classList.remove('rechazado','aprobado','repetido-clip');
      const badge = card.querySelector('.badge');
      if(badge){ badge.className='badge badge-clip'; badge.textContent='clip'; }
    }
  }
  loadStats();
}

async function rechazarImagen(idx){
  const ok = confirm(
    '¿Estás seguro de rechazar esta imagen Flow?\n\n' +
    'Se buscará un clip de YouTube para reemplazarla.\n' +
    'Esto puede tardar 1-2 minutos.'
  );
  if(!ok) return;

  document.getElementById('yt-loading').classList.add('open');
  try {
    const r = await fetch('/api/rechazar_imagen', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({idx})
    });
    const d = await r.json();
    document.getElementById('yt-loading').classList.remove('open');

    if(d.ok){
      showToast('✓ Clip de YouTube asignado', 'ok', 4000);
      loadPage(currentPage);
      loadStats();
    } else {
      showToast(`Error: ${d.error}`, 'err', 5000);
    }
  } catch(e){
    document.getElementById('yt-loading').classList.remove('open');
    showToast('Error de conexión', 'err');
  }
}

function openModal(src, label){
  const modal = document.getElementById('modal');
  const mv    = document.getElementById('modal-video');
  document.getElementById('modal-info').textContent = label;
  mv.src = src;
  mv.load();
  mv.play().catch(()=>{});
  modal.classList.add('open');
}
function closeModal(e){
  if(e && e.target !== document.getElementById('modal') && e.target !== document.getElementById('modal-close')) return;
  const mv = document.getElementById('modal-video');
  mv.pause(); mv.src = '';
  document.getElementById('modal').classList.remove('open');
}
document.addEventListener('keydown', e => {
  if(e.key === 'Escape') closeModal({target: document.getElementById('modal')});
});

async function aprobarTodos(){
  if(!confirm('¿Aprobar todos los pendientes?')) return;
  const r = await fetch('/api/aprobar_todos', {method:'POST'});
  const d = await r.json();
  await loadPage(currentPage);
  loadStats();
  showToast(d.icloud_msg, d.icloud ? 'ok' : 'err', 5000);
}

loadStats();
loadPage(1);
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return HTML.replace("__STATIC_BASE__", f"http://127.0.0.1:{STATIC_PORT}")


# ─── main ─────────────────────────────────────────────────────────────────────

def _detect_shot_dur() -> float:
    """El render consume cada clip a su duración NATURAL, no a un slot fijo.
    Si el dashboard dimensiona el timeline con otra duración crea menos slots
    de los que el render necesita, y el render termina reciclando clips en
    silencio. Derivamos SHOT_DUR de la duración real de clips_ref/."""
    clips_dir = VIDEO_FOLDER / "clips_ref"
    muestras = sorted(clips_dir.glob("clip_*.mp4"))[:15] if clips_dir.exists() else []
    durs = [d for d in (get_duration(c) for c in muestras) if d and d > 0.5]
    if not durs:
        return SHOT_DUR
    durs.sort()
    return round(durs[len(durs) // 2], 2)


if __name__ == "__main__":
    if not VIDEO_FOLDER:
        print("Uso: python3 dashboard_farandula_mono.py 'Farandula/NOMBRE/'")
        sys.exit(1)

    _detected = _detect_shot_dur()
    if abs(_detected - SHOT_DUR) > 0.05:
        print(f"✓ SHOT_DUR ajustado {SHOT_DUR}s → {_detected}s (duración real de clips_ref/)")
        SHOT_DUR = _detected

    items    = get_or_build_state()
    imagenes = sum(1 for i in items if i["tipo"] == "imagen")
    clips    = sum(1 for i in items if i["tipo"] == "clip")
    repetidos= sum(1 for i in items if i.get("repetido") and i["tipo"] == "clip")
    print(f"✓ Timeline: {len(items)} items ({clips} clips + {imagenes} imágenes Flow, {repetidos} repetidos)")
    print(f"  Abre http://localhost:5002")

    _start_static_server(VIDEO_FOLDER)
    print(f"  Servidor estático clips: http://127.0.0.1:{STATIC_PORT}/")

    app.run(host="0.0.0.0", port=5002, debug=False, threaded=True)
