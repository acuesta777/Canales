#!/usr/bin/env python3
"""
animar_clips.py — Convierte imágenes de la carpeta imagenes/ a MP4
con efecto zoom/pan (Ken Burns) usando ffmpeg.

Uso: python3 animar_clips.py /ruta/carpeta/personaje/

Coloca las imágenes en imagenes/ con cualquier nombre (.jpg .png .webp).
Las ordena alfabéticamente y genera 1.mp4, 2.mp4, 3.mp4, 4.mp4
"""

import sys, pathlib, subprocess, time

FFMPEG     = "/opt/homebrew/bin/ffmpeg"
if not pathlib.Path(FFMPEG).exists():
    FFMPEG = "/usr/local/bin/ffmpeg"

CLIP_SECS  = 6    # duración de cada clip
EXTS       = {".jpg", ".jpeg", ".png", ".webp"}

# Filtro vintage: desatura, calienta tonos, agrega grano de película
VINTAGE = (
    ",eq=saturation=0.50:contrast=1.08:brightness=-0.02"
    ",colorchannelmixer=rr=1.0:rg=0.04:rb=0:ra=0:gr=0:gg=0.90:gb=0:ga=0:br=0:bg=0:bb=0.78:ba=0"
    ",noise=alls=16:allf=t+u"
)

# Filtro B&W: blanco y negro con grano fuerte, para personajes de época clásica (antes de 1940)
BW = (
    ",hue=s=0"
    ",eq=contrast=1.15:brightness=-0.03"
    ",noise=alls=22:allf=t+u"
    ",curves=all='0/0 0.3/0.25 0.7/0.72 1/1'"
)

VERDE    = "\033[92m"
ROJO     = "\033[91m"
AMARILLO = "\033[93m"
RESET    = "\033[0m"

def ok(msg):   print(f"  {VERDE}✓{RESET} {msg}")
def err(msg):  print(f"  {ROJO}✗{RESET} {msg}")
def info(msg): print(f"  {AMARILLO}→{RESET} {msg}")

# Efectos distintos para que no todos los clips sean idénticos
# crop=16:9 primero para corregir imágenes cuadradas (API devuelve 1024x1024)
_CROP = "crop=iw:iw*9/16:0:(ih-iw*9/16)/2,"
# z=1.5 FIJO — pan correcto (~16.7% frame) — NUNCA incremental desde 1.0
EFFECTS = [
    _CROP + "scale=3840:2160,zoompan=z='1.5':x='(iw-iw/1.5)*0.5*(on/{d})':y='ih/2-(ih/1.5/2)':d={d}:s=1920x1080:fps=30,scale=1920:1080",
    _CROP + "scale=3840:2160,zoompan=z='1.5':x='(iw-iw/1.5)*0.5*(1-on/{d})':y='ih/2-(ih/1.5/2)':d={d}:s=1920x1080:fps=30,scale=1920:1080",
    _CROP + "scale=3840:2160,zoompan=z='1.5':x='iw/2-(iw/1.5/2)':y='(ih-ih/1.5)*0.5*(on/{d})':d={d}:s=1920x1080:fps=30,scale=1920:1080",
    _CROP + "scale=3840:2160,zoompan=z='1.5':x='(iw-iw/1.5)*0.5*(on/{d})':y='(ih-ih/1.5)*0.5*(on/{d})':d={d}:s=1920x1080:fps=30,scale=1920:1080",
]

def convertir(img_path, out_mp4, effect_idx, vintage=False, bw=False):
    frames = CLIP_SECS * 30
    vf = EFFECTS[effect_idx % len(EFFECTS)].format(d=frames)
    if bw:
        vf += BW
    elif vintage:
        vf += VINTAGE
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-loop", "1", "-framerate", "30",
        "-i", str(img_path),
        "-vf", vf,
        "-t", str(CLIP_SECS),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-an",
        "-y", str(out_mp4)
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode()[:300])

def main():
    args = sys.argv[1:]
    vintage = "--vintage" in args
    bw      = "--bw" in args
    args    = [a for a in args if a not in ("--vintage", "--bw")]

    if not args:
        print("Uso: python3 animar_clips.py /ruta/carpeta/personaje/ [--vintage]")
        sys.exit(1)

    char_folder = pathlib.Path(args[0])
    img_folder  = char_folder / "imagenes"

    if not img_folder.exists():
        err(f"No existe carpeta: {img_folder}")
        sys.exit(1)

    # Buscar imágenes ordenadas alfabéticamente
    imagenes = sorted([f for f in img_folder.iterdir() if f.suffix.lower() in EXTS])

    if not imagenes:
        err(f"No hay imágenes (.jpg .png .webp) en {img_folder}")
        sys.exit(1)

    print(f"\n{'='*55}")
    print(f"  ANIMAR CLIPS — {char_folder.name.upper()}")
    print(f"  {len(imagenes)} imagen(es) → MP4 zoom/pan ({CLIP_SECS}s c/u)")
    if bw:
        print(f"  Filtro: B&W (blanco y negro + grano clásico)")
    elif vintage:
        print(f"  Filtro: VINTAGE (desaturado + sepia + grano)")
    print(f"{'='*55}\n")

    t_inicio = time.time()
    ok_count = 0

    for i, img in enumerate(imagenes, 1):
        out_mp4 = img_folder / f"{i}.mp4"
        info(f"[{i}/{len(imagenes)}] {img.name} → {out_mp4.name}")
        t0 = time.time()
        try:
            convertir(img, out_mp4, effect_idx=i-1, vintage=vintage, bw=bw)
            dur = time.time() - t0
            ok(f"Listo en {dur:.1f}s — {out_mp4.stat().st_size // 1024} KB")
            ok_count += 1
        except Exception as e:
            err(f"Error: {e}")

    total = int(time.time() - t_inicio)
    print(f"\n{'='*55}")
    print(f"  {VERDE if ok_count == len(imagenes) else ROJO}"
          f"{ok_count}/{len(imagenes)} clips generados en {total}s{RESET}")
    print(f"{'='*55}\n")

    if ok_count == 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
