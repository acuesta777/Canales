#!/usr/bin/env python3
"""
tts_epocadeoro.py — TTS para canal La Verdad Dorada.

Concatena todos los TXT numerados del guion en un solo MP3.
Genera sections.json con posición de chars de cada sección.

Estructura esperada:
  00_HOOK.txt
  01_NOMBRE ARTISTA.txt
  ...
  08_CIERRE.txt

Uso: python3 tts_epocadeoro.py /ruta/carpeta/video/
"""

import sys, os, json, time, pathlib, uuid, subprocess
import urllib.request, urllib.error

# ================== CONFIG ==================
PRIMARY_PROVIDER  = "AI33"
FALLBACK_PROVIDER = "AI84"
SPEED             = "1"

# Voz masculina grave autoridad — actualizar ID cuando se defina
EPOCADEORO_VOICE  = "fishaudio_c4f308cb7c934564b789ba475f42e934"

POLL_SECONDS      = 8
MAX_WAIT_SECONDS  = 900
POST_TRIES        = 3
GET_TRIES         = 3
DL_TRIES          = 3

HOME = pathlib.Path.home()

PROVIDERS = {
    "AI33": {
        "base":         "https://api.ai33.pro",
        "tts_path":     "/v3/text-to-speech",
        "task_path":    "/v3/task",
        "key_file":     HOME / ".ai33_key",
    },
    "AI84": {
        "base":         "https://api.ai84.pro",
        "tts_path":     "/v2/text-to-speech",
        "task_path":    "/v2/task",
        "key_file":     HOME / ".ai84_key",
    },
}

# ================== HELPERS ==================
def read_file(path):
    try:
        return pathlib.Path(path).read_text(encoding="utf-8").strip()
    except Exception:
        return ""

def encode_multipart(fields):
    boundary = uuid.uuid4().hex
    body = b""
    for key, value in fields.items():
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode()
        body += str(value).encode("utf-8") + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"

def http_post_form(url, api_key, fields, tries=3):
    body, content_type = encode_multipart(fields)
    headers = {"xi-api-key": api_key, "Content-Type": content_type}
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            print(f"  [POST {attempt}/{tries}] HTTP {e.code}: {e.read().decode('utf-8', errors='ignore')[:200]}")
        except Exception as e:
            print(f"  [POST {attempt}/{tries}] Error: {e}")
        if attempt < tries:
            time.sleep(2 * attempt)
    return None

def http_get_json(url, api_key, tries=3):
    headers = {"xi-api-key": api_key}
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print(f"  [GET {attempt}/{tries}] Error: {e}")
        if attempt < tries:
            time.sleep(2 * attempt)
    return None

def download_file(url, dest_path, tries=3):
    for attempt in range(1, tries + 1):
        try:
            result = subprocess.run(
                ["curl", "-sL", "-o", dest_path, url],
                timeout=180, capture_output=True
            )
            if result.returncode == 0 and os.path.getsize(dest_path) > 0:
                return True
            print(f"  [DOWNLOAD {attempt}/{tries}] curl exit={result.returncode}")
        except Exception as e:
            print(f"  [DOWNLOAD {attempt}/{tries}] Error: {e}")
        if attempt < tries:
            time.sleep(2 * attempt)
    return False

# ================== TTS ==================
def run_tts(provider_name, txt_content, out_mp3):
    cfg     = PROVIDERS[provider_name]
    api_key = read_file(cfg["key_file"])

    if not api_key:
        print(f"[{provider_name}] Sin API key en {cfg['key_file']}")
        return False

    print(f"[{provider_name}] Verificando API...")
    try:
        base_check = cfg["base"].rstrip("/")
        hc_body = json.dumps({"model_id": "krea-2-medium", "generations_count": 1,
                               "model_parameters": {"aspect_ratio": "16:9"}, "assets": 0}).encode()
        req_check = urllib.request.Request(
            f"{base_check}/v1i/task/price", data=hc_body,
            headers={"Content-Type": "application/json", "xi-api-key": api_key}
        )
        with urllib.request.urlopen(req_check, timeout=15) as r:
            r.read()
        print(f"[{provider_name}] ✓ API OK")
    except Exception as e:
        print(f"[{provider_name}] ✗ API NO RESPONDE: {e}")
        return None

    base      = cfg["base"].rstrip("/")
    endpoint  = f"{base}{cfg['tts_path']}"
    task_base = f"{base}{cfg['task_path']}"

    print(f"[{provider_name}] Enviando {len(txt_content):,} chars | voice={EPOCADEORO_VOICE}")
    fields = {
        "text":            txt_content,
        "voice_id":        EPOCADEORO_VOICE,
        "speed":           SPEED,
        "with_transcript": "false",
    }
    response = http_post_form(endpoint, api_key, fields, tries=POST_TRIES)
    if not response:
        return False

    task_id = (response.get("task_id") or "").strip()
    if not task_id:
        print(f"[{provider_name}] Sin task_id. Respuesta: {response}")
        return False

    print(f"[{provider_name}] task_id={task_id} — esperando audio...")
    poll_url  = f"{task_base}/{task_id}"
    audio_url = ""
    start     = time.time()

    while time.time() - start < MAX_WAIT_SECONDS:
        time.sleep(POLL_SECONDS)
        resp = http_get_json(poll_url, api_key, tries=GET_TRIES)
        if not resp:
            continue
        inner  = resp.get("data") or resp
        status = (inner.get("status") or "").strip()
        print(f"  status={status} ({int(time.time()-start)}s)")
        if status == "done":
            meta      = inner.get("metadata") or {}
            audio_url = (meta.get("audio_url") or inner.get("audio_url") or "").strip()
            break
        elif status in ("error", "failed"):
            print(f"[{provider_name}] Error: {inner.get('error_message') or inner.get('error')}")
            return False

    if not audio_url:
        print(f"[{provider_name}] Timeout sin audio_url.")
        return False

    time.sleep(3)
    print(f"[{provider_name}] Descargando MP3...")
    ok = download_file(audio_url, out_mp3)
    if ok:
        size_mb = os.path.getsize(out_mp3) / 1024 / 1024
        print(f"[{provider_name}] ✓ MP3 guardado: {out_mp3} ({size_mb:.1f} MB)")
    return ok

# ================== MAIN ==================
def main():
    if len(sys.argv) < 2:
        print("Uso: python3 tts_epocadeoro.py /ruta/carpeta/video/")
        sys.exit(1)

    folder = pathlib.Path(sys.argv[1])
    if not folder.is_dir():
        print(f"No existe la carpeta: {folder}")
        sys.exit(1)

    out_mp3      = folder / "audio.mp3"
    out_sections = folder / "sections.json"

    if out_mp3.exists() and out_mp3.stat().st_size > 10000:
        print(f"✓ audio.mp3 ya existe ({out_mp3.stat().st_size // 1024} KB) — saltando TTS")
        sys.exit(0)

    # Recopilar TXTs numerados: 00_HOOK.txt, 01_ARTISTA.txt, ..., 08_CIERRE.txt
    txts = sorted(folder.glob("[0-9]*.txt"))
    if not txts:
        print(f"No encontré archivos .txt numerados en: {folder}")
        print("Esperado: 00_HOOK.txt, 01_NOMBRE.txt ... 08_CIERRE.txt")
        sys.exit(1)

    # Verificar largo mínimo del guion (25,000 chars)
    MIN_CHARS = 25000
    print(f"\nArchivos encontrados ({len(txts)}):")
    sections  = []
    full_text = ""
    for txt in txts:
        content    = txt.read_text(encoding="utf-8").strip()
        label      = txt.stem
        char_start = len(full_text)
        full_text  += content + "\n\n"
        char_end   = len(full_text)
        sections.append({"label": label, "file": txt.name, "char_start": char_start, "char_end": char_end})
        print(f"  {txt.name:40s} {len(content):>6,} chars")

    total_chars = len(full_text)
    print(f"\nTotal: {total_chars:,} chars en {len(txts)} secciones")

    if total_chars < MIN_CHARS:
        print(f"\n⚠ GUION CORTO: {total_chars:,} chars (mínimo {MIN_CHARS:,}) — continuando en modo prueba")
        # sys.exit(1)  # desactivado para pruebas parciales

    out_sections.write_text(json.dumps(sections, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ sections.json guardado")

    result = run_tts(PRIMARY_PROVIDER, full_text, str(out_mp3))
    if result is None:
        print("\n⚠ AI33 falló — no se generó audio.")
        print("  ¿Deseas intentar con AI84? (s/n): ", end="", flush=True)
        respuesta = input().strip().lower()
        if respuesta in ("s", "si", "sí", "y", "yes"):
            print("\n[FALLBACK AUTORIZADO] Intentando AI84...")
            result = run_tts(FALLBACK_PROVIDER, full_text, str(out_mp3))
        else:
            print("\n✗ Cancelado por el usuario. Sin audio.")
            sys.exit(2)

    if result:
        print(f"\n✓ TTS completado → {out_mp3}")
        print(f"  Siguiente: srt_single.py → timestamps_epocadeoro.py")
        sys.exit(0)
    else:
        print(f"\n✗ TTS falló.")
        sys.exit(1)

if __name__ == "__main__":
    main()
