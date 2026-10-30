#!/usr/bin/env python3
"""
Regenera los clips zoompan de Flow con duración exacta del timeline.
Cada clip dura exactamente end_seconds - start_seconds del timeline,
y el zoom va de 1.0x a 1.4x proporcionalmente a la duración del clip.
"""
import json, subprocess, pathlib, sys

FFMPEG = "/opt/homebrew/bin/ffmpeg"
FPS    = 30
ZOOM_START = 1.0
ZOOM_END   = 1.4

def run(cmd):
    subprocess.run(cmd, check=True)

def regen_clips(personaje_dir: pathlib.Path, config_path: pathlib.Path):
    timeline_f = personaje_dir / "05-montaje" / "timeline.json"
    img_dir    = personaje_dir / "03-imagenes"
    frames_dir = img_dir / "_frames"

    data     = json.loads(timeline_f.read_text(encoding="utf-8"))
    segments = data.get("visual_timeline", [])

    config = json.loads(config_path.read_text(encoding="utf-8"))
    zp_cfg = config.get("harvester", {}).get("zoompan", {})
    scale_target  = zp_cfg.get("scale_target", "3840:2160")
    output_res    = zp_cfg.get("output_res", "1920x1080")
    preview_res   = zp_cfg.get("preview_res", "640:360")
    era_filter    = zp_cfg.get("era_filter", False)

    for seg in segments:
        seg_id    = seg.get("segment_id")
        start_s   = seg.get("start_seconds", 0)
        end_s     = seg.get("end_seconds", start_s + 6)
        duration  = round(end_s - start_s, 3)
        era       = seg.get("era", "color")

        frame_jpg = frames_dir / f"flow_{seg_id:03d}.jpg"
        zp_out    = img_dir / f"flow_{seg_id:03d}_zp.mp4"
        preview   = img_dir / f"flow_{seg_id:03d}_preview.mp4"

        if not frame_jpg.exists():
            # Extraer frame del mp4 original
            src_mp4 = img_dir / f"flow_{seg_id:03d}.mp4"
            if not src_mp4.exists():
                print(f"  [SKIP] No existe {src_mp4.name}")
                continue
            frames_dir.mkdir(exist_ok=True)
            print(f"  Extrayendo frame: flow_{seg_id:03d}.jpg")
            run([FFMPEG, "-y", "-i", str(src_mp4),
                 "-frames:v", "1", "-q:v", "2", str(frame_jpg)])

        total_frames = int(duration * FPS)
        if total_frames < 1:
            total_frames = 1
        zoom_rate = (ZOOM_END - ZOOM_START) / total_frames

        # Filtro de época
        era_vf = ""
        if era_filter:
            if era == "bw":
                era_vf = ",hue=s=0,curves=all='0/0 0.4/0.6 1/1',eq=contrast=1.1"
            elif era == "vintage":
                era_vf = ",curves=r='0/0 0.5/0.55 1/0.9':g='0/0 0.5/0.5 1/0.85':b='0/0 0.5/0.45 1/0.75',eq=saturation=0.7:contrast=1.05"

        vf = (
            f"scale={scale_target},"
            f"zoompan=z='min({ZOOM_START}+on*{zoom_rate:.6f},{ZOOM_END})':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={total_frames}:s={output_res}:fps={FPS},"
            f"scale={output_res.replace('x',':')}"
            + era_vf
        )

        print(f"  [{seg_id:02d}] {duration:.1f}s | zoom_rate={zoom_rate:.6f} | era={era}")
        run([
            FFMPEG, "-y", "-loop", "1", "-i", str(frame_jpg),
            "-t", str(duration),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-r", str(FPS), "-an", str(zp_out)
        ])

        # Preview 640x360
        w, h = preview_res.split(":")
        run([
            FFMPEG, "-y", "-i", str(zp_out),
            "-vf", f"scale={w}:{h}",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-an", str(preview)
        ])

        # Recrear symlink img_NNNN.mp4
        link = img_dir / f"img_{seg_id:04d}.mp4"
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(zp_out.name)

    # Limpiar metadata.json: quitar entries img_* que no sean flow
    meta_path = personaje_dir / "metadata.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        footage = meta.get("footage", {})
        before = len(footage)
        footage = {k: v for k, v in footage.items() if k.startswith("flow_")}
        if len(footage) < before:
            print(f"  metadata.json: eliminados {before - len(footage)} entries img_* antiguos")
        meta["footage"] = footage
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n✓ Clips regenerados con duración exacta del timeline.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 regen_flow_clips.py <nicho>/<personaje>/")
        sys.exit(1)
    base = pathlib.Path("/Users/anyelocuesta/Downloads/Canales")
    personaje_dir = base / sys.argv[1].rstrip("/")
    nicho = sys.argv[1].split("/")[0]
    config_path = base / "_config" / f"{nicho}.json"
    regen_clips(personaje_dir, config_path)
