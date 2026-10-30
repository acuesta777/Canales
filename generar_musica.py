#!/usr/bin/env python3
"""
generar_musica.py — Genera música de fondo con Suno vía AI33.
Devuelve 2 variantes instrumentales. Uso por canal o por video.

Uso:
    python3 generar_musica.py <carpeta_destino> [prompt]
    python3 generar_musica.py seduccion/7_errores/
    python3 generar_musica.py seduccion/musica/  "dark cinematic ambient"
"""

import sys, json, time, pathlib, urllib.request, urllib.error, subprocess

HOME     = pathlib.Path.home()
KEY_FILE = HOME / ".ai33_key"
BASE     = "https://api.ai33.pro"

PROMPT_DEFAULT = (
    "cinematic ambient instrumental, masculine emotional tension, dark warm tones, "
    "no lyrics, introspective, subtle percussion, storytelling background, "
    "burnt orange mood, psychological depth"
)

POLL_SECONDS     = 10
MAX_WAIT_SECONDS = 300


def read_key():
    try:
        return KEY_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        print(f"ERROR: Sin API key en {KEY_FILE}")
        sys.exit(1)


def post_json(url, api_key, payload):
    body = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(url, data=body, headers={
        "xi-api-key":   api_key,
        "Content-Type": "application/json",
    }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode('utf-8', errors='ignore')[:300]}")
        return None
    except Exception as e:
        print(f"Error POST: {e}")
        return None


def get_json(url, api_key):
    try:
        req = urllib.request.Request(url, headers={"xi-api-key": api_key})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"Error GET: {e}")
        return None


def download(url, dest):
    r = subprocess.run(["curl", "-sL", "-o", str(dest), url], timeout=120, capture_output=True)
    return r.returncode == 0 and pathlib.Path(dest).stat().st_size > 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    carpeta = pathlib.Path(sys.argv[1])
    carpeta.mkdir(parents=True, exist_ok=True)
    prompt  = sys.argv[2] if len(sys.argv) > 2 else PROMPT_DEFAULT
    api_key = read_key()

    print(f"\n{'='*58}")
    print(f"  GENERANDO MÚSICA — Enigma Estoica")
    print(f"  Destino : {carpeta}")
    print(f"  Prompt  : {prompt[:70]}...")
    print(f"{'='*58}\n")

    # POST a Suno
    resp = post_json(f"{BASE}/v1s/task/music-generation", api_key, {
        "create_mode":           "simple",
        "gpt_description_prompt": prompt,
        "make_instrumental":     True,
    })

    if not resp or not resp.get("success"):
        print(f"ERROR al crear tarea: {resp}")
        sys.exit(1)

    task_id = resp.get("task_id", "").strip()
    print(f"task_id={task_id} — generando música...")

    # Poll
    audio_urls = []
    start = time.time()
    while time.time() - start < MAX_WAIT_SECONDS:
        time.sleep(POLL_SECONDS)
        data   = get_json(f"{BASE}/v1/task/{task_id}", api_key)
        if not data:
            continue
        inner  = data.get("data") or data
        status = (inner.get("status") or "").strip()
        elapsed = int(time.time() - start)
        print(f"  status={status} ({elapsed}s)")

        if status == "done":
            meta       = inner.get("metadata") or {}
            audio_urls = meta.get("all_audio_urls") or []
            if not audio_urls and meta.get("audio_url"):
                audio_urls = [meta["audio_url"]]
            break
        elif status in ("error", "failed"):
            print(f"ERROR en tarea: {inner.get('error_message', 'desconocido')}")
            sys.exit(1)

    if not audio_urls:
        print("ERROR: No se obtuvieron URLs de audio.")
        sys.exit(1)

    # Descargar variantes
    print(f"\n  {len(audio_urls)} variante(s) disponibles — descargando...\n")
    descargadas = []
    for i, url in enumerate(audio_urls, 1):
        dest = carpeta / f"musica_v{i}.mp3"
        print(f"  [{i}] {url[:70]}...")
        if download(url, dest):
            size = dest.stat().st_size // 1024
            print(f"       ✓ Guardado: {dest} ({size} KB)")
            descargadas.append(str(dest))
        else:
            print(f"       ✗ Falló la descarga")

    print(f"\n{'='*58}")
    print(f"  ✓ {len(descargadas)} pista(s) generadas en: {carpeta}")
    print(f"{'='*58}\n")
    print("  Escuchalas y decime cuál usamos para el canal.")
    print("  Una vez elegida la guardamos como referencia base")
    print("  y el render la mezcla automáticamente a -28 LUFS.\n")


if __name__ == "__main__":
    main()
