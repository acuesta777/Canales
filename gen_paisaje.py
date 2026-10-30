#!/usr/bin/env python3
"""Genera 3 opciones de paisaje para miniatura con prompts cinematográficos."""

import json, time, urllib.request, sys
from pathlib import Path

API_BASE = "https://api.muapi.ai/api/v1"
KEY_FILE = Path.home() / ".muapi_key"

PROMPTS = [
    {
        "nombre": "hacienda_tropical",
        "prompt": (
            "Cinematic wide establishing shot of a grand Mexican hacienda, "
            "rustic terracotta adobe walls with white arched columns, "
            "sprawling tropical garden in foreground with lush green lawn, "
            "towering royal palm trees lining the entrance driveway, "
            "vibrant magenta bougainvillea climbing the walls, "
            "dramatic golden hour sunlight at sunset casting long warm shadows, "
            "deep blue sky with volumetric clouds in background, "
            "stone fountain in the courtyard, "
            "photorealistic 8K cinematic photography, "
            "shot with wide angle 24mm lens, "
            "professional real estate photography style, "
            "National Geographic quality, warm color grading, "
            "no people"
        ),
    },
    {
        "nombre": "rancho_mexicano",
        "prompt": (
            "Cinematic aerial-perspective wide shot of a large Mexican cattle ranch, "
            "rustic wooden ranch house with red clay tile roof, "
            "split-rail wooden fences stretching into the distance, "
            "several horses grazing on lush green pastures, "
            "dramatic mountain range with misty peaks in the background, "
            "massive oak and ceiba trees providing shade, "
            "dirt road leading to the main house lined with agave plants, "
            "epic golden hour sunset lighting with orange and amber tones, "
            "dramatic clouds over the mountains, "
            "photorealistic cinematic 8K, "
            "wide establishing shot as seen in National Geographic documentaries, "
            "no people"
        ),
    },
    {
        "nombre": "mansion_lujo",
        "prompt": (
            "Cinematic wide establishing shot of a luxurious contemporary Mexican villa, "
            "white stucco walls with floor-to-ceiling glass windows, "
            "infinity pool reflecting the sunset sky in the foreground, "
            "perfectly manicured tropical garden with bird of paradise flowers, "
            "sleek palm trees and dramatic ornamental grasses, "
            "modern stone pathway leading to the entrance, "
            "warm amber and orange sunset sky filling the background, "
            "outdoor living area with elegant furniture visible, "
            "photorealistic architectural photography, "
            "8K cinematic quality, shot with 24mm wide lens, "
            "luxury real estate magazine style, "
            "no people"
        ),
    },
]


def api_post(endpoint, data, api_key):
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{API_BASE}{endpoint}",
        data=body,
        headers={"Content-Type": "application/json", "x-api-key": api_key},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def api_get(url, api_key):
    req = urllib.request.Request(url, headers={"x-api-key": api_key})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def poll(task_id, api_key, timeout=120):
    poll_url = f"{API_BASE}/predictions/{task_id}/result"
    start = time.time()
    while True:
        elapsed = int(time.time() - start)
        if elapsed >= timeout:
            raise TimeoutError(f"Timeout {timeout}s")
        time.sleep(8)
        try:
            r = api_get(poll_url, api_key)
        except Exception as e:
            print(f"  poll: {e} [{elapsed}s]", end="\r", flush=True)
            continue
        data   = r.get("data", r)
        status = data.get("status", "")
        print(f"  {status} [{elapsed}s]       ", end="\r", flush=True)
        if status == "completed":
            print()
            outputs = data.get("outputs", [])
            if outputs:
                return outputs[0]
            raise RuntimeError("Sin outputs")
        if status == "failed":
            print()
            raise RuntimeError(data.get("error", "failed"))


def generate(prompt, api_key):
    payload = {"prompt": prompt, "aspect_ratio": "16:9"}
    r = api_post("/grok-imagine-text-to-image", payload, api_key)
    data    = r.get("data", r)
    task_id = r.get("request_id") or data.get("id") or r.get("id")
    print(f"  task={task_id}")
    img_url = poll(task_id, api_key)
    req = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def main():
    personaje = sys.argv[1] if len(sys.argv) > 1 else "canek"
    out_dir   = Path("/Users/anyelocuesta/Downloads/Canales") / personaje.lower()
    out_dir.mkdir(exist_ok=True)
    api_key   = (Path.home() / ".muapi_key").read_text().strip()

    print(f"\n{'='*60}")
    print(f"  PAISAJES — {personaje.upper()} — 3 opciones ($0.15)")
    print(f"{'='*60}\n")

    for i, p in enumerate(PROMPTS, 1):
        print(f"[{i}/3] {p['nombre']}")
        print(f"  Prompt: {p['prompt'][:80]}...")
        img_bytes = generate(p["prompt"], api_key)
        out_path  = out_dir / f"paisaje_{p['nombre']}.jpg"
        out_path.write_bytes(img_bytes)
        print(f"  ✓ {out_path.name} ({len(img_bytes)//1024} KB)\n")

    import subprocess
    subprocess.run(
        ["osascript", "-e",
         'display notification "3 paisajes listos — revisa la carpeta" with title "🏡 Paisajes" sound name "Glass"'],
        check=False, capture_output=True
    )

    # Abrir los 3 para ver
    for p in PROMPTS:
        out = out_dir / f"paisaje_{p['nombre']}.jpg"
        subprocess.run(["open", str(out)], check=False)


if __name__ == "__main__":
    main()
