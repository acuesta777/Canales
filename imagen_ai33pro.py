#!/usr/bin/env python3
"""
imagen_ai33pro.py — Genera imágenes con AI33 Pro API desde el timeline.json
y las convierte a clips MP4 con zoompan para render.py.

Uso:
    python3 imagen_ai33pro.py <carpeta_personaje> [--model MODEL_ID] [--seg SEG_ID]

    --model   Modelo a usar (default: krea-2-medium)
    --seg     Generar solo el segmento N (para prueba o re-generación individual)
    --list    Listar modelos disponibles y salir
    --price   Calcular precio antes de generar (no genera)

API: https://api.ai33.pro
Key: ~/.ai33_key

Modelos recomendados (16:9 disponible):
    krea-2-medium          sin resolución extra — buena calidad/precio
    krea-2-large           premium
    flux-2-pro             720p/1080p/2K
    bytedance-seedream-4.5 2K/4K — muy buena calidad
    gpt-image-2            1K/2K/4K
    gemini-2.5-flash-image 1K

Flujo: timeline.json → ia_prompt → AI33 generate → polling → download JPEG →
       zoompan con duración exacta del segmento → flow_{:04d}_zp.mp4
"""

import sys, os, json, time, urllib.request, urllib.error, subprocess, tempfile, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from zoompan_clip import make_zoompan

API_BASE  = "https://api.ai33.pro"
KEY_FILE  = Path.home() / ".ai33_key"

DEFAULT_MODEL = "bytedance-seedream-4"

# Cadena de fallback: preferidos primero, luego resto
FALLBACK_CHAIN = [
    "gemini-2.5-flash-image",      # 1,004 — principal
    "gpt-image-2",                 # 870
    "gemini-3.1-flash-lite-image", # 914
    "bytedance-seedream-5-lite",   # 926
    "bytedance-seedream-4",        # 804 créditos
    "krea-2-medium",               # 864
    "bytedance-seedream-4.5",      # 986
    "recraft-v4.1",                # 986
    "gemini-2.5-flash-image",      # 1004
    "flux-2-pro",                  # 1046
    "wan-2.5-preview-image",       # 1106
    "krea-2-large",                # 1228
    "bytedance-seedream-5-pro",    # 2138
    "gemini-3-pro-image-preview",  # 2938
]

# Parámetros por modelo (todos 16:9)
MODEL_PARAMS = {
    "bytedance-seedream-4":        {"aspect_ratio": "16:9", "resolution": "2K"},
    "bytedance-seedream-4.5":      {"aspect_ratio": "16:9", "resolution": "2K"},
    "bytedance-seedream-5-lite":   {"aspect_ratio": "16:9", "resolution": "2K"},
    "bytedance-seedream-5-pro":    {"aspect_ratio": "16:9", "resolution": "1K"},
    "krea-2-medium":               {"aspect_ratio": "16:9"},
    "krea-2-large":                {"aspect_ratio": "16:9"},
    "flux-2-pro":                  {"aspect_ratio": "16:9", "resolution": "1080p"},
    "gpt-image-2":                 {"aspect_ratio": "16:9", "resolution": "2K"},
    "gemini-2.5-flash-image":      {"aspect_ratio": "16:9"},
    "gemini-3.1-flash-lite-image": {"aspect_ratio": "16:9"},
    "gemini-3-pro-image-preview":  {"aspect_ratio": "16:9", "resolution": "2K"},
    "recraft-v4.1":                {"aspect_ratio": "16:9", "resolution": "2K"},
    "wan-2.5-preview-image":       {"aspect_ratio": "16:9"},
    "kling-omni-image":            {"aspect_ratio": "16:9", "resolution": "2K"},
}

# ── helpers ───────────────────────────────────────────────────────────────────

def load_key():
    if not KEY_FILE.exists():
        sys.exit(f"[ERROR] No se encontró ~/.ai33_key")
    return KEY_FILE.read_text().strip()

def api_get(path, key):
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        headers={"xi-api-key": key, "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def api_post_json(path, key, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{API_BASE}{path}", data=body,
        headers={"xi-api-key": key, "Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def api_post_form(path, key, fields):
    """Multipart/form-data POST (requerido por generate-image)."""
    import urllib.parse
    boundary = "----Boundary" + str(int(time.time()))
    body_parts = []
    for k, v in fields.items():
        body_parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}".encode()
        )
    body_parts.append(f"--{boundary}--".encode())
    body = b"\r\n".join(body_parts)
    req = urllib.request.Request(
        f"{API_BASE}{path}", data=body,
        headers={
            "xi-api-key": key,
            "Content-Type": f"multipart/form-data; boundary={boundary}"
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def poll_task(task_id, key, timeout=60):
    """Polling hasta done/error/timeout. Retorna (metadata, credit_cost)."""
    start = time.time()
    delay = 4
    while time.time() - start < timeout:
        resp = api_get(f"/v1/task/{task_id}", key)
        status = resp.get("status", "")
        credit_cost = resp.get("credit_cost", 0)
        if status == "done":
            return resp.get("metadata", {}), credit_cost
        if status == "error":
            raise RuntimeError(f"Task error: {resp.get('error_message','?')}")
        time.sleep(delay)
    raise TimeoutError(f"Timeout {timeout}s — modelo demasiado lento")

def download_file(url, dest, key=None):
    """Descarga con curl (maneja redirects automáticamente)."""
    cmd = ["curl", "-s", "-L", "-o", str(dest)]
    if key:
        cmd += ["-H", f"xi-api-key: {key}"]
    cmd.append(url)
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"curl falló: {result.stderr.decode()[:200]}")
    if not Path(dest).exists() or Path(dest).stat().st_size < 1000:
        raise RuntimeError(f"Archivo descargado muy pequeño o vacío: {dest}")

def zoompan_clip(frame_path, out_path, duration, index=0):
    """Convierte JPEG a MP4 con zoompan — delega a zoompan_clip.py (z=1.5, pan rotativo)."""
    ok = make_zoompan(Path(frame_path), Path(out_path), duration, index=index)
    if not ok:
        raise RuntimeError(f"zoompan falló para {frame_path}")

# ── comandos ──────────────────────────────────────────────────────────────────

def cmd_list(key):
    data = api_get("/v1i/models", key)
    print(f"\n{'Modelo':<35} {'Aspect Ratios':<30} Resoluciones")
    print("-" * 80)
    for m in data.get("models", []):
        ar = ", ".join(m.get("aspect_ratios", []))
        res = ", ".join(m.get("resolutions", []))
        print(f"{m['model_id']:<35} {ar:<30} {res}")

def cmd_price(model_id, key):
    params = MODEL_PARAMS.get(model_id, {"aspect_ratio": "16:9"})
    data = api_post_json("/v1i/task/price", key, {
        "model_id": model_id,
        "generations_count": 1,
        "model_parameters": params,
        "assets": 0
    })
    credits = data.get("credits", "?")
    print(f"Precio: {credits} créditos por imagen con {model_id}")
    return credits

def _try_generate(prompt, model_id, key):
    """Intenta generar con un modelo. Retorna (metadata, credits) o lanza excepción."""
    params = MODEL_PARAMS.get(model_id, {"aspect_ratio": "16:9"})
    fields = {
        "prompt": prompt,
        "model_id": model_id,
        "generations_count": "1",
        "model_parameters": json.dumps(params),
    }
    resp = api_post_form("/v1i/task/generate-image", key, fields)
    if not resp.get("success"):
        raise RuntimeError(f"rechazado: {resp.get('message','?')}")
    task_id = resp["task_id"]
    return poll_task(task_id, key)

def generate_segment(seg, model_id, key, img_dir, prefix="flow"):
    """Genera un segmento con fallback automático. Retorna (ok, credits_used, model_used)."""
    seg_id   = seg["segment_id"]
    prompt   = seg.get("ia_prompt") or seg.get("ia_prompt_en") or seg.get("prompt_or_query", "")
    duration = seg.get("duration", 6.0)
    out_path = img_dir / f"{prefix}_{seg_id:04d}_zp.mp4"

    if not prompt:
        return False, 0, None
    if out_path.exists():
        return True, 0, "cached"

    chain = [model_id] + [m for m in FALLBACK_CHAIN if m != model_id]

    meta, credits, used_model = None, 0, None
    for attempt_model in chain:
        try:
            meta, credits = _try_generate(prompt, attempt_model, key)
            used_model = attempt_model
            break
        except Exception as e:
            print(f"    [SEG {seg_id:02d}][{attempt_model}] ✗ {e} — fallback...")
            time.sleep(2)

    if meta is None:
        return False, 0, None

    images = meta.get("result_images", [])
    if not images:
        return False, credits, used_model
    img_url = images[0].get("imageUrl") or images[0].get("previewUrl")

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tmp_frame = tf.name
    try:
        download_file(img_url, tmp_frame, key=key)
        # Si es Farandula (prefix=hook), guardar también el JPG fuente para el dashboard
        if prefix == "hook":
            jpg_path = img_dir / f"{prefix}_{seg_id:04d}.jpg"
            import shutil
            shutil.copy2(tmp_frame, str(jpg_path))
        zoompan_clip(tmp_frame, out_path, duration, index=seg_id)
    finally:
        try:
            os.unlink(tmp_frame)
        except Exception:
            pass

    return True, credits, used_model

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Genera imágenes con AI33 Pro para el timeline")
    parser.add_argument("carpeta", nargs="?", help="Carpeta del personaje (ej. riqueza/wolf_ruvinskis/)")
    parser.add_argument("--model",   default=DEFAULT_MODEL, help=f"Modelo principal (default: {DEFAULT_MODEL})")
    parser.add_argument("--seg",     type=int, default=None, help="Generar solo el segmento N")
    parser.add_argument("--workers", type=int, default=4,   help="Imágenes en paralelo (default: 4)")
    parser.add_argument("--list",    action="store_true",   help="Listar modelos y salir")
    parser.add_argument("--price",   action="store_true",   help="Mostrar precio estimado y salir")
    args = parser.parse_args()

    key = load_key()

    if args.list:
        cmd_list(key)
        return

    if not args.carpeta:
        parser.print_help()
        sys.exit(1)

    carpeta = Path(args.carpeta)

    # Detectar modo automáticamente:
    # Farandula Mono → hook_timeline.json en raíz → hook_images/ con nombres hook_NNNN
    # Riqueza/Fútbol → 05-montaje/timeline.json → 03-imagenes/ con nombres flow_NNNN
    farandula_tl = carpeta / "hook_timeline.json"
    riqueza_tl   = carpeta / "05-montaje" / "timeline.json"
    if farandula_tl.exists():
        timeline_path = farandula_tl
        img_dir       = carpeta / "hook_images"
        prefix        = "hook"
    elif riqueza_tl.exists():
        timeline_path = riqueza_tl
        img_dir       = carpeta / "03-imagenes"
        prefix        = "flow"
    else:
        sys.exit(f"[ERROR] No existe hook_timeline.json ni 05-montaje/timeline.json en {carpeta}")

    img_dir.mkdir(parents=True, exist_ok=True)

    timeline = json.loads(timeline_path.read_text())
    segments = timeline.get("visual_timeline", [])

    if args.price:
        credits = cmd_price(args.model, key)
        total = int(str(credits) if str(credits).isdigit() else 0) * len(segments)
        print(f"Estimado: {total} créditos para {len(segments)} segs con {args.model}")
        return

    if args.seg is not None:
        segments = [s for s in segments if s["segment_id"] == args.seg]
        if not segments:
            sys.exit(f"[ERROR] Segmento {args.seg} no encontrado")

    print(f"\n{'='*60}")
    print(f"  imagen_ai33pro — {carpeta.name}")
    print(f"  Modelo  : {args.model}  |  Workers: {args.workers}")
    print(f"  Segs    : {len(segments)}")
    print(f"{'='*60}\n")

    import threading
    lock = threading.Lock()
    results = []  # (seg_id, ok, credits, model)

    def worker(seg):
        sid = seg["segment_id"]
        try:
            ok, credits, model = generate_segment(seg, args.model, key, img_dir, prefix=prefix)
            with lock:
                status = "✓" if ok else "✗"
                cached = " (cached)" if model == "cached" else f" [{model}]" if model else ""
                print(f"  {status} SEG {sid:02d}{cached}  {credits} créditos")
                results.append((sid, ok, credits))
        except Exception as e:
            with lock:
                print(f"  ✗ SEG {sid:02d} ERROR: {e}")
                results.append((sid, False, 0))

    t_start = time.time()

    # Lotes de N workers en paralelo
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        ex.map(worker, segments)

    t_total = time.time() - t_start
    total_credits = sum(r[2] for r in results)
    ok_count  = sum(1 for r in results if r[1])
    fail_count = len(results) - ok_count
    found = sum(1 for s in segments if (img_dir / f"{prefix}_{s['segment_id']:04d}_zp.mp4").exists())

    print(f"\n{'='*60}")
    print(f"  RESUMEN FINAL — {carpeta.name}")
    print(f"{'='*60}")
    print(f"  ✓ Generados   : {ok_count}")
    print(f"  ✗ Fallidos    : {fail_count}")
    print(f"  Clips listos  : {found}/{len(segments)}")
    print(f"  Créditos AI33 : {total_credits:,}")
    print(f"  Tiempo total  : {int(t_total//60)}m {int(t_total%60)}s")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()
