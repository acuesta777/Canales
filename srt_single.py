#!/usr/bin/env python3
"""
SRT Single — Transcribe un MP3 con AssemblyAI y guarda el SRT en la misma carpeta.
Uso: python3 srt_single.py /ruta/carpeta/personaje/
"""

import sys, time, pathlib, subprocess, tempfile, urllib.request, urllib.error, json, re, argparse

HOME    = pathlib.Path.home()
KEY_FILE = HOME / ".assemblyai_key"
BASE    = "https://api.assemblyai.com"
CONFIG_DIR = pathlib.Path(__file__).parent / "_config"

FFMPEG       = "/opt/homebrew/bin/ffmpeg"
FFPROBE      = "/opt/homebrew/bin/ffprobe"
CUT_SECONDS_DEFAULT   = 600   # primeros 10 min — para canales largos (seducción ~18 min)
MIN_MP3_DURATION_DEFAULT = 720
MIN_SRT_COVERAGE  = 0.75

if not pathlib.Path(FFMPEG).exists():
    FFMPEG = "/usr/local/bin/ffmpeg"
if not pathlib.Path(FFPROBE).exists():
    FFPROBE = "/usr/local/bin/ffprobe"

def get_duration(path):
    """Devuelve duración en segundos usando ffprobe. Lanza RuntimeError si falla."""
    result = subprocess.run([
        FFPROBE, "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(path)
    ], capture_output=True, text=True, timeout=30)
    raw = result.stdout.strip()
    if not raw:
        raise RuntimeError(f"ffprobe no devolvió duración para {path}")
    return float(raw)

def srt_end_seconds(srt_text):
    """Extrae el timestamp final del SRT en segundos."""
    timestamps = re.findall(r"(\d{2}):(\d{2}):(\d{2}),(\d{3}) -->", srt_text)
    if not timestamps:
        return 0.0
    h, m, s, ms = timestamps[-1]
    return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000

def alert(msg):
    """Imprime alerta."""
    print(f"\n🚨 ALERTA SRT: {msg}")

def read_key():
    key = KEY_FILE.read_text().strip() if KEY_FILE.exists() else ""
    if not key:
        print(f"ERROR: Sin API key en {KEY_FILE}")
        sys.exit(1)
    return key

def api_post(path, headers, payload=None, file_path=None):
    url = BASE + path
    if file_path:
        data = pathlib.Path(file_path).read_bytes()
        headers["Content-Type"] = "application/octet-stream"
    else:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))

def api_get(path, headers):
    req = urllib.request.Request(BASE + path, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

def api_get_text(path, headers):
    req = urllib.request.Request(BASE + path, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")

def load_canal_config(canal: str) -> dict:
    if not canal:
        return {}
    cfg_path = CONFIG_DIR / f"{canal}.json"
    if cfg_path.exists():
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    return {}

def main():
    parser = argparse.ArgumentParser(description="SRT Single — transcribe MP3 con AssemblyAI")
    parser.add_argument("carpeta", help="Carpeta del video")
    parser.add_argument("--canal", default="", help="Nombre del canal para leer config (ej: botica)")
    args = parser.parse_args()

    char_folder = pathlib.Path(args.carpeta)
    if not char_folder.is_dir():
        print(f"ERROR: No existe: {char_folder}")
        sys.exit(1)

    # Leer parámetros del config del canal
    cfg = load_canal_config(args.canal)
    srt_cfg = cfg.get("srt", {})
    CUT_SECONDS = srt_cfg.get("cut_seconds", CUT_SECONDS_DEFAULT)
    MIN_MP3_DURATION = srt_cfg.get("min_mp3_duration", MIN_MP3_DURATION_DEFAULT)
    if args.canal:
        print(f"Canal: {args.canal} | corte={CUT_SECONDS}s | min_dur={MIN_MP3_DURATION}s")

    # Encontrar el MP3
    mp3s = sorted([f for f in char_folder.glob("*.mp3") if "_test" not in f.name and "_src" not in f.name])
    if not mp3s:
        print(f"ERROR: No encontré ningún .mp3 en {char_folder}")
        sys.exit(1)
    mp3_file = mp3s[0]
    char_name = mp3_file.stem
    out_srt = char_folder / f"{char_name}.srt"

    key = read_key()
    headers = {"authorization": key}

    print(f"Personaje : {char_name}")
    print(f"MP3       : {mp3_file}")
    print(f"Salida SRT: {out_srt}")
    print("-" * 50)

    # VALIDACIÓN 1: duración del MP3 original
    try:
        mp3_duration = get_duration(mp3_file)
    except Exception as e:
        alert(f"No se pudo medir duración del MP3 ({e}). Abortando.")
        sys.exit(1)
    print(f"[PRE] Duración MP3: {mp3_duration:.1f}s ({mp3_duration/60:.1f} min)")
    if mp3_duration < MIN_MP3_DURATION:
        msg = (f"MP3 dura solo {mp3_duration:.0f}s ({mp3_duration/60:.1f} min) — "
               f"se esperaban al menos {MIN_MP3_DURATION//60} min. "
               f"¿El TTS terminó de escribir? Abortando.")
        alert(msg)
        sys.exit(1)

    # Cortar MP3 a los primeros 10 min en archivo temporal
    tmp_dir = tempfile.mkdtemp(prefix="srt_cut_")
    mp3_cut = pathlib.Path(tmp_dir) / f"{char_name}_10min.mp3"
    print(f"[0/3] Cortando MP3 a {CUT_SECONDS//60} min para AssemblyAI...")
    subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", str(mp3_file),
        "-t", str(CUT_SECONDS),
        "-acodec", "libmp3lame", "-ar", "22050", "-ab", "64k",
        "-y", str(mp3_cut)
    ], check=True)
    cut_kb = mp3_cut.stat().st_size // 1024
    print(f"      Cortado: {cut_kb} KB")

    # VALIDACIÓN 2: duración del corte
    try:
        cut_duration = get_duration(mp3_cut)
    except Exception as e:
        alert(f"No se pudo medir duración del corte ({e}).")
        cut_duration = 0.0
    print(f"      Duración corte: {cut_duration:.1f}s ({cut_duration/60:.1f} min)")
    expected_cut = min(CUT_SECONDS, mp3_duration)
    if cut_duration < expected_cut * 0.85:
        msg = (f"El corte de audio duró solo {cut_duration:.0f}s "
               f"(se esperaban ~{expected_cut:.0f}s). ffmpeg cortó mal.")
        alert(msg)
        sys.exit(1)

    # 1. Subir el MP3 cortado
    print("[1/3] Subiendo MP3 a AssemblyAI...")
    upload = api_post("/v2/upload", {"authorization": key}, file_path=mp3_cut)
    audio_url = upload["upload_url"]
    print(f"      Audio URL obtenida")

    # 2. Solicitar transcripción
    print("[2/3] Iniciando transcripción en español...")
    transcript = api_post("/v2/transcript", headers,
                          payload={"audio_url": audio_url, "language_code": "es"})
    transcript_id = transcript["id"]
    print(f"      transcript_id={transcript_id}")

    # 3. Polling
    print("[3/3] Esperando resultado...")
    start = time.time()
    while True:
        time.sleep(10)
        resp = api_get(f"/v2/transcript/{transcript_id}", headers)
        status = resp.get("status", "")
        elapsed = int(time.time() - start)
        print(f"      status={status} ({elapsed}s)")
        if status == "completed":
            break
        elif status == "error":
            print(f"ERROR: {resp.get('error', 'desconocido')}")
            sys.exit(1)

    # Descargar SRT
    srt_content = api_get_text(f"/v2/transcript/{transcript_id}/srt", headers)
    out_srt.write_text(srt_content, encoding="utf-8")
    lines = srt_content.count("\n")

    # VALIDACIÓN 3: cobertura del SRT
    srt_end = srt_end_seconds(srt_content)
    min_expected = cut_duration * MIN_SRT_COVERAGE
    print(f"\n      SRT cubre hasta: {srt_end:.1f}s ({srt_end/60:.1f} min)")
    if srt_end < min_expected:
        msg = (f"SRT solo cubre {srt_end:.0f}s ({srt_end/60:.1f} min) de los {cut_duration:.0f}s "
               f"del corte. Posible problema con AssemblyAI (saldo, error silencioso, audio roto). "
               f"Personaje: {char_name}")
        alert(msg)
        # No abortamos — el SRT parcial puede ser útil, pero el pipeline debe saberlo
        print(f"⚠️  Pipeline continuará con SRT parcial — verificar manualmente.")
    else:
        print(f"✓ Cobertura SRT OK ({srt_end/60:.1f} min ≥ {min_expected/60:.1f} min mínimo)")

    print(f"✓ SRT guardado: {out_srt} ({lines} líneas, primeros {CUT_SECONDS//60} min)")
    # Limpiar temporal
    mp3_cut.unlink(missing_ok=True)
    try:
        pathlib.Path(tmp_dir).rmdir()
    except OSError:
        pass

if __name__ == "__main__":
    main()
