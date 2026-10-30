#!/usr/bin/env python3
"""
harvester_clips_futbol.py — Harvester de clips e imágenes para canal de fútbol.

Flujo completo:
  1. Descarga y extrae clips limpios (sin subs/logo) del video de referencia
  2. Extrae frames clave como imágenes para zoompan
  3. Lee SRT primeros 10 min + timeline.json → manda prompts realistas a Baserow (Flow)
  4. Pre-asigna clips de clips/ a los 5 bloques narrativos con anti-repeat
  5. Genera dashboard_meta.json para aprobación en dashboard_futbol.py

Uso:
  cd ~/Downloads/Canales
  # Con URL (extrae clips del video)
  python3 harvester_clips_futbol.py futbol/batistuta/ --url "https://youtube.com/watch?v=XXX"
  # Sin URL (usa clips/ ya existentes)
  python3 harvester_clips_futbol.py futbol/batistuta/
"""

import sys, json, math, random, pathlib, re, subprocess, argparse, urllib.request, urllib.parse, gzip, time

YTDLP    = "/opt/homebrew/bin/yt-dlp"
FFMPEG   = "/opt/homebrew/bin/ffmpeg"
FFPROBE  = "/opt/homebrew/bin/ffprobe"
HOME     = pathlib.Path.home()

BRAVE_KEY_FILE   = HOME / ".brave_key"
BASEROW_TOKEN    = '4QrZH5MkTLHKtGqTG97Gz2yQTAIhknMq'
BASEROW_TABLE_ID = '1100194'
BASEROW_API_BASE = 'https://api.baserow.io/api'

SHOT_DUR     = 7.5   # duración de cada slot
EXTRA        = 3     # slots extra por bloque
SRT_MAX_SECS = 600   # primeros 10 min para análisis Flow
CLIP_DUR     = 5     # segundos por clip extraído
FRAMES_PER_BATCH = 30  # frames a extraer como imágenes
IMG_EXTS     = {'.jpg', '.jpeg', '.png', '.webp'}

# ─── 5 bloques narrativos (futbol.md) ─────────────────────────────────────────

BLOQUES = [
    {"id": "hook",      "nombre": "Hook / Contraste",    "desde": 0.000, "hasta": 0.125},
    {"id": "casa",      "nombre": "La Casa / Vida",       "desde": 0.125, "hasta": 0.500},
    {"id": "origen",    "nombre": "Historia de Origen",   "desde": 0.500, "hasta": 0.813},
    {"id": "emocional", "nombre": "Momento Emocional",    "desde": 0.813, "hasta": 0.938},
    {"id": "cierre",    "nombre": "Cierre Filosófico",    "desde": 0.938, "hasta": 1.000},
]

# Prioridad de fuentes por bloque
FUENTES_PRIORIDAD = {
    "hook":      ["clips", "imagenes_web", "frames_extraidos"],
    "casa":      ["imagenes", "frames_extraidos", "imagenes_web", "clips"],
    "origen":    ["clips", "frames_extraidos", "imagenes_web"],
    "emocional": ["clips", "frames_extraidos", "imagenes_web"],
    "cierre":    ["clips", "imagenes_web", "frames_extraidos"],
}


# ─── Helpers ffprobe ──────────────────────────────────────────────────────────

def get_duration_file(path):
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nokey=1:noprint_wrappers=1", str(path)],
            capture_output=True, text=True, timeout=10
        )
        return round(float(r.stdout.strip()), 2)
    except Exception:
        return 0.0

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

def get_video_info(path):
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-show_entries", "format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=15
        )
        d   = json.loads(r.stdout)
        w   = int(d["streams"][0]["width"])
        h   = int(d["streams"][0]["height"])
        dur = float(d["format"]["duration"])
        return w, h, dur
    except Exception:
        return 1920, 1080, 0.0


# ─── PASO 1: Extracción de clips del video de referencia ──────────────────────

def detectar_logo(video_path, w, h):
    """Detecta logo en esquina superior derecha (mismo algoritmo que extraer_clips_video.py)."""
    import tempfile
    tmp = pathlib.Path(tempfile.mktemp(suffix=".jpg"))
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-i", str(video_path), "-vframes", "1", str(tmp)],
                   capture_output=True, timeout=15)
    if not tmp.exists():
        return None
    logo_x = int(w * 0.85)
    logo_h = int(h * 0.08)
    try:
        from PIL import Image, ImageStat
        img  = Image.open(tmp).convert("L")
        crop = img.crop((logo_x, 0, w, logo_h))
        mean = ImageStat.Stat(crop).mean[0]
        tmp.unlink(missing_ok=True)
        if mean > 160:
            print(f"    Logo detectado (brillo={mean:.0f}) — aplicando crop")
            return logo_x, 0, w - logo_x, logo_h
        return None
    except ImportError:
        tmp.unlink(missing_ok=True)
        return int(w * 0.85), 0, int(w * 0.15), int(h * 0.08)

def construir_vfilter(w, h, logo_region, apply_color=True):
    COLOR_FIX = "eq=brightness=-0.08:contrast=1.3:saturation=1.4:gamma=0.9,unsharp=3:3:0.5"
    SUB_H_PX  = 80
    parts = []
    if apply_color:
        parts.append(COLOR_FIX)
    crop_w = logo_region[0] if logo_region else w
    crop_h = h - SUB_H_PX
    parts.append(f"crop={crop_w}:{crop_h}:0:0")
    out_w = 1280
    out_h = int(crop_h * out_w / crop_w)
    if out_h % 2 != 0:
        out_h += 1
    parts.append(f"scale={out_w}:{out_h}")
    return ",".join(parts)

def extraer_clips(url, clips_dir, max_clips=60, clip_dur=CLIP_DUR):
    print(f"\n[PASO 1] Descargando video de referencia...")
    import tempfile, shutil
    clips_dir = pathlib.Path(clips_dir)
    clips_dir.mkdir(parents=True, exist_ok=True)

    existing = list(clips_dir.glob("*.mp4"))
    if existing:
        print(f"  ✓ Ya existen {len(existing)} clips en clips/ — saltando descarga")
        return True

    with tempfile.TemporaryDirectory(prefix="futbol_harvest_") as tmp:
        tmp = pathlib.Path(tmp)
        video_path = tmp / "video.mp4"

        print(f"  Descargando: {url}")
        cmd = [YTDLP, "--cookies-from-browser", "brave",
               "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]",
               "--merge-output-format", "mp4",
               "-o", str(video_path), "-q", "--no-playlist", url]
        r = subprocess.run(cmd, timeout=600)
        if not video_path.exists():
            print("  ✗ Error al descargar el video")
            return False
        print(f"  ✓ Descargado ({video_path.stat().st_size / 1e6:.0f} MB)")

        # Info + detectar logo
        w, h, dur = get_video_info(video_path)
        print(f"  Resolución: {w}x{h}  |  Duración: {dur:.0f}s")
        logo_region = detectar_logo(video_path, w, h)
        vfilter     = construir_vfilter(w, h, logo_region)

        # Cortar en clips raw
        clips_raw_dir = tmp / "raw"
        clips_raw_dir.mkdir()
        print(f"  Cortando en segmentos de {clip_dur}s...")
        subprocess.run(
            [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
             "-i", str(video_path),
             "-c", "copy", "-f", "segment", "-segment_time", str(clip_dur),
             "-reset_timestamps", "1", str(clips_raw_dir / "raw_%04d.mp4")],
            capture_output=True, timeout=600
        )
        raw_clips = sorted(clips_raw_dir.glob("raw_*.mp4"))
        print(f"  {len(raw_clips)} clips raw generados")

        random.shuffle(raw_clips)
        guardados = 0
        for i, clip in enumerate(raw_clips):
            if guardados >= max_clips:
                break
            out = clips_dir / f"clip_{i+1:04d}.mp4"
            subprocess.run([
                FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-i", str(clip), "-vf", vfilter,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
                "-an", str(out)
            ], capture_output=True, timeout=180)
            if out.exists() and out.stat().st_size > 5000:
                guardados += 1

        print(f"  ✓ {guardados} clips guardados en clips/")
    return True


# ─── PASO 2: Extraer frames clave como imágenes ───────────────────────────────

def extraer_frames(clips_dir, frames_dir, max_frames=FRAMES_PER_BATCH):
    print(f"\n[PASO 2] Extrayendo frames clave para zoompan...")
    frames_dir = pathlib.Path(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)

    existing = [f for f in frames_dir.iterdir() if f.suffix.lower() in IMG_EXTS]
    if existing:
        print(f"  ✓ Ya existen {len(existing)} frames — saltando extracción")
        return

    clips = sorted(pathlib.Path(clips_dir).glob("*.mp4"))
    if not clips:
        print("  ⚠ Sin clips disponibles para extraer frames")
        return

    # Tomar 1 frame del centro de clips espaciados uniformemente
    step = max(1, len(clips) // max_frames)
    selected = clips[::step][:max_frames]
    guardados = 0

    for i, clip in enumerate(selected):
        dur = get_duration_file(clip)
        mid = max(0.5, dur / 2)
        out = frames_dir / f"frame_{i+1:04d}.jpg"
        subprocess.run([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-ss", str(mid), "-i", str(clip),
            "-vframes", "1", "-q:v", "3",
            "-vf", "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080",
            str(out)
        ], capture_output=True, timeout=30)
        if out.exists() and out.stat().st_size > 5000:
            guardados += 1

    print(f"  ✓ {guardados} frames extraídos en frames_extraidos/")


# ─── SRT parser ───────────────────────────────────────────────────────────────

def parse_srt(srt_path, max_secs=None):
    entries = []
    content = pathlib.Path(srt_path).read_text(encoding="utf-8", errors="replace")
    blocks  = re.split(r'\n\s*\n', content.strip())
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        m = re.match(r'(\d+:\d+:\d+[,\.]\d+)\s+-->\s+(\d+:\d+:\d+[,\.]\d+)', lines[1])
        if not m:
            continue
        def to_s(t):
            t = t.replace(',', '.')
            h, mi, s = t.split(':')
            return int(h)*3600 + int(mi)*60 + float(s)
        start = to_s(m.group(1))
        end   = to_s(m.group(2))
        if max_secs and start > max_secs:
            break
        entries.append({"start": start, "end": end, "text": " ".join(lines[2:]).strip()})
    return entries

def srt_total_duration(srt_entries):
    return srt_entries[-1]["end"] if srt_entries else 0.0

def get_text_in_range(srt_entries, t_start, t_end):
    parts = []
    for e in srt_entries:
        if e["end"] < t_start: continue
        if e["start"] > t_end: break
        parts.append(e["text"])
    return " ".join(parts)


# ─── PASO 3: Leer timeline.json y mandar a Baserow (Flow) ─────────────────────

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

def enviar_flow_prompts(personaje, srt_10min, timeline_path, carpeta_video, ref_url=None):
    """
    Lee timeline.json, filtra segmentos en los primeros 10 min,
    genera ia_prompt y veo_prompt realistas basados en el SRT,
    y los manda a Baserow para que Flow genere las imágenes.
    """
    print(f"\n[PASO 3] Analizando timeline + SRT (primeros 10 min) → Flow...")

    if not timeline_path.exists():
        print(f"  ⚠ No existe timeline.json — saltando envío a Flow")
        print(f"    Corre primero: python3 generar_timeline_futbol.py {carpeta_video}")
        return []

    timeline = json.loads(timeline_path.read_text())
    segments = timeline.get("visual_timeline", [])

    # Filtrar solo segmentos dentro de los primeros 10 min
    segs_10min = [s for s in segments if s.get("start_seconds", 0) <= SRT_MAX_SECS]
    if not segs_10min:
        print(f"  ⚠ El timeline no tiene segmentos en los primeros 10 min")
        return []

    print(f"  {len(segs_10min)} segmentos del timeline en primeros 10 min")

    # Construir prompts realistas para cada segmento
    flow_items = []
    for seg in segs_10min:
        start   = seg.get("start_seconds", 0)
        end     = seg.get("end_seconds", start + 6)
        dur     = seg.get("duration", end - start)
        scene   = seg.get("scene_description_es", "")
        trigger = seg.get("trigger_type", "")
        srt_ctx = get_text_in_range(srt_10min, start, end)

        # Usar ia_prompt del timeline si ya viene generado por Gemini (nombre primero)
        # Si no, construir con el personaje adelante
        ia_prompt  = seg.get("ia_prompt") or (
            f"{personaje} el futbolista, {scene}. "
            f"Fotografía documental realista, auténtica, sin texto, sin logos, alta definición. "
            f"Contexto: {srt_ctx[:100]}"
        )
        veo_prompt = seg.get("veo_prompt") or f"Slow cinematic zoom in, {personaje}, {scene}"

        flow_items.append({
            "segment_id":   seg.get("segment_id", 0),
            "start":        start,
            "end":          end,
            "duration":     dur,
            "trigger":      trigger,
            "scene":        scene,
            "ia_prompt":    ia_prompt,
            "veo_prompt":   veo_prompt,
            "srt_text":     srt_ctx,
        })
        print(f"    [{start:.0f}s] {trigger}: {scene[:60]}...")

    # Limpiar Baserow y mandar batch
    print(f"\n  Limpiando Baserow y enviando {len(flow_items)} prompts...")
    borrados = limpiar_baserow()

    items_baserow = [{
        "Image Prompt": fi["ia_prompt"],
        "VEO Prompt":   fi["veo_prompt"],
        "Mode":         "Imagegen",
        "Status":       "pending",
        "segment_id":   str(fi["segment_id"]),
    } for fi in flow_items]

    result  = _baserow_curl('POST',
        f'/database/rows/table/{BASEROW_TABLE_ID}/batch/?user_field_names=true',
        {'items': items_baserow})
    created = result.get('items', [])

    # Guardar mapeo segment_id → row_id en flow_meta.json
    flow_meta = []
    for i, row in enumerate(created):
        if i >= len(flow_items): break
        fi = flow_items[i]
        flow_meta.append({**fi, "baserow_row_id": row.get("id")})

    flow_meta_file = carpeta_video / "flow_meta.json"
    flow_meta_file.write_text(json.dumps(flow_meta, ensure_ascii=False, indent=2))

    print(f"  ✓ {len(created)} filas en Baserow (borrados: {borrados})")
    print(f"  ✓ flow_meta.json guardado")

    # ── Calcular si hay suficientes clips base ─────────────────────────────
    clips_dir    = carpeta_video / "clips"
    clips_have   = len(list(clips_dir.glob("*.mp4"))) if clips_dir.exists() else 0
    flow_dur_total = sum(fi["duration"] for fi in flow_meta)
    gap_time       = max(0, SRT_MAX_SECS - flow_dur_total)
    clips_needed   = math.ceil(gap_time / CLIP_DUR)
    deficit        = max(0, clips_needed - clips_have)

    print(f"\n  ── Cálculo de cobertura ──────────────────────────")
    print(f"     Tiempo total:        {SRT_MAX_SECS}s (10 min)")
    print(f"     Flow total:          {flow_dur_total:.1f}s ({len(flow_meta)} imágenes)")
    print(f"     Tiempo para clips:   {gap_time:.1f}s")
    print(f"     Clips necesarios:    {clips_needed} × {CLIP_DUR}s")
    print(f"     Clips disponibles:   {clips_have}")
    if deficit <= 0:
        print(f"     ✓ Suficientes clips — sin repetidos")
    else:
        print(f"     ⚠ DÉFICIT: {deficit} clips faltan → iniciando cobertura por prioridades")
        flow_meta = _cubrir_deficit(
            personaje, srt_10min, flow_meta, deficit, carpeta_video,
            ref_url=ref_url
        )
        flow_meta_file.write_text(json.dumps(flow_meta, ensure_ascii=False, indent=2))
        print(f"  ✓ flow_meta.json actualizado con extras")

    print(f"\n  ⚡ AHORA: corre la extensión VEO en Brave para generar las imágenes")
    print(f"     Cuando termines avisa y se descargan automáticamente")
    return flow_meta


def _cubrir_deficit(personaje, srt_10min, flow_meta, deficit, carpeta_video, ref_url=None):
    """
    Cubre el déficit de clips siguiendo este orden de prioridad:
      1. Más clips del video original (gratis, sin repetir los ya extraídos)
      2. Imágenes de Brave (gratis, animadas con zoompan)
      3. Flow/Baserow: máx 30 total, SOLO temas mansion/carros/lujo/ciudad
    """
    clips_dir = carpeta_video / "clips"
    brave_dir = carpeta_video / "brave_images"
    MAX_FLOW_TOTAL = 30

    # ── Prioridad 1: más clips del video original ─────────────────────────
    if deficit > 0 and ref_url:
        existing = sorted(clips_dir.glob("*.mp4"))
        need_extra = deficit
        print(f"\n  [P1] Extrayendo {need_extra} clips extra del video original...")
        ok = _extraer_clips_extra_video(ref_url, clips_dir, existing, need_extra)
        nuevos = len(list(clips_dir.glob("*.mp4"))) - len(existing)
        deficit -= nuevos
        print(f"       ✓ {nuevos} clips extra extraídos → déficit restante: {deficit}")

    # ── Prioridad 2: imágenes Brave usando prompts del timeline ──────────
    if deficit > 0:
        brave_dir.mkdir(exist_ok=True)
        # Usar las escenas del timeline como queries de Brave — así cuadran con el audio
        ocupados_flow = {fi["segment_id"] for fi in flow_meta}
        queries_brave = []
        for entry in srt_10min:
            t = entry["start"]
            # Tomar entradas libres de Flow distribuidas en el tiempo
            en_flow = any(fi["start"] <= t <= fi["end"] for fi in flow_meta)
            if not en_flow and entry["text"].strip():
                queries_brave.append(f"{personaje} {entry['text'][:70]}")
        # Deduplicar y limitar
        queries_brave = list(dict.fromkeys(queries_brave))[:min(deficit * 2, 30)]
        print(f"\n  [P2] Buscando {min(deficit, 20)} imágenes en Brave (prompts del timeline)...")
        descargadas = _buscar_brave_imagenes(queries_brave, brave_dir, max_imgs=min(deficit, 20))
        deficit -= descargadas
        print(f"       ✓ {descargadas} imágenes Brave → déficit restante: {deficit}")

    # ── Prioridad 3: Flow/Baserow (máx 30 total, solo luxury) ────────────
    flow_ya = len(flow_meta)
    flow_disponible = max(0, MAX_FLOW_TOTAL - flow_ya)
    flow_extra = min(deficit, flow_disponible)

    if flow_extra > 0:
        print(f"\n  [P3] Generando {flow_extra} imágenes extra en Flow (luxury/mansion/carros)...")
        flow_meta = _flow_luxury_extra(personaje, flow_meta, flow_extra, carpeta_video)
        deficit -= flow_extra

    if deficit > 0:
        print(f"\n  ⚠ Aún faltan {deficit} clips — habrá algunos repetidos al final del video")
    else:
        print(f"\n  ✓ Déficit cubierto — sin repetidos")

    return flow_meta


def _extraer_clips_extra_video(url, clips_dir, existing_clips, need):
    """Descarga el video de referencia y extrae más clips (desde donde quedamos)."""
    import tempfile
    existing_names = {c.name for c in existing_clips}
    next_num = len(existing_clips) + 1

    with tempfile.TemporaryDirectory(prefix="futbol_extra_") as tmp:
        tmp = pathlib.Path(tmp)
        video_path = tmp / "video.mp4"
        cmd = [YTDLP, "--cookies-from-browser", "brave",
               "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]",
               "--merge-output-format", "mp4",
               "-o", str(video_path), "-q", "--no-playlist", url]
        try:
            r = subprocess.run(cmd, timeout=600, capture_output=True)
        except Exception as e:
            print(f"       ✗ Error descargando: {e}")
            return 0
        if not video_path.exists():
            return 0

        w, h, dur = get_video_info(video_path)
        logo_region = detectar_logo(video_path, w, h)
        vfilter     = construir_vfilter(w, h, logo_region)

        raw_dir = tmp / "raw"
        raw_dir.mkdir()
        subprocess.run(
            [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
             "-i", str(video_path),
             "-c", "copy", "-f", "segment", "-segment_time", str(CLIP_DUR),
             "-reset_timestamps", "1", str(raw_dir / "raw_%04d.mp4")],
            capture_output=True, timeout=600
        )
        raw_clips = sorted(raw_dir.glob("raw_*.mp4"))
        # Tomar clips que no tengamos aún (saltar los primeros len(existing) aprox.)
        skip = len(existing_clips)
        candidates = raw_clips[skip:]
        random.shuffle(candidates)

        guardados = 0
        for clip in candidates:
            if guardados >= need:
                break
            dest = clips_dir / f"clip_{next_num + guardados:04d}.mp4"
            try:
                cmd2 = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                        "-i", str(clip), "-vf", vfilter,
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                        "-an", str(dest)]
                r2 = subprocess.run(cmd2, capture_output=True, timeout=30)
                if dest.exists() and dest.stat().st_size > 10000:
                    guardados += 1
                elif dest.exists():
                    dest.unlink()
            except Exception:
                pass
        return guardados


def _buscar_brave_imagenes(queries, brave_dir, max_imgs=20):
    """Busca imágenes en Brave API y las descarga para zoompan."""
    key_file = HOME / ".brave_key"
    if not key_file.exists():
        print(f"       ⚠ Sin clave Brave ({key_file})")
        return 0

    api_key = key_file.read_text().strip()
    descargadas = 0

    for query in queries:
        if descargadas >= max_imgs:
            break
        try:
            import urllib.request, urllib.parse
            params = urllib.parse.urlencode({"q": query, "count": 5, "search_lang": "es"})
            req = urllib.request.Request(
                f"https://api.search.brave.com/res/v1/images/search?{params}",
                headers={"Accept": "application/json",
                         "Accept-Encoding": "gzip",
                         "X-Subscription-Token": api_key}
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                import gzip as _gzip, io as _io
                raw = r.read()
                if r.info().get("Content-Encoding") == "gzip":
                    raw = _gzip.decompress(raw)
                data = json.loads(raw)

            results = data.get("results", [])
            for img_result in results:
                if descargadas >= max_imgs:
                    break
                img_url = img_result.get("properties", {}).get("url") or img_result.get("url", "")
                if not img_url:
                    continue
                w = img_result.get("properties", {}).get("width", 0)
                h = img_result.get("properties", {}).get("height", 0)
                if w < 800 or h < 450:  # ignorar imágenes pequeñas
                    continue
                dest = brave_dir / f"brave_{descargadas+1:04d}.jpg"
                try:
                    req2 = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req2, timeout=10) as r2:
                        dest.write_bytes(r2.read())
                    if dest.stat().st_size > 20000:
                        descargadas += 1
                        print(f"       ↓ brave_{descargadas:04d}.jpg: {query[:40]}")
                    else:
                        dest.unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception as e:
            print(f"       ⚠ Brave error ({query[:30]}): {e}")

    return descargadas


# Triggers de lujo/riqueza para Flow extra
LUXURY_TRIGGERS = {"property", "car", "money", "birthplace", "mansion", "finca", "lujo"}
LUXURY_PROMPTS = [
    "lujosa mansion moderna con piscina infinita y jardines tropicales al atardecer",
    "colección de autos deportivos Ferrari Lamborghini en un garage de lujo",
    "finca ganadera de lujo en las montañas de Colombia con caballos de raza",
    "vista panorámica de Medellín Colombia desde las montañas al amanecer",
    "rancho rural con potrero verde y caballos en las afueras de Antioquia",
    "billetera llena de dinero dólares sobre mesa de madera de lujo",
    "mansión con campo de entrenamiento privado de fútbol al aire libre",
    "piscina de lujo con vista al valle de Antioquia al atardecer",
    "camioneta pickup lujosa 4x4 en camino rural de Colombia",
    "hacienda cafetera colombiana con casonas de arquitectura colonial",
]

def _flow_luxury_extra(personaje, flow_meta_existente, n, carpeta_video):
    """Envía n prompts extra a Baserow con temas de lujo/mansion/carros."""
    seg_id_base = max((fi["segment_id"] for fi in flow_meta_existente), default=0) + 1
    # Distribuir en momentos del video que no tengan Flow aún
    ocupados = {(fi["start"], fi["end"]) for fi in flow_meta_existente}
    # Momentos libres: distribuir uniformemente en 0-600s
    step = SRT_MAX_SECS / (n + 1)
    extra_items = []

    for k in range(n):
        t = step * (k + 1)
        # Evitar colisiones con flow existente
        while any(s <= t <= e for s, e in ocupados):
            t += 3
        end = min(t + 6.0, SRT_MAX_SECS)
        scene = LUXURY_PROMPTS[k % len(LUXURY_PROMPTS)]
        ia_prompt  = f"{personaje} el futbolista, {scene}. Fotografía hiperrealista, sin texto, sin logos, alta definición."
        veo_prompt = f"Slow cinematic zoom in, {personaje}, {scene}"

        extra_items.append({
            "segment_id": seg_id_base + k,
            "start":      round(t, 2),
            "end":        round(end, 2),
            "duration":   round(end - t, 2),
            "trigger":    "luxury",
            "scene":      scene,
            "ia_prompt":  ia_prompt,
            "veo_prompt": veo_prompt,
        })
        print(f"    + luxury [{t:.0f}s] {scene[:55]}...")

    items_baserow = [{
        "Image Prompt": it["ia_prompt"],
        "VEO Prompt":   it["veo_prompt"],
        "Mode":         "Imagegen",
        "Status":       "pending",
        "segment_id":   str(it["segment_id"]),
    } for it in extra_items]

    result  = _baserow_curl('POST',
        f'/database/rows/table/{BASEROW_TABLE_ID}/batch/?user_field_names=true',
        {'items': items_baserow})
    created = result.get('items', [])
    for i, row in enumerate(created):
        if i < len(extra_items):
            extra_items[i]["baserow_row_id"] = row.get("id")

    print(f"    ✓ {len(created)} prompts luxury enviados a Baserow")
    return flow_meta_existente + extra_items


# ─── PASO 4: Pre-asignar clips a bloques ──────────────────────────────────────

def listar_media(folder):
    if not folder.exists():
        return []
    files = []
    for f in folder.iterdir():
        if f.suffix == '.mp4' and '_zp' not in f.stem:
            files.append(f)
        elif f.suffix.lower() in IMG_EXTS:
            files.append(f)
    return files

def pre_seleccionar(pools_ordenados, num_slots, usados_global):
    combined = []
    seen = set()
    for pool in pools_ordenados:
        for f in pool:
            if str(f) not in seen:
                seen.add(str(f))
                combined.append(f)

    libres = [f for f in combined if str(f) not in usados_global]
    random.shuffle(libres)
    selected   = []
    used_local = set()

    for _ in range(num_slots):
        if not libres:
            libres = [f for f in combined if str(f) not in used_local]
            if not libres:
                libres = list(combined)
            random.shuffle(libres)

        for i, f in enumerate(libres):
            if str(f) not in used_local:
                used_local.add(str(f))
                usados_global.add(str(f))
                selected.append(libres.pop(i))
                break
        else:
            if libres:
                f = libres.pop(0)
                used_local.add(str(f))
                usados_global.add(str(f))
                selected.append(f)

    return selected

def detectar_fuente(path, carpeta_video):
    p = str(path)
    base = str(carpeta_video)
    if f"{base}/clips/" in p:              return "clips"
    if f"{base}/imagenes_web/" in p:       return "imagenes_web"
    if f"{base}/imagenes/" in p:           return "imagenes"
    if f"{base}/frames_extraidos/" in p:   return "frames_extraidos"
    return "local"

def build_search_query(personaje, srt_text, bloque_id):
    stop = {'el','la','los','las','un','una','y','de','en','que','se','su','con',
            'por','para','del','al','no','le','lo','era','fue','es','son','han',
            'sus','pero','como','más','muy','cuando','todo','esto','esta',
            'ese','esa','eso','hay','ya','si','porque','donde','quien'}
    words    = re.findall(r'\b[a-záéíóúüñ]{4,}\b', srt_text.lower())
    keywords = [w for w in words if w not in stop][:3]
    contextos = {
        "hook":      "jugador famoso futbol vida contraste",
        "casa":      "casa rancho propiedad hogar familia",
        "origen":    "infancia carrera historia futbol origen",
        "emocional": "momento emotivo historia personal futbol",
        "cierre":    "legado retiro filosofia vida futbol",
    }
    base = f"{personaje} {contextos.get(bloque_id, 'futbolista')}"
    if keywords:
        base += " " + " ".join(keywords)
    return base

def build_ia_prompt(personaje, srt_text, bloque_id, slot_start):
    descs = {
        "hook":      "action shot, stadium, dramatic lighting, football career highlights",
        "casa":      "rural estate, ranch, family home, countryside, golden hour, authentic",
        "origen":    "childhood, small town, young player training, nostalgic documentary style",
        "emocional": "emotional personal moment, intimate setting, documentary photograph",
        "cierre":    "peaceful countryside, sunset, retired athlete, philosophical atmosphere",
    }
    srt_short = srt_text[:100] if srt_text else ""
    return (
        f"Photorealistic documentary photograph of {personaje}, soccer legend, "
        f"{descs.get(bloque_id, 'cinematic')}, no text, no logos, high detail. "
        f"Context: {srt_short}"
    )

def scan_bloque(bloque, personaje, carpeta_video, srt_entries, total_dur, usados_global):
    bid   = bloque["id"]
    desde = total_dur * bloque["desde"]
    hasta = total_dur * bloque["hasta"]
    dur   = hasta - desde

    pools_map = {
        "clips":            listar_media(carpeta_video / "clips"),
        "imagenes_web":     listar_media(carpeta_video / "imagenes_web"),
        "imagenes":         listar_media(carpeta_video / "imagenes"),
        "frames_extraidos": listar_media(carpeta_video / "frames_extraidos"),
    }

    pools_ordenados  = [pools_map[f] for f in FUENTES_PRIORIDAD[bid] if pools_map.get(f)]
    total_disponibles = sum(len(p) for p in pools_ordenados)

    num_slots = math.ceil(dur / SHOT_DUR) + EXTRA
    print(f"    [{bid}] {dur:.0f}s → {num_slots} slots | media disponible: {total_disponibles}")

    if total_disponibles == 0:
        print(f"    ⚠ Sin media para bloque '{bid}'")
        return {}

    seleccionados = pre_seleccionar(pools_ordenados, num_slots, usados_global)

    clips = {}
    for i, path in enumerate(seleccionados):
        slot_start_abs = round(desde + i * SHOT_DUR, 2)
        slot_end_abs   = round(min(desde + (i + 1) * SHOT_DUR, hasta), 2)
        srt_text       = get_text_in_range(srt_entries, slot_start_abs, slot_end_abs)
        dur_clip       = get_duration_file(path) if path.suffix == ".mp4" else 0
        w, h           = get_dims(path)
        fuente         = detectar_fuente(path, carpeta_video)
        tipo           = "video" if path.suffix == ".mp4" else "imagen"
        slot_key       = f"{bid}_{i:03d}_{path.name}"
        reciclado      = any(v.get("path") == str(path) for v in clips.values())

        clips[slot_key] = {
            "slot":         i,
            "estado":       "pendiente",
            "tipo":         tipo,
            "path":         str(path),
            "orig_name":    path.name,
            "reciclado":    reciclado,
            "duration":     dur_clip,
            "slot_start":   slot_start_abs,
            "slot_end":     slot_end_abs,
            "srt_text":     srt_text,
            "search_query": build_search_query(personaje, srt_text, bid),
            "ia_prompt":    build_ia_prompt(personaje, srt_text, bid, slot_start_abs),
            "width":        w,
            "height":       h,
            "fuente":       fuente,
        }

    return clips


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Harvester de clips para canal de fútbol")
    parser.add_argument("carpeta", help="Carpeta del video: futbol/<personaje>/")
    parser.add_argument("--url",   help="URL del video de referencia en YouTube", default=None)
    parser.add_argument("--clips", type=int, default=60, help="Máx clips a extraer (default: 60)")
    parser.add_argument("--frames",type=int, default=30, help="Máx frames a extraer (default: 30)")
    parser.add_argument("--no-flow",   action="store_true", help="Saltarse el envío a Baserow/Flow")
    parser.add_argument("--solo-flow", action="store_true", help="Solo re-enviar prompts a Baserow (saltar clips y frames)")
    args = parser.parse_args()

    carpeta_video = pathlib.Path(args.carpeta).resolve()
    if not carpeta_video.exists():
        carpeta_video.mkdir(parents=True)
        print(f"  Creada carpeta: {carpeta_video}")

    personaje = carpeta_video.name.replace("_", " ").title()
    print(f"\n{'='*60}")
    print(f"  harvester_clips_futbol.py — {personaje}")
    print(f"{'='*60}\n")

    solo_flow = getattr(args, 'solo_flow', False)

    # Guardar/cargar URL de referencia en config.json
    config_file = carpeta_video / "config.json"
    config = json.loads(config_file.read_text()) if config_file.exists() else {}
    if args.url:
        config["url"] = args.url
        config_file.write_text(json.dumps(config, ensure_ascii=False, indent=2))
    ref_url = config.get("url")

    # ── PASO 1: Extraer clips del video de referencia ──────────────────────
    if solo_flow:
        existing_clips = list((carpeta_video / "clips").glob("*.mp4")) if (carpeta_video / "clips").exists() else []
        print(f"[PASO 1] --solo-flow: usando {len(existing_clips)} clips existentes")
    elif args.url:
        ok = extraer_clips(
            url=args.url,
            clips_dir=carpeta_video / "clips",
            max_clips=args.clips,
            clip_dur=CLIP_DUR,
        )
        if not ok:
            print("✗ Error extrayendo clips — abortando")
            sys.exit(1)
    else:
        existing_clips = list((carpeta_video / "clips").glob("*.mp4")) if (carpeta_video / "clips").exists() else []
        if existing_clips:
            print(f"[PASO 1] Usando {len(existing_clips)} clips existentes en clips/")
        else:
            print("[PASO 1] Sin URL ni clips existentes")
            print("  Pasa --url 'https://youtube.com/...' para extraer clips")

    # ── PASO 2: Extraer frames clave ───────────────────────────────────────
    if not solo_flow:
        extraer_frames(
            clips_dir=carpeta_video / "clips",
            frames_dir=carpeta_video / "frames_extraidos",
            max_frames=args.frames,
        )

    # ── PASO 3: SRT + timeline → Flow (Baserow) ────────────────────────────
    srt_files = list(carpeta_video.glob("*.srt"))
    if not srt_files:
        print("\n[PASO 3] ⚠ Sin SRT disponible — saltando análisis")
        srt_entries  = []
        srt_10min    = []
        total_dur    = 16 * 60  # estimado
    else:
        srt_path    = srt_files[0]
        print(f"\n  SRT: {srt_path.name}")
        srt_entries = parse_srt(srt_path)
        srt_10min   = parse_srt(srt_path, max_secs=SRT_MAX_SECS)
        total_dur   = srt_total_duration(srt_entries)
        print(f"  Duración total: {total_dur:.0f}s ({total_dur/60:.1f} min)")
        print(f"  Entradas SRT (10 min): {len(srt_10min)}")

    if not args.no_flow and srt_10min:
        # buscar timeline.json en la carpeta raíz o en 05-montaje/
        timeline_path = carpeta_video / "timeline.json"
        if not timeline_path.exists():
            alt = carpeta_video / "05-montaje" / "timeline.json"
            if alt.exists():
                timeline_path = alt
        flow_meta = enviar_flow_prompts(personaje, srt_10min, timeline_path, carpeta_video, ref_url=ref_url)
    else:
        flow_meta = []
        if args.no_flow:
            print("\n[PASO 3] --no-flow activo — saltando Baserow")

    # ── PASO 4: Pre-asignar clips a bloques ───────────────────────────────
    print(f"\n[PASO 4] Pre-asignando clips a los 5 bloques narrativos...")
    if total_dur == 0:
        total_dur = 16 * 60

    meta_file = carpeta_video / "dashboard_meta.json"
    existing  = {}
    if meta_file.exists():
        try:
            existing = json.loads(meta_file.read_text())
        except Exception:
            existing = {}

    meta          = {}
    usados_global = set()

    for bloque in BLOQUES:
        bid    = bloque["id"]
        nombre = bloque["nombre"]
        print(f"\n  [{nombre}]")
        prev_clips = existing.get(bid, {}).get("clips", {})

        clips = scan_bloque(bloque, personaje, carpeta_video, srt_entries, total_dur, usados_global)

        # Preservar estados anteriores
        for key in clips:
            if key in prev_clips:
                prev_estado = prev_clips[key].get("estado")
                if prev_estado in ("aprobado", "rechazado"):
                    clips[key]["estado"] = prev_estado

        desde = total_dur * bloque["desde"]
        hasta = total_dur * bloque["hasta"]
        meta[bid] = {
            "nombre":   nombre,
            "duration": round(hasta - desde, 2),
            "desde":    round(desde, 2),
            "hasta":    round(hasta, 2),
            "clips":    clips,
        }

    # Agregar slots de Flow al bloque correspondiente según timestamp
    if flow_meta:
        print(f"\n  Integrando {len(flow_meta)} slots de Flow en bloques...")
        for fi in flow_meta:
            start = fi["start"]
            ratio = start / total_dur if total_dur > 0 else 0
            for bloque in BLOQUES:
                if bloque["desde"] <= ratio < bloque["hasta"]:
                    bid = bloque["id"]
                    slot_key = f"flow_{fi['segment_id']:04d}"
                    meta[bid]["clips"][slot_key] = {
                        "slot":       999 + fi["segment_id"],
                        "estado":     "needs_flow",
                        "tipo":       "imagen",
                        "path":       "",
                        "orig_name":  f"Flow #{fi['segment_id']}",
                        "duration":   fi["duration"],
                        "slot_start": fi["start"],
                        "slot_end":   fi["end"],
                        "srt_text":   fi["srt_text"],
                        "ia_prompt":  fi["ia_prompt"],
                        "veo_prompt": fi["veo_prompt"],
                        "baserow_row": fi.get("baserow_row_id"),
                        "search_query": fi["scene"],
                        "fuente":     "flow",
                        "width": 0, "height": 0, "reciclado": False,
                    }
                    break

    meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    total_clips   = sum(len(s["clips"]) for s in meta.values())
    flow_slots    = sum(1 for s in meta.values() for c in s["clips"].values() if c.get("estado") == "needs_flow")
    print(f"\n{'='*60}")
    print(f"  ✓ dashboard_meta.json → {meta_file}")
    print(f"  {len(meta)} bloques, {total_clips} slots ({flow_slots} en Flow)")
    if flow_slots:
        print(f"\n  ⚡ Corre la extensión VEO en Brave y avisa cuando termine")
    print(f"\n  Cuando apruebes los clips:")
    print(f"    pkill -f dashboard_futbol 2>/dev/null")
    print(f"    python3 dashboard_futbol.py \"{carpeta_video}\"")
    print(f"    → http://localhost:5003")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
