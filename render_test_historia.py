#!/usr/bin/env python3
"""
Test render parcial para Canal Historia Animada.
Renderiza los primeros N clips animados para verificar cortes y sync de audio.
Uso: python3 render_test_18.py [n_clips]  (default: 18)
"""
import json, subprocess, pathlib, tempfile, sys

base    = pathlib.Path("/Users/anyelocuesta/Downloads/Canales/historia/greek-party-god-became-devil")
tl_path = base / "05-montaje" / "timeline.json"
img_dir = base / "03-imagenes"
audio   = base / "greek-party-god-became-devil.mp3"
out_dir = base / "06-master"
out_dir.mkdir(exist_ok=True)

n = int(sys.argv[1]) if len(sys.argv) > 1 else 18

tl   = json.load(open(tl_path))
segs = tl["visual_timeline"][:n]
out  = out_dir / f"test_{n}clips.mp4"
tmpdir = pathlib.Path(tempfile.mkdtemp())

trimmed = []
for i, s in enumerate(segs):
    sid  = s.get("segment_id", s.get("segmento_id"))
    dur  = s.get("duracion", 6.0)
    clip = img_dir / f"flow_{sid:04d}_zp.mp4"
    if not clip.exists():
        print(f"FALTA: {clip}"); sys.exit(1)
    out_clip = tmpdir / f"t{i:02d}.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", str(clip),
        "-t", str(dur),
        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1",
        "-r", "30", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-an",
        str(out_clip)
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        print(f"ERROR seg {sid}:", r.stderr.decode()[-300:]); sys.exit(1)
    print(f"  ✓ seg {sid} ({dur:.2f}s)")
    trimmed.append(out_clip)

concat_list = tmpdir / "concat.txt"
concat_list.write_text("\n".join(f"file '{p}'" for p in trimmed))
total_dur = sum(s.get("duracion", 0) for s in segs)

r = subprocess.run([
    "ffmpeg", "-y",
    "-f", "concat", "-safe", "0", "-i", str(concat_list),
    "-i", str(audio),
    "-t", str(total_dur),
    "-map", "0:v", "-map", "1:a",
    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
    "-c:a", "aac", "-b:a", "128k", "-shortest",
    str(out)
], capture_output=True)

if r.returncode != 0:
    print("ERROR concat:", r.stderr.decode()[-500:]); sys.exit(1)

probe = subprocess.run(
    ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
     "-of", "default=noprint_wrappers=1:nokey=1", str(out)],
    capture_output=True, text=True
)
print(f"\n✅ {out}")
print(f"   Duración: {probe.stdout.strip()}s  (esperada {total_dur:.1f}s)")
