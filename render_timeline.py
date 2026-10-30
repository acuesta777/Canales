#!/usr/bin/env python3
"""
render_timeline.py — Render genérico basado en timeline.json para cualquier canal.

Lee config/<canal>.json → parámetros de producción.
Lee 05-montaje/timeline.json → orden y duración exacta de cada segmento.
Clips: 03-imagenes/img_XXXX.mp4 (del harvester_timeline.py).
Concatena con audio + música de fondo en loop + subtítulos ASS.

Uso:
    python3 render_timeline.py seduccion/7_errores/ --canal seduccion
    python3 render_timeline.py riqueza/victoria_ruffo/ --canal riqueza --preview 60
    python3 render_timeline.py futbol/mbappe/ --canal futbol
    python3 render_timeline.py seduccion/7_errores/   # infiere canal del padre
"""

import sys, json, random, subprocess, pathlib, tempfile, re
from concurrent.futures import ThreadPoolExecutor, as_completed

FFMPEG  = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"
if not pathlib.Path(FFMPEG).exists():
    FFMPEG  = "/usr/local/bin/ffmpeg"
    FFPROBE = "/usr/local/bin/ffprobe"

FFMPEG_FULL = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
if not pathlib.Path(FFMPEG_FULL).exists():
    FFMPEG_FULL = FFMPEG

VERDE    = "\033[92m"
ROJO     = "\033[91m"
AMARILLO = "\033[93m"
RESET    = "\033[0m"

def ok(msg):   print(f"  {VERDE}✓{RESET} {msg}")
def err(msg):  print(f"  {ROJO}✗{RESET} {msg}"); sys.exit(1)
def warn(msg): print(f"  {AMARILLO}⚠{RESET} {msg}")


# ── Config ────────────────────────────────────────────────────────────────────

def cargar_config(canal):
    script_dir = pathlib.Path(__file__).parent
    cfg_path   = script_dir / "_config" / f"{canal}.json"
    if not cfg_path.exists():
        cfg_path = pathlib.Path(f"_config/{canal}.json")
    if not cfg_path.exists():
        canales = [p.stem for p in (script_dir / "_config").glob("*.json")]
        err(f"No encontré config/{canal}.json — disponibles: {canales}")
    return json.loads(cfg_path.read_text(encoding="utf-8"))


# ── Utilidades ────────────────────────────────────────────────────────────────

def run_cmd(cmd, check=True):
    return subprocess.run(cmd, check=check, capture_output=True, text=True)

def get_duration(path):
    r = run_cmd([FFPROBE, "-v", "error",
                 "-show_entries", "format=duration",
                 "-of", "default=nokey=1:noprint_wrappers=1", str(path)])
    return float(r.stdout.strip())


# ── Verificar aprobación ──────────────────────────────────────────────────────

def verificar_aprobacion(carpeta):
    meta_path = carpeta / "metadata.json"
    if not meta_path.exists():
        return
    meta      = json.loads(meta_path.read_text(encoding="utf-8"))
    footage   = meta.get("footage", {})
    pendientes = [k for k, v in footage.items() if v.get("estado") == "pendiente"]
    if pendientes:
        print(f"\n{ROJO}⛔ Render bloqueado — {len(pendientes)} imagen(s) pendiente(s).{RESET}")
        print(f"   Aprobá en: http://localhost:5001/aprobar/{carpeta.parent.name}/{carpeta.name}/")
        sys.exit(1)

    # Validar que clips_order coincide con el dashboard cuando hay segs source=yt
    tl_path = carpeta / "05-montaje" / "timeline.json"
    if tl_path.exists():
        tl = json.loads(tl_path.read_text(encoding="utf-8"))
        segs_yt = [s for s in tl.get("visual_timeline", []) if s.get("source") == "yt"]
        if segs_yt:
            clips_order = meta.get("clips_order", [])
            yt_in_order = [c for c in clips_order if c.startswith("clip_")]
            if not yt_in_order:
                print(f"\n{ROJO}⛔ Render bloqueado — hay {len(segs_yt)} segmentos source=yt en el timeline")
                print(f"   pero clips_order no tiene ningún clip YT aprobado.")
                print(f"   Aprobá los clips en el dashboard y vuelve a renderizar.{RESET}")
                sys.exit(1)
            print(f"   ✓ {len(yt_in_order)} clips YT en clips_order para {len(segs_yt)} segs source=yt")


# ── Subtítulos ────────────────────────────────────────────────────────────────

def srt_to_ass(srt_path, ass_path, cfg_sub):
    font      = cfg_sub.get("font", "Arial")
    fontsize  = cfg_sub.get("fontsize", 58)
    max_chars = cfg_sub.get("max_chars_per_line", 42)
    primary   = cfg_sub.get("primary_color", "&H00FFFFFF")
    outline_c = cfg_sub.get("outline_color", "&H00000000")
    outline   = cfg_sub.get("outline", 4)
    bold_flag = -1 if cfg_sub.get("bold", True) else 0
    margin_v  = cfg_sub.get("margin_v", 70)

    ASS_HEADER = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1920\n"
        "PlayResY: 1080\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font},{fontsize},{primary},&H000000FF,{outline_c},&H80000000,"
        f"{bold_flag},0,0,0,100,100,0,0,1,{outline},1,2,80,80,{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    def ts_to_ass(ts):
        ts = ts.strip().replace(',', '.')
        p  = ts.split(':')
        h, m = int(p[0]), int(p[1])
        s    = float(p[2])
        cs   = round((s - int(s)) * 100)
        return f"{h}:{m:02d}:{int(s):02d}.{cs:02d}"

    def wrap_text(text, max_c):
        words = text.split()
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if len(test) <= max_c:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return r"\N".join(lines)

    content = pathlib.Path(srt_path).read_text(encoding="utf-8")
    blocks  = re.split(r'\n\n+', content.strip())
    events  = []

    for block in blocks:
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if len(lines) < 3 or '-->' not in lines[1]:
            continue
        times = lines[1].split('-->')
        start = ts_to_ass(times[0])
        end   = ts_to_ass(times[1])
        text  = ' '.join(lines[2:]).strip().upper()
        text  = wrap_text(text, max_chars)
        events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    pathlib.Path(ass_path).write_text(ASS_HEADER + "\n".join(events) + "\n", encoding="utf-8")
    return len(events)


# ── Ken Burns ─────────────────────────────────────────────────────────────────

def kenburns_filter(duration, cfg_render, fps=30):
    RES_W   = cfg_render.get("res_w", 1920)
    RES_H   = cfg_render.get("res_h", 1080)
    flip_en = cfg_render.get("flip_enable", False)
    speed_r = cfg_render.get("speed_range", 0.04)
    frames  = max(1, int(duration * fps))

    zoom_speeds = [0.0001, 0.0003, 0.0005, 0.0007]  # reducidos — zoom sutil tipo documental
    zs = random.choice(zoom_speeds)

    moves = [
        (f"min(1+on*{zs},1.4)",    "iw/2-(iw/zoom/2)",                             "ih/2-(ih/zoom/2)"),
        (f"min(1+on*{zs},1.4)",    "0",                                              "ih/2-(ih/zoom/2)"),
        (f"min(1+on*{zs},1.4)",    "iw-(iw/zoom)",                                   "ih/2-(ih/zoom/2)"),
        ("1.15",                    f"on/{frames}*(iw-iw/zoom)",                      "ih/2-(ih/zoom/2)"),
        ("1.15",                    f"(iw-iw/zoom)-on/{frames}*(iw-iw/zoom)",         "ih/2-(ih/zoom/2)"),
        ("1.15",                    "iw/2-(iw/zoom/2)",                               f"on/{frames}*(ih-ih/zoom)"),
        ("1.15",                    "iw/2-(iw/zoom/2)",                               f"(ih-ih/zoom)-on/{frames}*(ih-ih/zoom)"),
        (f"max(1.4-on*{zs},1.05)", "iw/2-(iw/zoom/2)",                               "ih/2-(ih/zoom/2)"),
    ]

    z_expr, x_expr, y_expr = random.choice(moves)
    base = (
        f"scale=3840:2160,"
        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}'"
        f":d={frames}:s={RES_W}x{RES_H}:fps={fps},"
        f"scale={RES_W}:{RES_H}"
    )
    if flip_en and random.random() < 0.5:
        base += ",hflip"
    return base


# ── Preparar clip ─────────────────────────────────────────────────────────────

def _antidetect_filter(cfg_render, use_count):
    """Filtros anti-fingerprint para clips reciclados.
    use_count=2 → segunda vez, use_count=3 → tercera, etc.
    Cada ocurrencia garantiza una combinación de transformaciones distinta.
    """
    # Combinaciones de flip garantizadas distintas según el conteo
    flip_combos = [
        ["hflip"],           # 2ª vez
        ["hflip"],           # 3ª vez
        ["hflip"],           # 4ª vez
        [],                  # 5ª vez (solo hue+blur+crop)
    ]
    flips = flip_combos[(use_count - 2) % len(flip_combos)]

    # Semilla determinista por conteo para que hue/speed/crop sean distintos entre ocurrencias
    rng     = random.Random(use_count * 997)
    speed_r = cfg_render.get("speed_range", 0.04)
    speed   = 1.0 + rng.uniform(-speed_r, speed_r)
    pts     = 1.0 / speed
    # Hue cuadrantes distintos: 2ª→+, 3ª→-, 4ª→++, 5ª→--
    hue_base  = [6, -6, 10, -10]
    hue       = hue_base[(use_count - 2) % len(hue_base)] + rng.uniform(-2, 2)
    crop_pct  = rng.uniform(0.005, 0.018)

    vf_parts = []
    if flips:
        vf_parts.append(",".join(flips))
    vf_parts.append(f"hue=h={hue:.1f}")
    vf_parts.append(f"gblur=sigma=0.5")
    vf_parts.append(f"crop=iw*{1-crop_pct:.4f}:ih*{1-crop_pct:.4f},scale=1920:1080")
    vf_parts.append(f"setpts={pts:.4f}*PTS")
    return ",".join(vf_parts)


def preparar_clip(src, dst, duration, tmp_dir, idx, cfg_render, use_count=1, is_yt=False):
    src_path = pathlib.Path(src)
    png_src  = src_path.parent / (src_path.stem + ".png")
    PRESET   = cfg_render.get("preset", "ultrafast")
    CRF      = cfg_render.get("crf", 28)
    speed_r  = cfg_render.get("speed_range", 0.04)
    RES_W    = cfg_render.get("res_w", 1920)
    RES_H    = cfg_render.get("res_h", 1080)
    FPS_OUT  = cfg_render.get("fps", 30)
    scale_vf = f"scale={RES_W}:{RES_H}:force_original_aspect_ratio=decrease,pad={RES_W}:{RES_H}:(ow-iw)/2:(oh-ih)/2"

    # Si el src ya es un mp4 con zoompan (_zp.mp4 o flow_*.mp4), usarlo directo — no re-aplicar kenburns
    is_prebuilt_mp4 = src_path.suffix == ".mp4" and src_path.exists()

    if png_src.exists() and not is_prebuilt_mp4:
        speed = 1.0 + random.uniform(-speed_r, speed_r)
        pts   = 1.0 / speed
        vf    = kenburns_filter(duration, cfg_render) + f",setpts={pts:.4f}*PTS"
        r = run_cmd([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-loop", "1", "-framerate", str(FPS_OUT), "-i", str(png_src),
            "-vf", vf, "-t", str(duration),
            "-r", str(FPS_OUT),
            "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF),
            "-pix_fmt", "yuv420p", "-an", "-y", str(dst)
        ])
    elif is_prebuilt_mp4 and not is_yt:
        # Clip IA pre-construido (_zp.mp4): re-encodear con CRF bajo para preservar calidad
        # y normalizar PTS — stream copy causa DTS discontinuidades que corrompen el concat
        # -stream_loop -1: si el clip es más corto que duration (zoompan mal generado), lo cicla
        r = run_cmd([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-stream_loop", "-1", "-i", str(src), "-t", str(duration),
            "-vf", f"scale={RES_W}:{RES_H}:force_original_aspect_ratio=decrease,pad={RES_W}:{RES_H}:(ow-iw)/2:(oh-ih)/2,setpts=PTS-STARTPTS",
            "-r", str(FPS_OUT),
            "-c:v", "libx264", "-preset", PRESET, "-crf", "20",
            "-pix_fmt", "yuv420p", "-an", "-y", str(dst)
        ])
    elif is_yt and use_count > 1:
        # Clip YouTube reciclado — anti-fingerprint por ocurrencia
        vf = scale_vf + "," + _antidetect_filter(cfg_render, use_count)
        r = run_cmd([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-i", str(src), "-t", str(duration),
            "-vf", vf,
            "-r", str(FPS_OUT),
            "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF),
            "-pix_fmt", "yuv420p", "-an", "-y", str(dst)
        ])
    else:
        # IA, Google o YT (primer uso): re-encodear normalizando fps
        r = run_cmd([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-i", str(src), "-t", str(duration),
            "-vf", scale_vf,
            "-r", str(FPS_OUT),
            "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF),
            "-pix_fmt", "yuv420p", "-an", "-y", str(dst)
        ])
    return r.returncode == 0


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        script_dir = pathlib.Path(__file__).parent
        canales = [p.stem for p in (script_dir / "_config").glob("*.json")]
        print("Uso: python3 render_timeline.py <carpeta_video> --canal <canal> [--preview N]")
        print(f"  Canales: {canales}")
        sys.exit(1)

    carpeta = pathlib.Path(sys.argv[1])
    nombre  = carpeta.name

    canal = None
    if "--canal" in sys.argv:
        canal = sys.argv[sys.argv.index("--canal") + 1]
    else:
        canal = carpeta.parent.name
        print(f"  {AMARILLO}⚠{RESET} --canal no especificado, infiriendo: {canal}")

    preview_sec = None
    if "--preview" in sys.argv:
        preview_sec = float(sys.argv[sys.argv.index("--preview") + 1])

    cfg        = cargar_config(canal)
    cfg_render = cfg.get("render", {})
    cfg_sub    = cfg.get("subtitulos", {})
    cfg_musica = cfg.get("musica", {})

    PRESET    = cfg_render.get("preset", "ultrafast")
    CRF       = cfg_render.get("crf", 28)
    AUDIO_K   = cfg_render.get("audio_k", "128k")
    MUSIC_VOL = cfg_render.get("music_vol", 0.12)
    WORKERS   = cfg_render.get("workers", 4)

    timeline_f = carpeta / "05-montaje" / "timeline.json"
    img_dir    = carpeta / "03-imagenes"
    mp3s       = sorted([f for f in carpeta.glob("*.mp3")
                         if "_test" not in f.name and "_src" not in f.name])
    if not mp3s:
        err(f"No encontré .mp3 en {carpeta}")
    audio_file = mp3s[0]

    if not timeline_f.exists():
        err(f"No existe {timeline_f} — generá primero el timeline.json")

    verificar_aprobacion(carpeta)

    data     = json.loads(timeline_f.read_text(encoding="utf-8"))
    segments = data["visual_timeline"]

    audio_dur = get_duration(audio_file)
    if preview_sec:
        audio_dur = min(audio_dur, preview_sec)
        segments  = [s for s in segments if s["start_seconds"] < audio_dur]

    music_file = None
    for rel in cfg_musica.get("paths_relativos", []):
        candidate = (carpeta / rel).resolve()
        if candidate.exists():
            music_file = candidate
            break

    suffix   = f"_preview{int(preview_sec)}s" if preview_sec else "_final"
    out_file = carpeta / f"{nombre}{suffix}.mp4"

    flip_str = "con flip (anti-fingerprint)" if cfg_render.get("flip_enable") else "sin flip (IA)"
    print(f"\n{'═'*62}")
    print(f"  RENDER [{cfg['nombre_display']}] — {nombre.upper()}")
    print(f"{'═'*62}")
    print(f"  Canal    : {canal}")
    print(f"  Audio    : {audio_file.name} ({audio_dur/60:.1f} min)")
    print(f"  Segmentos: {len(segments)}")
    print(f"  Música   : {music_file.name if music_file else 'ninguna'}")
    print(f"  Salida   : {out_file.name}")
    print(f"  Movimiento: Ken Burns (8 modos) · speed ±{int(cfg_render.get('speed_range',0.04)*100)}% · {flip_str}")
    print()

    tmp_dir    = pathlib.Path(tempfile.mkdtemp(prefix=f"render_{canal}_"))
    concat_txt = tmp_dir / "concat.txt"
    total      = len(segments)

    tasks = []
    black_clips = {}   # i → clip_dst de clip negro ya generado para esa duración
    clip_uses   = {}   # path → cuántas veces se ha encolado (1=primera, 2=segunda, etc.)

    def make_black_clip(duration, clip_dst):
        """Genera clip negro de duración exacta a 1920x1080 30fps."""
        run_cmd([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-f", "lavfi", "-i", f"color=black:size=1920x1080:rate=30",
            "-t", str(duration), "-c:v", "libx264", "-preset", "ultrafast",
            "-crf", "28", "-pix_fmt", "yuv420p", "-an", "-y", str(clip_dst)
        ])
        return clip_dst.exists()

    # ── Cargar pool de clips YT del dashboard ──
    meta_path = carpeta / "metadata.json"
    clips_dir = carpeta / "clips"
    # clips_ref_extra: fallback de URL 1 (con logo blur), se usa cuando se agotan los de clips/
    clips_ref_extra_dir = carpeta / "clips_ref_extra"
    available = []
    fallback_pool = []   # clips de URL 1 — solo se usan cuando available se agota
    yt_clips_used = []
    recycled_start = None

    def _resolve_clip(name):
        """Busca clip en yt/ → google/ → 03-imagenes/ → clips/ (compat) y devuelve (path, is_yt)."""
        for sub, yt_flag in [("yt", True), ("google", False)]:
            p = clips_dir / sub / name
            if p.exists():
                return p, yt_flag
        p = carpeta / "03-imagenes" / name
        if p.exists():
            return p, False
        p = clips_dir / name
        return (p, name.startswith("clip_")) if p.exists() else (None, False)

    if meta_path.exists() and clips_dir.exists():
        _m = json.loads(meta_path.read_text(encoding="utf-8"))
        clips_order = _m.get("clips_order", [])
        deleted = set((_m.get("deleted_yt_clips") or {}).keys()) | set((_m.get("rejected_yt_clips") or {}).keys())
        for f in clips_order:
            if f in deleted:
                continue
            p, yt_flag = _resolve_clip(f)
            if p:
                available.append((f, p, yt_flag))

    # Cargar clips_ref_extra/ (URL 1, blur de logo aplicado al extraer)
    if clips_ref_extra_dir.exists():
        extra_clips = sorted(clips_ref_extra_dir.glob("clip_*.mp4"))
        for ec in extra_clips:
            fallback_pool.append((ec.name, ec, True))
        if fallback_pool:
            print(f"  + {len(fallback_pool)} clips fallback en clips_ref_extra/ (URL 1 con logo blur)")

    # ── Validador: orden dashboard == orden render ──────────────────────────────
    if meta_path.exists():
        _meta_order = [k for k in json.loads(meta_path.read_text()).get("footage", {}).keys()]
        _flow_sorted = sorted(
            [s for s in segments if s.get("source") != "yt"],
            key=lambda s: s["start_seconds"]
        )
        _render_order = [f"flow_{s['segment_id']:04d}_zp.mp4" for s in _flow_sorted]
        # Solo reordenar si metadata tiene footage entries — si está vacío, respetar timeline.json
        _dash_filtered = [k for k in _meta_order if k in set(_render_order)]
        if not _meta_order or not _dash_filtered:
            print(f"  ✅ Orden desde timeline.json: {len(_render_order)} imágenes IA (sin metadata footage)")
        elif _dash_filtered == _render_order:
            print(f"  ✅ Orden validado: {len(_render_order)} imágenes IA en el mismo orden que el dashboard")
        else:
            print(f"  ⚠️  ORDEN DISTINTO al dashboard — corrigiendo automáticamente")
            # Reordenar segments según dashboard
            _id_order = [int(k.replace("flow_","").replace("_zp.mp4","")) for k in _dash_filtered]
            _seg_map  = {s["segment_id"]: s for s in _flow_sorted}
            segments_flow_ordered = [_seg_map[sid] for sid in _id_order if sid in _seg_map]
            segments_yt = [s for s in segments if s.get("source") == "yt"]
            segments = sorted(segments_flow_ordered + segments_yt, key=lambda s: s["start_seconds"])
    # ────────────────────────────────────────────────────────────────────────────

    fill_target = audio_dur + 15
    # Pool primario: clips URL 2 (sin marca de agua)
    # Pool fallback: clips URL 1 (clips_ref_extra/, logo blur aplicado al extraer)
    # Cuando se agota el primario se pasa al fallback; si también se agota → ciclar el primario
    cycle = list(available)
    ci = 0
    fallback_ci = 0
    using_fallback = False

    def _next_yt_task(cursor, max_dur):
        """Toma el siguiente clip del pool primario; cuando se agota usa clips_ref_extra/."""
        nonlocal ci, fallback_ci, recycled_start, using_fallback
        # Determinar qué pool usar
        if not using_fallback:
            if not cycle:
                # Sin pool primario → ir directo al fallback
                using_fallback = bool(fallback_pool)
            elif ci >= len(cycle):
                # Pool primario agotado — pasar al fallback si existe
                if fallback_pool:
                    if not using_fallback:
                        print(f"  ⚡ Pool URL2 agotado ({len(cycle)} clips) — usando clips_ref_extra/ (URL1 con logo blur)")
                    using_fallback = True
                else:
                    # Sin fallback → reciclar pool primario con anti-fingerprint
                    if recycled_start is None:
                        recycled_start = len(yt_clips_used)

        if using_fallback and fallback_pool:
            clip_name, clip_path, is_yt = fallback_pool[fallback_ci % len(fallback_pool)]
            fallback_ci += 1
        elif cycle:
            clip_name, clip_path, is_yt = cycle[ci % len(cycle)]
            if ci >= len(cycle) and recycled_start is None:
                recycled_start = len(yt_clips_used)
            ci += 1
        else:
            return None, cursor
        clip_dur = min(get_duration(clip_path), cfg_render.get("max_clip_dur", 8.0))
        clip_dur = min(clip_dur, max_dur)
        if clip_dur < 0.5:
            return None, cursor
        idx = len(tasks) + 1
        clip_dst = tmp_dir / f"seg_{idx:05d}.mp4"
        key = str(clip_path)
        use_count = clip_uses.get(key, 0) + 1
        clip_uses[key] = use_count
        yt_clips_used.append(clip_name)
        task = (idx, 0, cursor, cursor + clip_dur, clip_dur, clip_path, clip_dst, False, use_count, is_yt)
        return task, cursor + clip_dur

    # ── Timeline unificado: flow segs en su timestamp, YT clips llenan los gaps ──
    flow_segs_sorted = sorted(
        [s for s in segments if s.get("source") not in ("yt", "yt_clip")],
        key=lambda s: s["start_seconds"]
    )
    cursor = 0.0

    if available:
        print(f"  + {len(available)} clips del dashboard intercalados con {len(flow_segs_sorted)} imágenes IA")

    for seg in flow_segs_sorted:
        seg_start = seg["start_seconds"]
        # Llenar gap antes de este segmento flow con clips YT
        # Solo si el gap es >= 2s; si es menor, el siguiente flow empieza donde terminó el anterior
        if seg_start - cursor >= 2.0:
            while cursor < seg_start - 0.3 and cycle:
                task, cursor = _next_yt_task(cursor, seg_start - cursor)
                if task:
                    tasks.append(task)
                else:
                    break
        else:
            cursor = seg_start  # saltar micro-gap sin insertar YT

        # Añadir segmento flow en su timestamp exacto
        seg_id = seg["segment_id"]
        duration = seg["duration"]
        end_s = seg["end_seconds"]
        if end_s > audio_dur:
            duration = max(0.5, audio_dur - seg_start)
        flow_src = img_dir / f"flow_{seg_id:04d}_zp.mp4"
        if not flow_src.exists():
            flow_src = img_dir / f"flow_{seg_id:04d}.mp4"
        img_src = img_dir / f"img_{seg_id:04d}.mp4"
        clip_src = flow_src if flow_src.exists() else img_src if img_src.exists() else None
        idx = len(tasks) + 1
        clip_dst = tmp_dir / f"seg_{idx:05d}.mp4"
        if clip_src:
            key = str(clip_src)
            use_count = clip_uses.get(key, 0) + 1
            clip_uses[key] = use_count
            tasks.append((idx, seg_id, seg_start, end_s, duration, clip_src, clip_dst, False, use_count, False))
        else:
            tasks.append((idx, seg_id, seg_start, end_s, duration, None, clip_dst, True, 1, False))
        cursor = end_s

    # Llenar el resto del video (después de la última imagen) con clips YT
    while cursor < fill_target and cycle:
        task, cursor = _next_yt_task(cursor, fill_target - cursor)
        if task:
            tasks.append(task)
        else:
            break

    # ── Validador: ningún segmento flow puede quedar sin archivo ──────────────
    missing_flow = [
        (t[1], t[2], t[3])  # (seg_id, start_s, end_s)
        for t in tasks
        if t[7]  # is_black=True → archivo faltante
        and not t[9]  # no es YT (ni yt_clip, ya filtrados arriba)
    ]
    if missing_flow:
        lines_err = "\n".join(
            f"  • seg#{sid} ({s:.1f}s→{e:.1f}s) → flow_{sid:04d}_zp.mp4 no existe"
            for sid, s, e in missing_flow
        )
        err(f"RENDER BLOQUEADO — {len(missing_flow)} segmento(s) flow sin archivo:\n{lines_err}\n"
            f"  Regenera los clips faltantes antes de renderizar.")

    print(f"  Procesando {len(tasks)} segmentos ({WORKERS} en paralelo)...")

    results = {}

    def procesar(task):
        i, seg_id, start_s, end_s, duration, img_src, clip_dst, is_black, use_count, is_yt = task
        if is_black:
            ok_flag = make_black_clip(duration, clip_dst)
        else:
            ok_flag = preparar_clip(img_src, clip_dst, duration, tmp_dir, i, cfg_render,
                                    use_count=use_count, is_yt=is_yt)
        return i, seg_id, start_s, end_s, duration, clip_dst, ok_flag, is_black, use_count, is_yt

    completados = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futuros = {ex.submit(procesar, t): t[0] for t in tasks}
        for fut in as_completed(futuros):
            i, seg_id, start_s, end_s, duration, clip_dst, ok_flag, is_black, use_count, is_yt = fut.result()
            completados += 1
            src_tag = "YT" if is_yt else "IA/G"
            label = "negro" if is_black else (f"♻ uso#{use_count} anti-FP [{src_tag}]" if is_yt and use_count > 1 else f"✓ [{src_tag}]")
            if not is_black:
                print(f"  [{completados:03d}/{len(tasks)}] seg#{seg_id} {start_s:.1f}s→{end_s:.1f}s ({duration:.2f}s) {label}", flush=True)
            if ok_flag:
                results[i] = clip_dst

    if not results:
        err("No se procesó ningún segmento")

    lines = [f"file '{results[k].resolve()}'" for k in sorted(results)]
    concat_txt.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  {len(lines)} segmentos listos. Concatenando (reset PTS + re-encode)...")

    video_raw = tmp_dir / "video_raw.mp4"
    RES_W = cfg_render.get("res_w", 1920)
    RES_H = cfg_render.get("res_h", 1080)
    FPS_OUT = cfg_render.get("fps", 30)
    run_cmd([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-fflags", "+genpts",
        "-f", "concat", "-safe", "0", "-i", str(concat_txt),
        "-vf", f"scale={RES_W}:{RES_H}:force_original_aspect_ratio=decrease,pad={RES_W}:{RES_H}:(ow-iw)/2:(oh-ih)/2,tpad=stop_mode=clone:stop_duration=20",
        "-r", str(FPS_OUT),
        "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF),
        "-pix_fmt", "yuv420p", "-an", "-y", str(video_raw)
    ])
    ok("Video raw concatenado")

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
            "-map", "0:v", "-map", "[audio_out]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", AUDIO_K,
            "-t", str(audio_dur), "-movflags", "+faststart", "-y", str(out_file)
        ]
    else:
        audio_cmd = [
            FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-i", str(video_raw), "-i", str(audio_file),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", AUDIO_K,
            "-t", str(audio_dur), "-movflags", "+faststart", "-y", str(out_file)
        ]

    run_cmd(audio_cmd)

    srt_file = carpeta / f"{nombre}.srt"
    if srt_file.exists() and cfg_render.get("burn_subs", True):
        print(f"  Quemando subtítulos ({srt_file.name})...")
        ass_file    = tmp_dir / f"{nombre}.ass"
        video_nosub = out_file
        out_file    = carpeta / out_file.name.replace(".mp4", "_sub.mp4")

        n_subs      = srt_to_ass(srt_file, ass_file, cfg_sub)
        ass_escaped = str(ass_file.resolve()).replace("'", "\\'")

        run_cmd([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-i", str(video_nosub),
            "-vf", f"ass={ass_escaped}",
            "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF),
            "-c:a", "copy", "-y", str(out_file)
        ])
        video_nosub.unlink(missing_ok=True)
        ok(f"Subtítulos quemados ({n_subs} líneas)")
    elif srt_file.exists():
        warn(f"burn_subs=false — subtítulos en .srt aparte, no quemados")

    # Guardar render_used_order.json para validar vs dashboard
    try:
        used_order_data = {
            "clips_order_dashboard": clips_order if 'clips_order' in dir() else [],
            "clips_used_render": yt_clips_used if 'yt_clips_used' in dir() else [],
            "recycled_start": recycled_start if 'recycled_start' in dir() and recycled_start is not None else len(yt_clips_used if 'yt_clips_used' in dir() else []),
        }
        used_order_path = carpeta / "render_used_order.json"
        used_order_path.write_text(json.dumps(used_order_data, indent=2, ensure_ascii=False))
    except Exception:
        pass

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
