#!/usr/bin/env python3
"""
higgsfield_clips.py — Genera clips de imagen con grok_image y los anima
con zoom/pan en ffmpeg (sin gastar créditos de video).

Flujo:
  1. Lee personaje_prompts.csv
  2. Para cada prompt → llama grok_image via MCP (1 crédito)
  3. Descarga la imagen generada
  4. Aplica zoom/pan con ffmpeg → imagenes/N.mp4 (6 segundos)

Uso:
  python3 higgsfield_clips.py /ruta/carpeta/personaje/

Requisito previo (una sola vez):
  higgsfield auth login
"""

import sys, csv, json, pathlib, subprocess, tempfile, time, urllib.request

# ── Config ───────────────────────────────────────────────────────────────────
FFMPEG      = "/opt/homebrew/bin/ffmpeg"
if not pathlib.Path(FFMPEG).exists():
    FFMPEG  = "/usr/local/bin/ffmpeg"

HF_BIN      = "/Users/anyelo/.npm-global/lib/node_modules/@higgsfield/cli/vendor/hf"
MCP_URL     = "https://mcp.higgsfield.ai/mcp"
CLIP_SECS   = 6       # duración del clip animado
POLL_SECS   = 8       # segundos entre polls de status
MAX_WAIT    = 180     # segundos máximo por imagen
# Efecto zoom/pan — z=1.5 FIJO, pan correcto (~16.7% frame) — NUNCA incremental desde 1.0
EFFECTS = [
    "scale=3840:2160,zoompan=z='1.5':x='(iw-iw/1.5)*0.5*(on/{d})':y='ih/2-(ih/1.5/2)':d={d}:s=1920x1080:fps=30,scale=1920:1080",
    "scale=3840:2160,zoompan=z='1.5':x='(iw-iw/1.5)*0.5*(1-on/{d})':y='ih/2-(ih/1.5/2)':d={d}:s=1920x1080:fps=30,scale=1920:1080",
    "scale=3840:2160,zoompan=z='1.5':x='iw/2-(iw/1.5/2)':y='(ih-ih/1.5)*0.5*(on/{d})':d={d}:s=1920x1080:fps=30,scale=1920:1080",
    "scale=3840:2160,zoompan=z='1.5':x='(iw-iw/1.5)*0.5*(on/{d})':y='(ih-ih/1.5)*0.5*(on/{d})':d={d}:s=1920x1080:fps=30,scale=1920:1080",
]

# ── Helpers ──────────────────────────────────────────────────────────────────
VERDE    = "\033[92m"
ROJO     = "\033[91m"
AMARILLO = "\033[93m"
RESET    = "\033[0m"

def ok(msg):    print(f"  {VERDE}✓{RESET} {msg}")
def err(msg):   print(f"  {ROJO}✗{RESET} {msg}")
def info(msg):  print(f"  {AMARILLO}→{RESET} {msg}")

def get_token():
    """Obtiene el OAuth token actual del CLI."""
    r = subprocess.run([HF_BIN, "auth", "token"],
                       capture_output=True, text=True)
    token = r.stdout.strip()
    if not token or "Error" in r.stderr:
        print(f"{ROJO}ERROR: No autenticado. Corre: higgsfield auth login{RESET}")
        sys.exit(1)
    return token

def mcp_call(token, tool_name, arguments, timeout=60):
    """Llama un tool MCP y retorna el structuredContent."""
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments}
    }).encode("utf-8")

    req = urllib.request.Request(
        MCP_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")

    # Parsear SSE: buscar línea "data: {...}"
    for line in raw.splitlines():
        if line.startswith("data:"):
            data = json.loads(line[5:].strip())
            result = data.get("result", {})
            if result.get("isError"):
                sc = result.get("structuredContent", {})
                raise RuntimeError(sc.get("error", "MCP error"))
            return result.get("structuredContent", result.get("content", {}))
    raise RuntimeError("Sin respuesta MCP válida")

def generate_image(token, prompt, aspect_ratio="16:9"):
    """Envía job de grok_image y retorna el job_id."""
    info(f"Generando imagen: {prompt[:70]}...")
    result = mcp_call(token, "generate_image", {
        "params": {
            "model": "grok_image",
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
        }
    }, timeout=30)
    job_id = result.get("job_id") or result.get("id")
    if not job_id:
        # Puede venir en content text
        raise RuntimeError(f"Sin job_id en respuesta: {result}")
    return job_id

def wait_for_job(token, job_id):
    """Polling hasta que el job complete. Retorna rawUrl."""
    start = time.time()
    attempt = 0
    while True:
        attempt += 1
        elapsed = int(time.time() - start)
        result = mcp_call(token, "job_status", {
            "jobId": job_id,
            "sync": True
        }, timeout=40)

        generation = result.get("generation", result)
        status = generation.get("status", "unknown")
        info(f"  status={status} ({elapsed}s)")

        if status == "completed":
            raw_url = generation.get("results", {}).get("rawUrl")
            if not raw_url:
                raise RuntimeError("Job completado pero sin rawUrl")
            return raw_url
        elif status in ("failed", "canceled", "nsfw", "ip_detected"):
            raise RuntimeError(f"Job terminó con status: {status}")

        if elapsed > MAX_WAIT:
            raise RuntimeError(f"Timeout ({MAX_WAIT}s) esperando imagen")

        time.sleep(POLL_SECS)

def download_image(url, dst_path):
    """Descarga imagen desde URL a dst_path."""
    with urllib.request.urlopen(url, timeout=60) as r:
        dst_path.write_bytes(r.read())

def image_to_video(img_path, out_path, effect_index=0):
    """Convierte imagen a video 6s con efecto zoom/pan via ffmpeg."""
    frames = CLIP_SECS * 30  # 180 frames a 30fps
    vf = EFFECTS[effect_index % len(EFFECTS)].format(d=frames)
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-loop", "1", "-framerate", "30",
        "-i", str(img_path),
        "-vf", vf,
        "-t", str(CLIP_SECS),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-an",
        "-y", str(out_path)
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg error: {r.stderr.decode()[:300]}")

def ts_to_sec(t):
    parts = [float(p) for p in str(t).strip().split(":")]
    return parts[0]*3600 + parts[1]*60 + parts[2] if len(parts) == 3 else parts[0]*60 + parts[1]

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print("Uso: python3 higgsfield_clips.py /ruta/carpeta/personaje/")
        sys.exit(1)

    char_folder = pathlib.Path(sys.argv[1])
    nombre      = char_folder.name
    csv_path    = char_folder / f"{nombre}_prompts.csv"
    img_folder  = char_folder / "imagenes"

    if not csv_path.exists():
        print(f"{ROJO}ERROR: No existe {csv_path}{RESET}")
        print("Primero corre: python3 prompts_single.py <carpeta>")
        sys.exit(1)

    img_folder.mkdir(exist_ok=True)

    # Leer CSV
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)

    if not rows:
        print(f"{ROJO}ERROR: CSV vacío{RESET}")
        sys.exit(1)

    print(f"\n{'='*55}")
    print(f"  HIGGSFIELD CLIPS — {nombre.upper()}")
    print(f"  {len(rows)} imágenes | grok_image → zoom/pan ffmpeg")
    print(f"{'='*55}\n")

    token = get_token()
    ok("Token OAuth obtenido")

    resultados = []
    t_total_start = time.time()

    with tempfile.TemporaryDirectory(prefix="hf_imgs_") as tmpdir:
        tmp = pathlib.Path(tmpdir)

        for i, row in enumerate(rows, 1):
            prompt  = row.get("prompt_imagen", "").strip()
            ts_str  = row.get("seg_inicio", "00:00")
            tema    = row.get("tema", "clip")
            out_mp4 = img_folder / f"{i}.mp4"

            print(f"\n[{i}/{len(rows)}] {tema.upper()} @ {ts_str}")

            if not prompt:
                err("Sin prompt — saltando")
                continue

            t_clip = time.time()
            try:
                # 1. Generar imagen
                job_id = generate_image(token, prompt)
                ok(f"Job enviado: {job_id[:8]}...")

                # 2. Esperar resultado
                raw_url = wait_for_job(token, job_id)
                ok(f"Imagen lista: {raw_url[:60]}...")

                # 3. Descargar imagen
                img_tmp = tmp / f"img_{i}.jpg"
                download_image(raw_url, img_tmp)
                ok(f"Descargada: {img_tmp.stat().st_size // 1024} KB")

                # 4. Convertir a video con zoom/pan
                info("Aplicando zoom/pan con ffmpeg...")
                image_to_video(img_tmp, out_mp4, effect_index=i-1)
                dur = time.time() - t_clip
                ok(f"Clip guardado: {out_mp4.name} ({out_mp4.stat().st_size // 1024} KB) en {dur:.0f}s")

                resultados.append({
                    "n": i, "ts": ts_str, "tema": tema,
                    "status": "OK", "file": str(out_mp4)
                })

            except Exception as e:
                err(f"Error: {e}")
                resultados.append({"n": i, "ts": ts_str, "tema": tema, "status": f"ERROR: {e}"})

    # ── Resumen ──────────────────────────────────────────────────────────────
    total_secs = int(time.time() - t_total_start)
    ok_count   = sum(1 for r in resultados if r["status"] == "OK")
    print(f"\n{'='*55}")
    print(f"  RESUMEN — {ok_count}/{len(rows)} clips generados en {total_secs//60}m{total_secs%60}s")
    for r in resultados:
        symbol = f"{VERDE}✓{RESET}" if r["status"] == "OK" else f"{ROJO}✗{RESET}"
        print(f"  {symbol} [{r['n']}] {r['tema'].upper()} @ {r['ts']} — {r['status']}")
    print(f"{'='*55}\n")

    if ok_count < len(rows):
        sys.exit(1)

if __name__ == "__main__":
    main()
