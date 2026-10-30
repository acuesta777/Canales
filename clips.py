#!/usr/bin/env python3
"""
CLIPS — Descarga un video de YouTube y genera clips de 5s reordenados.
Uso: python3 clips.py <youtube_url> <carpeta_personaje>

Flujo:
  1. Descarga el video con yt-dlp
  2. Corta en clips de 5s con ffmpeg
  3. Detecta y recorta cambios bruscos al inicio/fin de cada clip
  4. Reordena con Fisher-Yates + derangement garantizado
  5. Guarda en <carpeta_personaje>/clips/ como 1.mp4, 2.mp4...
"""

import sys, os, re, glob, json, random, subprocess, pathlib

# ================== CONFIG ==================
CLIP_DURATION    = 5        # segundos por clip (fijo)
SCENE_THRESHOLD  = 0.35     # detección de cortes bruscos (medio)
SCENE_MARGIN     = 0.15     # segundos a recortar alrededor del corte
MIN_CLIP_DUR     = 1.5      # clips más cortos que esto se eliminan
YT_FORMAT        = "bestvideo[ext=mp4][height>=720]+bestaudio[ext=m4a]/bestvideo[ext=mp4][height>=480]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"

# Paths de herramientas
YTDLP   = "/opt/homebrew/bin/yt-dlp"
FFMPEG  = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"

# Fallback Intel
if not pathlib.Path(YTDLP).exists():
    YTDLP = "/usr/local/bin/yt-dlp"
if not pathlib.Path(FFMPEG).exists():
    FFMPEG = "/usr/local/bin/ffmpeg"
if not pathlib.Path(FFPROBE).exists():
    FFPROBE = "/usr/local/bin/ffprobe"

# ================== HELPERS ==================
def run(cmd, check=True, capture=False):
    kwargs = dict(check=check)
    if capture:
        kwargs["capture_output"] = True
        kwargs["text"] = True
    return subprocess.run(cmd, **kwargs)

def check_tools():
    for tool, path in [("yt-dlp", YTDLP), ("ffmpeg", FFMPEG), ("ffprobe", FFPROBE)]:
        if not pathlib.Path(path).exists():
            print(f"ERROR: {tool} no encontrado en {path}")
            print(f"  Instala con: brew install {tool.replace('yt-dlp','yt-dlp') if 'yt' in tool else tool}")
            sys.exit(1)

# ================== PASO 1: DESCARGA ==================
def download_video(url, tmp_dir):
    print(f"[DESCARGA] URL: {url}")

    # Obtener el nombre exacto del archivo ANTES de descargar
    r = run([YTDLP, "--no-playlist", "--get-filename",
             "-o", "%(title)s.%(ext)s", url], capture=True, check=False)
    expected_name = r.stdout.strip() if r.returncode == 0 else None
    # Normalizar extensión a mp4
    if expected_name and not expected_name.endswith(".mp4"):
        expected_name = pathlib.Path(expected_name).stem + ".mp4"

    out_template = str(tmp_dir / "%(title)s.%(ext)s")

    # Intento 1: cookies de Brave + cliente web
    print("[DESCARGA] Intento 1: cookies Brave + web...")
    cmd = [
        YTDLP, "--no-playlist",
        "--cookies-from-browser", "brave",
        "--extractor-args", "youtube:player_client=web",
        "-f", YT_FORMAT,
        "--merge-output-format", "mp4",
        "-o", out_template,
        url,
    ]
    result = run(cmd, check=False)
    if result.returncode != 0:
        print("[DESCARGA] Intento 2: tv_embedded (sin PO Token)...")
        cmd2 = [
            YTDLP, "--no-playlist",
            "--extractor-args", "youtube:player_client=tv_embedded",
            "-f", YT_FORMAT,
            "--merge-output-format", "mp4",
            "-o", out_template,
            url,
        ]
        result2 = run(cmd2, check=False)
        if result2.returncode != 0:
            print("[DESCARGA] Intento 3: web_creator con cookies Brave...")
            cmd3 = [
                YTDLP, "--no-playlist",
                "--cookies-from-browser", "brave",
                "--extractor-args", "youtube:player_client=web_creator,web",
                "-f", YT_FORMAT,
                "--merge-output-format", "mp4",
                "-o", out_template,
                url,
            ]
            result3 = run(cmd3, check=False)
            if result3.returncode != 0:
                print("[DESCARGA] Intento 4: formato best fallback con Brave...")
                cmd4 = [
                    YTDLP, "--no-playlist",
                    "--cookies-from-browser", "brave",
                    "-f", "best",
                    "-o", out_template,
                    url,
                ]
                run(cmd4, check=True)

    # Buscar el archivo por nombre exacto primero, luego por el más reciente
    if expected_name:
        exact = tmp_dir / expected_name
        if exact.exists():
            print(f"[DESCARGA] ✓ Video: {exact.name}")
            return exact

    # Fallback: el MP4 más reciente de la carpeta
    mp4s = sorted(tmp_dir.glob("*.mp4"), key=lambda x: x.stat().st_mtime, reverse=True)
    if not mp4s:
        print("ERROR: No se encontró ningún mp4 después de la descarga.")
        sys.exit(1)
    video_path = mp4s[0]
    print(f"[DESCARGA] ✓ Video: {video_path.name}")
    return video_path

# ================== PASO 2: CORTAR CLIPS ==================
def cut_clips(video_path, clips_dir):
    print(f"[CORTE] Cortando en clips de {CLIP_DURATION}s...")

    # Obtener duración total
    r = run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nokey=1:noprint_wrappers=1", str(video_path)],
            capture=True, check=True)
    total_dur = float(r.stdout.strip())
    print(f"[CORTE] Duración total del video: {total_dur:.1f}s ({total_dur/60:.1f} min)")

    out_pattern = str(clips_dir / "__seg_%06d.mp4")
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", str(video_path),
        "-an",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-force_key_frames", f"expr:gte(t,n_forced*{CLIP_DURATION})",
        "-f", "segment",
        "-segment_time", str(CLIP_DURATION),
        "-segment_time_delta", "0.05",
        "-reset_timestamps", "1",
        out_pattern,
    ]
    run(cmd, check=True)

    segs = sorted(clips_dir.glob("__seg_*.mp4"))
    print(f"[CORTE] ✓ {len(segs)} clips generados")

    # Shuffle inmediato — renombrar con nombres aleatorios AHORA, antes de cualquier paso posterior.
    # Si el proceso muere después de este punto, los clips ya son irreconocibles para Content ID.
    n = len(segs)
    perm = list(range(n))
    for i in range(n - 1, 0, -1):
        j = random.randint(0, i)
        perm[i], perm[j] = perm[j], perm[i]
    # Derangement: eliminar puntos fijos
    for _ in range(50):
        fixed = [i for i in range(n) if perm[i] == i]
        if not fixed:
            break
        for i in fixed:
            swap = random.choice([x for x in range(n) if x != i])
            perm[i], perm[swap] = perm[swap], perm[i]
    # Renombrar __seg__ → __rnd__ con permutación aleatoria
    for i, f in enumerate(segs):
        f.rename(clips_dir / f"__rnd__{i:06d}.mp4")
    rnds = sorted(clips_dir.glob("__rnd__*.mp4"))
    for new_pos in range(n):
        rnds[perm[new_pos]].rename(clips_dir / f"__shuf__{new_pos:06d}.mp4")
    # Nombre final: __seg_%06d para mantener compatibilidad con pasos posteriores
    for i, f in enumerate(sorted(clips_dir.glob("__shuf__*.mp4"))):
        f.rename(clips_dir / f"__seg__{i:06d}.mp4")
    print(f"[CORTE] ✓ Clips shuffleados en el corte (Fisher-Yates + derangement)")

    segs = sorted(clips_dir.glob("__seg__*.mp4"))
    return segs

# ================== PASO 3: RECORTAR CORTES BRUSCOS ==================
def trim_scene_cuts(clips_dir):
    print(f"[TRIM] Detectando cortes bruscos (threshold={SCENE_THRESHOLD})...")
    segs = sorted(clips_dir.glob("__seg__*.mp4"))
    trimmed = 0

    for clip in segs:
        # Duración del clip
        r = run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nokey=1:noprint_wrappers=1", str(clip)],
                capture=True, check=False)
        try:
            cd = float(r.stdout.strip())
        except Exception:
            continue
        if cd < MIN_CLIP_DUR * 2:
            continue

        # Detectar escenas
        filter_str = f"movie={clip},select=gt(scene\\,{SCENE_THRESHOLD})"
        p = run([FFPROBE, "-v", "error", "-show_frames", "-select_streams", "v",
                 "-show_entries", "frame=best_effort_timestamp_time",
                 "-of", "json", "-f", "lavfi", filter_str],
                capture=True, check=False)
        scene_times = []
        try:
            for fr in json.loads(p.stdout).get("frames", []):
                t = fr.get("best_effort_timestamp_time")
                if t:
                    scene_times.append(float(t))
        except Exception:
            continue

        ts, te = 0.0, cd
        early = [t for t in scene_times if 0.05 < t < 1.5]
        if early:
            ts = max(early) + SCENE_MARGIN
        late = [t for t in scene_times if t > cd - 1.5]
        if late:
            te = min(late) - SCENE_MARGIN

        if ts == 0.0 and te == cd:
            continue
        if (te - ts) < MIN_CLIP_DUR or ts >= te:
            continue

        out = clip.parent / clip.name.replace("__seg__", "__trim__")
        res = run([FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
                   "-i", str(clip),
                   "-ss", str(ts), "-to", str(te),
                   "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-an",
                   str(out)],
                  capture=True, check=False)
        if res.returncode == 0 and out.exists():
            out.replace(clip)
            trimmed += 1

    print(f"[TRIM] ✓ {trimmed} clips con cortes bruscos recortados")

# ================== PASO 4: RENOMBRAR ==================
def rename_sequential(clips_dir):
    segs = sorted(clips_dir.glob("__seg__*.mp4"))
    if not segs:
        print("ERROR: No se encontraron segmentos para renombrar.")
        sys.exit(1)

    # tmp rename para evitar colisiones
    for i, f in enumerate(segs, 1):
        f.rename(clips_dir / f"__tmp__{i:06d}.mp4")
    tmps = sorted(clips_dir.glob("__tmp__*.mp4"))
    for i, f in enumerate(tmps, 1):
        f.rename(clips_dir / f"{i}.mp4")

    return len(tmps)

# ================== PASO 5: SHUFFLE + DERANGEMENT ==================
def shuffle_clips(clips_dir, n):
    print(f"[SHUFFLE] Reordenando {n} clips (Fisher-Yates + derangement)...")
    files = sorted(
        [f for f in clips_dir.glob("*.mp4") if re.fullmatch(r"\d+\.mp4", f.name)],
        key=lambda x: int(x.stem)
    )
    n = len(files)
    if n <= 1:
        return

    perm = list(range(n))
    # Fisher-Yates
    for i in range(n - 1, 0, -1):
        j = random.randint(0, i)
        perm[i], perm[j] = perm[j], perm[i]
    # Derangement: corregir posiciones fijas
    for _ in range(50):
        fixed = [i for i in range(n) if perm[i] == i]
        if not fixed:
            break
        for i in fixed:
            swap = random.choice([x for x in range(n) if x != i])
            perm[i], perm[swap] = perm[swap], perm[i]

    # Renombrar a __tmp__
    for i, f in enumerate(files):
        f.rename(clips_dir / f"__tmp__{i:06d}.mp4")
    tmps = sorted(clips_dir.glob("__tmp__*.mp4"))

    # Aplicar permutación → __ord__
    for new_pos in range(n):
        tmps[perm[new_pos]].rename(clips_dir / f"__ord__{new_pos:06d}.mp4")

    # Renombrar __ord__ → 1.mp4..N.mp4
    for i, f in enumerate(sorted(clips_dir.glob("__ord__*.mp4")), 1):
        f.rename(clips_dir / f"{i}.mp4")

    print(f"[SHUFFLE] ✓ Clips reordenados")

# ================== MAIN ==================
def main():
    if len(sys.argv) < 3:
        print("Uso: python3 clips.py <youtube_url> <carpeta_personaje>")
        sys.exit(1)

    url         = sys.argv[1]
    char_folder = pathlib.Path(sys.argv[2])

    if not char_folder.is_dir():
        print(f"ERROR: No existe la carpeta: {char_folder}")
        sys.exit(1)

    clips_dir = char_folder / "clips"
    clips_dir.mkdir(exist_ok=True)

    # Limpiar clips previos en la carpeta
    for f in clips_dir.glob("*.mp4"):
        f.unlink()
    for f in clips_dir.glob("__*.mp4"):
        f.unlink()

    check_tools()

    # Descargar en iCloud Drive/yt/
    icloud_yt = pathlib.Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/yt"
    icloud_yt.mkdir(parents=True, exist_ok=True)
    video_path = download_video(url, icloud_yt)

    cut_clips(video_path, clips_dir)

    trim_scene_cuts(clips_dir)
    n = rename_sequential(clips_dir)
    shuffle_clips(clips_dir, n)

    print(f"\n✓ Listo: {n} clips de {CLIP_DURATION}s en {clips_dir}")

if __name__ == "__main__":
    main()
