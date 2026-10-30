#!/usr/bin/env python3
"""
overlay_srt_datos.py — Agrega datos clave del SRT como overlays en output.mp4

Solo cubre los primeros 10 minutos (el SRT solo tiene esa cobertura).
Genera PNGs con PIL y los aplica con ffmpeg overlay filter.

Uso:
  python3 overlay_srt_datos.py
  python3 overlay_srt_datos.py --out output_con_datos.mp4
"""

import re, pathlib, subprocess, sys, argparse, shutil
from PIL import Image, ImageDraw, ImageFont

BASE = pathlib.Path("/Users/anyelocuesta/Downloads/Canales/EpocaDeOro/Video-001 Murieron en la Miseria")
SRT  = BASE / "audio.srt"
SRC  = BASE / "output.mp4"
TMP  = pathlib.Path("/private/tmp/claude-501/-Users-anyelocuesta-Downloads-Canales/d12dac1d-a96f-4424-9f99-121905bc8b28/scratchpad/srt_overlays")
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"

# ── Colores del estilo EpocaDeOro ──────────────────────────────────────────────
COLOR_GOLD   = (201, 162, 39, 255)    # #C9A227
COLOR_WHITE  = (255, 255, 255, 255)
COLOR_BG     = (0, 0, 0, 170)         # negro semitransparente
DISPLAY_DUR  = 3.0                    # segundos que aparece cada dato
MIN_INTERVAL = 8.0                    # al menos 8s entre overlays consecutivos

# ── Patrones para extraer datos clave ─────────────────────────────────────────
FACT_PATTERNS = [
    # nacimiento
    (r'[Nn]ació\s+en\s+(\d{4})[^\d]', lambda m: f"Nació en {m.group(1)}"),
    (r'[Nn]ació\s+en\s+\d{4}\s+en\s+([\w\s,]+?)[\.\,]', lambda m: f"Origen: {m.group(1).strip()}"),
    # muerte
    (r'[Mm]urió\s+en\s+(\d{4})', lambda m: f"Murió en {m.group(1)}"),
    (r'[Ff]alleció\s+en\s+(\d{4})', lambda m: f"Falleció en {m.group(1)}"),
    # debut
    (r'[Dd]ebutó\s+en\s+el\s+cine\s+a\s+los\s+(\d+)\s+años', lambda m: f"Debutó a los {m.group(1)} años"),
    # películas
    (r'[Pp]rotagonizó\s+(?:más\s+de\s+)?(\d+)\s+películas', lambda m: f"+{m.group(1)} películas"),
    # pelícuas específicas
    (r'[Pp]rotagonizó\s+(.{10,45}?)\s+de\s+[A-Z]', lambda m: f'"{m.group(1).strip()}"'),
    # filmó en
    (r'[Ff]ilmó\s+en\s+([\w\s,]+?)[\.\,]', lambda m: f"Filmó en {m.group(1).strip()[:30]}"),
    # fecha exacta
    (r'[Ll]a\s+noche\s+del\s+(\d+\s+de\s+\w+\s+de\s+\d{4})', lambda m: f"{m.group(1)}"),
]

def parse_srt(path: pathlib.Path, max_seconds: float = 600.0):
    """Devuelve lista de (start_sec, text_raw)"""
    blocks = path.read_text(encoding="utf-8", errors="ignore").strip().split("\n\n")
    entries = []
    for b in blocks:
        lines = b.strip().split("\n")
        if len(lines) < 3:
            continue
        m = re.match(r"(\d+):(\d+):(\d+)[,\.](\d+)", lines[1])
        if not m:
            continue
        t = int(m.group(1))*3600 + int(m.group(2))*60 + int(m.group(3)) + int(m.group(4))/1000
        if t > max_seconds:
            break
        text = " ".join(lines[2:])
        entries.append((t, text))
    return entries

def extract_facts(entries):
    """Devuelve lista de (start_sec, label) con los hechos clave"""
    facts = []
    last_t = -MIN_INTERVAL  # para garantizar espaciado mínimo

    for t, text in entries:
        if t - last_t < MIN_INTERVAL:
            continue
        for pat, fmt in FACT_PATTERNS:
            m = re.search(pat, text)
            if m:
                label = fmt(m)
                # Evitar duplicados muy similares
                if not any(abs(f[0] - t) < 5 and f[1] == label for f in facts):
                    facts.append((t, label))
                    last_t = t
                    break  # solo 1 hecho por bloque SRT
    return facts

def make_png(label: str, out_path: pathlib.Path, w=1920, h=1080):
    """Genera PNG RGBA con el texto del dato clave, estilo EpocaDeOro"""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))  # transparente
    draw = ImageDraw.Draw(img)

    # Intentar cargar fuente del sistema
    font_size = 42
    font_bold = 38
    try:
        font = ImageFont.truetype("/System/Library/Fonts/HelveticaNeue.ttc", font_size)
        font_b = ImageFont.truetype("/System/Library/Fonts/HelveticaNeue.ttc", font_bold)
    except Exception:
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", font_size)
            font_b = font
        except Exception:
            font = ImageFont.load_default()
            font_b = font

    # Línea dorada decorativa + texto
    text_upper = label.upper()
    bbox = draw.textbbox((0, 0), text_upper, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    pad_x, pad_y = 40, 20
    box_w = tw + pad_x * 2
    box_h = th + pad_y * 2 + 4  # 4 = línea dorada superior

    # Posición: esquina inferior izquierda (estilo lower-third)
    x0 = 80
    y0 = h - 180 - box_h

    # Fondo semitransparente
    draw.rectangle([x0, y0, x0 + box_w, y0 + box_h], fill=COLOR_BG)

    # Línea dorada superior del recuadro
    draw.rectangle([x0, y0, x0 + box_w, y0 + 4], fill=COLOR_GOLD)

    # Texto blanco
    draw.text((x0 + pad_x, y0 + pad_y + 4), text_upper, font=font, fill=COLOR_WHITE)

    img.save(out_path, "PNG")

def build_overlay(facts, out_path: pathlib.Path):
    """Aplica todos los PNGs como overlays sobre output.mp4 con ffmpeg filter_complex"""
    if not facts:
        print("No se encontraron hechos clave en el SRT")
        return False

    TMP.mkdir(parents=True, exist_ok=True)

    # Generar PNGs
    png_paths = []
    for i, (t, label) in enumerate(facts):
        p = TMP / f"fact_{i:02d}.png"
        make_png(label, p)
        png_paths.append((t, label, p))
        print(f"  t={t:.1f}s → {label}")

    # Construir comando ffmpeg con filter_complex
    # Usamos: -loop 1 -t DUR -i fact_N.png para cada PNG
    # Luego en filter_complex: overlay con enable='between(t,START,END)'
    cmd = [FFMPEG, "-y"]

    # Input 0: video fuente
    cmd += ["-i", str(SRC)]

    # Inputs 1..N: PNGs (no necesitan loop ya que usamos enable para el timing)
    for _, _, p in png_paths:
        cmd += ["-loop", "1", "-t", str(DISPLAY_DUR + 0.5), "-i", str(p)]

    # Construir filter_complex
    # Cada PNG se convierte a RGBA y se overlay en el tiempo correcto
    n = len(png_paths)
    fc_parts = []

    # Escalar fuente a 1920x1080 si hace falta
    fc_parts.append("[0:v]scale=1920:1080[base]")

    for i, (t, _, _) in enumerate(png_paths):
        t_end = t + DISPLAY_DUR
        input_ref = f"[{i+1}:v]"
        cur = f"[base{i}]" if i < n - 1 else "[vout]"
        prev = "[base]" if i == 0 else f"[base{i-1}]"

        # fade in/out suave: usamos el PNG sin fade primero (overlay directo)
        # enable para controlar cuándo aparece
        fc_parts.append(
            f"{prev}{input_ref}overlay=80:{1080-180-80}:enable='between(t,{t:.2f},{t_end:.2f})'{cur}"
        )

    fc = ";".join(fc_parts)
    cmd += ["-filter_complex", fc, "-map", "[vout]", "-map", "0:a",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
            "-pix_fmt", "yuv420p", "-c:a", "copy",
            "-movflags", "+faststart", str(out_path)]

    print(f"\nEjecutando ffmpeg ({n} overlays) — puede tardar varios minutos...")
    result = subprocess.run(cmd, capture_output=False, timeout=3600)
    if result.returncode != 0:
        print(f"\n✗ ffmpeg falló (código {result.returncode})")
        return False
    print(f"\n✓ Video listo: {out_path}")
    return True

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(BASE / "output_con_datos.mp4"))
    parser.add_argument("--preview", action="store_true", help="Solo mostrar hechos detectados, no renderizar")
    args = parser.parse_args()

    if not SRT.exists():
        print(f"✗ No existe: {SRT}")
        sys.exit(1)
    if not SRC.exists():
        print(f"✗ No existe: {SRC}")
        sys.exit(1)

    print("Parseando SRT (primeros 10 minutos)...")
    entries = parse_srt(SRT)
    print(f"  {len(entries)} bloques SRT en los primeros 10 min")

    facts = extract_facts(entries)
    print(f"\n{len(facts)} hechos clave detectados:")
    for t, label in facts:
        print(f"  t={t:6.1f}s → {label}")

    if args.preview or not facts:
        return

    out = pathlib.Path(args.out)
    build_overlay(facts, out)

if __name__ == "__main__":
    main()
