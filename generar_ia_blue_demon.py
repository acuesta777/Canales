#!/usr/bin/env python3
"""Genera imágenes con muapi.ai para blue_demon y convierte a zoompan."""
import json, time, subprocess, requests, base64, tempfile, os
from pathlib import Path

BASE_DIR = Path("/Users/anyelocuesta/Downloads/Canales/riqueza/blue_demon")
TIMELINE = BASE_DIR / "05-montaje/timeline.json"
OUT_DIR = BASE_DIR / "03-imagenes"
OUT_DIR.mkdir(exist_ok=True)

MUAPI_KEY = open(os.path.expanduser("~/.muapi_key")).read().strip()
MUAPI_URL = "https://api.muapi.ai/v1/images/generations"

def generate_image(prompt: str) -> bytes | None:
    headers = {"Authorization": f"Bearer {MUAPI_KEY}", "Content-Type": "application/json"}
    body = {
        "model": "flux-schnell",
        "prompt": prompt,
        "width": 1280,
        "height": 720,
        "n": 1,
        "response_format": "b64_json"
    }
    r = requests.post(MUAPI_URL, json=body, headers=headers, timeout=60)
    if r.status_code != 200:
        print(f"  ERROR muapi: {r.status_code} {r.text[:200]}")
        return None
    data = r.json()
    b64 = data["data"][0]["b64_json"]
    return base64.b64decode(b64)

def make_zoompan(jpg_path: Path, out_path: Path, duration: float):
    dur_frames = max(1, int(duration * 25))
    vf = (
        f"scale=8000:-1,"
        f"zoompan=z='1+0.15*(on/{dur_frames})':d={dur_frames}"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1280x720,"
        f"scale=1280:720,fps=25"
    )
    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-framerate", "25",
        "-i", str(jpg_path),
        "-vf", vf,
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-an", str(out_path)
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        print(f"  ERROR ffmpeg: {r.stderr.decode()[-300:]}")
        return False
    return True

def main():
    segs = json.load(open(TIMELINE))["visual_timeline"]
    total = len(segs)
    done = 0
    failed = []

    for seg in segs:
        sid = seg["segment_id"]
        out_mp4 = OUT_DIR / f"flow_{sid:04d}_zp.mp4"
        if out_mp4.exists():
            print(f"[{sid}/{total}] Ya existe, saltando")
            done += 1
            continue

        prompt = seg.get("ia_prompt") or seg.get("prompt_or_query", "")
        dur = float(seg["duration"])
        print(f"[{sid}/{total}] Generando imagen ({dur:.1f}s)...")
        print(f"  Prompt: {prompt[:80]}...")

        img_bytes = generate_image(prompt)
        if not img_bytes:
            failed.append(sid)
            continue

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(img_bytes)
            tmp_jpg = f.name

        try:
            ok = make_zoompan(Path(tmp_jpg), out_mp4, dur)
            if ok:
                print(f"  ✓ Guardado: {out_mp4.name}")
                done += 1
            else:
                failed.append(sid)
        finally:
            os.unlink(tmp_jpg)

        time.sleep(0.5)

    print(f"\n✓ Completado: {done}/{total}")
    if failed:
        print(f"✗ Fallidos: {failed}")

if __name__ == "__main__":
    main()
