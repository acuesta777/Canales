#!/usr/bin/env python3
"""
render_hook_epocadeoro.py — Renderiza el hook visual de La Verdad Dorada.

Por cada artista en hook_timeline.json:
  - Fondo cuadrícula oscura animada (Ken Burns lento sobre grid)
  - Foto o clip del artista en B&W (hflip + reframe fair-use)
  - Placa dorada con nombre del artista generada con Pillow (fade-in)

Salida: hook_render.mp4 (sin audio)

Uso:
  python3 render_hook_epocadeoro.py "Video-001/"
"""

import sys, json, pathlib, subprocess, shutil, random
from PIL import Image, ImageDraw, ImageFont

FFMPEG  = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"

W, H   = 1920, 1080
FPS    = 30

# Brandkit
BG_HEX    = (13, 13, 13)        # #0D0D0D
GRID_HEX  = (42, 42, 42)        # #2A2A2A
GOLD_HEX  = (201, 162, 39)      # #C9A227
WHITE     = (255, 255, 255)

FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

VERDE    = "\033[92m"
ROJO     = "\033[91m"
AMARILLO = "\033[93m"
NEGRITA  = "\033[1m"
RESET    = "\033[0m"


def get_duration(path):
    r = subprocess.run([
        FFPROBE, "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(path)
    ], capture_output=True, text=True, timeout=30)
    raw = r.stdout.strip()
    return float(raw) if raw else 0.0


def generar_placa(nombre, out_png):
    """Genera PNG de la placa dorada con el nombre del artista (1920x200, fondo transparente)."""
    placa_w, placa_h = 700, 90
    img = Image.new("RGBA", (placa_w, placa_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Caja dorada
    draw.rectangle([0, 0, placa_w, placa_h], fill=(*GOLD_HEX, 242))
    # Borde blanco
    draw.rectangle([0, 0, placa_w - 1, placa_h - 1], outline=(*WHITE, 100), width=2)

    # Texto centrado
    try:
        font = ImageFont.truetype(FONT_PATH, 42)
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), nombre, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (placa_w - tw) // 2
    ty = (placa_h - th) // 2 - bbox[1]
    draw.text((tx, ty), nombre, fill=(*WHITE, 255), font=font)

    # Guardar en 1920x1080 con padding (placa centrada horizontalmente en y=810)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    px = (W - placa_w) // 2
    py = 810
    canvas.paste(img, (px, py))
    canvas.save(str(out_png))
    return out_png


def render_segmento(seg, fotos_dir, clips_dir, tmp_dir):
    idx    = seg["idx"]
    dur    = seg["dur"]
    nombre = seg["nombre"]

    # ── Seleccionar media ────────────────────────────────────────────────────
    media_clips = sorted(clips_dir.glob(f"{idx:02d}_*.mp4"))
    media_fotos = sorted(fotos_dir.glob(f"{idx:02d}_*.jpg"))

    usar_clip = len(media_clips) > 0
    if usar_clip:
        media_src = media_clips[0]
        src_dur   = get_duration(media_src)
        offset    = random.uniform(0, max(0, src_dur - dur - 2)) if src_dur > dur + 3 else 0
        speed     = random.choice([0.98, 1.02])
        # crop desplazado para reencuadre (fair use)
        cx_off = random.randint(-80, 80)
        cy_off = random.randint(-40, 40)
        vf_media = (
            f"setpts={1/speed:.4f}*PTS,"
            f"scale={int(W*1.18)}:{int(H*1.18)}:flags=lanczos,"
            f"crop={W}:{H}:(iw-ow)/2+{cx_off}:(ih-oh)/2+{cy_off},"
            f"hflip,"
            f"hue=s=0"
        )
        input_args = ["-ss", str(round(offset, 2)), "-t", str(dur + 0.5), "-i", str(media_src)]
    else:
        if not media_fotos:
            print(f"  {ROJO}✗ Sin media para [{idx}] {nombre}{RESET}")
            return None
        media_src = media_fotos[0]
        dur_frames = int(dur * FPS)
        # Ken Burns lento + hflip + B&W
        vf_media = (
            f"scale={int(W*1.3)}:{int(H*1.3)}:flags=lanczos,"
            f"zoompan=z='min(zoom+0.0002\\,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={dur_frames}:s={W}x{H}:fps={FPS},"
            f"hflip,"
            f"hue=s=0"
        )
        input_args = ["-loop", "1", "-t", str(dur + 0.5), "-i", str(media_src)]

    # Paso 1: normalizar media
    tmp_media = tmp_dir / f"media_{idx:02d}.mp4"
    cmd_media = [
        FFMPEG, "-y",
        *input_args,
        "-vf", vf_media,
        "-t", str(dur),
        "-r", str(FPS),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
        "-an", "-pix_fmt", "yuv420p",
        str(tmp_media), "-loglevel", "error"
    ]
    r = subprocess.run(cmd_media, timeout=300, capture_output=True)
    if r.returncode != 0:
        print(f"  {ROJO}✗ media: {r.stderr.decode()[-300:]}{RESET}")
        return None

    # Paso 2: generar placa PNG
    placa_png = tmp_dir / f"placa_{idx:02d}.png"
    generar_placa(nombre, placa_png)

    # Paso 3: componer grid + media + placa con fade-in de placa
    # Grid animado: desplazamiento de 8px/s (efecto parallax sutil)
    # Implementado como color+drawgrid con offset en función de t
    GRID_SIZE = 60
    dur_frames = int(dur * FPS)
    fade_out_start = max(0, dur - 0.35)

    tmp_seg = tmp_dir / f"seg_{idx:02d}.mp4"

    # Filtro grid: fondo oscuro + drawgrid
    grid_vf = (
        f"color=c=0x0D0D0D:s={W}x{H}:r={FPS},"
        f"drawgrid=width={GRID_SIZE}:height=0:thickness=1:color=0x2A2A2A@0.7,"
        f"drawgrid=width=0:height={GRID_SIZE}:thickness=1:color=0x2A2A2A@0.7"
    )

    # Placa con fade-in: alpha sube de 0→1 entre t=0.7 y t=1.2s
    # Usamos overlay con enable y el alpha de la imagen PNG
    filter_complex = (
        # 0: grid bg | 1: media B&W | 2: placa PNG
        f"[0:v][1:v]overlay=(W-w)/2:(H-h)/2:format=auto,"
        f"fade=in:st=0:d=0.4,"
        f"fade=out:st={fade_out_start:.2f}:d=0.35[base];"
        f"[2:v]fade=in:st=0.7:d=0.5:alpha=1[placa];"
        f"[base][placa]overlay=0:0:format=auto[out]"
    )

    cmd_seg = [
        FFMPEG, "-y",
        "-f", "lavfi", "-i", grid_vf,
        "-i", str(tmp_media),
        "-i", str(placa_png),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-t", str(dur),
        "-r", str(FPS),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
        "-an", "-pix_fmt", "yuv420p",
        str(tmp_seg), "-loglevel", "error"
    ]
    r = subprocess.run(cmd_seg, timeout=300, capture_output=True)
    if r.returncode != 0:
        print(f"  {ROJO}✗ composición: {r.stderr.decode()[-400:]}{RESET}")
        return None

    tmp_media.unlink(missing_ok=True)
    return tmp_seg


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)

    folder = pathlib.Path(sys.argv[1])
    tl_path = folder / "hook_timeline.json"

    if not tl_path.exists():
        sys.exit("[ERROR] No existe hook_timeline.json")

    tl       = json.loads(tl_path.read_text(encoding="utf-8"))
    fotos    = folder / "hook_fotos"
    clips    = folder / "hook_clips"
    out_mp4  = folder / "hook_render.mp4"
    tmp_dir  = folder / "_tmp_hook"
    tmp_dir.mkdir(exist_ok=True)

    print(f"\n{NEGRITA}{'='*58}")
    print(f"  RENDER HOOK — La Verdad Dorada")
    print(f"  {len(tl['segments'])} segmento(s) | {tl['hook_dur']:.1f}s total")
    print(f"{'='*58}{RESET}\n")

    seg_paths = []
    for seg in tl["segments"]:
        print(f"{NEGRITA}[{seg['idx']:02d}] {seg['nombre']} ({seg['dur']:.1f}s){RESET}")
        path = render_segmento(seg, fotos, clips, tmp_dir)
        if path:
            seg_paths.append(path)
            print(f"  {VERDE}✓ {path.name}{RESET}")
        else:
            print(f"  {ROJO}✗ Falló{RESET}")
        print()

    if not seg_paths:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        sys.exit(f"{ROJO}✗ Ningún segmento generado{RESET}")

    # Concatenar
    if len(seg_paths) == 1:
        shutil.copy(seg_paths[0], out_mp4)
    else:
        concat_txt = tmp_dir / "concat.txt"
        concat_txt.write_text(
            "\n".join(f"file '{p.resolve()}'" for p in seg_paths),
            encoding="utf-8"
        )
        cmd_cat = [
            FFMPEG, "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_txt),
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-an",
            str(out_mp4), "-loglevel", "error"
        ]
        r = subprocess.run(cmd_cat, timeout=120, capture_output=True)
        if r.returncode != 0:
            sys.exit(f"{ROJO}✗ Concat: {r.stderr.decode()[-300:]}{RESET}")

    shutil.rmtree(tmp_dir, ignore_errors=True)

    dur_f   = get_duration(out_mp4)
    size_mb = out_mp4.stat().st_size / 1024 / 1024
    print(f"{NEGRITA}{VERDE}{'='*58}")
    print(f"  ✓ hook_render.mp4  {dur_f:.1f}s  {size_mb:.1f} MB")
    print(f"  {out_mp4}")
    print(f"{'='*58}{RESET}")


if __name__ == "__main__":
    main()
