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

def apply_effects(src, dst, flip):
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
    run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", str(src),
        "-vf", ",".join(filters),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
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
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-an",
        "-y", str(dst)
    ]
    run(cmd)

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
                result.append((ts_to_sec(row["seg_inicio"]), i))
            except Exception:
                pass
    return sorted(result)
    """Retorna lista de (segundos_float, indice_1based) desde CSV, filtrada por imágenes disponibles."""
    csv_path = char_folder / f"{char_name}_prompts.csv"
    if not csv_path.exists():
        return []
    result = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f), 1):
            if i > n_imagenes:
                break
            try:
                result.append((ts_to_sec(row["seg_inicio"]), i))
            except Exception:
                pass
    return sorted(result)

def shuffled_cycle(n):
    """Generador que entrega índices 0..n-1 en orden aleatorio,
    re-shuffleando cada vez que completa un ciclo (nunca repite el orden)."""
    indices = list(range(n))
    last_end = -1
    while True:
        random.shuffle(indices)
        # Evitar que el primer elemento del nuevo ciclo sea igual al último del anterior
        if indices[0] == last_end and n > 1:
            indices[0], indices[-1] = indices[-1], indices[0]
        for i in indices:
            yield i
        last_end = indices[-1]

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

def download_extra_clips(url, clips_dir, char_folder):
    """Descarga clips extra de una URL adicional y los añade a clips_dir."""
    import subprocess, pathlib
    YTDLP  = "/opt/homebrew/bin/yt-dlp"
    FFMPEG = "/opt/homebrew/bin/ffmpeg"
    FFPROBE= "/opt/homebrew/bin/ffprobe"
    if not pathlib.Path(YTDLP).exists():
        YTDLP  = "/usr/local/bin/yt-dlp"
        FFMPEG = "/usr/local/bin/ffmpeg"
        FFPROBE= "/usr/local/bin/ffprobe"

    icloud_yt = pathlib.Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/yt"
    icloud_yt.mkdir(parents=True, exist_ok=True)

    print(f"[EXTRA] Descargando video adicional...")
    out_tpl = str(icloud_yt / "%(title)s.%(ext)s")
    YT_FORMAT = "bestvideo[ext=mp4][height=1080]+bestaudio[ext=m4a]/bestvideo[ext=mp4][height=720]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
    for cmd in [
        [YTDLP, "--no-playlist", "--extractor-args", "youtube:player_client=ios,web,mweb",
         "-f", YT_FORMAT, "--merge-output-format", "mp4", "-o", out_tpl, url],
        [YTDLP, "--no-playlist", "--cookies-from-browser", "chrome",
         "-f", "best", "-o", out_tpl, url],
    ]:
        r = subprocess.run(cmd, check=False)
        if r.returncode == 0:
            break

    mp4s = sorted(icloud_yt.glob("*.mp4"), key=lambda x: x.stat().st_mtime, reverse=True)
    if not mp4s:
        print("[EXTRA] ERROR: no se descargó ningún video"); return

    video_path = mp4s[0]
    print(f"[EXTRA] Video descargado: {video_path.name}")

    # Obtener el número más alto de clip existente
    existing = [int(f.stem) for f in clips_dir.glob("*.mp4") if re.fullmatch(r"\d+\.mp4", f.name)]
    next_n = max(existing) + 1 if existing else 1

    # Duración del video
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nokey=1:noprint_wrappers=1", str(video_path)],
                       capture_output=True, text=True)
    total_dur = float(r.stdout.strip())

    # Cortar en clips de 5s y agregar con numeración continua
    tmp_pattern = str(clips_dir / "__extra_%06d.mp4")
    subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", str(video_path), "-an",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-force_key_frames", "expr:gte(t,n_forced*5)",
        "-f", "segment", "-segment_time", "5", "-reset_timestamps", "1",
        tmp_pattern
    ], check=True)

    extras = sorted(clips_dir.glob("__extra_*.mp4"))
    for i, f in enumerate(extras):
        f.rename(clips_dir / f"{next_n + i}.mp4")

    print(f"[EXTRA] ✓ {len(extras)} clips adicionales agregados (desde {next_n})")

def build_timeline(audio_dur, clip_durs, inserts, n_web=0, sync_inserts=None):
    """
    Construye lista de segmentos (tipo, datos, dur).
    tipos:
      'clip'      — clip del video (indice en clip_durs)
      'img'       — imagen IA en timestamp fijo del CSV prompts
      'web'       — imagen web relleno aleatorio cada IMG_WEB_INTERVAL clips
      'sync'      — imagen sincronizada con guion (path absoluta)
    - sync_inserts: lista de (seg_secs, path) del *_sync.csv — tienen prioridad
    """
    timeline = []
    pos = 0.0
    pending_csv  = list(inserts)          # timestamps del CSV prompts (img IA fijas)
    pending_sync = list(sync_inserts or [])  # timestamps del sync CSV (img-guion)
    clip_gen = shuffled_cycle(len(clip_durs))
    web_gen  = shuffled_cycle(n_web) if n_web > 0 else None
    clips_since_web = 0

    while pos < audio_dur - 0.05:
        remaining = audio_dur - pos

        # ¿Toca insertar imagen sincronizada con guion? (prioridad máxima)
        if pending_sync and pos + 2.5 >= pending_sync[0][0]:
            t_insert, img_path = pending_sync.pop(0)
            dur = min(IMAGE_DUR, remaining)
            timeline.append(("sync", img_path, dur))
            pos += dur
            continue

        # ¿Toca insertar imagen fija del CSV prompts?
        if pending_csv and pos + 2.5 >= pending_csv[0][0]:
            t_insert, img_idx = pending_csv.pop(0)
            dur = min(IMAGE_DUR, remaining)
            timeline.append(("img", img_idx, dur))
            pos += dur
            continue

        # ¿Toca insertar imagen web de relleno? (cada IMG_WEB_INTERVAL clips)
        if web_gen is not None and clips_since_web >= IMG_WEB_INTERVAL:
            dur = min(IMAGE_DUR, remaining)
            wi = next(web_gen)
            timeline.append(("web", wi, dur))
            pos += dur
            clips_since_web = 0
            continue

        # Clip normal
        ci = next(clip_gen)
        dur = min(clip_durs[ci], remaining)
        flip = random.random() < FLIP_CHANCE
        timeline.append(("clip", ci, dur, flip))
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

    # ── Audio ──────────────────────────────────────────────────────────────
    mp3s = sorted([f for f in char_folder.glob("*.mp3") if "_test" not in f.name and "_src" not in f.name])
    if not mp3s:
        print("ERROR: No encontré ningún .mp3 en la carpeta"); sys.exit(1)
    audio_file = mp3s[0]
    char_name  = audio_file.stem
    audio_dur  = get_duration(audio_file)
    if preview_secs:
        audio_dur = min(audio_dur, preview_secs)

    # ── Clips ──────────────────────────────────────────────────────────────
    clips = sorted(
        [f for f in clips_dir.glob("*.mp4") if re.fullmatch(r"\d+\.mp4", f.name)],
        key=lambda x: int(x.stem)
    )
    if not clips:
        print("ERROR: No encontré clips en clips/"); sys.exit(1)
    clip_dur = get_duration(clips[0])

    # ── Verificar cobertura de clips vs audio ─────────────────────────────
    needed, available, deficit_pct = check_clips_coverage(audio_dur, clip_dur, len(clips))
    if deficit_pct >= 0.50:
        print(f"\n⚠️  Material insuficiente:")
        print(f"   Audio necesita : {needed} clips ({audio_dur/60:.1f} min)")
        print(f"   Clips disponibles: {available} ({available*clip_dur/60:.1f} min)")
        print(f"   Déficit: {deficit_pct*100:.0f}% del material falta")
        print(f"\n   Se necesita un video adicional para completar el render.")
        url_extra = input("   Pega una URL de YouTube adicional del personaje: ").strip()
        if url_extra:
            download_extra_clips(url_extra, clips_dir, char_folder)
            # Recargar clips
            clips = sorted(
                [f for f in clips_dir.glob("*.mp4") if re.fullmatch(r"\d+\.mp4", f.name)],
                key=lambda x: int(x.stem)
            )
            print(f"   ✓ Ahora hay {len(clips)} clips disponibles")
        else:
            print("   Continuando con ciclo re-shuffleado (puede haber repetición visible).")
    elif deficit_pct > 0:
        print(f"ℹ️  Clips insuficientes ({deficit_pct*100:.0f}% de déficit) — usando ciclo re-shuffleado")

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

    # Filtrar imagenes_web: excluir las que ya están asignadas en sync para no repetir
    imagenes_web_filtradas = [
        f for f in imagenes_web
        if f"imagenes_web/{f.name.replace('.mp4', '.jpg')}" not in sync_used_files
        and f"imagenes_web/{f.name}" not in sync_used_files
    ]
    if len(imagenes_web_filtradas) < len(imagenes_web):
        excluidas = len(imagenes_web) - len(imagenes_web_filtradas)
        print(f"  ℹ️  {excluidas} imgs web excluidas del relleno (ya en sync)")

    out_file = char_folder / (f"{char_name}_preview.mp4" if preview_secs else f"{char_name}_final.mp4")

    print(f"Personaje  : {char_name}")
    print(f"Audio      : {audio_file.name} ({audio_dur/60:.1f} min)")
    print(f"Clips      : {len(clips)} disponibles ({clip_dur:.1f}s c/u)")
    if imagenes:
        print(f"Imágenes   : {len(imagenes)} · {len(inserts)} inserciones en timestamps del CSV")
    else:
        print(f"Imágenes   : ninguna — modo solo clips")
    if imagenes_web:
        print(f"Imgs web   : {len(imagenes_web_filtradas)} disponibles para relleno · cada {IMG_WEB_INTERVAL} clips")
    if sync_inserts:
        print(f"Sync guion : {len(sync_inserts)} imágenes sincronizadas con narración")
    print(f"Salida     : {out_file.name}")
    print("-" * 50)

    # ── Construir timeline ────────────────────────────────────────────────
    print("Midiendo duración real de cada clip...")
    clip_durs = [get_duration(c) for c in clips]
    timeline = build_timeline(audio_dur, clip_durs, inserts, n_web=len(imagenes_web_filtradas), sync_inserts=sync_inserts)
    n_clips_in_tl = sum(1 for s in timeline if s[0] == "clip")
    n_imgs_in_tl  = sum(1 for s in timeline if s[0] == "img")
    n_web_in_tl   = sum(1 for s in timeline if s[0] == "web")
    n_sync_in_tl  = sum(1 for s in timeline if s[0] == "sync")
    print(f"Timeline   : {len(timeline)} segmentos ({n_clips_in_tl} clips + {n_imgs_in_tl} imgs CSV + {n_web_in_tl} imgs web + {n_sync_in_tl} imgs sync)")

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
            if seg[0] == "clip":
                _, ci, dur, flip = seg
                if ci not in processed_clips:
                    # Usar el clip original directamente — sin re-encodear
                    processed_clips[ci] = clips[ci].resolve()
                src = processed_clips[ci]
                actual_dur = get_duration(src)
                if dur < actual_dur - 0.1:
                    trimmed = tmp_dir / f"trim_{i:05d}.mp4"
                    strip_and_trim(src, trimmed, dur)
                    concat_lines.append(f"file '{trimmed.resolve()}'")
                else:
                    concat_lines.append(f"file '{src}'")

            elif seg[0] == "sync":  # imagen sincronizada con guion — usar MP4 pre-convertido
                _, img_path, dur = seg
                # Si ya es MP4 pre-convertido, usarlo directamente
                if img_path.suffix.lower() == ".mp4":
                    src = img_path
                else:
                    # Fallback: JPG → buscar MP4 hermano
                    mp4 = img_path.with_suffix(".mp4")
                    src = mp4 if mp4.exists() else img_path
                safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', img_path.stem)
                dst = tmp_dir / f"sync_{safe_name}_{i:05d}.mp4"
                if src.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                    # Último recurso: convertir desde imagen estática
                    cmd = [
                        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
                        "-loop", "1", "-framerate", "30", "-i", str(src),
                        "-t", str(IMAGE_DUR),
                        "-vf", f"scale={ref_w}:{ref_h}:force_original_aspect_ratio=disable,fps={ref_fps}",
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
                        "-pix_fmt", "yuv420p", "-an", "-y", str(dst)
                    ]
                    run(cmd)
                else:
                    strip_and_trim(src, dst, IMAGE_DUR, ref_w, ref_h, ref_fps)
                actual_dur = get_duration(dst)
                if dur < actual_dur - 0.1:
                    trimmed = tmp_dir / f"synctrim_{i:05d}.mp4"
                    strip_and_trim(dst, trimmed, dur, ref_w, ref_h, ref_fps)
                    concat_lines.append(f"file '{trimmed}'")
                else:
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

            else:  # web — imagen de imagenes_web/, relleno general
                _, wi, dur = seg
                src = imagenes_web_filtradas[wi] if imagenes_web_filtradas else imagenes_web[wi]
                dst = tmp_dir / f"web_{wi:03d}.mp4"
                if not dst.exists():
                    strip_and_trim(src, dst, IMAGE_DUR, ref_w, ref_h, ref_fps)
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
        run([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
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
