#!/usr/bin/env python3
"""
miniatura_seduccion_muapi.py — Genera 3 miniaturas con muapi.ai
Stick figures neon, grandes, sin texto, fondo negro puro.

Uso:
  python3 miniatura_seduccion_muapi.py seduccion/7_errores/
"""

import sys, time, json, pathlib, urllib.request, io
from PIL import Image

API_BASE = "https://api.muapi.ai/api/v1"
KEY_FILE = pathlib.Path.home() / ".muapi_key"
W, H     = 1280, 720

VERSIONES = [
    {
        "nombre": "muapi_v1_obsesion_pensamiento",
        "prompt": (
            "neon glowing stick figures on pure solid black background, "
            "large cyan neon glowing stick figure woman center-left, "
            "giant glowing neon thought bubble above her head filled with a bright green neon stick figure man silhouette, "
            "woman's hands pressed to temples looking overwhelmed and obsessed, "
            "multiple smaller neon thought bubbles cascading upward like she cannot stop thinking, "
            "thick bright neon tube glow effect on all lines, figures very large filling most of frame, "
            "simple round heads with expressive dot eyes, "
            "no text, no letters, no words, no watermark, no scenery, "
            "pure black background only, "
            "ThatGuy YouTube channel neon stick figure thumbnail style"
        ),
    },
    {
        "nombre": "muapi_v2_hombre_misterioso",
        "prompt": (
            "neon glowing stick figures on pure solid black background, "
            "large yellow neon glowing stick figure man on the right standing confidently, arms crossed, slight smirk, "
            "large magenta neon stick figure woman on the left reaching toward him with glowing question marks floating around her head, "
            "bright neon magnetic pull lines connecting them like invisible force, "
            "glowing pink neon hearts orbiting around the woman showing attraction and confusion, "
            "thick bright neon tube glow on all outlines, figures very large and expressive, "
            "no text, no letters, no words, no watermark, "
            "pure black background, "
            "ThatGuy YouTube channel neon stick figure thumbnail style"
        ),
    },
    {
        "nombre": "muapi_v3_ella_no_puede_parar",
        "prompt": (
            "neon glowing stick figures on pure solid black background, "
            "large cyan neon stick figure woman lying in bed at night unable to sleep, "
            "above her: huge glowing green neon thought bubble with a confident stick figure man standing inside, "
            "multiple glowing neon clocks floating around showing late hours, "
            "small neon spiral lines near her head showing dizzy obsessed state, "
            "thick bright neon tube glow on all lines, very large expressive figures, "
            "no text, no letters, no words, no watermark, no scenery except the black void, "
            "pure black background only, "
            "ThatGuy YouTube channel neon stick figure thumbnail style"
        ),
    },
]


def generar(prompt, api_key):
    body = json.dumps({"prompt": prompt, "width": 1024, "height": 576}).encode()
    req  = urllib.request.Request(
        f"{API_BASE}/flux-schnell-image",
        data=body,
        headers={"x-api-key": api_key, "Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())

    task_id = data.get("request_id")
    if not task_id:
        raise ValueError(f"Sin request_id: {data}")

    poll_url = f"{API_BASE}/predictions/{task_id}/result"
    for _ in range(60):
        time.sleep(4)
        poll = urllib.request.Request(poll_url, headers={"x-api-key": api_key})
        with urllib.request.urlopen(poll, timeout=20) as r:
            d = json.loads(r.read())
        if d.get("status") == "completed":
            outputs = d.get("outputs") or []
            if outputs:
                with urllib.request.urlopen(outputs[0], timeout=30) as r:
                    return r.read()
        elif d.get("status") == "failed":
            raise RuntimeError(f"Fallido: {d}")
    raise TimeoutError("Timeout")


def main():
    if len(sys.argv) < 2:
        print("Uso: python3 miniatura_seduccion_muapi.py seduccion/7_errores/")
        sys.exit(1)

    carpeta = pathlib.Path(sys.argv[1]).expanduser()
    api_key = KEY_FILE.read_text().strip()

    print(f"\n  Generando 3 miniaturas con muapi — neon, grandes, sin texto\n")

    for i, ver in enumerate(VERSIONES, 1):
        out = carpeta / f"{ver['nombre']}.jpg"
        print(f"  [{i}/3] {ver['nombre']} ...", end=" ", flush=True)
        try:
            img_bytes = generar(ver["prompt"], api_key)
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            img = img.resize((W, H), Image.LANCZOS)
            img.save(out, "JPEG", quality=95)
            print(f"✓  →  {out.name}")
        except Exception as e:
            print(f"✗  {e}")

    print(f"\n  Listas en {carpeta}/\n")


if __name__ == "__main__":
    main()
