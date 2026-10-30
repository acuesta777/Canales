#!/usr/bin/env python3
"""
render_farandula.py — Render canal Farandula v3.

RENDER POR SEGMENTOS:
  Cada artista se guarda en CARPETA/segmentos/seg_XX_nombre.mp4
  Si un artista sale mal, solo se re-renderiza ese segmento.

Uso normal (render completo):
  python3 render_farandula.py "CARPETA/"

Re-renderizar solo un artista (y reconcat):
  python3 render_farandula.py "CARPETA/" --solo-artista "La Chupitos"

Solo reconcat (sin re-renderizar nada):
  python3 render_farandula.py "CARPETA/" --solo-concat

Para revertir al comportamiento anterior: usar render_farandula.py.bak
"""

import sys, json, random, subprocess, pathlib, tempfile, shutil, unicodedata, re, math
from PIL import Image, ImageDraw, ImageFont
from icloud_match import buscar_carpeta_icloud as _buscar_carpeta_segura

FFMPEG  = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"
HOME    = pathlib.Path.home()
ICLOUD  = HOME / "Library/Mobile Documents/com~apple~CloudDocs/Artistas"

FONT        = "/Library/Fonts/Arial Bold.ttf"
SHOT_DUR    = 7.5
CLIP_MAX    = 5.0
ZOOM        = 1.04
FLIP_CHANCE = 0.50
TITLE_DUR   = 3.0   # segundos de la tarjeta de nombre
MUSIC_VOL   = 0.07  # volumen de música de fondo (0.0-1.0)

VERDE    = "\033[92m"
ROJO     = "\033[91m"
AMARILLO = "\033[93m"
RESET    = "\033[0m"

def ok(msg):   print(f"  {VERDE}✓{RESET} {msg}")
def err(msg):  print(f"  {ROJO}✗{RESET} {msg}")
def warn(msg): print(f"  {AMARILLO}⚠{RESET} {msg}")

# ── Utilidades ─────────────────────────────────────────────────────────────────

def norm(text):
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")

def get_duration(path):
    r = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nokey=1:noprint_wrappers=1", str(path)],
        capture_output=True, text=True, timeout=15
    )
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0

def buscar_carpeta_icloud(nombre):
    try:
        return _buscar_carpeta_segura(nombre)
    except PermissionError:
        return None

# ── Anti-fingerprint ───────────────────────────────────────────────────────────

def apply_antifp(src, dst, flip=None, dur=None, use_count=0):
    # Transformaciones deterministas por número de uso — garantiza que cada
    # ocurrencia del mismo clip sea visualmente distinta para YouTube
    seed = use_count
    rng  = random.Random(seed)

    # Flip: alterna hflip/vflip/ninguno según uso
    if flip is None:
        flip_opts = [False, True, False, "vflip", True, False, "vflip", True]
        flip = flip_opts[seed % len(flip_opts)]

    # Speed: variación distinta por uso
    speeds = [1.00, 0.98, 1.02, 0.97, 1.03, 0.99, 1.01, 0.98]
    speed  = speeds[seed % len(speeds)]
    pts    = f"setpts={1/speed:.4f}*PTS"

    # Hue: rotación leve distinta por uso
    hues   = [0, 5, -5, 8, -8, 3, -3, 10]
    hue_v  = hues[seed % len(hues)]

    # Crop offset: esquina distinta por uso (evita frame idéntico)
    offsets = [(0,0),(2,2),(4,0),(0,4),(2,4),(4,2),(0,2),(4,4)]
    ox, oy  = offsets[seed % len(offsets)]

    crop_f = f"scale=iw*{ZOOM}:ih*{ZOOM},crop=iw/{ZOOM}:ih/{ZOOM}:x={ox}:y={oy},scale=1920:1080"
    filters = [crop_f, "fps=25", pts]
    if hue_v != 0:
        filters.append(f"hue=h={hue_v}")
    if flip == "vflip":
        filters.append("vflip")
    elif flip:
        filters.append("hflip")

    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
           "-i", str(src)]
    if dur:
        cmd += ["-t", str(dur)]
    cmd += ["-vf", ",".join(filters),
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-an", str(dst)]
    subprocess.run(cmd, capture_output=True, timeout=120)
    return dst.exists() and dst.stat().st_size > 5000

def trim_mp4_clip(src, dst, max_dur=CLIP_MAX):
    total = get_duration(src)
    if total <= 0:
        return False
    start = random.uniform(0, max(0, total - max_dur))
    dur   = min(max_dur, total - start)
    subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-ss", str(start), "-i", str(src), "-t", str(dur),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-vf", "scale=1920:1080,fps=25", "-an", str(dst)
    ], capture_output=True, timeout=60)
    return dst.exists() and dst.stat().st_size > 5000

def jpeg_a_clip(img_path, dst, dur=SHOT_DUR, variation=0, allow_flip=True):
    """
    Convierte JPEG a clip con Ken Burns fluido usando scale+crop (NO filtro zoompan).
    El filtro zoompan de ffmpeg produce micro-stutters porque usa offsets enteros.
    En su lugar: scale a canvas 1.3x, luego crop con expresión lineal de 't' → movimiento suave.
    allow_flip=False para imágenes IA.
    """
    # Escala 1.3x para tener margen de pan — canvas 2496x1404
    SCALE_W, SCALE_H = 2496, 1404
    OUT_W,   OUT_H   = 1920, 1080
    margin_x = SCALE_W - OUT_W   # 576px de margen horizontal
    margin_y = SCALE_H - OUT_H   # 324px de margen vertical

    # 7 variaciones: combinaciones de dirección y zoom (in/out)
    # (zoom_start, zoom_end, pan_x_start, pan_x_end, pan_y_start, pan_y_end)
    # pan en píxeles dentro del canvas escalado
    variations = [
        # zoom in, pan tl→br
        (1.00, 1.20, 0,         margin_x//2, 0,         margin_y//2),
        # zoom out, pan br→tl
        (1.20, 1.00, margin_x,  margin_x//2, margin_y,  margin_y//2),
        # zoom in, pan tr→bl
        (1.00, 1.20, margin_x,  margin_x//2, 0,         margin_y//2),
        # zoom out, pan bl→tr
        (1.20, 1.00, 0,         margin_x//2, margin_y,  margin_y//2),
        # zoom in, centro fijo (ligero zoom)
        (1.00, 1.15, margin_x//2, margin_x//2, margin_y//2, margin_y//2),
        # zoom out, pan left→right suave
        (1.15, 1.00, 0,         margin_x,    margin_y//2, margin_y//2),
        # zoom in, pan right→left suave
        (1.00, 1.15, margin_x,  0,           margin_y//2, margin_y//2),
    ]
    v = variation % len(variations)
    zs, ze, xs, xe, ys, ye = variations[v]

    color_filters = [
        "", "colorbalance=rs=0.05:gs=0.02:bs=-0.03",
        "colorbalance=rs=-0.03:gs=0.02:bs=0.05",
        "eq=brightness=0.04:saturation=1.1",
        "eq=brightness=-0.04:saturation=0.9",
        "eq=saturation=1.3", "hue=s=0.7",
    ]
    color_f = color_filters[v]
    do_flip = allow_flip and (variation % 2 == 1)

    # Expresiones de tiempo con 't' (segundos) — interpolación lineal suave
    # scale dinámico: ffmpeg no soporta zoom con scale+t directamente,
    # así que usamos un canvas fijo 1.3x y solo movemos el crop.
    # Para el zoom dinámico usamos zoompan SOLO para zoom (d=1, sin pan) sobre el canvas ya escalado.
    # Esto evita el stuttering porque el pan lo hace crop con 't'.
    crop_x = f"'({xs})+({xe}-{xs})*t/{dur}'"
    crop_y = f"'({ys})+({ye}-{ys})*t/{dur}'"

    vf_parts = [
        f"scale={SCALE_W}:{SCALE_H}:force_original_aspect_ratio=increase",
        f"crop={SCALE_W}:{SCALE_H}",   # recortar bordes si el aspecto no es exacto
        f"crop={OUT_W}:{OUT_H}:{crop_x}:{crop_y}",
        "fps=25",
    ]
    if do_flip:
        vf_parts.append("hflip")
    if color_f:
        vf_parts.append(color_f)

    subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-loop", "1", "-framerate", "25", "-i", str(img_path),
        "-vf", ",".join(vf_parts),
        "-t", str(dur),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-an", str(dst)
    ], capture_output=True, timeout=300)

    return dst.exists() and dst.stat().st_size > 5000

# ── Overlay de nombre de artista (lower-third al inicio del segmento) ──────────

def aplicar_overlay_nombre(seg_path, dst_path, nombre_display):
    """
    Banda roja solo del ancho del nombre, centrada, texto amarillo 88pt.
    PNG único + fade alpha en filter_complex — sin frames, sin qtrle.
    """
    import tempfile, shutil
    DUR_SHOW = 4.0; FADE_IN = 0.3; FADE_OUT = 0.5; OV_DUR = DUR_SHOW + FADE_OUT

    font_path = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
    try:
        font = ImageFont.truetype(font_path, 88)
    except Exception:
        font = ImageFont.load_default()

    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bb = dummy.textbbox((0, 0), nombre_display, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    PAD_X = 32; PAD_Y = 20
    BAND_W = tw + PAD_X * 2; BAND_H = th + PAD_Y * 2
    bx = (1920 - BAND_W) // 2; by = (1080 - BAND_H) // 2
    tx = bx + (BAND_W - tw) // 2 - bb[0]
    ty = by + (BAND_H - th) // 2 - bb[1]

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="overlay_png_"))
    try:
        img = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rectangle([(bx, by), (bx + BAND_W, by + BAND_H)], fill=(140, 10, 10, 224))
        d.text((tx + 3, ty + 3), nombre_display, font=font, fill=(0, 0, 0, 180))
        d.text((tx, ty), nombre_display, font=font, fill=(255, 229, 102, 255))
        png = tmp / "ov.png"
        img.save(png)

        fc = (
            f"[1:v]fade=in:st=0:d={FADE_IN}:alpha=1,"
            f"fade=out:st={DUR_SHOW - FADE_OUT:.2f}:d={FADE_OUT}:alpha=1[ov];"
            f"[0:v][ov]overlay=0:0:eof_action=pass[v]"
        )
        r = subprocess.run([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(seg_path),
            "-loop", "1", "-t", str(OV_DUR), "-i", str(png),
            "-filter_complex", fc,
            "-map", "[v]", "-an",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-pix_fmt", "yuv420p", str(dst_path)
        ], capture_output=True, timeout=600)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return dst_path.exists() and dst_path.stat().st_size > 10000


# ── Tarjeta animada de artista ─────────────────────────────────────────────────

def _find_font(size):
    """Busca una fuente disponible en el sistema."""
    candidates = [
        "/Library/Fonts/Arial Bold.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Supplemental/Futura.ttc",
    ]
    for path in candidates:
        if pathlib.Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()

def generar_tarjeta_artista(numero, nombre_display, dst, dur=TITLE_DUR):
    """
    Genera clip TITLE_DUR s con Pillow — diseño cinematográfico:
      - Fondo degradado oscuro (azul-gris, no negro puro)
      - Franja dorada izquierda ancha con gradiente
      - Número en dorado grande desliza desde izquierda
      - Línea divisora dorada
      - Nombre en blanco bold, centrado
    """
    W, H   = 1920, 1080
    FPS    = 25
    frames = int(dur * FPS)

    font_num  = _find_font(180)
    font_name = _find_font(90)
    font_sub  = _find_font(36)

    GOLD  = (212, 175, 55)
    WHITE = (240, 240, 240)
    BG1   = (18, 22, 38)   # azul-gris muy oscuro (arriba)
    BG2   = (10, 12, 18)   # casi negro (abajo)

    frames_dir = pathlib.Path(tempfile.mkdtemp(prefix="hf_tarjeta_"))

    for i in range(frames):
        t = i / FPS
        progress = t / dur   # 0.0 → 1.0

        # Fondo degradado vertical azul-gris → casi negro
        img = Image.new("RGB", (W, H), BG1)
        draw = ImageDraw.Draw(img)
        for y in range(H):
            frac = y / H
            r = int(BG1[0] + (BG2[0] - BG1[0]) * frac)
            g = int(BG1[1] + (BG2[1] - BG1[1]) * frac)
            b = int(BG1[2] + (BG2[2] - BG1[2]) * frac)
            draw.line([(0, y), (W, y)], fill=(r, g, b))

        # Fade global: fade-in primeros 0.3s, fade-out últimos 0.3s
        if t < 0.3:
            alpha_global = t / 0.3
        elif t > dur - 0.3:
            alpha_global = (dur - t) / 0.3
        else:
            alpha_global = 1.0

        # Franja dorada izquierda (ancha, degradada)
        stripe_w = 14
        for sx in range(stripe_w):
            intensity = 1.0 - (sx / stripe_w) * 0.5
            c = tuple(int(c * intensity * alpha_global) for c in GOLD)
            draw.line([(sx, 0), (sx, H)], fill=c)

        # Línea horizontal dorada — aparece con slide
        line_progress = min(1.0, t / 0.4) * alpha_global
        line_w = int((W - 100) * line_progress)
        line_y = int(H * 0.75)
        if line_w > 0:
            draw.rectangle([80, line_y, 80 + line_w, line_y + 3],
                           fill=tuple(int(c * alpha_global) for c in GOLD))

        # Número — slide desde -350 hasta x=80
        slide_dur = 0.4
        if t < slide_dur:
            ease = (t / slide_dur) ** 0.5   # ease-out
            x_num = int(-350 + (80 - (-350)) * ease)
        else:
            x_num = 80
        num_alpha = int(255 * min(1.0, t / 0.25) * alpha_global)
        if num_alpha > 0:
            num_img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            num_draw = ImageDraw.Draw(num_img)
            num_draw.text((x_num, int(H * 0.58)), f"#{numero}",
                          font=font_num, fill=(*GOLD, num_alpha))
            img.paste(num_img, (0, 0), num_img)

        # Nombre — fade in desde t=0.35
        name_alpha = int(max(0, min(255, (t - 0.35) / 0.3 * 255)) * alpha_global)
        if name_alpha > 0:
            bbox = draw.textbbox((0, 0), nombre_display.upper(), font=font_name)
            tw = bbox[2] - bbox[0]
            x_name = (W - tw) // 2
            name_img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            name_draw = ImageDraw.Draw(name_img)
            name_draw.text((x_name, int(H * 0.79)), nombre_display.upper(),
                           font=font_name, fill=(*WHITE, name_alpha))
            img.paste(name_img, (0, 0), name_img)

        img.save(frames_dir / f"frame_{i:04d}.png")

    subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-framerate", "25", "-i", str(frames_dir / "frame_%04d.png"),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-an", str(dst)
    ], capture_output=True, timeout=60)

    shutil.rmtree(frames_dir, ignore_errors=True)
    return dst.exists() and dst.stat().st_size > 5000

# ── Construir segmento de contenido ───────────────────────────────────────────

def validar_aspecto_imagen(img_path, min_ratio=1.0, max_ratio=2.5):
    """Rechaza imágenes con aspect ratio fuera del rango esperado (evita estiramientos)."""
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0", str(img_path)],
            capture_output=True, text=True, timeout=10
        )
        parts = r.stdout.strip().split(",")
        if len(parts) < 2:
            return True  # no se pudo leer, dejar pasar
        w, h = int(parts[0]), int(parts[1])
        if h == 0:
            return False
        ratio = w / h
        return min_ratio <= ratio <= max_ratio
    except Exception:
        return True

def clips_ordenados_de_meta(meta_section):
    """
    Devuelve lista ordenada de paths según slot del dashboard.
    - Excluye rechazados
    - Si no hay NINGÚN aprobado/rechazado (todos pendientes) → None (sin filtro de dashboard)
    - Si hay al menos un aprobado o rechazado → usa los no-rechazados en orden de slot
    """
    clips = meta_section.get("clips", {})
    hay_decision = any(c.get("estado") in ("aprobado", "rechazado") for c in clips.values())
    if not hay_decision:
        return None  # sin filtro, el render elige libremente

    no_rechazados = [(fname, info) for fname, info in clips.items()
                     if info.get("estado") != "rechazado"]
    no_rechazados.sort(key=lambda x: x[1].get("slot", 999))
    resultado = []
    for fname, info in no_rechazados:
        p = pathlib.Path(info.get("path", ""))
        if p.exists():
            resultado.append((p, info.get("tipo", "video")))
    return resultado  # lista de (path, tipo)


def construir_segmento(nombre, carpeta, duracion, tmp_dir, seg_idx, meta_section=None):
    # Si hay dashboard con decisiones tomadas, usar clips pre-seleccionados en orden
    if meta_section:
        ordenados = clips_ordenados_de_meta(meta_section)
        if ordenados is not None:
            ok(f"{nombre}: usando {len(ordenados)} clips del dashboard (en orden)")
            return _construir_desde_lista_ordenada(nombre, ordenados, duracion, tmp_dir, seg_idx)

    all_mp4   = sorted(carpeta.glob("*.mp4")) if carpeta else []
    zp_clips  = [f for f in all_mp4 if "_zp" in f.stem]
    raw_clips = [f for f in all_mp4 if "_zp" not in f.stem
                 and not any(f.stem.startswith(p) for p in ("tmp", "flow"))]
    jpegs_all = sorted([f for f in carpeta.iterdir()
                        if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp')]) if carpeta else []
    # Filtrar imágenes con aspect ratio válido (evita estiramiento)
    jpegs = [j for j in jpegs_all if validar_aspecto_imagen(j)]
    if len(jpegs) < len(jpegs_all):
        warn(f"{nombre}: {len(jpegs_all)-len(jpegs)} imagen(s) descartada(s) por aspecto inválido")

    random.shuffle(raw_clips)
    random.shuffle(zp_clips)
    random.shuffle(jpegs)
    return _construir_con_fuentes(nombre, raw_clips, zp_clips, jpegs, duracion, tmp_dir, seg_idx)


def _construir_desde_lista_ordenada(nombre, ordenados, duracion, tmp_dir, seg_idx):
    """Construye el segmento usando exactamente los clips del dashboard, en orden de slot."""
    processed = tmp_dir / f"seg{seg_idx:02d}_ord"
    processed.mkdir(exist_ok=True)
    planos = []
    total_built = 0.0
    needed = duracion + 2

    pool = list(ordenados)
    idx  = 0

    while total_built < needed:
        if not pool:
            pool = list(ordenados)
            if not pool:
                break

        path, tipo = pool.pop(0)
        out = processed / f"plano_{idx:04d}.mp4"

        if tipo == "imagen":
            variation = idx % 7
            if jpeg_a_clip(path, out, dur=SHOT_DUR, variation=variation, allow_flip=False):
                planos.append(out)
                total_built += SHOT_DUR
        else:
            trimmed = processed / f"trim_{idx:04d}.mp4"
            if trim_mp4_clip(path, trimmed, max_dur=CLIP_MAX):
                if apply_antifp(trimmed, out, flip=(idx % 2 == 1)):
                    d = get_duration(out)
                    if d > 0.5:
                        planos.append(out)
                        total_built += d
            trimmed.unlink(missing_ok=True)

        idx += 1
        if idx > 500:
            break

    if not planos:
        return None

    concat_list = processed / "concat.txt"
    concat_list.write_text("\n".join(f"file '{p.resolve()}'" for p in planos), encoding="utf-8")
    raw_seg = tmp_dir / f"raw_seg_{seg_idx:02d}.mp4"
    subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-an", str(raw_seg)
    ], capture_output=True, timeout=1800)
    if not raw_seg.exists():
        return None
    final_seg = tmp_dir / f"seg_{seg_idx:02d}.mp4"
    subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", str(raw_seg), "-t", str(duracion), "-c:v", "copy", str(final_seg)
    ], capture_output=True, timeout=120)
    return final_seg if final_seg.exists() else None


def _construir_con_fuentes(nombre, raw_clips, zp_clips, jpegs, duracion, tmp_dir, seg_idx):
    planos    = []
    processed = tmp_dir / f"seg{seg_idx:02d}"
    processed.mkdir(exist_ok=True)

    clip_idx    = 0
    total_built = 0.0
    needed      = duracion + 2
    variation   = 0

    # Anti-repeat: se usa cada clip UNA vez antes de reutilizar
    # clip_uses rastrea cuántas veces se usó cada clip → transformación distinta por ocurrencia
    raw_pool  = list(raw_clips)
    zp_pool   = list(zp_clips)
    jpg_base  = list(jpegs)
    clip_uses = {}  # str(path) → use_count

    iteration = 0
    while total_built < needed:
        iteration += 1
        out = processed / f"plano_{clip_idx:04d}.mp4"

        if raw_pool:
            src     = raw_pool.pop(0)
            trimmed = processed / f"trim_{clip_idx:04d}.mp4"
            use_n   = clip_uses.get(str(src), 0)
            clip_uses[str(src)] = use_n + 1
            if trim_mp4_clip(src, trimmed, max_dur=CLIP_MAX):
                if apply_antifp(trimmed, out, use_count=use_n):
                    d = get_duration(out)
                    if d > 0.5:
                        planos.append(out)
                        total_built += d
                        clip_idx += 1
            trimmed.unlink(missing_ok=True)
            # Solo reutilizar si ya se agotaron todos Y se necesita más
            if not raw_pool and total_built < needed:
                raw_pool = list(raw_clips)
                random.shuffle(raw_pool)

        elif jpg_base:
            # Reciclar fotos con variaciones distintas para evitar imagen repetida igual
            src = jpg_base[variation % len(jpg_base)]
            if jpeg_a_clip(src, out, dur=SHOT_DUR, variation=variation):
                planos.append(out)
                total_built += SHOT_DUR
                clip_idx += 1
            variation += 1

        elif zp_pool:
            src   = zp_pool.pop(0)
            use_n = clip_uses.get(str(src), 0)
            clip_uses[str(src)] = use_n + 1
            if apply_antifp(src, out, dur=SHOT_DUR, use_count=use_n):
                d = get_duration(out)
                if d > 0.5:
                    planos.append(out)
                    total_built += d
                    clip_idx += 1
            if not zp_pool and total_built < needed:
                zp_pool = list(zp_clips)
                random.shuffle(zp_pool)

        else:
            subprocess.run([
                FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-f", "lavfi", "-i", f"color=c=black:size=1920x1080:rate=25:duration={SHOT_DUR}",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-pix_fmt", "yuv420p", str(out)
            ], capture_output=True, timeout=30)
            if out.exists():
                planos.append(out)
                total_built += SHOT_DUR
                clip_idx += 1

        if iteration > 600:
            warn(f"[{nombre}] Límite iteraciones")
            break

    if not planos:
        return None

    concat_list = processed / "concat.txt"
    concat_list.write_text("\n".join(f"file '{p.resolve()}'" for p in planos), encoding="utf-8")

    raw_seg = tmp_dir / f"raw_seg_{seg_idx:02d}.mp4"
    subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-an", str(raw_seg)
    ], capture_output=True, timeout=1800)

    if not raw_seg.exists():
        return None

    final_seg = tmp_dir / f"seg_{seg_idx:02d}.mp4"
    subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", str(raw_seg), "-t", str(duracion),
        "-c:v", "copy", str(final_seg)
    ], capture_output=True, timeout=60)

    return final_seg if final_seg.exists() else None

# ── Segmento hook: usa clips de artistas ──────────────────────────────────────

def construir_hook(duracion, timestamps, tmp_dir, folder=None):
    """
    Hook: prioridad de fuentes:
      1. MP4s animados por VEO3 en hook_images/ (hook_0001.mp4 … ) — sin zoompan
      2. JPEGs en hook_images/ con zoompan (fallback si VEO3 no corrió)
      3. Clips de artistas (último recurso)
    """
    if folder:
        hook_dir = pathlib.Path(folder) / "hook_images"
        tl_file  = pathlib.Path(folder) / "hook_timeline.json"

        dur_map = {}
        if tl_file.exists():
            segs = json.load(tl_file.open())["visual_timeline"]
            for i, s in enumerate(segs):
                dur_map[i] = s["duration"]

        # ── Prioridad 1: Timeline mixto Flow+YT (hook_timeline.json + hook_yt_state.json) ──
        # Nombres posibles: 001_Slow-cinematic.mp4 (VEO3 original) o hook_0001_zp.mp4 (renombrados)
        veo_clips = sorted(hook_dir.glob("[0-9][0-9][0-9]_*.mp4")) if hook_dir.exists() else []
        if not veo_clips:
            veo_clips = sorted(hook_dir.glob("hook_[0-9]*_zp.mp4")) if hook_dir.exists() else []
        if veo_clips and tl_file.exists():
            ok(f"Hook: {len(veo_clips)} clips VEO3 encontrados")
            # Leer estado clips YT asignados
            yt_state_file = pathlib.Path(folder) / "hook_yt_state.json"
            yt_state = {}
            if yt_state_file.exists():
                yt_state = json.load(yt_state_file.open())

            segs_full = json.load(tl_file.open())["visual_timeline"]
            processed = tmp_dir / "hook_clips"
            processed.mkdir(exist_ok=True)
            planos = []
            flow_idx = 0  # índice en veo_clips

            for slot, seg in enumerate(segs_full):
                seg_type = seg.get("type", "flow")
                dur_seg = seg.get("duration", SHOT_DUR)
                out = processed / f"hook_{slot:04d}.mp4"

                if seg_type == "flow":
                    if flow_idx >= len(veo_clips):
                        warn(f"  hook slot {slot} Flow — sin VEO3 disponible, saltando")
                        flow_idx += 1
                        continue
                    clip = veo_clips[flow_idx]
                    flow_idx += 1
                    subprocess.run([
                        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                        "-i", str(clip),
                        "-t", str(dur_seg),
                        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=25",
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                        "-pix_fmt", "yuv420p", "-an", str(out)
                    ], capture_output=True, timeout=120)
                    if out.exists() and out.stat().st_size > 5000:
                        planos.append(out)
                    else:
                        warn(f"  hook_{slot:04d} Flow VEO3 falló — saltando")

                else:  # type == "youtube"
                    seg_id = str(seg.get("segment_id", ""))
                    yt_path = yt_state.get(seg_id)
                    if not yt_path or not pathlib.Path(yt_path).exists():
                        warn(f"  hook slot {slot} YT — clip no encontrado ({yt_path}), saltando")
                        continue
                    # Re-encodar clip YT a 1920x1080 25fps recortado a dur_seg
                    subprocess.run([
                        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                        "-stream_loop", "-1", "-i", str(yt_path),
                        "-t", str(dur_seg),
                        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=25",
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                        "-pix_fmt", "yuv420p", "-an", str(out)
                    ], capture_output=True, timeout=120)
                    if out.exists() and out.stat().st_size > 5000:
                        planos.append(out)
                        ok(f"  hook slot {slot} YT: {pathlib.Path(yt_path).name[:40]} ({dur_seg}s)")
                    else:
                        warn(f"  hook_{slot:04d} YT encode falló — saltando")

            if planos:
                concat_list = processed / "concat.txt"
                concat_list.write_text("\n".join(f"file '{p.resolve()}'" for p in planos), encoding="utf-8")
                raw_hook = tmp_dir / "raw_hook.mp4"
                subprocess.run([
                    FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-f", "concat", "-safe", "0", "-i", str(concat_list),
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                    "-pix_fmt", "yuv420p", "-an", str(raw_hook)
                ], capture_output=True, timeout=1800)
                hook_out = tmp_dir / "hook.mp4"
                subprocess.run([
                    FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-i", str(raw_hook), "-t", str(duracion), "-c:v", "copy", str(hook_out)
                ], capture_output=True, timeout=60)
                if hook_out.exists():
                    n_flow = sum(1 for s in segs_full if s.get("type","flow")=="flow")
                    n_yt = sum(1 for s in segs_full if s.get("type")=="youtube")
                    ok(f"Hook mixto: {n_flow} Flow + {n_yt} YT → {duracion:.1f}s")
                    return hook_out

        # ── Prioridad 2: JPEGs con zoompan (fallback) ────────────────────────
        # Nombres renombrados: 01_hook_0001.jpg
        hook_imgs = (sorted(hook_dir.glob("[0-9][0-9]_hook_*.jpg")) or
                     sorted(hook_dir.glob("hook_[0-9]*.jpg"))) if hook_dir.exists() else []
        if hook_imgs:
            warn(f"Hook: sin MP4s VEO3 — usando {len(hook_imgs)} JPEGs con zoompan")
            processed = tmp_dir / "hook_clips"
            processed.mkdir(exist_ok=True)
            planos = []
            for i, img in enumerate(hook_imgs):
                dur_img = dur_map.get(i, SHOT_DUR)
                out = processed / f"hook_{i:04d}.mp4"
                if jpeg_a_clip(img, out, dur=dur_img, variation=i, allow_flip=False):
                    planos.append(out)
            if planos:
                concat_list = processed / "concat.txt"
                concat_list.write_text("\n".join(f"file '{p.resolve()}'" for p in planos), encoding="utf-8")
                raw_hook = tmp_dir / "raw_hook.mp4"
                subprocess.run([
                    FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-f", "concat", "-safe", "0", "-i", str(concat_list),
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                    "-pix_fmt", "yuv420p", "-an", str(raw_hook)
                ], capture_output=True, timeout=1800)
                hook_out = tmp_dir / "hook.mp4"
                subprocess.run([
                    FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-i", str(raw_hook), "-t", str(duracion), "-c:v", "copy", str(hook_out)
                ], capture_output=True, timeout=60)
                if hook_out.exists():
                    ok(f"Hook JPEG+zoompan: {len(planos)} → {duracion:.1f}s")
                    return hook_out

    # Fallback: clips de artistas
    pool = []
    for seg in timestamps:
        if seg.get('is_hook') or seg.get('is_cierre'):
            continue
        carpeta = buscar_carpeta_icloud(seg['name'])
        if not carpeta:
            continue
        mp4s = [f for f in carpeta.glob("*.mp4")
                if "_zp" not in f.stem and not f.stem.startswith("tmp")]
        random.shuffle(mp4s)
        pool.extend(mp4s[:8])  # max 8 clips por artista para el hook

    random.shuffle(pool)
    if not pool:
        # Fallback: negro
        out = tmp_dir / "hook.mp4"
        subprocess.run([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "lavfi", "-i", f"color=c=black:size=1920x1080:rate=25:duration={duracion}",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-pix_fmt", "yuv420p", str(out)
        ], capture_output=True, timeout=60)
        return out

    # Construir hook igual que un segmento de artista
    processed = tmp_dir / "hook_clips"
    processed.mkdir(exist_ok=True)
    planos = []
    total_built = 0.0
    clip_idx = 0
    pool_cycle = list(pool)
    random.shuffle(pool_cycle)

    while total_built < duracion + 2 and pool_cycle:
        src     = pool_cycle.pop(0)
        out     = processed / f"hook_{clip_idx:04d}.mp4"
        trimmed = processed / f"htrim_{clip_idx:04d}.mp4"
        if trim_mp4_clip(src, trimmed, max_dur=CLIP_MAX):
            if apply_antifp(trimmed, out):
                d = get_duration(out)
                if d > 0.5:
                    planos.append(out)
                    total_built += d
                    clip_idx += 1
        trimmed.unlink(missing_ok=True)
        if clip_idx > 100:
            break

    if not planos:
        return None

    concat_list = processed / "concat.txt"
    concat_list.write_text("\n".join(f"file '{p.resolve()}'" for p in planos), encoding="utf-8")
    raw_hook = tmp_dir / "raw_hook.mp4"
    subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-an", str(raw_hook)
    ], capture_output=True, timeout=300)

    hook_out = tmp_dir / "hook.mp4"
    subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", str(raw_hook), "-t", str(duracion), "-c:v", "copy", str(hook_out)
    ], capture_output=True, timeout=60)
    return hook_out if hook_out.exists() else None

# ── Main ───────────────────────────────────────────────────────────────────────

def seg_label(label_raw, nombre):
    """Nombre de archivo estable para un segmento persistente."""
    safe = re.sub(r'[^a-z0-9]', '_', norm(nombre))[:25].strip('_')
    return f"seg_{label_raw[:18]}_{safe}.mp4"


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--solo-artista", default=None,
                    help="Re-renderiza solo este artista y reconcat")
    ap.add_argument("--solo-concat", action="store_true",
                    help="Solo reconcat desde segmentos/ sin renderizar")
    ap.add_argument("--skip-preflight", action="store_true",
                    help="Saltar verificación de clips (usar si iCloud no es accesible)")
    ap.add_argument("--url-ref", default=None,
                    help="URL YouTube del video de referencia (para cubrir déficit automáticamente)")
    ap.add_argument("--solo-hook", action="store_true",
                    help="Re-renderiza solo el hook y reconcat desde segmentos/")
    args = ap.parse_args()

    folder = pathlib.Path(args.folder)
    if not folder.is_dir():
        print(f"ERROR: {folder} no existe")
        sys.exit(1)

    ts_file  = folder / "timestamps.json"
    mp3_file = folder / "audio.mp3"
    out_file = folder / "output.mp4"

    for f in [ts_file, mp3_file]:
        if not f.exists():
            print(f"ERROR: falta {f}")
            sys.exit(1)

    timestamps = json.loads(ts_file.read_text(encoding="utf-8"))

    # Directorio persistente de segmentos
    seg_dir = folder / "segmentos"
    seg_dir.mkdir(exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  RENDER FARANDULA v3 — {folder.name}")
    if args.solo_artista:
        print(f"  MODO: re-render → {args.solo_artista}")
    elif args.solo_concat:
        print(f"  MODO: solo concat desde segmentos/")
    print(f"{'='*60}\n")

    # ── Modo solo-concat: cargar manifest y saltar al concat ─────────────────
    if args.solo_concat:
        manifest = seg_dir / "manifest.txt"
        if not manifest.exists():
            err("No existe segmentos/manifest.txt — corre el render completo primero")
            sys.exit(1)
        segments_final = []
        for line in manifest.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            p = pathlib.Path(line)
            if not p.exists():
                err(f"Segmento faltante: {p.name}")
                sys.exit(1)
            segments_final.append(p)
        ok(f"{len(segments_final)} segmentos desde segmentos/")
        tmp_dir = pathlib.Path(tempfile.mkdtemp(prefix="render_farandula_"))
        _mux_final(segments_final, mp3_file, out_file, tmp_dir, folder)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return

    tmp_dir = pathlib.Path(tempfile.mkdtemp(prefix="render_farandula_"))
    print(f"  Tmp: {tmp_dir}\n")

    HF_PROJ    = pathlib.Path(__file__).parent / "tarjeta_hf"
    segments_final = []

    # Cargar dashboard_meta.json si existe (clips aprobados)
    dash_meta_file = folder / "dashboard_meta.json"
    dash_meta = {}
    if dash_meta_file.exists():
        try:
            dash_meta = json.loads(dash_meta_file.read_text())
            aprobados_total = sum(
                1 for s in dash_meta.values()
                for c in s.get("clips", {}).values()
                if c.get("estado") == "aprobado"
            )
            if aprobados_total > 0:
                ok(f"Dashboard: {aprobados_total} clips aprobados cargados")
        except Exception:
            dash_meta = {}

    # ── Pre-flight: verificar clips suficientes por artista ───────────────────────
    if not args.skip_preflight:
        YT_BACKUP = HOME / "Library/Mobile Documents/com~apple~CloudDocs/yt"
        print("  Verificando clips por artista...")
        deficit = []
        try:
            for seg in timestamps:
                if seg.get('is_hook') or seg.get('is_cierre'):
                    continue
                nombre   = seg['name']
                duracion = seg['duration']
                label_raw = seg['label']
                slots_needed = math.ceil(duracion / SHOT_DUR)
                meta_sec = dash_meta.get(label_raw, {})
                clips_dash = [c for c in meta_sec.get('clips', {}).values()
                              if c.get('estado') != 'rechazado']
                n_dash = len(clips_dash)
                carpeta = buscar_carpeta_icloud(nombre)
                n_icloud = len(list(carpeta.glob("*.mp4"))) if carpeta else 0
                disponibles = max(n_dash, n_icloud)
                if disponibles < slots_needed:
                    deficit.append((nombre, duracion, slots_needed, disponibles, carpeta))
        except PermissionError:
            warn("iCloud no accesible — saltando preflight. Usa --skip-preflight para evitar este aviso.")
            deficit = []

        if deficit:
            print(f"\n  {AMARILLO}⚠ DÉFICIT DE CLIPS detectado:{RESET}")
            print(f"  {'Artista':<30} {'Duración':>8} {'Necesita':>9} {'Tiene':>6}")
            print(f"  {'-'*60}")
            for nombre, dur, need, tiene, carpeta in deficit:
                print(f"  {nombre:<30} {dur:>7.0f}s {need:>9} {tiene:>6}")

            if args.url_ref:
                print(f"\n  Intentando cubrir déficit automáticamente con cubrir_deficit.py...")
                cubrir_script = pathlib.Path(__file__).parent / "cubrir_deficit.py"
                cmd = [sys.executable, str(cubrir_script),
                       args.folder, "--url-ref", args.url_ref]
                r = subprocess.run(cmd, timeout=3600)
                if r.returncode != 0:
                    err("cubrir_deficit.py falló — verifica manualmente")
                    sys.exit(1)
                # Re-verificar después de cubrir
                deficit2 = []
                for seg in timestamps:
                    if seg.get('is_hook') or seg.get('is_cierre'):
                        continue
                    nombre   = seg['name']
                    duracion = seg['duration']
                    label_raw = seg['label']
                    slots_needed = math.ceil(duracion / SHOT_DUR)
                    carpeta = buscar_carpeta_icloud(nombre)
                    n_icloud = len(list(carpeta.glob("*.mp4"))) if carpeta else 0
                    if n_icloud < slots_needed:
                        deficit2.append((nombre, slots_needed, n_icloud))
                if deficit2:
                    err("Déficit no resuelto — artistas con clips insuficientes:")
                    for nombre, need, tiene in deficit2:
                        print(f"    {nombre}: tiene {tiene}, necesita {need}")
                    sys.exit(1)
                ok("Déficit cubierto — continuando render")
            else:
                print()
                print(f"  {ROJO}⛔ Render cancelado por déficit.{RESET}")
                print(f"  Pasa --url-ref 'URL' para cubrir déficit automáticamente, o")
                print(f"  usa --skip-preflight para forzar el render igual.")
                sys.exit(1)
        ok(f"Clips suficientes para todos los artistas\n")
    else:
        ok("Pre-flight saltado\n")
    # ─────────────────────────────────────────────────────────────────────────────

    for seg in timestamps:
        nombre    = seg['name']
        duracion  = seg['duration']
        is_hook   = seg.get('is_hook', False)
        is_cierre = seg.get('is_cierre', False)
        label_raw = seg['label']

        num_match = re.match(r'^(\d+)_', label_raw)
        numero    = int(num_match.group(1)) if num_match else 0

        print(f"\n  [{label_raw}] {duracion:.1f}s")

        # ── Modo --solo-artista / --solo-hook: reutilizar segmentos ─────────
        if args.solo_artista:
            target_norm = norm(args.solo_artista)
            this_norm   = norm(nombre)
            es_target   = target_norm in this_norm or this_norm in target_norm
            if not es_target:
                persistent = seg_dir / seg_label(label_raw, nombre)
                if persistent.exists():
                    segments_final.append(persistent)
                    ok(f"Reutilizando: {persistent.name}")
                    continue
                else:
                    warn(f"Segmento previo no encontrado para {nombre} — se re-renderizará")

        if args.solo_hook and not is_hook:
            persistent = seg_dir / seg_label(label_raw, nombre)
            if persistent.exists():
                segments_final.append(persistent)
                ok(f"Reutilizando: {persistent.name}")
                continue
            else:
                warn(f"Segmento previo no encontrado para {nombre} — se re-renderizará")
        # ─────────────────────────────────────────────────────────────────────

        if is_cierre:
            out = tmp_dir / "cierre.mp4"
            # Recopilar clips de todos los artistas del video para el cierre
            artistas_segs = [s for s in timestamps if not s.get('is_hook') and not s.get('is_cierre')]
            pool_cierre = []
            for seg_art in artistas_segs:
                c = buscar_carpeta_icloud(seg_art['name'])
                if c:
                    clips_art = [f for f in c.glob("*.mp4") if "_zp" not in f.stem]
                    if not clips_art:
                        clips_art = list(c.glob("*.mp4"))
                    pool_cierre.extend(clips_art)
            random.shuffle(pool_cierre)
            slots_cierre = math.ceil(duracion / CLIP_MAX)
            cierre_clips = []
            used_cierre = set()
            cycle = list(pool_cierre)
            while len(cierre_clips) < slots_cierre and cycle:
                clip = cycle.pop(0)
                if str(clip) not in used_cierre:
                    used_cierre.add(str(clip))
                    cierre_clips.append(clip)
                if not cycle:
                    cycle = list(pool_cierre)
                    random.shuffle(cycle)
            if cierre_clips:
                cierre_procesados = tmp_dir / "cierre_clips"
                cierre_procesados.mkdir(exist_ok=True)
                planos_cierre = []
                for ci, cp in enumerate(cierre_clips):
                    co = cierre_procesados / f"c_{ci:04d}.mp4"
                    trimmed = cierre_procesados / f"trim_{ci:04d}.mp4"
                    subprocess.run([
                        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                        "-i", str(cp), "-t", str(CLIP_MAX),
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                        "-pix_fmt", "yuv420p", "-an", str(trimmed)
                    ], capture_output=True, timeout=60)
                    if trimmed.exists() and apply_antifp(trimmed, co):
                        planos_cierre.append(co)
                if planos_cierre:
                    cl = cierre_procesados / "concat.txt"
                    cl.write_text("\n".join(f"file '{p.resolve()}'" for p in planos_cierre))
                    subprocess.run([
                        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                        "-f", "concat", "-safe", "0", "-i", str(cl),
                        "-t", str(duracion),
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                        "-pix_fmt", "yuv420p", "-an", str(out)
                    ], capture_output=True, timeout=300)
            if not out.exists():
                # Fallback negro si no hay clips
                subprocess.run([
                    FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-f", "lavfi", "-i", f"color=c=black:size=1920x1080:rate=25:duration={duracion}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                    "-pix_fmt", "yuv420p", str(out)
                ], capture_output=True, timeout=30)
            if out.exists():
                persistent = seg_dir / seg_label(label_raw, nombre)
                shutil.copy2(str(out), str(persistent))
                segments_final.append(persistent)
                ok(f"Cierre: {len(cierre_clips)} clips de artistas ({duracion:.1f}s)")
            continue

        if is_hook:
            hook = construir_hook(duracion, timestamps, tmp_dir, folder=folder)
            if hook:
                persistent = seg_dir / seg_label(label_raw, nombre)
                shutil.copy2(str(hook), str(persistent))
                segments_final.append(persistent)
                ok(f"Hook: {duracion:.1f}s con clips de artistas")
            else:
                err("Hook: falló")
            continue

        # ── Artista ──────────────────────────────────────────────────────────
        carpeta = buscar_carpeta_icloud(nombre)
        if carpeta:
            ok(f"iCloud: {carpeta.name}")
        else:
            warn(f"Sin carpeta iCloud para {nombre}")

        nombre_display = nombre.title()

        # 1. Contenido del artista (duración total)
        meta_section = dash_meta.get(label_raw)
        contenido = construir_segmento(nombre, carpeta, duracion, tmp_dir, numero, meta_section=meta_section)
        if contenido is None:
            warn(f"{nombre}: sin contenido, usando negro")
            contenido = tmp_dir / f"negro_{numero}.mp4"
            subprocess.run([
                FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-f", "lavfi", "-i", f"color=c=black:size=1920x1080:rate=25:duration={duracion}",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-pix_fmt", "yuv420p", str(contenido)
            ], capture_output=True, timeout=30)

        # Overlay de nombre centrado al inicio del segmento (fade-in/out con Pillow)
        overlay_out = tmp_dir / f"seg_{numero:02d}_overlay.mp4"
        if aplicar_overlay_nombre(contenido, overlay_out, nombre_display):
            seg_final = overlay_out
        else:
            warn(f"{nombre}: overlay falló, usando segmento sin overlay")
            seg_final = contenido

        if seg_final.exists():
            persistent = seg_dir / seg_label(label_raw, nombre)
            shutil.copy2(str(seg_final), str(persistent))
            segments_final.append(persistent)
            ok(f"Segmento listo: {get_duration(persistent):.1f}s → segmentos/{persistent.name}")
        elif contenido and contenido.exists():
            persistent = seg_dir / seg_label(label_raw, nombre)
            shutil.copy2(str(contenido), str(persistent))
            segments_final.append(persistent)

    # ── Guardar manifest y llamar a mux ──────────────────────────────────────
    manifest = seg_dir / "manifest.txt"
    manifest.write_text(
        "\n".join(str(p.resolve()) for p in segments_final),
        encoding="utf-8"
    )
    ok(f"Manifest guardado: {len(segments_final)} segmentos en segmentos/")

    _mux_final(segments_final, mp3_file, out_file, tmp_dir, folder)
    shutil.rmtree(tmp_dir, ignore_errors=True)


def _mux_final(segments_final, mp3_file, out_file, tmp_dir, folder):
    """Concat + mux audio. Separado para reutilizarlo en --solo-concat."""
    print(f"\n  Concatenando {len(segments_final)} segmentos...")
    concat_list = tmp_dir / "final_concat.txt"
    concat_list.write_text(
        "\n".join(f"file '{p.resolve()}'" for p in segments_final),
        encoding="utf-8"
    )

    video_sin_audio = tmp_dir / "video_sin_audio.mp4"
    subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-an", str(video_sin_audio)
    ], capture_output=True, timeout=3600)

    if not video_sin_audio.exists():
        err("Concatenación final falló")
        sys.exit(1)
    ok(f"Video concatenado: {get_duration(video_sin_audio):.1f}s")

    # Buscar música
    music_file = None
    script_dir = pathlib.Path(__file__).parent.parent
    for c in [
        folder / "musica.mp3", folder / "musica_v1.mp3",
        script_dir / "_musica/farandula/musica_v1.mp3",
        script_dir / "_musica/farandula/musica_v2.mp3",
    ]:
        if c.exists() and c.stat().st_size > 50000:
            music_file = c
            break

    print(f"\n  Muxeando audio → {out_file.name}")
    if music_file:
        print(f"  Música: {music_file.name} (vol={MUSIC_VOL})")
        filter_audio = (
            "[1:a]volume=1.0[voz];"
            f"[2:a]volume={MUSIC_VOL},aloop=loop=-1:size=2e+09[musica];"
            "[voz][musica]amix=inputs=2:duration=first:dropout_transition=3[audio_out]"
        )
        subprocess.run([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(video_sin_audio), "-i", str(mp3_file), "-i", str(music_file),
            "-filter_complex", filter_audio,
            "-map", "0:v:0", "-map", "[audio_out]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            "-shortest", str(out_file)
        ], capture_output=True, timeout=1800)
    else:
        warn("Sin música de fondo")
        subprocess.run([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(video_sin_audio), "-i", str(mp3_file),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            "-shortest", str(out_file)
        ], capture_output=True, timeout=1800)

    if out_file.exists():
        size_mb = out_file.stat().st_size / 1024 / 1024
        dur = get_duration(out_file)
        print(f"\n{'='*60}")
        print(f"  ✅ output.mp4: {size_mb:.0f}MB, {dur/60:.1f} min")
        print(f"  {out_file}")
        print(f"{'='*60}\n")
        # Notificar al dashboard
        try:
            import urllib.request as _ur, json as _json
            _msg = _json.dumps({"ok": True, "size_mb": round(size_mb), "dur_min": round(dur/60, 1)}).encode()
            _ur.urlopen(_ur.Request("http://localhost:5002/api/render_done",
                data=_msg, headers={"Content-Type": "application/json"}), timeout=3)
        except Exception:
            pass
    else:
        err("output.mp4 no se generó")
        sys.exit(1)


if __name__ == "__main__":
    main()
