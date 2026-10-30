#!/usr/bin/env python3
"""
harvester_seduccion.py — Genera/descarga imágenes para cada segmento del timeline.json.

Lee 05-montaje/timeline.json → por cada segmento genera/busca imagen según source_order
del canal → anima con Ken Burns → guarda en 03-imagenes/ → actualiza metadata.json.

Source order se configura en seduccion/config.json:
  ["ia"]                     → todo IA (default Enigma Estoica)
  ["pexels","pixabay","ia"]  → stock primero, IA como fallback

Uso:
    python3 harvester_seduccion.py seduccion/7_errores/
    python3 harvester_seduccion.py seduccion/7_errores/ --desde 50   (reanudar desde segmento 50)
"""

import sys, json, time, subprocess, urllib.request, urllib.error, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from zoompan_clip import make_zoompan  # NUNCA reescribir zoompan inline — z=1.5 fijo

FFMPEG  = "/opt/homebrew/bin/ffmpeg"
if not pathlib.Path(FFMPEG).exists():
    FFMPEG = "/usr/local/bin/ffmpeg"

HOME           = pathlib.Path.home()
MUAPI_KEY_FILE = HOME / ".muapi_key"
PEXELS_KEY_FILE  = HOME / ".pexels_key"
PIXABAY_KEY_FILE = HOME / ".pixabay_key"
BRAVE_KEY_FILE   = HOME / ".brave_key"

MUAPI_BASE   = "https://api.muapi.ai/api/v1"
CLIP_SECS    = 6
IMG_W, IMG_H = 1024, 576

VERDE    = "\033[92m"
ROJO     = "\033[91m"
AMARILLO = "\033[93m"
RESET    = "\033[0m"

def ok(msg):   print(f"  {VERDE}✓{RESET} {msg}")
def err(msg):  print(f"  {ROJO}✗{RESET} {msg}")
def warn(msg): print(f"  {AMARILLO}⚠{RESET} {msg}")

# ── Keys ──────────────────────────────────────────────────────────────────────

def leer_key(path):
    try:
        return pathlib.Path(path).read_text().strip()
    except Exception:
        return None

# ── Metadata ──────────────────────────────────────────────────────────────────

def cargar_metadata(carpeta):
    p = carpeta / "metadata.json"
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
    else:
        data = {}
    data.setdefault("footage", {})
    return data

def guardar_metadata(carpeta, meta):
    p = carpeta / "metadata.json"
    p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

# ── muapi.ai IA ───────────────────────────────────────────────────────────────

def generar_imagen_ia(prompt, api_key):
    payload = json.dumps({"prompt": prompt, "width": IMG_W, "height": IMG_H}).encode()
    req = urllib.request.Request(
        f"{MUAPI_BASE}/flux-schnell-image",
        data=payload,
        headers={"Content-Type": "application/json", "x-api-key": api_key},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read())
    task_id = resp.get("request_id") or resp.get("data", {}).get("id")
    if not task_id:
        raise RuntimeError(f"Sin task_id: {resp}")

    poll_url = f"{MUAPI_BASE}/predictions/{task_id}/result"
    for _ in range(20):
        time.sleep(6)
        with urllib.request.urlopen(
            urllib.request.Request(poll_url, headers={"x-api-key": api_key}), timeout=20
        ) as r2:
            data = json.loads(r2.read())
        d = data.get("data", data)
        if d.get("status") == "completed":
            outputs = d.get("outputs", [])
            if outputs:
                return outputs[0]
        if d.get("status") == "failed":
            raise RuntimeError(f"IA falló: {d.get('error')}")
    raise TimeoutError("muapi no completó en 120s")

# ── Pexels ────────────────────────────────────────────────────────────────────

def buscar_pexels(query, api_key):
    import urllib.parse
    url = f"https://api.pexels.com/videos/search?query={urllib.parse.quote(query)}&per_page=5&size=medium"
    req = urllib.request.Request(url, headers={"Authorization": api_key})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    videos = data.get("videos", [])
    for v in videos:
        for f in v.get("video_files", []):
            if f.get("width", 0) >= 1280:
                return f["link"]
    return None

# ── Pixabay ───────────────────────────────────────────────────────────────────

def buscar_pixabay(query, api_key):
    import urllib.parse
    url = (f"https://pixabay.com/api/videos/?key={api_key}"
           f"&q={urllib.parse.quote(query)}&per_page=5&video_type=film")
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.loads(r.read())
    hits = data.get("hits", [])
    for h in hits:
        videos = h.get("videos", {})
        for quality in ["large", "medium"]:
            v = videos.get(quality)
            if v and v.get("width", 0) >= 1280:
                return v["url"]
    return None

# ── Descarga URL → archivo ────────────────────────────────────────────────────

def descargar_url(url, dest):
    r = subprocess.run(["curl", "-sL", "-o", str(dest), url], timeout=60, capture_output=True)
    return r.returncode == 0 and dest.stat().st_size > 1000

# ── Ken Burns sobre imagen estática ──────────────────────────────────────────

def imagen_a_clip(img_path, dst, duracion=CLIP_SECS, index=0):
    return make_zoompan(pathlib.Path(img_path), pathlib.Path(dst), duracion, index=index)

# ── Normalizar clip de video (Pexels/Pixabay) ────────────────────────────────

def normalizar_clip(src, dst, duracion=CLIP_SECS):
    r = subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", str(src), "-t", str(duracion),
        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,"
               "pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-an", "-y", str(dst)
    ], capture_output=True)
    return r.returncode == 0

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 harvester_seduccion.py <carpeta_video> [--desde N]")
        sys.exit(1)

    carpeta    = pathlib.Path(sys.argv[1])
    nombre     = carpeta.name
    desde      = 0
    hasta      = None
    if "--desde" in sys.argv:
        idx = sys.argv.index("--desde")
        desde = int(sys.argv[idx + 1])
    if "--hasta" in sys.argv:
        idx = sys.argv.index("--hasta")
        hasta = int(sys.argv[idx + 1])

    timeline_f = carpeta / "05-montaje" / "timeline.json"
    img_dir    = carpeta / "03-imagenes"
    img_dir.mkdir(parents=True, exist_ok=True)

    if not timeline_f.exists():
        print(f"ERROR: No existe {timeline_f}"); sys.exit(1)

    # Config de canal (source_order)
    config_f = carpeta.parent.parent / "_config" / f"{carpeta.parent.name}.json"
    source_order = ["ia"]
    if config_f.exists():
        cfg = json.loads(config_f.read_text(encoding="utf-8"))
        source_order = cfg.get("source_order", ["ia"])

    # Keys
    muapi_key   = leer_key(MUAPI_KEY_FILE)
    pexels_key  = leer_key(PEXELS_KEY_FILE)
    pixabay_key = leer_key(PIXABAY_KEY_FILE)

    # Timeline
    data     = json.loads(timeline_f.read_text(encoding="utf-8"))
    segments = data["visual_timeline"]
    meta     = cargar_metadata(carpeta)

    total = len(segments)
    print(f"\n{'='*60}")
    print(f"  HARVESTER SEDUCCIÓN — {nombre.upper()}")
    rango_str = f"{desde}–{hasta}" if hasta else f"{desde}–{total}"
    print(f"  Segmentos: {total} | Rango: {rango_str} | Fuentes: {source_order}")
    print(f"{'='*60}\n")

    generadas = 0
    errores   = 0

    for seg in segments:
        idx      = seg.get("segment_id", 0)
        if idx < desde:
            continue
        if hasta is not None and idx > hasta:
            break

        clip_name = f"img_{idx:04d}.mp4"
        img_name  = f"img_{idx:04d}.png"
        clip_path = img_dir / clip_name
        img_path  = img_dir / img_name
        prompt    = seg.get("prompt_or_query", "")
        source    = seg.get("source", "ia_stickfigure")
        start_s   = seg.get("start_seconds", 0)
        desc      = seg.get("scene_description_es", "")[:50]

        # Si ya existe y está aprobado, saltar
        estado_previo = meta["footage"].get(clip_name, {}).get("estado")
        if clip_path.exists() and estado_previo == "aprobado":
            ok(f"[{idx}/{total}] {clip_name} — ya aprobado")
            continue

        print(f"  [{idx:03d}/{total}] {start_s:.1f}s — {desc}")

        fuente_usada = None
        exito        = False

        for fuente in source_order:

            # ── IA (muapi.ai flux-schnell) ────────────────────────────────
            if fuente == "ia":
                if not muapi_key:
                    warn("Sin muapi key"); continue
                try:
                    img_url = generar_imagen_ia(prompt, muapi_key)
                    if descargar_url(img_url, img_path):
                        if imagen_a_clip(img_path, clip_path, index=idx):
                            fuente_usada = "ia"
                            exito = True
                            ok(f"  IA → {clip_name}")
                            break
                except Exception as e:
                    warn(f"  IA falló: {e}")

            # ── Pexels ────────────────────────────────────────────────────
            elif fuente == "pexels":
                if not pexels_key:
                    warn("Sin pexels key"); continue
                try:
                    video_url = buscar_pexels(prompt[:80], pexels_key)
                    if video_url:
                        tmp = img_dir / f"_tmp_{idx:04d}.mp4"
                        if descargar_url(video_url, tmp):
                            if normalizar_clip(tmp, clip_path):
                                tmp.unlink(missing_ok=True)
                                fuente_usada = "pexels"
                                exito = True
                                ok(f"  Pexels → {clip_name}")
                                break
                except Exception as e:
                    warn(f"  Pexels falló: {e}")

            # ── Pixabay ───────────────────────────────────────────────────
            elif fuente == "pixabay":
                if not pixabay_key:
                    warn("Sin pixabay key"); continue
                try:
                    video_url = buscar_pixabay(prompt[:80], pixabay_key)
                    if video_url:
                        tmp = img_dir / f"_tmp_{idx:04d}.mp4"
                        if descargar_url(video_url, tmp):
                            if normalizar_clip(tmp, clip_path):
                                tmp.unlink(missing_ok=True)
                                fuente_usada = "pixabay"
                                exito = True
                                ok(f"  Pixabay → {clip_name}")
                                break
                except Exception as e:
                    warn(f"  Pixabay falló: {e}")

        # Actualizar metadata
        if exito:
            meta["footage"][clip_name] = {
                "estado":      "pendiente",
                "fuente":      fuente_usada,
                "keywords":    prompt[:100],
                "start_s":     start_s,
                "descripcion": desc,
                "segment_id":  idx,
            }
            generadas += 1
        else:
            meta["footage"][clip_name] = {
                "estado":   "error",
                "fuente":   "ninguna",
                "keywords": prompt[:100],
                "start_s":  start_s,
            }
            err(f"  FALLÓ: {clip_name}")
            errores += 1

        guardar_metadata(carpeta, meta)

    print(f"\n{'='*60}")
    print(f"  ✓ Generadas: {generadas} | ✗ Errores: {errores}")
    print(f"  Imágenes en: {img_dir}")
    print(f"  Abrí el dashboard para aprobar visualmente antes del render.")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()
