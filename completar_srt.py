#!/usr/bin/env python3
"""
completar_srt.py — Transcribe la parte faltante de un MP3 y la fusiona con el SRT existente.

Uso: python3 completar_srt.py seduccion/7_errores/
"""

import sys, re, time, pathlib, subprocess, tempfile, urllib.request, json

HOME     = pathlib.Path.home()
KEY_FILE = HOME / ".assemblyai_key"
BASE     = "https://api.assemblyai.com"
FFMPEG   = "/opt/homebrew/bin/ffmpeg"

if not pathlib.Path(FFMPEG).exists():
    FFMPEG = "/usr/local/bin/ffmpeg"

def read_key():
    k = KEY_FILE.read_text().strip() if KEY_FILE.exists() else ""
    if not k:
        print(f"ERROR: Sin key en {KEY_FILE}"); sys.exit(1)
    return k

def api_post(path, key, payload=None, file_path=None):
    url  = BASE + path
    hdrs = {"authorization": key}
    if file_path:
        data = pathlib.Path(file_path).read_bytes()
        hdrs["Content-Type"] = "application/octet-stream"
    else:
        data = json.dumps(payload).encode()
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())

def api_get(path, key):
    req = urllib.request.Request(BASE + path, headers={"authorization": key})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()

def ts_to_sec(ts):
    ts = ts.strip().replace(',', '.')
    p  = ts.split(':')
    return int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])

def sec_to_ts(s):
    h   = int(s // 3600); s -= h * 3600
    m   = int(s // 60);   s -= m * 60
    ms  = int(round((s % 1) * 1000))
    sec = int(s)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"

def parse_srt(path):
    """Devuelve lista de (num, start_s, end_s, text)"""
    blocks  = re.split(r'\n\n+', pathlib.Path(path).read_text(encoding='utf-8').strip())
    entries = []
    for block in blocks:
        lines = [l for l in block.strip().split('\n') if l.strip()]
        if len(lines) < 3 or '-->' not in lines[1]:
            continue
        ts    = lines[1].split('-->')
        start = ts_to_sec(ts[0])
        end   = ts_to_sec(ts[1])
        text  = ' '.join(lines[2:]).strip()
        entries.append((int(lines[0]), start, end, text))
    return entries

def srt_from_raw(raw_srt, offset_secs):
    """Parsea el SRT devuelto por AssemblyAI y suma offset a todos los timestamps."""
    blocks = re.split(r'\n\n+', raw_srt.strip())
    result = []
    for block in blocks:
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if len(lines) < 3 or '-->' not in lines[1]:
            continue
        ts    = lines[1].split('-->')
        start = ts_to_sec(ts[0]) + offset_secs
        end   = ts_to_sec(ts[1]) + offset_secs
        text  = ' '.join(lines[2:]).strip()
        result.append((start, end, text))
    return result

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 completar_srt.py <carpeta_video>"); sys.exit(1)

    carpeta    = pathlib.Path(sys.argv[1])
    nombre     = carpeta.name
    mp3_file   = carpeta / f"{nombre}.mp3"
    srt_file   = carpeta / f"{nombre}.srt"

    if not mp3_file.exists():
        print(f"ERROR: No existe {mp3_file}"); sys.exit(1)
    if not srt_file.exists():
        print(f"ERROR: No existe {srt_file}"); sys.exit(1)

    # Duración total del MP3
    r = subprocess.run(
        ["/opt/homebrew/bin/ffprobe", "-v", "quiet",
         "-show_entries", "format=duration", "-of", "csv=p=0", str(mp3_file)],
        capture_output=True, text=True
    )
    total_dur = float(r.stdout.strip())

    # Hasta dónde llega el SRT actual
    existing = parse_srt(srt_file)
    srt_end  = existing[-1][2]  # end del último entry

    print(f"Audio total : {total_dur:.1f}s ({total_dur/60:.1f} min)")
    print(f"SRT cubre   : hasta {srt_end:.1f}s ({srt_end/60:.1f} min)")
    print(f"Faltante    : {total_dur - srt_end:.1f}s ({(total_dur - srt_end)/60:.1f} min)")

    if total_dur - srt_end < 5:
        print("✓ El SRT ya cubre todo el audio."); return

    offset = srt_end  # el corte empieza aquí
    key    = read_key()

    # Cortar la parte faltante
    tmp_dir  = pathlib.Path(tempfile.mkdtemp(prefix="srt_faltante_"))
    mp3_cut  = tmp_dir / f"{nombre}_faltante.mp3"
    print(f"\n[0/3] Cortando MP3 desde {offset:.1f}s hasta el final...")
    subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", str(mp3_file), "-ss", str(offset),
        "-acodec", "copy", "-y", str(mp3_cut)
    ], check=True)
    print(f"      Tamaño: {mp3_cut.stat().st_size // 1024} KB")

    # Subir a AssemblyAI
    print("[1/3] Subiendo a AssemblyAI...")
    upload    = api_post("/v2/upload", key, file_path=mp3_cut)
    audio_url = upload["upload_url"]

    # Solicitar transcripción
    print("[2/3] Iniciando transcripción en español...")
    transcript    = api_post("/v2/transcript", key, payload={"audio_url": audio_url, "language_code": "es"})
    transcript_id = transcript["id"]
    print(f"      transcript_id={transcript_id}")

    # Polling
    print("[3/3] Esperando resultado...")
    t0 = time.time()
    while True:
        time.sleep(10)
        hdrs = {"authorization": key}
        req  = urllib.request.Request(f"{BASE}/v2/transcript/{transcript_id}", headers=hdrs)
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = json.loads(resp.read())
        status = raw.get("status", "")
        print(f"      status={status} ({int(time.time()-t0)}s)")
        if status == "completed":
            break
        elif status == "error":
            print(f"ERROR: {raw.get('error')}"); sys.exit(1)

    # Descargar SRT y ajustar timestamps
    hdrs = {"authorization": key}
    req  = urllib.request.Request(f"{BASE}/v2/transcript/{transcript_id}/srt", headers=hdrs)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw_srt = resp.read().decode()

    new_entries = srt_from_raw(raw_srt, offset)
    print(f"\n  Nuevas entradas: {len(new_entries)}")

    # Fusionar: numero SRT continuando desde el último
    last_num = existing[-1][0]
    fused    = srt_file.read_text(encoding='utf-8').rstrip() + "\n\n"
    for i, (start, end, text) in enumerate(new_entries, 1):
        fused += f"{last_num + i}\n{sec_to_ts(start)} --> {sec_to_ts(end)}\n{text}\n\n"

    srt_file.write_text(fused, encoding='utf-8')
    total_entries = last_num + len(new_entries)
    print(f"✓ SRT actualizado: {total_entries} entradas totales")
    print(f"  Cubre hasta: {new_entries[-1][1]:.1f}s")

    # Limpiar temporales
    mp3_cut.unlink(missing_ok=True)
    tmp_dir.rmdir()

    print(f"\nAhora corré el planificador para el rango faltante:")
    print(f"  python3 relanzar_lote.py {carpeta} {offset:.1f} {total_dur:.1f}")

if __name__ == "__main__":
    main()
