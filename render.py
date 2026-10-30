#!/usr/bin/env python3
"""
RENDER — Concatena clips con efectos TV + audio y renderiza el video final.
Uso: python3 render.py /ruta/carpeta/personaje/

Efectos por clip:
  - Flip horizontal aleatorio (50%)
  - Zoom 4%
  - Grano de película (noise estilo TV)
  - Variación sutil de brillo/saturación

Imágenes animadas (opcional):
  - imagenes/1.mp4, 2.mp4... → se insertan en timestamps fijos del CSV
  - imagenes_web/1.mp4, 2.mp4... → pool de relleno general, se intercalan
    cada IMG_WEB_INTERVAL clips entre los clips del video (rotación aleatoria)
  - Si no hay ninguna carpeta de imágenes, renderiza solo con clips.
"""

import sys, re, csv, math, random, itertools, subprocess, pathlib, tempfile

FFMPEG  = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"
if not pathlib.Path(FFMPEG).exists():
    FFMPEG  = "/usr/local/bin/ffmpeg"
    FFPROBE = "/usr/local/bin/ffprobe"

ZOOM        = 1.04
NOISE       = 9
FLIP_CHANCE = 0.5
IMAGE_DUR   = 6.0     # duración fija de cada imagen animada
IMG_WEB_INTERVAL = 4  # insertar 1 imagen web cada N clips de video

def run(cmd, check=True, capture=False):
    return subprocess.run(cmd, check=check,
                          capture_output=capture, text=capture)

def get_duration(path):
    r = run([FFPROBE, "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=nokey=1:noprint_wrappers=1",
             str(path)], capture=True)
    return float(r.stdout.strip())

def ts_to_sec(t):
    """MM:SS o HH:MM:SS a segundos float."""
    parts = [float(p) for p in str(t).strip().split(":")]
    if len(parts) == 3:
        return parts[0]*3600 + parts[1]*60 + parts[2]
    return parts[0]*60 + parts[1]

def apply_effects(src, dst, flip, fps=None, width=None, height=None):
    # Velocidad: ±1-2% aleatorio (imperceptible, rompe huellas temporales)
    speed = random.uniform(0.98, 1.02)
    pts = f"setpts={1/speed:.4f}*PTS"

    # Crop asimétrico: recortar 1-3% de cada lado de forma distinta
    cl = random.randint(1, 3)   # left
    cr = random.randint(1, 3)   # right
    ct = random.randint(1, 3)   # top
    cb = random.randint(1, 3)   # bottom
    # Zoom + crop simétrico primero, luego crop asimétrico
    crop_asym = (
        f"scale=iw*{ZOOM}:ih*{ZOOM},"
        f"crop=iw/{ZOOM}:ih/{ZOOM},"
        f"crop=iw-{cl+cr}:ih-{ct+cb}:{cl}:{ct},"
        f"scale=trunc((iw+{cl+cr})/2)*2:trunc((ih+{ct+cb})/2)*2"   # dimensiones pares siempre
    )

    filters = [crop_asym, pts]
    if flip:
        filters.append("hflip")
    br = random.uniform(-0.03, 0.03)
    sat = random.uniform(0.92, 1.08)
    filters.append(f"eq=brightness={br:.3f}:saturation={sat:.3f}")
    # Normalizar resolución y fps al final para que el concat no mezcle timebases
    if width and height:
        filters.append(f"scale={width}:{height}:force_original_aspect_ratio=disable")
    if fps:
        filters.append(f"fps={fps}")
    run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", str(src),
        "-vf", ",".join(filters),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-pix_fmt", "yuv420p", "-an",
        "-y", str(dst)
    ])

def apply_effects_recycled(src, dst, flip):
    """Clip reciclado: transformaciones agresivas para evadir Content ID."""
    speed = random.uniform(0.96, 1.04)
    pts = f"setpts={1/speed:.4f}*PTS"
    # Crop más agresivo: lados opuestos al clip original
    cl = random.randint(4, 8)
    cr = random.randint(8, 14)
    ct = random.randint(4, 8)
    cb = random.randint(8, 14)
    crop_asym = (
        f"scale=iw*{ZOOM}:ih*{ZOOM},"
        f"crop=iw/{ZOOM}:ih/{ZOOM},"
        f"crop=iw-{cl+cr}:ih-{ct+cb}:{cl}:{ct},"
        f"scale=trunc((iw+{cl+cr})/2)*2:trunc((ih+{ct+cb})/2)*2"
    )
    filters = [crop_asym, pts]
    # Siempre hflip en reciclados — opuesto al original
    filters.append("hflip")
    # vflip aleatorio 30% — cambia composición radicalmente
    if random.random() < 0.30:
        filters.append("vflip")
    # Hue shift ±8° — cambia el fingerprint de color
    hue = random.uniform(-8, 8)
    br  = random.uniform(-0.08, 0.08)
    sat = random.uniform(0.80, 1.20)
    filters.append(f"hue=h={hue:.1f}")
    filters.append(f"eq=brightness={br:.3f}:saturation={sat:.3f}")
    # Blur leve 0-0.5px — distorsiona el hash perceptual
    if random.random() < 0.50:
        filters.append("gblur=sigma=0.4")
    run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", str(src),
        "-vf", ",".join(filters),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-pix_fmt", "yuv420p", "-an",
        "-y", str(dst)
    ])

def strip_and_trim(src, dst, duration, width=None, height=None, fps=None):
    """Re-encodea imagen animada sin audio, recorta a 'duration' segundos.
    fps debe ser el racional EXACTO de los clips (ej. "30000/1001") para que
    el timebase del clip de imagen coincida con el de los clips normales.
    NO usar -video_track_timescale: causa mismatch con el timebase de apply_effects."""
    vf_parts = []
    if width and height:
        vf_parts.append(f"scale={width}:{height}:force_original_aspect_ratio=disable")
    if fps:
        vf_parts.append(f"fps={fps}")
    vf = ",".join(vf_parts) if vf_parts else "null"
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", str(src),
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-pix_fmt", "yuv420p", "-an",
        "-y", str(dst)
    ]
    run(cmd)

def load_canal_config(char_folder):
    """Lee _config/<nicho>.json. El nicho es el directorio padre de char_folder."""
    import json as _json
    nicho      = char_folder.parent.name
    base_dir   = char_folder.parent.parent
    config_path = base_dir / "_config" / f"{nicho}.json"
    if config_path.exists():
        return _json.loads(config_path.read_text(encoding="utf-8"))
    return {}

def load_timeline_inserts(char_folder):
    """Lee 05-montaje/timeline.json + 03-imagenes/.
    El prefijo del clip (flow_ o img_) se toma de _config/<nicho>.json:
      harvester.default_source == "flow"  → flow_{:04d}_zp.mp4
      cualquier otro valor               → img_{:04d}.mp4
    Siempre intenta el prefijo del config primero; si no existe, prueba el otro.
    """
    timeline_f = char_folder / "05-montaje" / "timeline.json"
    img_dir    = char_folder / "03-imagenes"
    if not timeline_f.exists():
        return []
    import json as _json
    cfg    = load_canal_config(char_folder)
    source = cfg.get("harvester", {}).get("default_source", "img")
    # Mapa source → prefijo de archivo en 03-imagenes/
    PREFIX = {"flow": "flow", "higgsfield": "hf", "ia": "img", "img": "img"}
    primary_prefix   = PREFIX.get(source, "img")
    secondary_prefix = "flow" if primary_prefix != "flow" else "img"

    data     = _json.loads(timeline_f.read_text(encoding="utf-8"))
    segments = data.get("visual_timeline", [])
    result   = []
    for seg in segments:
        seg_id  = seg.get("segment_id", 0)
        start_s = seg.get("start_seconds", 0)
        # seg_id puede ser int (1) o string ('flow_0001')
        if isinstance(seg_id, str) and '_' in seg_id:
            _num = seg_id.split('_')[-1]  # '0001'
            _id_fmt = _num
        else:
            _id_fmt = f"{int(seg_id):04d}"
        primary   = img_dir / f"{primary_prefix}_{_id_fmt}_zp.mp4"
        secondary = img_dir / f"{secondary_prefix}_{_id_fmt}_zp.mp4"
        if not secondary.exists():
            secondary = img_dir / f"img_{_id_fmt}.mp4"
        clip_path = primary if primary.exists() else secondary
        if clip_path.exists():
            dur = seg.get("duration", seg.get("end_seconds", start_s + 6) - start_s)
            result.append((start_s, clip_path, round(dur, 3)))
    result.sort(key=lambda x: x[0])
    return result


def load_sync(char_folder):
    """Lee *_sync.csv y retorna lista de (seg_secs, path_mp4_absoluta) ordenada por tiempo.
    Siempre busca el MP4 pre-convertido (.mp4) junto al JPG original."""
    csv_path = next(char_folder.glob("*_sync.csv"), None)
    if not csv_path:
        return []
    result = []
    used_files = set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                t = ts_to_sec(row["seg_inicio"])
                fuente = row["fuente"].strip()
                archivo = row["archivo"].strip()
                # Buscar MP4 pre-convertido primero, fallback a JPG original
                base = char_folder / fuente / pathlib.Path(archivo).stem
                mp4_path = base.with_suffix(".mp4")
                jpg_path = char_folder / fuente / archivo
                path = mp4_path if mp4_path.exists() else jpg_path
                if not path.exists():
                    print(f"  ⚠️  Archivo no encontrado: {path}")
                    continue
                key = f"{fuente}/{archivo}"
                if key in used_files:
                    print(f"  ⚠️  Imagen duplicada en sync CSV: {key} — se omite repetición")
                    continue
                used_files.add(key)
                result.append((t, path))
            except Exception as e:
                print(f"  ⚠️  Error en sync CSV: {e}")
    return sorted(result, key=lambda x: x[0]), used_files

def load_web_pool(char_folder, sync_used_files):
    """
    Carga el pool de imágenes de relleno en orden de prioridad:
    1. imagenes_web/ (excluyendo las ya usadas en sync)
    2. frames_extraidos/ del video
    Devuelve lista de paths MP4, sin repeticiones, mezclada aleatoriamente.
    Cada imagen se usa como máximo UNA vez.
    """
    pool = []
    
    # 1. imagenes_web/ no usadas en sync
    web_dir = char_folder / "imagenes_web"
    if web_dir.exists():
        for f in sorted(web_dir.glob("*.mp4")):
            key_jpg = f"imagenes_web/{f.stem}.jpg"
            key_mp4 = f"imagenes_web/{f.name}"
            if key_jpg not in sync_used_files and key_mp4 not in sync_used_files:
                pool.append(f)
    
    # 2. frames_extraidos/
    frames_dir = char_folder / "frames_extraidos"
    if frames_dir.exists():
        for f in sorted(frames_dir.glob("*.mp4")):
            pool.append(f)
    
    random.shuffle(pool)
    return pool  # lista finita — cada imagen se usa exactamente una vez

def load_inserts(char_folder, char_name, n_imagenes):
    """Retorna lista de (segundos_float, indice_1based) desde CSV prompts, filtrada por imágenes disponibles."""
    csv_path = char_folder / f"{char_name}_prompts.csv"
    if not csv_path.exists():
        return []
    result = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f), 1):
            if i > n_imagenes:
                break
            try:
                ts_col = row.get("seg_inicio") or row.get("timestamp") or ""
                result.append((ts_to_sec(ts_col), i))
            except Exception:
                pass
    return sorted(result)

def shuffled_cycle(n, ordered=False):
    """Generador que entrega (índice, is_recycled).
    Primera pasada completa: is_recycled=False.
    Ciclos siguientes: is_recycled=True (clips reciclados, al final del video).
    Si ordered=True respeta el orden 0..n-1 sin mezclar (cuando el usuario ordenó en el dashboard)."""
    indices = list(range(n))
    if not ordered:
        random.shuffle(indices)
    last_yielded = -1
    first_pass = True
    while True:
        for idx, i in enumerate(indices):
            if not ordered and i == last_yielded and n > 1:
                swap = (idx + 1) % len(indices)
                indices[idx], indices[swap] = indices[swap], indices[idx]
                i = indices[idx]
            yield (i, not first_pass)
            last_yielded = i
        last_end = last_yielded
        first_pass = False
        if not ordered:
            random.shuffle(indices)
            if indices[0] == last_end and n > 1:
                indices[0], indices[-1] = indices[-1], indices[0]

def check_clips_coverage(audio_dur, clip_dur, n_clips):
    """
    Retorna (necesarios, disponibles, deficit_pct).
    deficit_pct = qué % del material falta (0 si hay suficiente).
    """
    needed = math.ceil(audio_dur / clip_dur)
    if n_clips >= needed:
        return needed, n_clips, 0.0
    deficit_pct = (needed - n_clips) / needed
    return needed, n_clips, deficit_pct


def build_timeline(audio_dur, clip_durs, inserts, web_pool=None, sync_inserts=None, ordered=False):
    """
    Construye lista de segmentos. Cada imagen del pool se usa máximo UNA vez.
    tipos: 'clip' | 'img' | 'web' (path absoluta) | 'sync' (path absoluta)
    """
    timeline = []
    pos = 0.0
    pending_csv  = list(inserts)
    pending_sync = list(sync_inserts or [])
    clip_gen = shuffled_cycle(len(clip_durs), ordered=ordered)

    # Pool finito — cada imagen aparece exactamente 1 vez
    web_iter = iter(web_pool) if web_pool else iter([])
    next_web = next(web_iter, None)
    clips_since_web = 0

    def next_fixed_event():
        """Timestamp del próximo evento de tiempo fijo (sync o img CSV)."""
        t = None
        if pending_sync:
            t = pending_sync[0][0]
        if pending_csv:
            t_csv = pending_csv[0][0]
            t = t_csv if t is None else min(t, t_csv)
        return t

    def cap_dur(dur, pos, remaining):
        """Trunca cualquier segmento para que termine EXACTO en el próximo evento fijo."""
        nf = next_fixed_event()
        if nf is not None and pos < nf < pos + dur:
            dur = nf - pos
        return min(dur, remaining)

    MIN_SEG = 2.5  # ningún segmento puede durar menos — evita cortes bruscos

    while pos < audio_dur - 0.05:
        remaining = audio_dur - pos

        # Anti-corte-brusco: si falta menos de MIN_SEG para el próximo evento fijo,
        # el evento entra AHORA (un poco antes) en vez de meter un segmento de 1s
        nf = next_fixed_event()
        entra_ya = nf is not None and (nf - pos) < MIN_SEG

        # Sync: imagen sincronizada con guion (prioridad máxima, timestamp exacto)
        if pending_sync and (pos >= pending_sync[0][0] - 0.05 or
                             (entra_ya and nf == pending_sync[0][0])):
            entry = pending_sync.pop(0)
            t_insert, img_path = entry[0], entry[1]
            clip_dur = entry[2] if len(entry) > 2 else IMAGE_DUR
            dur = cap_dur(clip_dur, pos, remaining)
            timeline.append(("sync", img_path, dur))
            pos += dur
            continue

        # CSV prompts: imagen IA en timestamp fijo
        if pending_csv and (pos >= pending_csv[0][0] - 0.05 or
                            (entra_ya and nf == pending_csv[0][0])):
            t_insert, img_idx = pending_csv.pop(0)
            dur = cap_dur(IMAGE_DUR, pos, remaining)
            timeline.append(("img", img_idx, dur))
            pos += dur
            continue

        # Relleno: cada IMG_WEB_INTERVAL clips, si quedan imágenes disponibles
        if next_web is not None and clips_since_web >= IMG_WEB_INTERVAL:
            dur = cap_dur(IMAGE_DUR, pos, remaining)
            timeline.append(("web", next_web, dur))
            pos += dur
            clips_since_web = 0
            next_web = next(web_iter, None)  # avanza — nunca repite
            continue

        # Clip del video — también se trunca en el próximo evento fijo
        ci, is_recycled = next(clip_gen)
        flip = random.random() < FLIP_CHANCE
        dur = cap_dur(clip_durs[ci], pos, remaining)
        seg_type = "recycled_clip" if is_recycled else "clip"
        timeline.append((seg_type, ci, dur, flip))
        pos += dur
        clips_since_web += 1

    return timeline

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 render.py /ruta/carpeta/personaje/ [--preview SEGUNDOS]")
        sys.exit(1)

    char_folder  = pathlib.Path(sys.argv[1])
    clips_dir    = char_folder / "clips"
    imagenes_dir = char_folder / "imagenes"

    # ── Flag --preview ─────────────────────────────────────────────────────
    preview_secs = None
    for i, arg in enumerate(sys.argv[2:]):
        if arg == "--preview" and i + 3 < len(sys.argv):
            preview_secs = float(sys.argv[i + 3])
        elif arg.startswith("--preview="):
            preview_secs = float(arg.split("=", 1)[1])

    # ── Chequeo footage aprobado ────────────────────────────────────────────
    meta_path = char_folder / "metadata.json"
    if meta_path.exists():
        import json as _json
        _meta    = _json.loads(meta_path.read_text(encoding="utf-8"))
        _footage = _meta.get("footage", {})
        if _footage:
            _pendientes = [c for c, v in _footage.items() if v.get("estado") == "pendiente"]
            _errores    = [c for c, v in _footage.items() if v.get("estado") == "error"]
            if _pendientes:
                print(f"\n⛔ RENDER BLOQUEADO — {len(_pendientes)} imagen(s) sin aprobar:")
                for c in _pendientes[:5]:
                    print(f"   · {c}")
                print(f"\n   Abrí el dashboard: http://localhost:5001/aprobar/{sys.argv[1]}")
                print(f"   Aprobá las imágenes y volvé a lanzar el render.\n")
                sys.exit(1)
            if _errores:
                print(f"⚠  {len(_errores)} imagen(s) con error — se omitirán en el render.")

    # ── Audio ──────────────────────────────────────────────────────────────
    mp3s = sorted([f for f in char_folder.glob("*.mp3") if "_test" not in f.name and "_src" not in f.name])
    if not mp3s:
        print("ERROR: No encontré ningún .mp3 en la carpeta"); sys.exit(1)
    audio_file = mp3s[0]
    char_name  = audio_file.stem
    audio_dur  = get_duration(audio_file)
    if preview_secs:
        audio_dur = min(audio_dur, preview_secs)

    # ── Música de fondo (opcional) ─────────────────────────────────────────
    # Busca musica.mp3 en la carpeta del video, o musica/musica_v1.mp3 en el nicho padre
    music_file = None
    for candidate in [
        char_folder / "musica.mp3",
        char_folder / "musica_v1.mp3",
        char_folder.parent.parent / "_musica" / char_folder.parent.name / "musica_v1.mp3",
        char_folder.parent.parent / "_musica" / char_folder.parent.name / "musica_v2.mp3",
    ]:
        if candidate.exists():
            music_file = candidate
            break
    if music_file:
        print(f"Música     : {music_file.name} (se mezcla a -20dB en loop)")

    # ── Clips (respetar orden del dashboard; excluir rechazados) ──────────────
    import json as _json
    _rejected_yt = set()
    _clips_order  = []
    if meta_path.exists():
        _meta_full   = _json.loads(meta_path.read_text(encoding="utf-8"))
        # rejected_yt_clips = marcados como rechazados
        # deleted_yt_clips  = borrados físicamente desde el dashboard
        _rejected_yt = {k for k, v in _meta_full.get("rejected_yt_clips", {}).items() if v == "rechazado"}
        _rejected_yt |= set(_meta_full.get("deleted_yt_clips", {}).keys())
        _clips_order = _meta_full.get("clips_order", [])
    if _rejected_yt:
        print(f"ℹ️  Excluyendo {len(_rejected_yt)} clips rechazados desde dashboard")
    def _clip_num(f):
        m = re.search(r"(\d+)", f.stem)
        return int(m.group(1)) if m else 0
    _all_clip_files = {f.name: f for f in clips_dir.glob("*.mp4")
                       if re.search(r"\d+", f.stem) and f.name not in _rejected_yt}
    if _clips_order:
        # Respetar EXACTAMENTE el orden del dashboard — sin agregar clips extra
        clips = [_all_clip_files[n] for n in _clips_order if n in _all_clip_files]
        print(f"ℹ️  Orden clips: respetando dashboard ({len(clips)} clips)")
    else:
        clips = sorted(_all_clip_files.values(), key=_clip_num)
    if not clips:
        print("ERROR: No encontré clips en clips/"); sys.exit(1)
    clip_dur = get_duration(clips[0])

    # ── Verificar cobertura de clips vs audio ─────────────────────────────
    needed, available, deficit_pct = check_clips_coverage(audio_dur, clip_dur, len(clips))
    if deficit_pct > 0:
        print(f"ℹ️  Clips insuficientes ({deficit_pct*100:.0f}% de déficit) — reciclando con crop/flip diferente al final")

    # ── Imágenes animadas (opcionales) ────────────────────────────────────
    imagenes_dir.mkdir(exist_ok=True)  # siempre crear la carpeta
    imagenes = []
    if imagenes_dir.exists():
        imagenes = sorted(
            [f for f in imagenes_dir.glob("*.mp4") if re.fullmatch(r"\d+\.mp4", f.name)],
            key=lambda x: int(x.stem)
        )

    # ── Imágenes web (relleno general) ────────────────────────────────────
    imagenes_web_dir = char_folder / "imagenes_web"
    imagenes_web = []
    if imagenes_web_dir.exists():
        imagenes_web = sorted(
            [f for f in imagenes_web_dir.glob("*.mp4") if re.fullmatch(r"\d+\.mp4", f.name)],
            key=lambda x: int(x.stem)
        )

    inserts = load_inserts(char_folder, char_name, len(imagenes))
    sync_result = load_sync(char_folder)
    if sync_result:
        sync_inserts, sync_used_files = sync_result
    else:
        sync_inserts, sync_used_files = [], set()

    # timeline.json (nuevo sistema) — se mezcla con sync_inserts si existe
    timeline_inserts = load_timeline_inserts(char_folder)
    if timeline_inserts:
        print(f"Timeline   : {len(timeline_inserts)} imágenes desde timeline.json (Pexels/IA)")
        sync_inserts = sorted(sync_inserts + timeline_inserts, key=lambda x: x[0])

    # Pool de relleno: imagenes_web + frames_extraidos, sin repeticiones, sin las ya usadas en sync
    web_pool = load_web_pool(char_folder, sync_used_files)
    if web_pool:
        print(f"Pool relleno: {len(web_pool)} imágenes únicas (web + frames) · cada {IMG_WEB_INTERVAL} clips")

    out_file = (char_folder / (f"{char_name}_preview.mp4" if preview_secs else f"{char_name}_final.mp4")).resolve()

    print(f"Personaje  : {char_name}")
    print(f"Audio      : {audio_file.name} ({audio_dur/60:.1f} min)")
    print(f"Clips      : {len(clips)} disponibles ({clip_dur:.1f}s c/u)")
    if imagenes:
        print(f"Imágenes   : {len(imagenes)} · {len(inserts)} inserciones en timestamps del CSV")
    else:
        print(f"Imágenes   : ninguna — modo solo clips")
    if sync_inserts:
        print(f"Sync guion : {len(sync_inserts)} imágenes sincronizadas con narración")
    print(f"Salida     : {out_file.name}")
    print("-" * 50)

    # ── Construir timeline ────────────────────────────────────────────────
    print("Midiendo duración real de cada clip...")
    clip_durs = [get_duration(c) for c in clips]
    timeline = build_timeline(audio_dur, clip_durs, inserts, web_pool=web_pool, sync_inserts=sync_inserts, ordered=bool(_clips_order))
    n_clips_in_tl    = sum(1 for s in timeline if s[0] == "clip")
    n_recycled_in_tl = sum(1 for s in timeline if s[0] == "recycled_clip")
    n_imgs_in_tl     = sum(1 for s in timeline if s[0] == "img")
    n_web_in_tl      = sum(1 for s in timeline if s[0] == "web")
    n_sync_in_tl     = sum(1 for s in timeline if s[0] == "sync")
    print(f"Timeline   : {len(timeline)} segmentos ({n_clips_in_tl} clips + {n_recycled_in_tl} reciclados + {n_imgs_in_tl} imgs CSV + {n_web_in_tl} imgs relleno + {n_sync_in_tl} imgs sync)")

    # Guardar orden real de clips usado en el render (para validar vs dashboard)
    import json as _json
    _render_order = [clips[s[1]].name for s in timeline if s[0] in ("clip", "recycled_clip")]
    _render_order_path = char_folder / "render_used_order.json"
    _render_order_path.write_text(_json.dumps({
        "clips_order_dashboard": _clips_order,
        "clips_used_render": _render_order,
        "total_clips": len(_render_order),
        "recycled_start": n_clips_in_tl,
    }, indent=2, ensure_ascii=False))

    # Obtener resolución y fps del primer clip procesado (referencia para imágenes)
    ref_info = run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=width,height,r_frame_rate",
                    "-of", "csv=p=0", str(clips[0])], capture=True)
    ref_w, ref_h, ref_fps_raw = ref_info.stdout.strip().split(",")
    ref_w, ref_h = int(ref_w), int(ref_h)
    # Usar el racional EXACTO (ej. "30000/1001") — NO redondear a decimal,
    # el concat descarta frames si los timebases no coinciden exactamente
    ref_fps = ref_fps_raw

    with tempfile.TemporaryDirectory(prefix="render_") as tmp:
        tmp_dir = pathlib.Path(tmp)
        processed_clips = {}  # cache: clip_index → path procesado

        concat_lines = []
        print(f"\nProcesando segmentos... (clips: {ref_w}x{ref_h} @ {ref_fps}fps)")

        for i, seg in enumerate(timeline, 1):
            if seg[0] in ("clip", "recycled_clip"):
                _, ci, dur, flip = seg
                is_recycled = seg[0] == "recycled_clip"
                if is_recycled:
                    # Reciclado: aplicar crop distinto, siempre re-encodear
                    recycled_key = f"r_{ci}"
                    if recycled_key not in processed_clips:
                        dst_r = tmp_dir / f"recycled_{ci:05d}.mp4"
                        apply_effects_recycled(clips[ci], dst_r, flip)
                        processed_clips[recycled_key] = dst_r
                    src = processed_clips[recycled_key]
                else:
                    if ci not in processed_clips:
                        # Re-encodear siempre para normalizar fps/timebase y aplicar anti-fingerprint
                        dst_clip = tmp_dir / f"clip_{ci:05d}.mp4"
                        apply_effects(clips[ci], dst_clip, flip, ref_fps, ref_w, ref_h)
                        processed_clips[ci] = dst_clip
                    src = processed_clips[ci]
                actual_dur = get_duration(src)
                if dur < actual_dur - 0.1:
                    trimmed = tmp_dir / f"trim_{i:05d}.mp4"
                    strip_and_trim(src, trimmed, dur, ref_w, ref_h, ref_fps)
                    concat_lines.append(f"file '{trimmed.resolve()}'")
                else:
                    concat_lines.append(f"file '{src}'")

            elif seg[0] == "sync":  # imagen sincronizada con guion — usar MP4 pre-convertido
                _, img_path, dur = seg
                if img_path.suffix.lower() == ".mp4":
                    src = img_path
                else:
                    mp4 = img_path.with_suffix(".mp4")
                    src = mp4 if mp4.exists() else img_path
                safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', img_path.stem)
                dst = tmp_dir / f"sync_{safe_name}_{i:05d}.mp4"
                if src.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                    cmd = [
                        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
                        "-loop", "1", "-framerate", "30", "-i", str(src),
                        "-t", str(IMAGE_DUR),
                        "-vf", f"scale={ref_w}:{ref_h}:force_original_aspect_ratio=disable,fps={ref_fps}",
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                        "-pix_fmt", "yuv420p", "-an", "-y", str(dst)
                    ]
                    run(cmd)
                else:
                    strip_and_trim(src, dst, dur, ref_w, ref_h, ref_fps)
                concat_lines.append(f"file '{dst}'")

            elif seg[0] == "img":  # img CSV — re-encodear con resolución y fps de los clips
                _, img_idx, dur = seg
                src = imagenes[img_idx - 1]
                dst = tmp_dir / f"img_{img_idx:03d}.mp4"
                if not dst.exists():
                    strip_and_trim(src, dst, IMAGE_DUR, ref_w, ref_h, ref_fps)
                actual_dur = get_duration(dst)
                if dur < actual_dur - 0.1:
                    trimmed = tmp_dir / f"imgtrim_{i:05d}.mp4"
                    strip_and_trim(dst, trimmed, dur, ref_w, ref_h, ref_fps)
                    concat_lines.append(f"file '{trimmed}'")
                else:
                    concat_lines.append(f"file '{dst}'")

            else:  # web — imagen de relleno (path absoluta del pool)
                _, img_path, dur = seg
                safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', img_path.stem)
                dst = tmp_dir / f"web_{safe_name}_{i:05d}.mp4"
                strip_and_trim(img_path, dst, IMAGE_DUR, ref_w, ref_h, ref_fps)
                actual_dur = get_duration(dst)
                if dur < actual_dur - 0.1:
                    trimmed = tmp_dir / f"webtrim_{i:05d}.mp4"
                    strip_and_trim(dst, trimmed, dur, ref_w, ref_h, ref_fps)
                    concat_lines.append(f"file '{trimmed}'")
                else:
                    concat_lines.append(f"file '{dst}'")

            if i % 30 == 0 or i == len(timeline):
                print(f"  {i}/{len(timeline)} segmentos")

        concat_file = tmp_dir / "concat.txt"
        concat_file.write_text("\n".join(concat_lines) + "\n")

        print(f"\nRenderizando video final...")
        if music_file:
            # Mezcla: voz + música en loop a -20dB (≈-28 LUFS bajo la voz)
            filter_complex = (
                f"[2:a]aloop=loop=-1:size=2e+09,atrim=duration={audio_dur:.3f},"
                f"asetpts=PTS-STARTPTS,volume=0.12[music];"
                f"[1:a][music]amix=inputs=2:duration=first:dropout_transition=2[audio]"
            )
            run([
                FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
                "-fflags", "+genpts",
                "-f", "concat", "-safe", "0", "-i", str(concat_file),
                "-i", str(audio_file),
                "-i", str(music_file),
                "-t", str(audio_dur),
                "-filter_complex", filter_complex,
                "-map", "0:v", "-map", "[audio]",
                "-vf", "scale=iw:ih",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                "-pix_fmt", "yuv420p",
                "-fps_mode", "cfr",
                "-c:a", "aac", "-b:a", "128k",
                "-shortest",
                "-y", str(out_file)
            ])
        else:
            run([
                FFMPEG, "-hide_banner", "-loglevel", "warning", "-nostdin",
                "-fflags", "+genpts",
                "-f", "concat", "-safe", "0", "-i", str(concat_file),
                "-i", str(audio_file),
                "-t", str(audio_dur),
                "-map", "0:v", "-map", "1:a",
                "-vf", "scale=iw:ih",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                "-pix_fmt", "yuv420p",
                "-fps_mode", "cfr",
                "-c:a", "aac", "-b:a", "128k",
                "-shortest",
                "-y", str(out_file)
            ])

    size_mb = out_file.stat().st_size / (1024 * 1024)
    print(f"\n✓ Video final: {out_file}")
    print(f"  Duración: {audio_dur/60:.1f} min | Tamaño: {size_mb:.0f} MB")
    msg = f"✅ {out_file.name} listo — {audio_dur/60:.1f} min | {size_mb:.0f} MB"
    _macos_notify(f"Render terminado", msg)

def _macos_notify(title, body):
    try:
        import subprocess
        script = f'display notification "{body}" with title "{title}" sound name "Glass"'
        subprocess.run(["osascript", "-e", script], check=False)
    except Exception:
        pass

if __name__ == "__main__":
    main()
