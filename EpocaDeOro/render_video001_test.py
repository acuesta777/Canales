#!/usr/bin/env python3
"""
render_video001_test.py — Renderiza prueba: HOOK + LUPE VÉLEZ con nombre animado.

Salida: Video-001/test_video001.mp4
"""

import sys, subprocess, pathlib, shutil, json

FFMPEG  = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"
W, H    = 1920, 1080
FPS     = 30

BASE    = pathlib.Path("/Users/anyelocuesta/Downloads/Canales/EpocaDeOro")
FOLDER  = BASE / "Video-001 Murieron en la Miseria"
TMP     = FOLDER / "_tmp_test"
TMP.mkdir(exist_ok=True)

AUDIO      = FOLDER / "audio.mp3"
HOOK_MP4   = BASE / "hook-motion/renders/hook_card_audio.mp4"
NOMBRE_WBM = BASE / "nombre-reveal/renders/nombre_reveal.webm"
OUT        = FOLDER / "test_video001.mp4"

ICLOUD = pathlib.Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Artistas"
FOTOS = sorted((FOLDER / "hook_fotos").glob("01_lupe_velez_*.jpg"))
CLIPS = sorted((ICLOUD / "Lupe Velez").glob("*.mp4"))

ARTISTA_START = 20.16   # inicio del segmento en el audio
ARTISTA_DUR   = 312.19  # duración del segmento Lupe Vélez

VERDE  = "\033[92m"; ROJO = "\033[91m"; RESET = "\033[0m"; NEGRITA = "\033[1m"

def run(cmd, timeout=600):
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if r.returncode != 0:
        print(f"{ROJO}ERROR: {r.stderr.decode()[-500:]}{RESET}")
        sys.exit(1)
    return r

def probe_dur(path):
    r = subprocess.run([FFPROBE,"-v","error","-show_entries","format=duration",
                        "-of","csv=p=0", str(path)], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)

print(f"\n{NEGRITA}{'='*60}")
print("  TEST RENDER — Hook + Lupe Vélez")
print(f"{'='*60}{RESET}\n")

# ─── VERIFICAR APROBACIÓN DEL DASHBOARD ──────────────────────────────────────
STATE_FILE = FOLDER / "dashboard_state.json"
if not STATE_FILE.exists():
    print(f"{ROJO}✗ No hay estado de dashboard. Lanza primero:{RESET}")
    print(f"  python3 EpocaDeOro/dashboard_epocadeoro.py \"{FOLDER}\"")
    sys.exit(1)

dashboard_state = json.loads(STATE_FILE.read_text())
if not dashboard_state.get("approved"):
    print(f"{ROJO}✗ Dashboard no aprobado. Abre http://localhost:5005 y aprueba los clips.{RESET}")
    sys.exit(1)

print(f"{VERDE}✓ Dashboard aprobado — usando clips seleccionados{RESET}\n")

# ─── PASO 1: Leer clips aprobados del estado del dashboard ───────────────────
# Solo clips para el cuerpo del artista (intercalar imágenes es solo del hook)
artist_state   = dashboard_state["artists"][0]  # Lupe Vélez
approved_clips = [pathlib.Path(c["path"]) for c in artist_state["clips"]]

plan = []
total = 0
clip_idx = 0

while total < ARTISTA_DUR:
    c   = approved_clips[clip_idx % len(approved_clips)]
    dur = min(5.0, ARTISTA_DUR - total)
    plan.append({"type": "clip", "src": c, "dur": dur})
    total += dur
    clip_idx += 1

print(f"Plan de segmentos ({len(plan)} bloques, {total:.1f}s):")
for i, b in enumerate(plan):
    print(f"  [{i+1}] {b['type']} {b['src'].name}  {b['dur']:.1f}s")
print()

# ─── PASO 2: Procesar cada bloque ────────────────────────────────────────────
segs = []
for i, b in enumerate(plan):
    out_seg = TMP / f"seg_{i:03d}.mp4"
    dur = b["dur"]

    if b["type"] == "clip":
        # Clip: hflip + crop reencuadre + B&W (fair use)
        vf = (f"hflip,"
              f"scale={int(W*1.1)}:{int(H*1.1)}:force_original_aspect_ratio=increase:flags=lanczos,"
              f"crop={W}:{H}:(iw-ow)/2:(ih-oh)/2,"
              f"hue=s=0,eq=contrast=1.05")
        cmd = [FFMPEG,"-y","-ss","0","-t",str(dur),"-i",str(b["src"]),
               "-vf",vf,"-t",str(dur),"-r",str(FPS),
               "-c:v","libx264","-preset","ultrafast","-crf","23","-an",
               "-pix_fmt","yuv420p", str(out_seg),"-loglevel","error"]
    else:
        # Foto: zoompan Ken Burns B&W
        frames = int(dur * FPS)
        vf = (f"scale={int(W*1.3)}:{int(H*1.3)}:flags=lanczos,"
              f"zoompan=z='min(zoom+0.0003\\,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              f":d={frames}:s={W}x{H}:fps={FPS},"
              f"hflip,hue=s=0,eq=contrast=1.08")
        cmd = [FFMPEG,"-y","-loop","1","-t",str(dur+0.5),"-i",str(b["src"]),
               "-vf",vf,"-t",str(dur),"-r",str(FPS),
               "-c:v","libx264","-preset","ultrafast","-crf","23","-an",
               "-pix_fmt","yuv420p", str(out_seg),"-loglevel","error"]

    print(f"  Procesando [{i+1}/{len(plan)}] {b['type']} {b['src'].name}...", end=" ", flush=True)
    run(cmd, timeout=300)
    print(f"{VERDE}✓{RESET}")
    segs.append(out_seg)

# ─── PASO 3: Concat cuerpo del artista ───────────────────────────────────────
print(f"\nConcatenando {len(segs)} segmentos...", end=" ", flush=True)
concat_txt = TMP / "concat.txt"
concat_txt.write_text("\n".join(f"file '{p.resolve()}'" for p in segs))
body_raw = TMP / "body_raw.mp4"
run([FFMPEG,"-y","-f","concat","-safe","0","-i",str(concat_txt),
     "-c:v","libx264","-preset","ultrafast","-crf","22",
     "-pix_fmt","yuv420p","-an",
     str(body_raw),"-loglevel","error"])
print(f"{VERDE}✓  {probe_dur(body_raw):.1f}s{RESET}")

# ─── PASO 4: Agregar audio del artista (offset 20.16s en audio.mp3) ──────────
print(f"Agregando audio (offset {ARTISTA_START}s)...", end=" ", flush=True)
body_audio = TMP / "body_audio.mp4"
run([FFMPEG,"-y",
     "-i", str(body_raw),
     "-ss", str(ARTISTA_START), "-t", str(ARTISTA_DUR), "-i", str(AUDIO),
     "-c:v","copy","-c:a","aac","-b:a","192k",
     "-shortest", str(body_audio),"-loglevel","error"])
print(f"{VERDE}✓{RESET}")

# ─── PASO 5: Nombre artista animado con Pillow — alpha real ──────────────────
print(f"Generando frames del nombre...", end=" ", flush=True)
from PIL import Image, ImageDraw, ImageFont
import math

FRAMES_DIR = TMP / "nombre_frames"
FRAMES_DIR.mkdir(exist_ok=True)
TOTAL_FRAMES = 90   # 3s × 30fps
FONT_PATH    = "/System/Library/Fonts/Supplemental/Arial Black.ttf"
NAME_TEXT    = "LUPE VÉLEZ"
GOLD         = (201, 162, 39)

try:
    font_name = ImageFont.truetype(FONT_PATH, 72)
except:
    font_name = ImageFont.load_default()

def ease_out(t): return 1 - (1-t)**3
def ease_in(t):  return t**3

for f in range(TOTAL_FRAMES):
    t = f / 30.0  # segundos
    img = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)

    # Fade in 0→0.5s, hold 0.5→2.5s, fade out 2.5→3.0s
    if t < 0.5:
        alpha = ease_out(t / 0.5)
    elif t < 2.5:
        alpha = 1.0
    else:
        alpha = ease_in((3.0 - t) / 0.5)
    a = int(alpha * 255)

    # Gradiente oscuro en la parte inferior
    grad_h = 220
    for y in range(grad_h):
        frac = 1 - y / grad_h
        ga   = int(a * 0.85 * frac)
        d.line([(0, 1080 - grad_h + y), (1920, 1080 - grad_h + y)],
               fill=(0, 0, 0, ga))

    # Slide-up del nombre: entra desde abajo
    slide = 0 if t > 0.3 else int((1 - ease_out(t/0.3)) * 40)
    y_nombre = 1080 - 160 + slide

    # Línea dorada superior
    if t > 0.05:
        line_prog = min(1.0, (t - 0.05) / 0.45)
        line_w    = int(ease_out(line_prog) * 480)
        d.rectangle([(76, 1080 - 148), (76 + line_w, 1080 - 145)],
                    fill=(*GOLD, a))

    # Nombre principal
    d.text((76, y_nombre), NAME_TEXT, font=font_name,
           fill=(255, 255, 255, a),
           stroke_width=2, stroke_fill=(0, 0, 0, a))

    # Línea dorada inferior
    if t > 0.55:
        lp2 = min(1.0, (t - 0.55) / 0.4)
        lw2 = int(ease_out(lp2) * 360)
        d.rectangle([(76, 1080 - 62), (76 + lw2, 1080 - 60)],
                    fill=(*GOLD, int(a * 0.5)))

    img.save(str(FRAMES_DIR / f"frame_{f:04d}.png"))

print(f"{VERDE}✓ {TOTAL_FRAMES} frames{RESET}")

# Convertir frames a video con alpha
nombre_alpha = TMP / "nombre_alpha.mov"
run([FFMPEG,"-y","-framerate","30",
     "-i", str(FRAMES_DIR / "frame_%04d.png"),
     "-c:v","qtrle","-pix_fmt","argb",
     str(nombre_alpha),"-loglevel","error"])

# Overlay sobre el cuerpo del artista
print(f"Overlay nombre artista...", end=" ", flush=True)
body_nombre = TMP / "body_nombre.mp4"
run([FFMPEG,"-y",
     "-i", str(body_audio),
     "-i", str(nombre_alpha),
     "-filter_complex",
     "[0:v][1:v]overlay=0:0:enable='between(t,0,3)':format=auto[v]",
     "-map","[v]","-map","0:a",
     "-c:v","libx264","-preset","ultrafast","-crf","20",
     "-c:a","copy","-pix_fmt","yuv420p",
     str(body_nombre),"-loglevel","error"],
    timeout=600)
print(f"{VERDE}✓{RESET}")

# ─── PASO 6: Concat hook + cuerpo ────────────────────────────────────────────
print(f"Concatenando hook + artista...", end=" ", flush=True)
final_concat = TMP / "final_concat.txt"
final_concat.write_text(
    f"file '{HOOK_MP4.resolve()}'\n"
    f"file '{body_nombre.resolve()}'\n"
)
run([FFMPEG,"-y",
     "-f","concat","-safe","0","-i",str(final_concat),
     "-c:v","libx264","-preset","medium","-crf","20",
     "-c:a","aac","-b:a","192k",
     "-pix_fmt","yuv420p","-movflags","+faststart",
     str(OUT),"-loglevel","error"],
    timeout=600)
print(f"{VERDE}✓{RESET}")

# ─── RESULTADO ────────────────────────────────────────────────────────────────
shutil.rmtree(TMP, ignore_errors=True)
dur_f  = probe_dur(OUT)
size   = OUT.stat().st_size / 1024 / 1024
print(f"\n{NEGRITA}{VERDE}{'='*60}")
print(f"  ✓  test_video001.mp4")
print(f"  Duración: {dur_f:.1f}s  |  Tamaño: {size:.1f} MB")
print(f"  {OUT}")
print(f"{'='*60}{RESET}\n")
