#!/usr/bin/env python3
"""
GenAIPro — Imagen a Video (frames-to-video)
Uso: python genaipro_i2v.py <imagen.jpg> [--prompt "texto"] [--end-image fin.jpg] [--portrait] [--no-upscale]
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error

API_KEY  = os.environ.get("GENAIPRO_API_KEY", "sk_gap_1t5IarOSN_Y-zFuq5MersCWb-LJvniDOwk4h9Tg4xcY")
BASE_URL = "https://genaipro.io/api"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://genaipro.io",
    "Referer": "https://genaipro.io/",
}


# ── helpers ──────────────────────────────────────────────────────────────────

def _boundary():
    import uuid
    return uuid.uuid4().hex


def _encode_multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    """Build multipart/form-data body. files = {field: (filename, bytes)}"""
    bnd = _boundary()
    parts = []
    for key, val in fields.items():
        parts.append(
            f'--{bnd}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{val}\r\n'.encode()
        )
    for key, (fname, data) in files.items():
        parts.append(
            f'--{bnd}\r\nContent-Disposition: form-data; name="{key}"; filename="{fname}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
            + data + b"\r\n"
        )
    parts.append(f"--{bnd}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={bnd}"


def api_get(path: str) -> dict:
    req = urllib.request.Request(f"{BASE_URL}{path}", headers=HEADERS)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def api_post_multipart(path: str, fields: dict, files: dict) -> dict:
    body, content_type = _encode_multipart(fields, files)
    headers = {**HEADERS, "Content-Type": content_type}
    req = urllib.request.Request(f"{BASE_URL}{path}", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"[ERROR] HTTP {e.code}: {e.read().decode()}")
        sys.exit(1)


def download(url: str, dest: str):
    print(f"  Descargando → {dest}")
    urllib.request.urlretrieve(url, dest)


# ── core ─────────────────────────────────────────────────────────────────────

def submit_job(start_image: str, prompt: str, end_image: str | None,
               portrait: bool, upscale: bool, n_videos: int) -> str:
    fields = {
        "prompt":            prompt,
        "aspect_ratio":      "VIDEO_ASPECT_RATIO_PORTRAIT" if portrait else "VIDEO_ASPECT_RATIO_LANDSCAPE",
        "number_of_videos":  str(n_videos),
        "upscale_resolution": "1080p" if upscale else "none",
    }
    files = {
        "start_image": (os.path.basename(start_image), open(start_image, "rb").read()),
    }
    if end_image:
        files["end_image"] = (os.path.basename(end_image), open(end_image, "rb").read())

    print(f"[1/3] Enviando job a GenAIPro…")
    resp = api_post_multipart("/v2/veo/frames-to-video", fields, files)
    # Formato nuevo: {"histories": [{"id": ..., "status": ..., "file_url": ...}]}
    if "histories" in resp and resp["histories"]:
        task_id = resp["histories"][0].get("id")
    else:
        task_id = resp.get("id") or resp.get("task_id") or resp.get("taskId")
    if not task_id:
        print(f"[ERROR] Respuesta inesperada: {resp}")
        sys.exit(1)
    print(f"      task_id = {task_id}")
    return task_id


def poll(task_id: str, interval: int = 8) -> list[str]:
    print("[2/3] Esperando resultado", end="", flush=True)
    while True:
        time.sleep(interval)
        try:
            data = api_get(f"/v2/veo/tasks/{task_id}")
        except Exception as e:
            print(f"\n[WARN] Error al consultar estado: {e}")
            continue

        # Formato nuevo: {"histories": [{"id":..., "status":..., "file_url":...}]}
        if "histories" in data and data["histories"]:
            item = data["histories"][0]
            status = item.get("status", "")
            if status == "completed":
                print(" ✓")
                url = item.get("file_url", "")
                return [url] if url else []
            elif status in ("failed", "error"):
                print(f"\n[ERROR] Tarea fallida: {item.get('error', '(sin detalle)')}")
                sys.exit(1)
            else:
                print(".", end="", flush=True)
            continue
        status = data.get("status", "")
        if status == "completed":
            print(" ✓")
            return data.get("file_urls", [])
        elif status == "failed":
            print(f"\n[ERROR] Tarea fallida: {data.get('error', '(sin detalle)')}")
            sys.exit(1)
        else:
            print(".", end="", flush=True)


def save_videos(urls: list[str], base_name: str):
    print(f"[3/3] Descargando {len(urls)} video(s)…")
    saved = []
    for i, url in enumerate(urls):
        ext  = url.split("?")[0].rsplit(".", 1)[-1] or "mp4"
        dest = f"{base_name}_{i+1}.{ext}" if len(urls) > 1 else f"{base_name}.{ext}"
        download(url, dest)
        saved.append(dest)
    return saved


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="GenAIPro imagen→video")
    ap.add_argument("start_image", help="Imagen de inicio (JPEG/PNG/WEBP, max 20 MB)")
    ap.add_argument("--prompt",    default="Cinematic slow motion animation", help="Descripción del movimiento")
    ap.add_argument("--end-image", default=None, dest="end_image", help="Imagen final opcional")
    ap.add_argument("--portrait",  action="store_true", help="Formato vertical (9:16)")
    ap.add_argument("--no-upscale",action="store_true", dest="no_upscale", help="Sin upscale a 1080p")
    ap.add_argument("--n",         type=int, default=1, choices=range(1,5), metavar="1-4", help="Cantidad de videos")
    ap.add_argument("--out",       default=None, help="Nombre base del archivo de salida (sin extensión)")
    args = ap.parse_args()

    if not os.path.isfile(args.start_image):
        print(f"[ERROR] No se encontró: {args.start_image}")
        sys.exit(1)

    out_base = args.out or os.path.splitext(args.start_image)[0] + "_video"

    task_id = submit_job(
        start_image=args.start_image,
        prompt=args.prompt,
        end_image=args.end_image,
        portrait=args.portrait,
        upscale=not args.no_upscale,
        n_videos=args.n,
    )

    urls  = poll(task_id)
    saved = save_videos(urls, out_base)

    print("\n✅ Listo:")
    for f in saved:
        print(f"   {f}")


if __name__ == "__main__":
    main()
