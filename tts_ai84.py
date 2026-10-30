#!/usr/bin/env python3
"""
TTS AI84 — Envía un TXT al API de ai84.pro y descarga el MP3.
Uso: python3 tts_ai84.py /ruta/carpeta/personaje/
     python3 tts_ai84.py /ruta/carpeta/personaje/ test   <- solo envía _test.txt

API: https://api.ai84.pro/v2/text-to-speech/async  (JSON, no multipart)
Key: ~/.ai84_key
Voice: ~/.ai84_voice_id
"""

import sys, os, json, time, pathlib, subprocess
import urllib.request, urllib.error

# ── CONFIG ────────────────────────────────────────────────────────────────────
BASE_URL     = "https://api.ai84.pro"
TTS_PATH     = "/v2/text-to-speech/async"
POLL_PATH    = "/v2/text-to-speech/async/{job_id}"
MODEL_ID     = "eleven_multilingual_v2"
POLL_SECONDS = 10
MAX_WAIT     = 1800   # 30 min máximo
POST_TRIES   = 3
GET_TRIES    = 3
DL_TRIES     = 3

HOME       = pathlib.Path.home()
KEY_FILE   = HOME / ".ai84_key"
VOICE_FILE = HOME / ".ai84_voice_id"
# ─────────────────────────────────────────────────────────────────────────────


def read_file(path):
    try:
        return pathlib.Path(path).read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def http_post_json(url, api_key, payload, tries=POST_TRIES):
    for attempt in range(1, tries + 1):
        try:
            result = subprocess.run(
                [
                    "curl", "-sS", "-X", "POST", url,
                    "-H", f"xi-api-key: {api_key}",
                    "-H", "Content-Type: application/json",
                    "-H", "Accept: application/json",
                    "-d", json.dumps(payload),
                    "--max-time", "90",
                ],
                capture_output=True, timeout=100
            )
            raw = result.stdout.decode("utf-8", errors="ignore").strip()
            if not raw:
                print(f"  [POST intento {attempt}/{tries}] Sin respuesta (stderr: {result.stderr.decode()[:100]})")
            else:
                try:
                    return json.loads(raw)
                except Exception:
                    print(f"  [POST intento {attempt}/{tries}] JSON inválido: {raw[:200]}")
        except Exception as e:
            print(f"  [POST intento {attempt}/{tries}] Error: {e}")
        if attempt < tries:
            time.sleep(3 * attempt)
    return None


def http_get_json(url, api_key, tries=GET_TRIES):
    for attempt in range(1, tries + 1):
        try:
            result = subprocess.run(
                [
                    "curl", "-sS", url,
                    "-H", f"xi-api-key: {api_key}",
                    "-H", "Accept: application/json",
                    "--max-time", "30",
                ],
                capture_output=True, timeout=40
            )
            raw = result.stdout.decode("utf-8", errors="ignore").strip()
            if raw:
                return json.loads(raw)
        except Exception as e:
            print(f"  [GET intento {attempt}/{tries}] Error: {e}")
        if attempt < tries:
            time.sleep(2 * attempt)
    return None


def download_file(url, dest_path, tries=DL_TRIES):
    for attempt in range(1, tries + 1):
        try:
            result = subprocess.run(
                ["curl", "-sL", "-o", str(dest_path), url],
                timeout=300, capture_output=True
            )
            if result.returncode == 0 and os.path.getsize(dest_path) > 0:
                return True
            print(f"  [DOWNLOAD intento {attempt}/{tries}] curl exit={result.returncode}")
        except Exception as e:
            print(f"  [DOWNLOAD intento {attempt}/{tries}] Error: {e}")
        if attempt < tries:
            time.sleep(3 * attempt)
    return False


def health_check(api_key):
    """Verifica que la API de ai84 responde antes de enviar el guion."""
    url = f"{BASE_URL}/v1/models?tts_only=true"
    headers = {"xi-api-key": api_key}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
        return True
    except Exception as e:
        print(f"[AI84] ✗ Health check falló: {e}")
        return False


def run_tts(txt_path, out_mp3):
    api_key  = read_file(KEY_FILE)
    voice_id = read_file(VOICE_FILE)

    if not api_key:
        print(f"[AI84] ✗ Sin API key en {KEY_FILE}")
        return False
    if not voice_id:
        print(f"[AI84] ✗ Sin voice ID en {VOICE_FILE}")
        return False

    # Quitar prefijo "elevenlabs_" si existe (heredado de ai33)
    voice_id = voice_id.removeprefix("elevenlabs_")

    txt_content = read_file(txt_path)
    if not txt_content:
        print(f"[AI84] ✗ Archivo vacío o no encontrado: {txt_path}")
        return False

    # ── POST ──────────────────────────────────────────────────────────────────
    tts_url = f"{BASE_URL}{TTS_PATH}"
    payload = {
        "text":     txt_content,
        "voice_id": voice_id,
        "model_id": MODEL_ID,
    }

    print(f"[AI84] Enviando guion ({len(txt_content):,} chars)...")
    resp = http_post_json(tts_url, api_key, payload)
    if not resp:
        print("[AI84] ✗ POST falló, sin respuesta")
        return False

    job_id = resp.get("job_id") or resp.get("task_id")
    if not job_id:
        print(f"[AI84] ✗ Sin job_id en respuesta: {resp}")
        return False

    print(f"[AI84] ✓ Job creado: {job_id}  (status: {resp.get('status', '?')})")

    # ── POLLING ───────────────────────────────────────────────────────────────
    poll_url = f"{BASE_URL}{POLL_PATH.format(job_id=job_id)}"
    audio_url = ""
    start = time.time()

    while time.time() - start < MAX_WAIT:
        time.sleep(POLL_SECONDS)
        data = http_get_json(poll_url, api_key)
        if not data:
            continue

        job    = data.get("job") or data
        status = (job.get("status") or "").strip()
        elapsed = int(time.time() - start)
        print(f"  status={status} ({elapsed}s)")

        if status == "done":
            audio_url = (job.get("audioUrl") or job.get("audio_url") or "").strip()
            break
        elif status in ("error", "failed"):
            err = job.get("errorMessage") or job.get("error_message") or "error en tarea"
            print(f"[AI84] ✗ Error en job: {err}")
            return False

    if not audio_url:
        print(f"[AI84] ✗ Timeout ({MAX_WAIT}s) sin audioUrl")
        return False

    # ── DOWNLOAD ──────────────────────────────────────────────────────────────
    print(f"[AI84] Descargando MP3...")
    if not download_file(audio_url, out_mp3):
        print(f"[AI84] ✗ Descarga fallida")
        return False

    size_mb = os.path.getsize(out_mp3) / 1_048_576
    print(f"[AI84] ✓ MP3 guardado: {out_mp3}  ({size_mb:.1f} MB)")
    return True


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print("Uso: python3 tts_ai84.py /ruta/carpeta/personaje/ [test]")
        sys.exit(1)

    folder   = pathlib.Path(sys.argv[1].rstrip("/"))
    test_mode = len(sys.argv) > 2 and sys.argv[2] == "test"

    if not folder.is_dir():
        print(f"✗ Carpeta no encontrada: {folder}")
        sys.exit(1)

    personaje = folder.name

    if test_mode:
        txt_path = folder / f"{personaje}_test.txt"
    else:
        txt_path = folder / f"{personaje}.txt"

    if not txt_path.exists():
        print(f"✗ Archivo no encontrado: {txt_path}")
        sys.exit(1)

    out_mp3 = folder / f"{personaje}.mp3"

    print(f"{'='*55}")
    print(f"  TTS AI84 — {personaje}")
    print(f"  Texto : {txt_path.name}")
    print(f"  Salida: {out_mp3.name}")
    print(f"{'='*55}")

    ok = run_tts(str(txt_path), str(out_mp3))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
