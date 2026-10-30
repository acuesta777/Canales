#!/usr/bin/env python3
"""
regen_zoompan_bailleres.py — Regenera TODOS los _zp.mp4 de bailleres a 4s con fondo negro
para imágenes no-16:9 (en vez de 7.5s estirado).

Flow: usa frame del _preview.mp4
Img:  usa frame del _zp.mp4 actual (único source disponible)
"""
import subprocess, pathlib, sys, concurrent.futures, tempfile, shutil

FFMPEG   = "/opt/homebrew/bin/ffmpeg"
CARPETA  = pathlib.Path("familias/bailleres")
IMG_DIR  = CARPETA / "03-imagenes"
CLIPS    = CARPETA / "clips"
WORKERS  = 4
DUR      = 4.0
FPS      = 30
FRAMES   = int(DUR * FPS)   # 120

ZOOMPAN_MOVES = [
    ("zoom_in_center", "min(zoom+0.0015,1.4)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    ("pan_lr",  "1.4", "iw*0.04*(on/120)",       "ih/2-(ih/zoom/2)"),
    ("pan_rl",  "1.4", "iw*0.04*(1-on/120)",     "ih/2-(ih/zoom/2)"),
    ("pan_tb",  "1.4", "iw/2-(iw/zoom/2)",        "ih*0.04*(on/120)"),
    ("pan_bt",  "1.4", "iw/2-(iw/zoom/2)",        "ih*0.04*(1-on/120)"),
    ("ken_tl",  "min(zoom+0.0013,1.4)", "iw*0.02*(1-on/120)",                  "ih*0.02*(1-on/120)"),
    ("ken_br",  "min(zoom+0.0013,1.4)", "iw/2-(iw/zoom/2)+iw*0.02*(on/120)",  "ih/2-(ih/zoom/2)+ih*0.02*(on/120)"),
]

def get_dims(path):
    try:
        r = subprocess.run(
            [FFMPEG.replace("ffmpeg","ffprobe"), "-v","error","-select_streams","v:0",
             "-show_entries","stream=width,height","-of","csv=p=0", str(path)],
            capture_output=True, text=True, timeout=10)
        w, h = r.stdout.strip().split(",")
        return int(w), int(h)
    except Exception:
        return 0, 0

def extract_frame(src_video, out_jpg):
    """Extrae frame 1 de un video como JPEG."""
    subprocess.run(
        [FFMPEG, "-y", "-ss", "0.1", "-i", str(src_video),
         "-vframes", "1", "-q:v", "2", str(out_jpg)],
        capture_output=True, timeout=30)
    return out_jpg.exists() and out_jpg.stat().st_size > 1000

def make_zoompan(src_jpg, dst_mp4, move_idx):
    """Aplica zoompan 4s con fondo negro para no-16:9."""
    w, h = get_dims(src_jpg)
    if w == 0 or h == 0:
        return False

    _, z, x, y = ZOOMPAN_MOVES[move_idx % len(ZOOMPAN_MOVES)]
    is_16_9 = abs((w / h) - (16 / 9)) < 0.15

    if is_16_9:
        zp = f"zoompan=z='{z}':x='{x}':y='{y}':d={FRAMES}:s=1920x1080:fps={FPS}"
        vf = f"scale=8000:-1,{zp}"
    else:
        # Fondo negro — NO estirar, centrar y zoom suave
        zp_safe = (f"zoompan=z='min(zoom+0.0005,1.08)'"
                   f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                   f":d={FRAMES}:s=1920x1080:fps={FPS}")
        vf = (f"scale=1920:1080:force_original_aspect_ratio=decrease,"
              f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,setsar=1:1,{zp_safe}")

    cmd = [FFMPEG, "-y", "-loop", "1", "-i", str(src_jpg), "-vf", vf,
           "-t", str(DUR), "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
           "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", str(dst_mp4)]
    r = subprocess.run(cmd, capture_output=True, timeout=60)
    return dst_mp4.exists() and dst_mp4.stat().st_size > 50_000

def process_flow(args):
    seg_id, move_idx, preview_mp4, zp_mp4 = args
    with tempfile.TemporaryDirectory() as tmp:
        frame = pathlib.Path(tmp) / f"flow_{seg_id:04d}.jpg"
        if not extract_frame(preview_mp4, frame):
            return seg_id, False, "frame_fail"
        tmp_zp = pathlib.Path(tmp) / "out.mp4"
        if not make_zoompan(frame, tmp_zp, move_idx):
            return seg_id, False, "zp_fail"
        # Backup y reemplazar
        if zp_mp4.exists():
            zp_mp4.rename(str(zp_mp4) + ".bak_regen")
        shutil.copy2(str(tmp_zp), str(zp_mp4))
    return seg_id, True, "ok"

def process_img(args):
    name, move_idx, old_zp, new_zp_path = args
    with tempfile.TemporaryDirectory() as tmp:
        frame = pathlib.Path(tmp) / "frame.jpg"
        if not extract_frame(old_zp, frame):
            return name, False, "frame_fail"
        tmp_zp = pathlib.Path(tmp) / "out.mp4"
        if not make_zoompan(frame, tmp_zp, move_idx):
            return name, False, "zp_fail"
        # Backup y reemplazar
        old_zp.rename(str(old_zp) + ".bak_regen")
        shutil.copy2(str(tmp_zp), str(new_zp_path))
    return name, True, "ok"

def main():
    print(f"\n{'═'*60}")
    print(f"  REGEN ZOOMPAN 4s — bailleres")
    print(f"{'═'*60}\n")

    # ── FLOW clips ──────────────────────────────────────────────
    flow_tasks = []
    previews = sorted(IMG_DIR.glob("flow_*_preview.mp4"))
    print(f"  Flow previews encontrados: {len(previews)}")
    for i, preview in enumerate(previews):
        seg_id = int(preview.name.split("_")[1])
        zp = IMG_DIR / f"flow_{seg_id:04d}_zp.mp4"
        if zp.exists():
            flow_tasks.append((seg_id, i, preview, zp))

    print(f"  Regenerando {len(flow_tasks)} flow_*_zp.mp4...")
    ok_flow = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for seg_id, success, reason in ex.map(process_flow, flow_tasks):
            if success:
                ok_flow += 1
                print(f"    ✓ flow_{seg_id:04d}_zp.mp4")
            else:
                print(f"    ✗ flow_{seg_id:04d}: {reason}")
    print(f"\n  Flow: {ok_flow}/{len(flow_tasks)} OK\n")

    # ── IMG clips ───────────────────────────────────────────────
    img_zps = sorted(CLIPS.glob("img_*_zp.mp4"))
    print(f"  Img clips encontrados: {len(img_zps)}")
    img_tasks = [(zp.name, i, zp, zp) for i, zp in enumerate(img_zps)]

    print(f"  Regenerando {len(img_tasks)} img_*_zp.mp4...")
    ok_img = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for name, success, reason in ex.map(process_img, img_tasks):
            if success:
                ok_img += 1
                print(f"    ✓ {name}")
            else:
                print(f"    ✗ {name}: {reason}")

    print(f"\n  Img: {ok_img}/{len(img_tasks)} OK")
    print(f"\n{'═'*60}")
    print(f"  ✅ LISTO — re-corre el render para usar los nuevos clips")
    print(f"{'═'*60}\n")

if __name__ == "__main__":
    main()
