#!/usr/bin/env python3
"""
TTS Single — Envía un TXT al API de AI33 (con fallback a AI84) y descarga el MP3.
Uso: python3 tts_single.py /ruta/carpeta/personaje/
     python3 tts_single.py /ruta/carpeta/personaje/ test   <- envía solo el archivo _test.txt

Motor AI84 (default: elevenlabs):
  AI84_ENGINE=elevenlabs  voice en ~/.ai84_voice_id    (eleven_multilingual_v2)
  AI84_ENGINE=minimax     voice en ~/.minimax_voice_id  (speech-02-hd)

Ejemplo con MiniMax:
  AI84_ENGINE=minimax python3 tts_single.py riqueza/pipino_cuevas/
"""

import sys, os, json, time, pathlib, uuid, subprocess
import urllib.request, urllib.error

# ================== CONFIG ==================
PRIMARY_PROVIDER  = "AI33"
FALLBACK_PROVIDER = "AI84"
SPEED             = "0.95"
POLL_SECONDS      = 8
MAX_WAIT_SECONDS  = 900
POST_TRIES        = 3
GET_TRIES         = 3
DL_TRIES          = 3

# Motor de síntesis para AI84: "elevenlabs" (default) o "minimax"
# Cambiar aquí o pasar env var AI84_ENGINE=minimax antes de correr el script
AI84_ENGINE = os.environ.get("AI84_ENGINE", "elevenlabs").lower()

HOME = pathlib.Path.home()

PROVIDERS = {
    "AI33": {
        "base":         "https://api.ai33.pro",
        "tts_path":     "/v3/text-to-speech",
        "task_path":    "/v3/task",
        "key_file":     HOME / ".ai33_key",
        "voice_file":   HOME / ".ai33_voice_id",
        "voice_prefix": "fishaudio_",
    },
    "AI84": {
        "base":         "https://api.ai84.pro",
        "tts_path":     "/v2/text-to-speech/async",
        "task_path":    "/v2/text-to-speech/async",   # poll: GET {task_path}/{job_id}
        "key_file":     HOME / ".ai84_key",
        # voice_file se elige dinámicamente según AI84_ENGINE
        "voice_file_elevenlabs": HOME / ".ai84_voice_id",
        "voice_file_minimax":    HOME / ".minimax_voice_id",
        "voice_prefix": "",
    },
}

# Elegir voice_file de AI84 según motor
PROVIDERS["AI84"]["voice_file"] = (
    PROVIDERS["AI84"]["voice_file_minimax"]
    if AI84_ENGINE == "minimax"
    else PROVIDERS["AI84"]["voice_file_elevenlabs"]
)

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
    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type

def http_post_json(url, api_key, payload, tries=3):
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "xi-api-key":   api_key,
        "Content-Type": "application/json",
        "Accept":       "application/json",
        "User-Agent":   "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Origin":       "https://ai84.pro",
        "Referer":      "https://ai84.pro/",
    }
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body_err = e.read().decode("utf-8", errors="ignore")
            print(f"  [POST intento {attempt}/{tries}] HTTP {e.code}: {body_err[:200]}")
        except Exception as e:
            print(f"  [POST intento {attempt}/{tries}] Error: {e}")
        if attempt < tries:
            time.sleep(2 * attempt)
    return None

def http_post_form(url, api_key, fields, tries=3):
    body, content_type = encode_multipart(fields)
    headers = {
        "xi-api-key": api_key,
        "Content-Type": content_type,
    }
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body_err = e.read().decode("utf-8", errors="ignore")
            print(f"  [POST intento {attempt}/{tries}] HTTP {e.code}: {body_err[:200]}")
        except Exception as e:
            print(f"  [POST intento {attempt}/{tries}] Error: {e}")
        if attempt < tries:
            time.sleep(2 * attempt)
    return None

def http_get_json(url, api_key, tries=3, browser_headers=False):
    headers = {"xi-api-key": api_key}
    if browser_headers:
        headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Origin":     "https://ai84.pro",
            "Referer":    "https://ai84.pro/",
            "Accept":     "application/json",
        })
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print(f"  [GET intento {attempt}/{tries}] Error: {e}")
        if attempt < tries:
            time.sleep(2 * attempt)
    return None

def download_file(url, dest_path, api_key=None, tries=3):
    import subprocess
    for attempt in range(1, tries + 1):
        try:
            result = subprocess.run(
                ["curl", "-sL", "-o", dest_path, url],
                timeout=180, capture_output=True
            )
            if result.returncode == 0 and os.path.getsize(dest_path) > 0:
                return True
            print(f"  [DOWNLOAD intento {attempt}/{tries}] curl exit={result.returncode}")
        except Exception as e:
            print(f"  [DOWNLOAD intento {attempt}/{tries}] Error: {e}")
        if attempt < tries:
            time.sleep(2 * attempt)
    return False

# ================== TTS POR PROVIDER ==================
def run_tts(provider_name, txt_content, out_mp3):
    cfg = PROVIDERS.get(provider_name)
    if not cfg:
        print(f"[{provider_name}] Provider desconocido.")
        return False

    api_key  = read_file(cfg["key_file"])
    voice_id = cfg.get("_canal_voice_id") or read_file(cfg["voice_file"])

    if not api_key:
        print(f"[{provider_name}] Sin API key en {cfg['key_file']}")
        return False
    if not voice_id:
        print(f"[{provider_name}] Sin voice ID en {cfg['voice_file']}")
        return False

    # Health check — verificar que la API responde antes de enviar el guion
    # Solo aplica a AI33 (usa /v1i/task/price); AI84 no tiene ese endpoint
    if provider_name == "AI33":
        print(f"[{provider_name}] Verificando API...")
        try:
            import json as _json
            base_check = cfg["base"].rstrip("/")
            hc_body = _json.dumps({"model_id": "krea-2-medium", "generations_count": 1,
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
            print(f"\n{'='*55}")
            print(f"  ⚠ AI33 CAÍDO — ESPERANDO INSTRUCCIONES")
            print(f"  Confirma si deseas cambiar a AI84")
            print(f"{'='*55}")
            return None  # señal de caída — main sale con exit code 2
    else:
        print(f"[{provider_name}] Saltando health check — enviando directo...")

    # Añadir prefijo de provider si no lo tiene ya
    prefix = cfg["voice_prefix"]
    full_voice_id = voice_id if (not prefix or voice_id.startswith(prefix)) else f"{prefix}{voice_id}"

    base      = cfg["base"].rstrip("/")
    endpoint  = f"{base}{cfg['tts_path']}"
    task_base = f"{base}{cfg['task_path']}"

    # 1. POST — AI84 usa JSON async; AI33 usa FormData
    # ⚠️ AI84: si ya hay un job_id guardado en disco, saltamos el POST para no gastar créditos
    job_id_file = pathlib.Path(out_mp3).parent / ".tts_job_id"
    saved_job_id = ""
    if provider_name == "AI84" and job_id_file.exists():
        saved_job_id = job_id_file.read_text().strip()
        if saved_job_id:
            print(f"[{provider_name}] Reanudando job existente: {saved_job_id} (sin nuevo POST)")

    print(f"[{provider_name}] Enviando texto ({len(txt_content)} chars) | voice={full_voice_id}")

    if provider_name == "AI84" and saved_job_id:
        # Reanudar — no mandamos POST
        response = None
    elif provider_name == "AI84":
        if AI84_ENGINE == "minimax":
            # MiniMax T2A v2 vía AI84
            payload = {
                "text":     txt_content,
                "voice_id": full_voice_id,
                "model_id": "speech-02-hd",
                "with_transcript": False,
                "voice_setting": {
                    "speed": float(SPEED),
                    "vol":   1.0,
                    "pitch": 0,
                },
            }
            print(f"[{provider_name}] Engine: MiniMax (speech-02-hd)")
        else:
            # ElevenLabs vía AI84 (default)
            payload = {
                "text":     txt_content,
                "voice_id": full_voice_id,
                "model_id": "eleven_multilingual_v2",
                "with_transcript": False,
                "voice_settings": {
                    "stability":        0.5,
                    "similarity_boost": 0.75,
                    "style":            0,
                    "speed":            float(SPEED),
                    "use_speaker_boost": True,
                },
            }
            print(f"[{provider_name}] Engine: ElevenLabs (eleven_multilingual_v2)")
        response = http_post_json(endpoint, api_key, payload, tries=POST_TRIES)
    else:
        fields = {
            "text":            txt_content,
            "voice_id":        full_voice_id,
            "speed":           SPEED,
            "with_transcript": "false",
        }
        response = http_post_form(endpoint, api_key, fields, tries=POST_TRIES)

    if provider_name == "AI84":
        if saved_job_id:
            job_id = saved_job_id
        else:
            if not response:
                print(f"[{provider_name}] Sin respuesta al POST.")
                return False
            job_id = (response.get("job_id") or "").strip()
            if not job_id:
                print(f"[{provider_name}] No recibí job_id. Respuesta: {response}")
                return False
            # Guardar en disco para poder reanudar si el proceso muere
            job_id_file.write_text(job_id)
        poll_url = f"{task_base}/{job_id}"
        print(f"[{provider_name}] job_id={job_id} — esperando audio...")
    else:
        task_id = (response.get("task_id") or "").strip()
        if not task_id:
            print(f"[{provider_name}] No recibí task_id. Respuesta: {response}")
            return False
        # ⛔ Guardar task_id en disco para que un relanzamiento no reenvíe el job
        job_id_file.write_text(task_id)
        poll_url = f"{task_base}/{task_id}"
        print(f"[{provider_name}] task_id={task_id} — esperando audio...")

    # 2. POLL — esperar que el task esté done
    audio_url = ""
    start     = time.time()

    while time.time() - start < MAX_WAIT_SECONDS:
        time.sleep(POLL_SECONDS)
        resp = http_get_json(poll_url, api_key, tries=GET_TRIES,
                             browser_headers=(provider_name == "AI84"))
        if not resp:
            continue

        elapsed = int(time.time() - start)

        if provider_name == "AI84":
            # Respuesta: { "success": true, "job": { "status": "done", "audioUrl": "..." } }
            job = resp.get("job") or {}
            status = (job.get("status") or "").strip()
            print(f"  status={status} ({elapsed}s)")
            if status == "done":
                audio_url = (job.get("audioUrl") or "").strip()
                break
            elif status == "failed":
                print(f"[{provider_name}] Tarea fallida: {job}")
                return False
        else:
            # Respuesta AI33: puede venir en "data" o en raíz
            inner = resp.get("data") or resp
            status = (inner.get("status") or "").strip()
            print(f"  status={status} ({elapsed}s)")
            if status == "done":
                meta = inner.get("metadata") or {}
                audio_url = (meta.get("audio_url") or inner.get("audio_url") or "").strip()
                break
            elif status in ("error", "failed"):
                err = inner.get("error_message") or inner.get("error") or "error en tarea"
                print(f"[{provider_name}] Error en tarea: {err}")
                return False

    if not audio_url:
        print(f"[{provider_name}] Timeout o sin audio_url después de {int(time.time()-start)}s.")
        return False

    # 3. DOWNLOAD — esperar 3s extra por si el CDN aún no propagó el archivo
    time.sleep(3)
    print(f"[{provider_name}] Descargando de: {audio_url}")
    ok = download_file(audio_url, out_mp3, api_key=api_key, tries=DL_TRIES)
    if not ok:
        print(f"[{provider_name}] Falló la descarga.")
        return False

    print(f"[{provider_name}] ✓ MP3 guardado en: {out_mp3}")
    # Limpiar job_id guardado — el MP3 ya existe, el próximo run empieza limpio
    if job_id_file.exists():
        job_id_file.unlink()
    return True

# ================== MAIN ==================
def main():
    if len(sys.argv) < 2:
        print("Uso: python3 tts_single.py /ruta/carpeta/personaje/ [test] [--confirmar]")
        sys.exit(1)

    args = sys.argv[1:]
    confirmar = "--confirmar" in args
    auto_fallback = "--auto-fallback" in args
    args = [a for a in args if a not in ("--confirmar", "--auto-fallback")]

    char_folder = pathlib.Path(args[0])
    test_mode   = len(args) > 1 and args[1].lower() == "test"

    if not char_folder.is_dir():
        print(f"No existe la carpeta: {char_folder}")
        sys.exit(1)

    # --confirmar solo se usa cuando el MP3 ya existe (relanzamiento/corrección)

    txts = sorted(char_folder.glob("*.txt"))

    if test_mode:
        # En modo test: preferir el _test.txt
        test_txts = [t for t in txts if "_test" in t.name]
        txt_file  = test_txts[0] if test_txts else (txts[0] if txts else None)
    else:
        # Modo normal: preferir el que NO es _test
        main_txts = [t for t in txts if "_test" not in t.name]
        txt_file  = main_txts[0] if main_txts else (txts[0] if txts else None)

    if not txt_file:
        print(f"No encontré ningún .txt en: {char_folder}")
        sys.exit(1)

    char_name   = txt_file.stem.replace("_test", "")
    txt_content = txt_file.read_text(encoding="utf-8", errors="ignore")

    # Leer voz del config del canal si existe — inyectar directamente sin tocar ~/.ai33_voice_id
    try:
        import json as _json
        _base_dir = pathlib.Path(__file__).parent
        _canal = char_folder.parent.name  # ej: "secretos-mexicanos"
        _cfg_file = _base_dir / "_config" / f"{_canal}.json"
        if _cfg_file.exists():
            _canal_cfg = _json.loads(_cfg_file.read_text())
            _voz = _canal_cfg.get("voz", {}).get("voice_id", "")
            if _voz:
                # Inyectar directamente en PROVIDERS sin sobrescribir el archivo global
                PROVIDERS["AI33"]["_canal_voice_id"] = _voz
                PROVIDERS["AI84"]["_canal_voice_id"] = _voz
                print(f"Voz canal  : {_voz} (desde _config/{_canal}.json)")
    except Exception as _e:
        print(f"[WARN] No se pudo leer voz del canal: {_e}")

    # ⛔ REGLA DURA: la primera línea NO puede ser el título del video
    primera_linea = txt_content.lstrip().split('\n')[0].strip()
    if len(primera_linea) > 40 and ('...' in primera_linea or primera_linea.isupper() or any(c in primera_linea for c in ['DESTRUYÓ','ASQUEROSO','BRUTAL','ESCALOFRIANTE','BORRÓ','DESTRUYO'])):
        print(f"⛔ ERROR: La primera línea del guion parece ser el título del video.")
        print(f"   Primera línea: {primera_linea[:80]}")
        print(f"   El guion debe empezar directo con la narración (lugar + fecha).")
        print(f"   El título va SOLO en 07-metadatos/upload_pack.json.")
        sys.exit(1)
    # Verificación genérica: primera línea no debe tener el patrón "Artista: algo..."
    import re as _re
    if _re.match(r'^[A-ZÁÉÍÓÚÑ][^:]{3,40}:.{10,}', primera_linea):
        print(f"⛔ ERROR: La primera línea del guion parece ser el título del video.")
        print(f"   Primera línea: {primera_linea[:80]}")
        print(f"   El guion debe empezar directo con la narración (lugar + fecha).")
        print(f"   El título va SOLO en 07-metadatos/upload_pack.json.")
        sys.exit(1)

    # Verificar que no haya dígitos sueltos (el TTS los lee en inglés)
    digitos = _re.findall(r'\b\d+\b', txt_content)
    if digitos:
        print(f"⛔ ERROR: El guion tiene {len(digitos)} número(s) en dígitos — el TTS los leerá en inglés.")
        print(f"   Ejemplos: {digitos[:10]}")
        print(f"   Escríbelos en letras antes de continuar.")
        sys.exit(1)

    if test_mode:
        out_mp3 = str(char_folder / f"{char_name}_test.mp3")
    else:
        out_mp3 = str(char_folder / f"{char_name}.mp3")

    print(f"Modo      : {'TEST' if test_mode else 'PRODUCCIÓN'}")
    print(f"Personaje : {char_name}")
    print(f"TXT       : {txt_file}")
    print(f"Salida MP3: {out_mp3}")
    print("-" * 50)

    # ⛔ REGLA DURA: si ya hay un job enviado (timeout anterior), NO reenviar — retomar o esperar
    job_id_file = char_folder / ".tts_job_id"
    if job_id_file.exists() and not confirmar:
        job_id = job_id_file.read_text().strip()
        if job_id:
            print("=" * 60)
            print("  ⛔  JOB TTS YA ENVIADO — NO SE REENVÍA")
            print("=" * 60)
            print(f"  Job activo: {job_id}")
            print(f"  El TTS anterior pudo haber hecho timeout pero el job")
            print(f"  sigue procesándose en el servidor (se gastarían créditos dobles).")
            print()
            print(f"  Opciones:")
            print(f"  1. Espera y vuelve a correr este script — retomará el job existente.")
            print(f"  2. Si el job falló definitivamente, borra {job_id_file} y relanza.")
            print("=" * 60)
            sys.exit(3)

    # Si el MP3 ya existe, requiere --confirmar para relanzar (evita gastar créditos por error)
    if pathlib.Path(out_mp3).exists() and pathlib.Path(out_mp3).stat().st_size > 10000:
        if not confirmar and not test_mode:
            print("=" * 60)
            print("  ⚠  MP3 YA EXISTE — ¿Relanzar y sobreescribir?")
            print("=" * 60)
            print(f"  Archivo : {out_mp3} ({pathlib.Path(out_mp3).stat().st_size // 1024} KB)")
            print()
            print("  Si corregiste el guion y quieres regenerar, pasa --confirmar:")
            print(f"  python3 tts_single.py {args[0]} --confirmar")
            print("=" * 60)
            sys.exit(2)
        print(f"✓ MP3 ya existe ({pathlib.Path(out_mp3).stat().st_size // 1024} KB) — saltando TTS")
        success = True
    else:
        result = run_tts(PRIMARY_PROVIDER, txt_content, out_mp3)
        # Si AI33 caído (None) o falló (False), preguntar antes de usar AI84
        if result is None or result is False:
            print(f"\n⚠ AI33 falló — no se generó audio.")
            if auto_fallback:
                respuesta = "s"
                print(f"  [--auto-fallback] Usando AI84 automáticamente.")
            else:
                print(f"  ¿Deseas intentar con AI84? (s/n): ", end="", flush=True)
                respuesta = input().strip().lower()
            if respuesta in ("s", "si", "sí", "y", "yes"):
                print(f"\n[FALLBACK AUTORIZADO] Intentando AI84...")
                result = run_tts(FALLBACK_PROVIDER, txt_content, out_mp3)
                if result is None:
                    print(f"\n✗ AI84 también cayó. Sin audio.")
                    sys.exit(2)
            else:
                print(f"\n✗ Cancelado por el usuario. Sin audio.")
                sys.exit(2)
        success = result

    if success:
        print(f"\n✓ Proceso completado: {os.path.basename(out_mp3)}")
        sys.exit(0)
    else:
        print(f"\n✗ TTS falló en todos los providers. Sin audio.")
        sys.exit(1)

if __name__ == "__main__":
    main()
