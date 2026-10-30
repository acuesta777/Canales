#!/usr/bin/env python3
"""
imagen_clips.py — Genera imágenes con Muapi.ai desde el CSV de prompts y las anima con zoom/pan.

Uso:
    python3 imagen_clips.py <carpeta_personaje> [--model MODEL_ID]

API: https://api.muapi.ai  — header: x-api-key
Polling: GET /api/v1/predictions/{id}/result
Clave: ~/.muapi_key

Modelos disponibles (text-to-image, 16:9):
    grok-imagine-text-to-image         $0.05  (default, realista premium)
    grok-imagine-text-to-image-quality $0.05  (calidad máxima)
    google-imagen4                     $0.03  (muy buena calidad)
    google-imagen4-fast                $0.02  (rápido y bueno)
    hidream-i1-fast                    $0.008 (rápido)
    hidream-i1-full                    $0.015 (full quality)
    flux-2-klein-4b-turbo              $0.005 (barato)
    flux-schnell                       $0.003 (ultrabarato, fallback final)
    flux-dev                           $0.025 (alta calidad flux)
"""

import sys, os, csv, time, json, subprocess, urllib.request, urllib.error
from pathlib import Path

API_BASE  = "https://api.muapi.ai/api/v1"
KEY_FILE  = Path.home() / ".muapi_key"

DEFAULT_MODEL = "flux-schnell"

# Orden de fallback cuando el modelo principal falla
FALLBACK_CHAIN = [
    "flux-schnell",    # $0.003 — funciona confirmado, 1024x576 16:9
    "flux-dev",        # $0.025 — mejor calidad
]

# Parámetros por modelo — 1024x576 = 16:9 con múltiplos de 64 (requerido por la API)
# Endpoint real: /api/v1/{model}-image  (sufijo -image siempre)
MODEL_PARAMS = {
    "flux-schnell":    {"width": 1024, "height": 576},
    "flux-dev":        {"width": 1024, "height": 576},
    "hidream-i1-fast": {"width": 1024, "height": 576},
    "hidream-i1-full": {"width": 1024, "height": 576},
    # Modelos endpoint SIN sufijo -image (width/height)
    "nano-banana":     {"width": 1024, "height": 576},
    "nano-banana-2":   {"width": 1024, "height": 576},
    "flux-2-pro":      {"width": 1024, "height": 576},
    "seedream-5.0":    {"width": 1024, "height": 576},
    # Modelos con aspect_ratio — endpoint sin sufijo -image
    "google-imagen4":                     {"aspect_ratio": "16:9"},
    "google-imagen4-fast":                {"aspect_ratio": "16:9"},
    "flux-2-klein-4b-turbo":              {"aspect_ratio": "16:9"},
    "grok-imagine-text-to-image":         {"aspect_ratio": "16:9"},
    "grok-imagine-text-to-image-quality": {"aspect_ratio": "16:9"},
}

# Modelos que usan endpoint SIN sufijo -image
NO_IMAGE_SUFFIX = {
    "google-imagen4", "google-imagen4-fast", "flux-2-klein-4b-turbo",
    "grok-imagine-text-to-image", "grok-imagine-text-to-image-quality",
    "nano-banana", "nano-banana-2", "flux-2-pro", "seedream-5.0",
}


def get_api_key():
    if not KEY_FILE.exists():
        sys.exit(f"[ERROR] No encontré clave Muapi en {KEY_FILE}\nCrea el archivo con tu API key.")
    return KEY_FILE.read_text().strip()


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


def check_api_health(api_key):
    try:
        r = api_get(f"{API_BASE}/models/flux-schnell", api_key)
        return True, r.get("price", "?")
    except Exception as e:
        return False, str(e)


def generate_image(prompt, model_id, api_key):
    params = MODEL_PARAMS.get(model_id, {"width": 1024, "height": 576})
    payload = {"prompt": prompt, **params}
    suffix = "" if model_id in NO_IMAGE_SUFFIX else "-image"
    endpoint = f"/{model_id}{suffix}"
    return api_post(endpoint, payload, api_key)


def poll_task(task_id, api_key, timeout=90):
    """Polling hasta status=completed. Timeout 90s por modelo."""
    start = time.time()
    poll_url = f"{API_BASE}/predictions/{task_id}/result"
    while True:
        elapsed = int(time.time() - start)
        if elapsed >= timeout:
            raise TimeoutError(f"Task {task_id} no completó en {timeout}s")
        time.sleep(8)
        try:
            r = api_get(poll_url, api_key)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"  rate limit — esperando 10s [{elapsed}s]", end="\r", flush=True)
                time.sleep(10)
                continue
            print(f"  poll error HTTP {e.code} — reintentando [{elapsed}s]", end="\r", flush=True)
            continue
        except Exception as e:
            print(f"  poll error: {e} [{elapsed}s]", end="\r", flush=True)
            continue

        data   = r.get("data", r)
        status = data.get("status", "")
        elapsed = int(time.time() - start)
        print(f"  status={status} [{elapsed}s]        ", end="\r", flush=True)

        if status == "completed":
            print()
            outputs = data.get("outputs", [])
            if outputs:
                return outputs[0]
            raise RuntimeError("Sin outputs en respuesta completed")
        if status == "failed":
            print()
            raise RuntimeError(data.get("error", "Generation failed"))


def download_file(url, dest_path):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        dest_path.write_bytes(r.read())


def simplify_prompt(prompt):
    cuts = [", YouTube thumbnail style", ", high contrast", ", cinematic lighting",
            ", photorealistic", ", 16:9", "Cinematic hyperrealistic photo of ",
            "Cinematic hyperrealistic "]
    s = prompt
    for c in cuts:
        s = s.replace(c, "")
    s = s.strip().rstrip(",")
    if len(s) > 300:
        s = s[:297] + "..."
    return s + ", realistic photo, 16:9"


def try_generate(prompt, model_id, api_key, img_num):
    r = generate_image(prompt, model_id, api_key)
    data = r.get("data", r)
    task_id = r.get("request_id") or data.get("id") or r.get("id")
    if not task_id:
        raise RuntimeError(f"Sin task_id en respuesta: {r}")
    print(f"         task={task_id} (modelo: {model_id})")
    image_url = poll_task(task_id, api_key)
    return image_url


def generate_with_fallback(prompt, primary_model, api_key, img_num):
    models_to_try = [primary_model] + [m for m in FALLBACK_CHAIN if m != primary_model]
    last_error = None

    for attempt, model in enumerate(models_to_try, 1):
        try:
            print(f"         [{attempt}/{len(models_to_try)}] {model}")
            url = try_generate(prompt, model, api_key, img_num)
            return url, model, prompt
        except Exception as e:
            last_error = e
            print(f"         ✗ falló: {e}")
            if attempt < len(models_to_try):
                time.sleep(5)

    # Intenta con prompt simplificado
    simple = simplify_prompt(prompt)
    print(f"         [prompt simplificado] {simple[:80]}...")
    for attempt, model in enumerate(models_to_try, 1):
        try:
            print(f"         [simple {attempt}] {model}")
            url = try_generate(simple, model, api_key, img_num)
            return url, model, simple
        except Exception as e:
            last_error = e
            print(f"         ✗ falló: {e}")
            if attempt < len(models_to_try):
                time.sleep(5)

    raise RuntimeError(f"Imagen {img_num}: todos los modelos fallaron. Último: {last_error}")


def macos_notify(title, body):
    script = f'display notification "{body}" with title "{title}" sound name "Glass"'
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)


def detectar_epoca(carpeta):
    """
    Detecta la época del personaje leyendo el guion o metadata.
    Retorna: 'bw' (antes 1940), 'vintage' (1940-1989), 'color' (1990+)
    """
    import re
    personaje = carpeta.name
    # Buscar año de nacimiento en el guion
    txt_path = carpeta / f"{personaje}.txt"
    anio_nacimiento = None
    if txt_path.exists():
        texto = txt_path.read_text(encoding="utf-8", errors="ignore")
        # Buscar patrones: "nació en 1929", "26 de marzo de 1929", "(1929–", "1929-"
        matches = re.findall(r'\b(18[5-9]\d|19[0-9]\d|20[0-2]\d)\b', texto[:3000])
        if matches:
            candidatos = [int(a) for a in matches if 1850 <= int(a) <= 2010]
            if candidatos:
                anio_nacimiento = min(candidatos)  # el más antiguo = nacimiento
    if anio_nacimiento is None:
        return "vintage"  # default seguro
    if anio_nacimiento < 1940:
        return "bw"
    if anio_nacimiento < 1990:
        return "vintage"
    return "color"


PROMPT_SUFFIX_EPOCA = {
    "bw":      "black and white vintage film photography, 1930s-1940s cinematic style, grainy",
    "vintage": "vintage warm film photography, slightly desaturated, 1950s-1960s cinematic style",
    "color":   "",  # color radiante, sin modificar
}


def run_animar_clips(carpeta, epoca="vintage"):
    script = Path(__file__).parent / "animar_clips.py"
    cmd = ["python3", str(script), str(carpeta)]
    if epoca == "bw":
        cmd.append("--bw")
    elif epoca == "vintage":
        cmd.append("--vintage")
    result = subprocess.run(cmd, capture_output=False)
    return result.returncode == 0


def load_prompts(carpeta):
    personaje = carpeta.name
    csv_path  = carpeta / f"{personaje}_prompts.csv"
    if not csv_path.exists():
        sys.exit(f"[ERROR] No encontré {csv_path}")
    prompts = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            prompts.append(row["prompt"].strip())
    return prompts


def show_manual_mode(carpeta, prompts):
    personaje = carpeta.name
    csv_path  = carpeta / f"{personaje}_prompts.csv"
    print(f"\n{'='*60}")
    print(f"  ⚠  MUAPI NO DISPONIBLE — MODO MANUAL")
    print(f"  Genera las imágenes y colócalas en:")
    print(f"  {carpeta}/imagenes/")
    print(f"  Nombres: 1.jpg, 2.jpg, ... {len(prompts)}.jpg\n")
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            for idx, row in enumerate(csv.DictReader(f), 1):
                print(f"  [{idx}] seg {row['seg_inicio']}")
                print(f"  {row['prompt']}\n")
    except Exception:
        for i, p in enumerate(prompts, 1):
            print(f"  [{i}] {p}\n")
    print(f"{'='*60}")
    imagenes_dir = carpeta / "imagenes"
    imagenes_dir.mkdir(exist_ok=True)
    while True:
        existentes = list(imagenes_dir.glob("*.jpg")) + list(imagenes_dir.glob("*.png"))
        if len(existentes) >= len(prompts):
            print(f"\n  ✓ {len(existentes)} imágenes detectadas — animando...")
            run_animar_clips(carpeta, epoca=detectar_epoca(carpeta))
            sys.exit(0)
        print(f"  {len(existentes)}/{len(prompts)} imágenes encontradas — esperando 20s...")
        time.sleep(20)


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)

    carpeta = Path(sys.argv[1]).resolve()
    if not carpeta.is_dir():
        sys.exit(f"[ERROR] Carpeta no encontrada: {carpeta}")

    primary_model = DEFAULT_MODEL
    for i, arg in enumerate(sys.argv[2:]):
        if arg == "--model" and i + 3 < len(sys.argv):
            primary_model = sys.argv[i + 3]
        elif arg.startswith("--model="):
            primary_model = arg.split("=", 1)[1]

    api_key   = get_api_key()
    personaje = carpeta.name
    prompts   = load_prompts(carpeta)

    print("  Verificando API Muapi...")
    api_ok, info = check_api_health(api_key)
    if not api_ok:
        show_manual_mode(carpeta, prompts)
        return
    print(f"  ✓ Muapi OK\n")

    imagenes_dir = carpeta / "imagenes"
    imagenes_dir.mkdir(exist_ok=True)

    # Detectar época y ajustar prompts
    epoca        = detectar_epoca(carpeta)
    suffix_epoca = PROMPT_SUFFIX_EPOCA.get(epoca, "")
    if suffix_epoca:
        prompts = [f"{p}, {suffix_epoca}" if suffix_epoca not in p else p for p in prompts]

    print("=" * 60)
    print(f"  IMAGEN CLIPS — {personaje.upper()}")
    print(f"  Modelo principal : {primary_model}")
    print(f"  Imágenes         : {len(prompts)}")
    print(f"  Época detectada  : {epoca.upper()} ({'B&W' if epoca=='bw' else 'vintage' if epoca=='vintage' else 'color radiante'})")
    print(f"  Fallback chain   : {len(FALLBACK_CHAIN)} modelos")
    print("=" * 60)
    print()

    generated = 0
    results   = []
    for i, prompt in enumerate(prompts, 1):
        short = prompt[:75] + "..." if len(prompt) > 75 else prompt
        print(f"  [{i}/{len(prompts)}] {short}")
        t0 = time.time()
        try:
            image_url, used_model, used_prompt = generate_with_fallback(
                prompt, primary_model, api_key, i
            )
            dest = imagenes_dir / f"{i}.jpg"
            download_file(image_url, dest)
            elapsed  = round(time.time() - t0)
            size_kb  = dest.stat().st_size // 1024
            note_m   = f" (via {used_model})" if used_model != primary_model else ""
            note_p   = " [prompt simplificado]" if used_prompt != prompt else ""
            print(f"  ✓ Imagen {i} guardada — {size_kb} KB — {elapsed}s{note_m}{note_p}")
            results.append({"img": i, "model": used_model, "seconds": elapsed, "kb": size_kb, "ok": True})
            generated += 1
        except Exception as e:
            elapsed = round(time.time() - t0)
            print(f"\n  ✗ Imagen {i} saltada — {e}")
            print(f"    Continúa con las demás...")
            results.append({"img": i, "model": "—", "seconds": elapsed, "kb": 0, "ok": False})
        print()

    failed = [r for r in results if not r["ok"]]
    if failed:
        print(f"\n  ⚠  Imágenes pendientes (genera manual y pon en imagenes/):")
        csv_path = carpeta / f"{personaje}_prompts.csv"
        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        for r in failed:
            row = rows[r["img"] - 1]
            print(f"  [{r['img']}] seg {row['seg_inicio']} — {row['prompt']}")
        print()

    print("=" * 60)
    print(f"  {generated}/{len(prompts)} imágenes generadas — animando...")
    print("=" * 60)
    print()

    run_animar_clips(carpeta, epoca=epoca)

    # Copiar clips animados a 03-imagenes/ y registrar en metadata.json para el dashboard
    _registrar_ia_en_dashboard(carpeta, results)

    print()
    print("=" * 60)
    print("  RESUMEN")
    print("=" * 60)
    for r in results:
        s = "✓" if r["ok"] else "✗"
        print(f"  {s} [{r['img']}] {r['model']:<20} {r['seconds']:>5}s  {r['kb']:>5} KB")
    print("=" * 60)
    print(f"  IMAGEN_RESUMEN_JSON:{json.dumps(results)}")

    ok_count  = len([r for r in results if r["ok"]])
    fail_count = len([r for r in results if not r["ok"]])
    msg = f"{ok_count}/{len(results)} imágenes listas — clips animados"
    if fail_count:
        msg += f" ({fail_count} fallidas)"
    macos_notify("✅ Imágenes listas", msg)


def _registrar_ia_en_dashboard(carpeta, results):
    """Copia clips IA a 03-imagenes/ y los registra en metadata.json para el dashboard."""
    import shutil
    imagenes_dir = carpeta / "imagenes"
    img03_dir    = carpeta / "03-imagenes"
    meta_path    = carpeta / "metadata.json"
    csv_path     = carpeta / f"{carpeta.name}_prompts.csv"

    img03_dir.mkdir(exist_ok=True)
    if not meta_path.exists():
        return

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        rows = []
        if csv_path.exists():
            with open(csv_path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

        for r in results:
            if not r.get("ok"):
                continue
            i   = r["img"]
            src = imagenes_dir / f"{i}.mp4"
            dst = img03_dir / f"ia_{i:04d}.mp4"
            if src.exists():
                import subprocess as _sp
                _sp.run([
                    "ffmpeg", "-i", str(src),
                    "-vf", "scale=640:360",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                    "-an", "-y", str(dst)
                ], stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
            prompt   = rows[i - 1].get("prompt", "") if i <= len(rows) else ""
            seg_raw  = rows[i - 1].get("seg_inicio", "0") if i <= len(rows) else "0"
            # Convertir HH:MM:SS a segundos float para compatibilidad con el dashboard
            try:
                parts = seg_raw.strip().split(":")
                seg = sum(float(p) * (60 ** (len(parts) - 1 - j)) for j, p in enumerate(parts))
            except Exception:
                seg = 0.0
            clip_key = dst.name
            # Solo registrar si no existe ya como aprobado
            prev = meta.setdefault("footage", {}).get(clip_key, {})
            if prev.get("estado") != "aprobado":
                meta["footage"][clip_key] = {
                    "estado":        "pendiente",
                    "fuente":        "ia",
                    "prompt":        prompt[:200],
                    "timestamp":     seg,
                    "descripcion_es": f"IA imagen {i} — {prompt[:60]}",
                }

        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  ✓ {len([r for r in results if r.get('ok')])} imágenes IA registradas en dashboard")
    except Exception as e:
        print(f"  ⚠ No se pudo registrar en dashboard: {e}")


if __name__ == "__main__":
    main()
