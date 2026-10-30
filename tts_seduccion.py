#!/usr/bin/env python3
"""
tts_seduccion.py — TTS para canal Enigma Estoica.
Soporta cualquier proveedor de AI33 v3: minimax_, fishaudio_, edge_, kokoro_, elevenlabs_, clone_

Voice ID se guarda en ~/.ai33_voice_seduccion con el prefijo incluido.
Ejemplo: minimax_male-qn-qingse

Uso:
    python3 tts_seduccion.py seduccion/7_errores/
    python3 tts_seduccion.py seduccion/7_errores/ test
"""

import sys, os, json, time, pathlib, uuid
import urllib.request, urllib.error

# ================== CONFIG ==================
SPEED            = "1"
POLL_SECONDS     = 8
MAX_WAIT_SECONDS = 900
POST_TRIES       = 3
GET_TRIES        = 3
DL_TRIES         = 3

HOME             = pathlib.Path.home()
KEY_FILE         = HOME / ".ai33_key"
VOICE_FILE       = HOME / ".ai33_voice_seduccion"   # prefijo ya incluido en el valor
FALLBACK_VOICE   = HOME / ".ai33_voice_id"           # fallback al voice por defecto

BASE             = "https://api.ai33.pro"
TTS_ENDPOINT     = f"{BASE}/v3/text-to-speech"
TASK_ENDPOINT    = f"{BASE}/v3/task"

VALID_PREFIXES   = ("elevenlabs_", "minimax_", "fishaudio_", "edge_", "kokoro_", "clone_", "vbee_")

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
            print(f"  [POST intento {attempt}/{tries}] HTTP {e.code}: {e.read().decode('utf-8', errors='ignore')[:200]}")
        except Exception as e:
            print(f"  [POST intento {attempt}/{tries}] Error: {e}")
        if attempt < tries:
            time.sleep(2 * attempt)
    return None


def http_get_json(url, api_key, tries=3):
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers={"xi-api-key": api_key})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print(f"  [GET intento {attempt}/{tries}] Error: {e}")
        if attempt < tries:
            time.sleep(2 * attempt)
    return None


def download_file(url, dest, tries=3):
    import subprocess
    for attempt in range(1, tries + 1):
        try:
            r = subprocess.run(["curl", "-sL", "-o", dest, url], timeout=180, capture_output=True)
            if r.returncode == 0 and os.path.getsize(dest) > 0:
                return True
            print(f"  [DOWNLOAD intento {attempt}/{tries}] curl exit={r.returncode}")
        except Exception as e:
            print(f"  [DOWNLOAD intento {attempt}/{tries}] Error: {e}")
        if attempt < tries:
            time.sleep(2 * attempt)
    return False


# ================== TTS ==================
def run_tts(txt_content, out_mp3, api_key, voice_id):
    print(f"[TTS] Enviando {len(txt_content)} chars | voice={voice_id}")

    response = http_post_form(TTS_ENDPOINT, api_key, {
        "text":            txt_content,
        "voice_id":        voice_id,
        "speed":           SPEED,
        "with_transcript": "false",
    }, tries=POST_TRIES)

    if not response:
        print("[TTS] Sin respuesta al POST.")
        return False

    task_id = (response.get("task_id") or "").strip()
    if not task_id:
        print(f"[TTS] No recibí task_id. Respuesta: {response}")
        return False

    print(f"[TTS] task_id={task_id} — esperando audio...")

    poll_url  = f"{TASK_ENDPOINT}/{task_id}"
    audio_url = ""
    start     = time.time()

    while time.time() - start < MAX_WAIT_SECONDS:
        time.sleep(POLL_SECONDS)
        resp = http_get_json(poll_url, api_key, tries=GET_TRIES)
        if not resp:
            continue
        inner  = resp.get("data") or resp
        status = (inner.get("status") or "").strip()
        elapsed = int(time.time() - start)
        print(f"  status={status} ({elapsed}s)")

        if status == "done":
            meta      = inner.get("metadata") or {}
            audio_url = (meta.get("audio_url") or inner.get("audio_url") or "").strip()
            break
        elif status in ("error", "failed"):
            print(f"[TTS] Error en tarea: {inner.get('error_message') or 'desconocido'}")
            return False

    if not audio_url:
        print(f"[TTS] Timeout o sin audio_url después de {int(time.time()-start)}s.")
        return False

    time.sleep(3)
    print(f"[TTS] Descargando de: {audio_url}")
    if not download_file(audio_url, out_mp3):
        print("[TTS] Falló la descarga.")
        return False

    print(f"[TTS] ✓ MP3 guardado: {out_mp3}")
    return True


# ================== MAIN ==================
def main():
    if len(sys.argv) < 2:
        print("Uso: python3 tts_seduccion.py <carpeta_video> [test]")
        sys.exit(1)

    carpeta   = pathlib.Path(sys.argv[1])
    test_mode = len(sys.argv) > 2 and sys.argv[2].lower() == "test"

    if not carpeta.is_dir():
        print(f"No existe la carpeta: {carpeta}")
        sys.exit(1)

    # Buscar .txt del guion
    txts = sorted(carpeta.glob("*.txt"))
    if test_mode:
        tests = [t for t in txts if "_test" in t.name]
        txt_file = tests[0] if tests else (txts[0] if txts else None)
    else:
        mains = [t for t in txts if "_test" not in t.name]
        txt_file = mains[0] if mains else (txts[0] if txts else None)

    if not txt_file:
        print(f"No encontré ningún .txt en: {carpeta}")
        sys.exit(1)

    nombre      = txt_file.stem.replace("_test", "")
    txt_content = txt_file.read_text(encoding="utf-8", errors="ignore")
    out_mp3     = str(carpeta / (f"{nombre}_test.mp3" if test_mode else f"{nombre}.mp3"))

    # Cargar API key
    api_key = read_file(KEY_FILE)
    if not api_key:
        print(f"ERROR: Sin API key en {KEY_FILE}")
        sys.exit(1)

    # Cargar voice_id — si no hay, preguntar interactivamente
    voice_id = read_file(VOICE_FILE)
    if not voice_id:
        print(f"{'='*55}")
        print(f"  NO HAY VOZ CONFIGURADA PARA ENIGMA ESTOICA")
        print(f"{'='*55}")
        print()
        print("  Buscá el ID de voz en:")
        print("  • ElevenLabs  → voice library → copiar ID → prefijo: elevenlabs_<id>")
        print("  • Minimax     → platform.minimax.io/audio/voices → prefijo: minimax_<id>")
        print("  • Fish Audio  → fish.audio → prefijo: fishaudio_<id>")
        print()
        print("  Ejemplos:")
        print("    elevenlabs_TX3LPaxmHKxFdv7VOQHJ")
        print("    minimax_male-qn-qingse")
        print("    fishaudio_abc123def456")
        print()
        try:
            voice_id = input("  Pegá el voice_id (con prefijo): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nCancelado.")
            sys.exit(1)

        if not voice_id:
            print("ERROR: No ingresaste ningún voice_id.")
            sys.exit(1)

        # Validar prefijo antes de guardar
        if not any(voice_id.startswith(p) for p in VALID_PREFIXES):
            print(f"\nERROR: El voice_id '{voice_id}' no tiene prefijo válido.")
            print(f"Prefijos aceptados: {', '.join(VALID_PREFIXES)}")
            sys.exit(1)

        # Guardar para futuras ejecuciones
        VOICE_FILE.write_text(voice_id, encoding="utf-8")
        print(f"\n  ✓ Voz guardada en {VOICE_FILE}")
        print()

    # Validar prefijo del voice_id guardado
    if not any(voice_id.startswith(p) for p in VALID_PREFIXES):
        print(f"ERROR: El voice_id guardado '{voice_id}' no tiene prefijo válido.")
        print(f"Prefijos aceptados: {', '.join(VALID_PREFIXES)}")
        print(f"Corregí el archivo: {VOICE_FILE}")
        sys.exit(1)

    print(f"{'='*55}")
    print(f"  TTS SEDUCCIÓN — Enigma Estoica")
    print(f"  Video   : {nombre}")
    print(f"  Modo    : {'TEST' if test_mode else 'PRODUCCIÓN'}")
    print(f"  Voz     : {voice_id}")
    print(f"  Chars   : {len(txt_content):,}")
    print(f"  Salida  : {out_mp3}")
    print(f"{'='*55}\n")

    # Si MP3 ya existe y es grande, saltar
    if pathlib.Path(out_mp3).exists() and pathlib.Path(out_mp3).stat().st_size > 10000:
        print(f"✓ MP3 ya existe ({pathlib.Path(out_mp3).stat().st_size // 1024} KB) — saltando TTS")
        sys.exit(0)

    ok = run_tts(txt_content, out_mp3, api_key, voice_id)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
