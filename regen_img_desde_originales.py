#!/usr/bin/env python3
"""
regen_img_desde_originales.py — Convierte imágenes originales a zoompan con fondo negro.
Naming estable con MD5. Maneja jpg/jpeg/png/webp/avif via Pillow fallback.
"""
import subprocess, pathlib, sys, concurrent.futures, hashlib, io, time

FFMPEG   = "/opt/homebrew/bin/ffmpeg"
FFPROBE  = "/opt/homebrew/bin/ffprobe"
SRC_DIR  = pathlib.Path("/Users/anyelocuesta/Downloads/veo-folder-1")
DST_DIR  = pathlib.Path("familias/bailleres/clips")
WORKERS  = 4
DUR      = 4.0
FPS      = 30
FRAMES   = int(DUR * FPS)  # 120
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.avif'}

ZOOMPAN_MOVES = [
    ("zoom_in_center", "min(zoom+0.0015,1.4)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    ("pan_lr",  "1.4", f"iw*0.04*(on/{FRAMES})",       "ih/2-(ih/zoom/2)"),
    ("pan_rl",  "1.4", f"iw*0.04*(1-on/{FRAMES})",     "ih/2-(ih/zoom/2)"),
    ("pan_tb",  "1.4", "iw/2-(iw/zoom/2)",              f"ih*0.04*(on/{FRAMES})"),
    ("pan_bt",  "1.4", "iw/2-(iw/zoom/2)",              f"ih*0.04*(1-on/{FRAMES})"),
    ("ken_tl",  "min(zoom+0.0013,1.4)", f"iw*0.02*(1-on/{FRAMES})",                  f"ih*0.02*(1-on/{FRAMES})"),
    ("ken_br",  "min(zoom+0.0013,1.4)", f"iw/2-(iw/zoom/2)+iw*0.02*(on/{FRAMES})",  f"ih/2-(ih/zoom/2)+ih*0.02*(on/{FRAMES})"),
]

def stable_id(path):
    """MD5 del nombre de archivo — determinístico entre runs."""
    return hashlib.md5(path.name.encode()).hexdigest()[:8]

def to_jpg(src):
    """Convierte avif/webp a JPG temporal via Pillow. Retorna Path o None."""
    try:
        from PIL import Image
        img = Image.open(src).convert("RGB")
        tmp = pathlib.Path(f"/tmp/regen_{stable_id(src)}.jpg")
        img.save(str(tmp), "JPEG", quality=95)
        return tmp
    except Exception as e:
        print(f"    ✗ Pillow fallo {src.name}: {e}")
        return None

def get_dims_ffprobe(path):
    try:
        r = subprocess.run(
            [FFPROBE, "-v","error","-select_streams","v:0",
             "-show_entries","stream=width,height","-of","csv=p=0", str(path)],
            capture_output=True, text=True, timeout=15)
        parts = r.stdout.strip().split(",")
        return int(parts[0]), int(parts[1])
    except Exception:
        return 0, 0

def get_dims(src):
    w, h = get_dims_ffprobe(src)
    if w > 0:
        return w, h
    # Fallback PIL
    try:
        from PIL import Image
        img = Image.open(src)
        return img.size  # (w, h)
    except Exception:
        return 0, 0

def make_zoompan(src, dst_mp4, move_idx):
    w, h = get_dims(src)
    if w == 0 or h == 0:
        return False

    _, z, x, y = ZOOMPAN_MOVES[move_idx % len(ZOOMPAN_MOVES)]
    ratio  = w / h if h > 0 else 0
    is_16_9 = abs(ratio - (16 / 9)) < 0.15

    if is_16_9:
        zp = f"zoompan=z='{z}':x='{x}':y='{y}':d={FRAMES}:s=1920x1080:fps={FPS}"
        vf = f"scale=8000:-1,{zp}"
    else:
        # Fondo NEGRO — centrar con barras, no estirar
        zp_safe = (f"zoompan=z='min(zoom+0.0005,1.08)'"
                   f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                   f":d={FRAMES}:s=1920x1080:fps={FPS}")
        vf = (f"scale=1920:1080:force_original_aspect_ratio=decrease,"
              f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,setsar=1:1,{zp_safe}")

    cmd = [FFMPEG, "-y", "-loop", "1", "-i", str(src), "-vf", vf,
           "-t", str(DUR), "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
           "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", str(dst_mp4)]
    r = subprocess.run(cmd, capture_output=True, timeout=90)
    return dst_mp4.exists() and dst_mp4.stat().st_size > 50_000

def process(args):
    src, dst, move_idx = args
    tmp_jpg = None
    work_src = src

    # avif/webp pueden fallar en ffmpeg — convertir via Pillow
    if src.suffix.lower() in ('.avif', '.webp'):
        tmp_jpg = to_jpg(src)
        if tmp_jpg:
            work_src = tmp_jpg

    ok = make_zoompan(work_src, dst, move_idx)

    if tmp_jpg and tmp_jpg.exists():
        tmp_jpg.unlink(missing_ok=True)

    return src.name, dst.name, ok

def main():
    DST_DIR.mkdir(parents=True, exist_ok=True)
    sources = sorted([f for f in SRC_DIR.iterdir() if f.suffix.lower() in IMAGE_EXTS])

    print(f"\n{'═'*58}")
    print(f"  REGEN IMG → zoompan 4s fondo negro")
    print(f"  {len(sources)} imágenes · {WORKERS} workers")
    print(f"{'═'*58}\n")

    tasks = []
    for i, src in enumerate(sources):
        sid  = stable_id(src)
        dst  = DST_DIR / f"img_{sid}_zp.mp4"
        tasks.append((src, dst, i))

    ok_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for src_name, dst_name, ok in ex.map(process, tasks):
            status = "✓" if ok else "✗"
            print(f"  {status} {src_name[:50]:50s} → {dst_name}")
            if ok:
                ok_count += 1

    print(f"\n  {'✅' if ok_count==len(tasks) else '⚠'} {ok_count}/{len(tasks)} convertidas")
    print(f"  Clips en: {DST_DIR}\n")

if __name__ == "__main__":
    main()
