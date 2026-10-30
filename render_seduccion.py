#!/usr/bin/env python3
"""
render_seduccion.py — Render para canal Enigma Estoica (nicho seducción).

Lógica específica de este nicho:
  - Lee 05-montaje/timeline.json → orden y duración exacta de cada segmento
  - Cada segmento usa su img_XXXX.mp4 ya animada (Ken Burns del harvester)
  - Recorta cada clip a la duración exacta del segmento
  - Concatena todo con el audio de locución
  - Mezcla música de fondo en loop a -20dB
  - Anti-fingerprint: flip 50% + speed ±2% + zoom 4%
  - Sin noise ni vignette (estilo minimalista stick figure)
  - Bloquea si hay footage pendiente de aprobación en metadata.json

Uso:
    python3 render_seduccion.py seduccion/7_errores/
    python3 render_seduccion.py seduccion/7_errores/ --preview 60
"""

import sys, json, random, subprocess, pathlib, tempfile, re
from concurrent.futures import ThreadPoolExecutor, as_completed

FFMPEG  = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"
if not pathlib.Path(FFMPEG).exists():
    FFMPEG  = "/usr/local/bin/ffmpeg"
    FFPROBE = "/usr/local/bin/ffprobe"

# ffmpeg-full tiene libass/libfreetype — usar para subtítulos
FFMPEG_FULL = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
if not pathlib.Path(FFMPEG_FULL).exists():
    FFMPEG_FULL = FFMPEG  # fallback al ffmpeg normal

# Valores por defecto — se sobreescriben con _config/seduccion.json en main()
CRF          = 28
PRESET       = "ultrafast"
AUDIO_K      = "128k"
RES_W        = 1920
RES_H        = 1080
FPS          = 30
MAX_CLIP_DUR = 8.0
SPEED_RANGE  = 0.04
MUSIC_VOL    = 0.12
WORKERS      = 4

VERDE    = "\033[92m"
ROJO     = "\033[91m"
AMARILLO = "\033[93m"
RESET    = "\033[0m"

def ok(msg):   print(f"  {VERDE}✓{RESET} {msg}")
def err(msg):  print(f"  {ROJO}✗{RESET} {msg}"); sys.exit(1)
def warn(msg): print(f"  {AMARILLO}⚠{RESET} {msg}")

# ── Utilidades ───────────────────────────────────────────────────────────────

def run(cmd, check=True):
    return subprocess.run(cmd, check=check, capture_output=True, text=True)

def get_duration(path):
    r = run([FFPROBE, "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=nokey=1:noprint_wrappers=1", str(path)])
    return float(r.stdout.strip())

def sec_to_hms(s):
    h = int(s // 3600); s -= h * 3600
    m = int(s // 60);   s -= m * 60
    return f"{h:02d}:{m:02d}:{s:05.2f}"

# ── Verificar aprobación ──────────────────────────────────────────────────────

def verificar_aprobacion(carpeta):
    meta_path = carpeta / "metadata.json"
    if not meta_path.exists():
        return
    meta    = json.loads(meta_path.read_text(encoding="utf-8"))
    footage = meta.get("footage", {})
    pendientes = [k for k, v in footage.items() if v.get("estado") == "pendiente"]
    if pendientes:
        print(f"\n{ROJO}⛔ Render bloqueado — {len(pendientes)} imagen(s) pendiente(s) de aprobación.{RESET}")
        print(f"   Aprobá en: http://localhost:5001/aprobar/{carpeta.parent.name}/{carpeta.name}/")
        sys.exit(1)

# ── Subtítulos estilo viral ──────────────────────────────────────────────────

def srt_to_ass(srt_path, ass_path, max_chars_per_line=42):
    """Convierte SRT a ASS para quemarlo con ffmpeg-full (libass).
    Estilo: Arial 58pt bold, blanco, borde negro 4px, mayúsculas, centrado abajo.
    """
    import re as _re

    ASS_HEADER = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,58,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,2,80,80,70,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def ts_to_ass(ts):
        ts = ts.strip().replace(',', '.')
        p  = ts.split(':')
        h, m = int(p[0]), int(p[1])
        s    = float(p[2])
        cs   = round((s - int(s)) * 100)
        return f"{h}:{m:02d}:{int(s):02d}.{cs:02d}"

    def wrap_text(text, max_chars):
        words = text.split()
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if len(test) <= max_chars:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return r"\N".join(lines)

    content = pathlib.Path(srt_path).read_text(encoding="utf-8")
    blocks  = _re.split(r'\n\n+', content.strip())
    events  = []

    for block in blocks:
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if len(lines) < 3 or '-->' not in lines[1]:
            continue
        times = lines[1].split('-->')
        start = ts_to_ass(times[0])
        end   = ts_to_ass(times[1])
        text  = ' '.join(lines[2:]).strip().upper()
        text  = wrap_text(text, max_chars_per_line)
        events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    pathlib.Path(ass_path).write_text(ASS_HEADER + "\n".join(events) + "\n", encoding="utf-8")
    return len(events)


def srt_to_drawtext_filter(srt_path, max_chars_per_line=36):
    """
    Convierte SRT a filtro drawtext de FFmpeg (no requiere libass).
    Estilo: blanco bold, borde negro grueso, centrado abajo, mayúsculas.
    """
    import re as _re

    def ts_to_sec(ts):
        ts = ts.strip().replace(',', '.')
        p  = ts.split(':')
        return int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])

    def escape_dt(text):
        # drawtext escaping: \ → \\, ' → \', : → \:, % → \\%
        text = text.replace("\\", "\\\\")
        text = text.replace("'",  "\\'")
        text = text.replace(":",  "\\:")
        text = text.replace("%",  "\\%")
        return text

    def wrap_lines(text, max_chars):
        """Devuelve lista de líneas (sin unir) para escapar antes de agregar \\n."""
        words   = text.split()
        lines   = []
        current = ""
        for w in words:
            test = (current + " " + w).strip()
            if len(test) <= max_chars:
                current = test
            else:
                if current:
                    lines.append(current)
                current = w
        if current:
            lines.append(current)
        return lines

    content = pathlib.Path(srt_path).read_text(encoding="utf-8")
    blocks  = _re.split(r'\n\n+', content.strip())
    entries = []

    for block in blocks:
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if len(lines) < 3 or '-->' not in lines[1]:
            continue
        times  = lines[1].split('-->')
        start  = ts_to_sec(times[0])
        end    = ts_to_sec(times[1])
        raw    = ' '.join(lines[2:]).strip().upper()
        # Escapar cada línea individualmente, luego unir con \n
        wrapped = wrap_lines(raw, max_chars_per_line)
        text    = r"\n".join(escape_dt(l) for l in wrapped)
        entries.append((start, end, text))

    if not entries:
        return "null"

    # Un drawtext por entrada, encadenados con ","
    # fontfile apunta a Arial Bold en macOS
    FONT = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
    if not pathlib.Path(FONT).exists():
        FONT = "/System/Library/Fonts/Arial.ttf"

    parts = []
    for start, end, text in entries:
        dt = (
            f"drawtext="
            f"fontfile='{FONT}'"
            f":text='{text}'"
            f":fontsize=58"
            f":fontcolor=white"
            f":borderw=4"
            f":bordercolor=black"
            f":shadowx=2:shadowy=2:shadowcolor=black@0.6"
            f":x=(w-text_w)/2"
            f":y=h-text_h-70"
            f":line_spacing=8"
            f":enable='between(t,{start:.3f},{end:.3f})'"
        )
        parts.append(dt)

    return ",".join(parts)

# ── Movimiento de cámara variado ─────────────────────────────────────────────

def kenburns_filter(duration, fps=None):
    fps = fps or FPS
    """
    Genera un zoompan variado: dirección y velocidad distintas cada clip.
    Sin flip — imágenes IA no necesitan anti-fingerprint de clip de YouTube.
    Movimientos disponibles:
      zoom_in_center  — clásico zoom hacia el centro
      zoom_in_left    — zoom entrando por la izquierda
      zoom_in_right   — zoom entrando por la derecha
      pan_left        — paneo suave izquierda a derecha
      pan_right       — paneo derecha a izquierda
      pan_up          — paneo de abajo hacia arriba
      pan_down        — paneo de arriba hacia abajo
      zoom_out        — alejar ligeramente (zoom out suave)
    """
    frames = max(1, int(duration * fps))

    # Velocidad de zoom: lenta / media / rápida
    zoom_speeds = [0.0005, 0.001, 0.0018, 0.0025]
    zs = random.choice(zoom_speeds)

    # Tuplas: (z_expr, x_expr, y_expr) — solo la expresión, sin z=/x=/y= ni comillas
    moves = [
        # zoom in centrado
        (f"min(1+on*{zs},1.4)",   "iw/2-(iw/zoom/2)",                   "ih/2-(ih/zoom/2)"),
        # zoom in hacia la izquierda
        (f"min(1+on*{zs},1.4)",   "0",                                   "ih/2-(ih/zoom/2)"),
        # zoom in hacia la derecha
        (f"min(1+on*{zs},1.4)",   "iw-(iw/zoom)",                        "ih/2-(ih/zoom/2)"),
        # paneo izquierda → derecha
        ("1.15",                   f"on/{frames}*(iw-iw/zoom)",           "ih/2-(ih/zoom/2)"),
        # paneo derecha → izquierda
        ("1.15",                   f"(iw-iw/zoom)-on/{frames}*(iw-iw/zoom)", "ih/2-(ih/zoom/2)"),
        # paneo abajo → arriba
        ("1.15",                   "iw/2-(iw/zoom/2)",                    f"on/{frames}*(ih-ih/zoom)"),
        # paneo arriba → abajo
        ("1.15",                   "iw/2-(iw/zoom/2)",                    f"(ih-ih/zoom)-on/{frames}*(ih-ih/zoom)"),
        # zoom out suave
        (f"max(1.4-on*{zs},1.05)", "iw/2-(iw/zoom/2)",                   "ih/2-(ih/zoom/2)"),
    ]

    z_expr, x_expr, y_expr = random.choice(moves)
    return (
        f"scale=3840:2160,"
        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}'"
        f":d={frames}:s={RES_W}x{RES_H}:fps={fps},"
        f"scale={RES_W}:{RES_H}"
    )

def preparar_clip(src, dst, duration, tmp_dir, idx):
    """
    Estrategia según lo que existe en 03-imagenes/:
      - img_XXXX.png  → fabricar Ken Burns variado (imagen estática, lento)
      - img_XXXX.mp4  → ya animado por el harvester, solo recortar a duration (rápido)
    Sin flip — imágenes IA no necesitan anti-fingerprint de clip YouTube.
    """
    src_path = pathlib.Path(src)
    png_src  = src_path.parent / (src_path.stem + ".png")

    if png_src.exists():
        # Imagen estática: generar Ken Burns + speed variado
        speed = 1.0 + random.uniform(-SPEED_RANGE, SPEED_RANGE)
        pts   = 1.0 / speed
        vf    = kenburns_filter(duration) + f",setpts={pts:.4f}*PTS"
        r = run([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-loop", "1", "-framerate", "30", "-i", str(png_src),
            "-vf", vf, "-t", str(duration),
            "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF),
            "-pix_fmt", "yuv420p", "-an", "-y", str(dst)
        ])
    else:
        # Clip .mp4 ya animado por el harvester
        # SIEMPRE re-encodar a 30fps para evitar mezcla de fps en concat
        # Los clips de Brave/Pixabay pueden ser 24/25/30fps — el stream copy mezcla fps
        # y produce imagen congelada + subtítulos desincronizados
        clip_dur = get_duration(src)
        if clip_dur < duration:
            # Clip más corto → loop + re-encode a 30fps
            r = run([
                FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
                "-stream_loop", "-1", "-i", str(src),
                "-t", str(duration),
                "-vf", f"fps={FPS},scale={RES_W}:{RES_H}",
                "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF),
                "-pix_fmt", "yuv420p", "-an", "-y", str(dst)
            ])
        else:
            # Clip suficientemente largo → recortar + re-encode a 30fps
            r = run([
                FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
                "-i", str(src),
                "-t", str(duration),
                "-vf", f"fps={FPS},scale={RES_W}:{RES_H}",
                "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF),
                "-pix_fmt", "yuv420p", "-an", "-y", str(dst)
            ])
    return r.returncode == 0

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 render_seduccion.py <carpeta_video> [--preview N]")
        sys.exit(1)

    carpeta     = pathlib.Path(sys.argv[1])
    nombre      = carpeta.name
    preview_sec = None

    # Cargar config del canal (_config/seduccion.json) — sobreescribe defaults globales
    global CRF, PRESET, AUDIO_K, RES_W, RES_H, FPS, MAX_CLIP_DUR, SPEED_RANGE, MUSIC_VOL, WORKERS
    cfg_path = pathlib.Path(__file__).parent / "_config" / "seduccion.json"
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text())
        r = cfg.get("render", {})
        CRF          = r.get("crf",          CRF)
        PRESET       = r.get("preset",       PRESET)
        AUDIO_K      = r.get("audio_k",      AUDIO_K)
        RES_W        = r.get("res_w",        RES_W)
        RES_H        = r.get("res_h",        RES_H)
        FPS          = r.get("fps",          FPS)
        MAX_CLIP_DUR = r.get("max_clip_dur", MAX_CLIP_DUR)
        SPEED_RANGE  = r.get("speed_range",  SPEED_RANGE)
        MUSIC_VOL    = r.get("music_vol",    MUSIC_VOL)
        WORKERS      = r.get("workers",      WORKERS)

    if "--preview" in sys.argv:
        idx = sys.argv.index("--preview")
        preview_sec = float(sys.argv[idx + 1])

    # Archivos clave
    timeline_f = carpeta / "05-montaje" / "timeline.json"
    img_dir    = carpeta / "03-imagenes"
    mp3s       = sorted([f for f in carpeta.glob("*.mp3")
                         if "_test" not in f.name and "_src" not in f.name])
    if not mp3s:
        err(f"No encontré .mp3 en {carpeta}")
    audio_file = mp3s[0]

    if not timeline_f.exists():
        err(f"No existe {timeline_f} — corré primero generar_timeline_seduccion.py")

    # Verificar aprobación antes de empezar
    verificar_aprobacion(carpeta)

    # Leer timeline
    data     = json.loads(timeline_f.read_text(encoding="utf-8"))
    segments = data["visual_timeline"]

    audio_dur = get_duration(audio_file)
    if preview_sec:
        audio_dur = min(audio_dur, preview_sec)
        segments  = [s for s in segments if s["start_seconds"] < audio_dur]

    # Música de fondo
    music_file = None
    for candidate in [
        carpeta / "musica.mp3",
        carpeta.parent.parent / "_musica" / carpeta.parent.name / "musica_v1.mp3",
        carpeta.parent.parent / "_musica" / carpeta.parent.name / "musica_v2.mp3",
    ]:
        if candidate.exists():
            music_file = candidate
            break

    suffix     = f"_preview{int(preview_sec)}s" if preview_sec else "_final"
    out_file   = carpeta / f"{nombre}{suffix}.mp4"

    print(f"\n{'═'*62}")
    print(f"  RENDER SEDUCCIÓN — {nombre.upper()}")
    print(f"{'═'*62}")
    print(f"  Audio    : {audio_file.name} ({audio_dur/60:.1f} min)")
    print(f"  Segmentos: {len(segments)}")
    print(f"  Música   : {music_file.name if music_file else 'ninguna'}")
    print(f"  Salida   : {out_file.name}")
    print(f"  Movimiento: Ken Burns variado (8 modos) · speed ±{int(SPEED_RANGE*100)}% · sin flip (IA)")
    print()

    tmp_dir    = pathlib.Path(tempfile.mkdtemp(prefix="render_seduccion_"))
    concat_txt = tmp_dir / "concat.txt"
    total      = len(segments)

    # Preparar tareas
    tasks = []
    for i, seg in enumerate(segments, 1):
        seg_id   = seg["segment_id"]
        duration = seg["duration"]
        end_s    = seg["end_seconds"]
        if end_s > audio_dur:
            duration = max(0.5, audio_dur - seg["start_seconds"])
        if duration > MAX_CLIP_DUR:
            duration = MAX_CLIP_DUR
        img_src  = img_dir / f"img_{seg_id:04d}.mp4"
        clip_dst = tmp_dir / f"seg_{i:05d}.mp4"
        if img_src.exists():
            tasks.append((i, seg_id, seg["start_seconds"], end_s, duration, img_src, clip_dst))
        else:
            warn(f"[{i}/{total}] Falta img_{seg_id:04d}.mp4 — saltando")

    print(f"  Procesando {len(tasks)} segmentos ({WORKERS} en paralelo)...")

    # Mapa orden → ruta para mantener secuencia en el concat
    results = {}

    def procesar(task):
        i, seg_id, start_s, end_s, duration, img_src, clip_dst = task
        ok_flag = preparar_clip(img_src, clip_dst, duration, tmp_dir, i)
        return i, seg_id, start_s, end_s, duration, clip_dst, ok_flag

    completados = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futuros = {ex.submit(procesar, t): t[0] for t in tasks}
        for fut in as_completed(futuros):
            i, seg_id, start_s, end_s, duration, clip_dst, ok_flag = fut.result()
            completados += 1
            status = "✓" if ok_flag else f"{ROJO}✗{RESET}"
            print(f"  [{completados:03d}/{len(tasks)}] seg#{seg_id} {start_s:.1f}s→{end_s:.1f}s ({duration:.2f}s) {status}", flush=True)
            if ok_flag:
                results[i] = clip_dst

    if not results:
        err("No se procesó ningún segmento")

    # Concat en orden (i = posición original)
    lines = [f"file '{results[k].resolve()}'" for k in sorted(results)]
    concat_txt.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  {len(lines)} segmentos listos. Concatenando con stream copy...")

    # Paso 1: video sin audio — stream copy (instantáneo, no re-encodea)
    video_raw = tmp_dir / "video_raw.mp4"
    run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "concat", "-safe", "0", "-i", str(concat_txt),
        "-c", "copy",
        "-y", str(video_raw)
    ])
    ok("Video raw concatenado")

    # Paso 2: mezclar audio (locución + música de fondo en loop)
    print(f"  Mezclando audio (locución{' + música' if music_file else ''})...")

    if music_file:
        filter_complex = (
            f"[1:a]volume=1.0[voz];"
            f"[2:a]volume={MUSIC_VOL},aloop=loop=-1:size=2e+09[musica];"
            f"[voz][musica]amix=inputs=2:duration=first:dropout_transition=3[audio_out]"
        )
        audio_cmd = [
            FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-i", str(video_raw),
            "-i", str(audio_file),
            "-i", str(music_file),
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[audio_out]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", AUDIO_K,
            "-t", str(audio_dur),
            "-y", str(out_file)
        ]
    else:
        audio_cmd = [
            FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-i", str(video_raw),
            "-i", str(audio_file),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", AUDIO_K,
            "-t", str(audio_dur),
            "-y", str(out_file)
        ]

    run(audio_cmd)

    # Paso 3: quemar subtítulos con libass (ffmpeg-full)
    srt_file = carpeta / f"{nombre}.srt"
    if srt_file.exists():
        print(f"  Quemando subtítulos ({srt_file.name}) con ffmpeg-full...")
        ass_file    = tmp_dir / f"{nombre}.ass"
        video_nosub = out_file
        out_file    = carpeta / out_file.name.replace(".mp4", "_sub.mp4")

        n_subs = srt_to_ass(srt_file, ass_file)
        ass_escaped = str(ass_file.resolve()).replace("'", "\\'")

        run([
            FFMPEG_FULL, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-i", str(video_nosub),
            "-vf", f"ass={ass_escaped}",
            "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF),
            "-c:a", "copy",
            "-y", str(out_file)
        ])
        video_nosub.unlink(missing_ok=True)
        ok(f"Subtítulos quemados ({n_subs} líneas)")
    else:
        warn(f"No encontré {srt_file.name} — render sin subtítulos")

    # Limpiar temporales
    for f in tmp_dir.iterdir():
        f.unlink(missing_ok=True)
    tmp_dir.rmdir()

    size_mb = out_file.stat().st_size / 1_048_576
    ok(f"Render completo → {out_file.name} ({size_mb:.0f} MB)")
    print(f"\n{'═'*62}")
    print(f"  ✓ {out_file}")
    print(f"  Duración : {audio_dur/60:.1f} min")
    print(f"  Tamaño   : {size_mb:.0f} MB")
    print(f"{'═'*62}\n")

if __name__ == "__main__":
    main()
