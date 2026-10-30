#!/usr/bin/env python3
"""
render_futbol.py — Render completo para canal Fútbol
Uso: python3 render_futbol.py "futbol/rene_higuita"
"""
import sys, json, pathlib, subprocess, random, math, tempfile, os

FFMPEG  = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"

CLIP_DUR   = 5.0     # duración objetivo por slot de clip base
FLOW_10MIN = 600.0   # los flow inserts están en los primeros 10 min

# ── Anti-fingerprint ──────────────────────────────────────────────────────────
random.seed(42)

def antifp_filters(seed):
    r = random.Random(seed)
    flip   = "hflip," if r.random() < 0.5 else ""
    speed  = 1.0 + r.uniform(-0.02, 0.02)
    zoom   = 1.04
    return flip, speed, zoom

def get_duration(path):
    r = subprocess.run(
        [FFPROBE, "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True
    )
    try:
        return float(r.stdout.strip())
    except:
        return 0.0

def get_dims(path):
    r = subprocess.run(
        [FFPROBE, "-v", "quiet", "-select_streams", "v:0",
         "-show_entries", "stream=width,height",
         "-of", "csv=s=x:p=0", str(path)],
        capture_output=True, text=True
    )
    try:
        w, h = r.stdout.strip().split("x")
        return int(w), int(h)
    except:
        return 1920, 1080

# ── Construir secuencia de clips ──────────────────────────────────────────────
def build_sequence(carpeta, flow_meta, audio_dur):
    clips_dir    = carpeta / "clips"
    frames_dir   = carpeta / "frames_extraidos"
    rechazados_f = carpeta / "clips_rechazados.json"
    rechazados   = set(json.loads(rechazados_f.read_text()).keys()) if rechazados_f.exists() else set()

    # Pool de clips base (excluir rechazados)
    pool = sorted([c for c in clips_dir.glob("*.mp4") if str(c) not in rechazados])
    frames_pool = sorted(frames_dir.glob("*.jpg")) if frames_dir.exists() else []

    # Índice de flow por timestamp de inicio
    flow_by_start = sorted(flow_meta, key=lambda x: x["start"])

    sequence = []   # list of dicts: {type, path, duration, insert_start(opt)}
    t = 0.0
    fi = 0          # índice en flow
    pool_idx = 0

    def next_clip():
        nonlocal pool_idx
        if not pool and not frames_pool:
            return None, 0
        src = pool if pool else frames_pool
        c = src[pool_idx % len(src)]
        pool_idx += 1
        dur = get_duration(c)
        if dur <= 0:
            dur = CLIP_DUR
        dur = min(dur, CLIP_DUR)
        return c, dur

    while t < audio_dur:
        # ¿Hay un flow insert que empieza aquí (o pronto)?
        if fi < len(flow_by_start):
            fs = flow_by_start[fi]
            # Si el flow empieza dentro de los próximos CLIP_DUR segundos
            if fs["start"] <= t + 0.5:
                # Usar flow clip
                seg_id  = fs["segment_id"]
                zp_path = carpeta / "flow_images" / f"flow_{seg_id:04d}_zp.mp4"
                if zp_path.exists():
                    dur = fs["duration"]
                    sequence.append({
                        "type":         "flow",
                        "path":         zp_path,
                        "duration":     dur,
                        "insert_start": fs["start"],
                    })
                    t  = fs["end"]
                    fi += 1
                    continue
                else:
                    fi += 1  # skip missing flow clip
                    continue

            # ¿Hay un flow que empieza pronto — no llenar más de lo que cabe?
            gap = fs["start"] - t
            if gap < CLIP_DUR and gap > 0.2:
                # Insertar un clip corto para llegar exacto al flow
                c, _ = next_clip()
                if c:
                    sequence.append({"type": "clip", "path": c, "duration": gap})
                t = fs["start"]
                continue

        # Clip normal
        c, dur = next_clip()
        if c is None:
            break
        remaining = audio_dur - t
        dur = min(dur, remaining)
        if dur <= 0:
            break
        sequence.append({"type": "clip", "path": c, "duration": dur})
        t += dur

    return sequence

# ── Filtros por tipo ──────────────────────────────────────────────────────────
def vfilter_clip(path, duration, seed):
    flip, speed, _ = antifp_filters(seed)
    pts = f"setpts={1/speed:.4f}*PTS,"
    w, h = get_dims(path)
    if w == 0: w, h = 1920, 1080
    # Mantener aspect ratio → pad a 16:9
    return (
        f"{flip}{pts}"
        f"scale=1920:1080:force_original_aspect_ratio=increase,"
        f"crop=1920:1080,"
        f"fps=30,"
        f"trim=duration={duration:.3f},"
        f"setpts=PTS-STARTPTS"
    )

def vfilter_flow(path, duration, seed):
    # Flow clips ya tienen zoompan bakeado — NO aplicar fps filter
    flip, speed, _ = antifp_filters(seed)
    pts = f"setpts={1/speed:.4f}*PTS,"
    return (
        f"{flip}{pts}"
        f"scale=1920:1080:force_original_aspect_ratio=increase,"
        f"crop=1920:1080,"
        f"trim=duration={duration:.3f},"
        f"setpts=PTS-STARTPTS"
    )

def vfilter_image(duration, seed):
    flip, speed, zoom = antifp_filters(seed)
    r = random.Random(seed + 1)
    # Zoompan suave
    z_expr  = f"'min(zoom+0.0015,{zoom})'"
    x_expr  = f"'iw/2-(iw/zoom/2)+{r.randint(-20,20)}'"
    y_expr  = f"'ih/2-(ih/zoom/2)+{r.randint(-15,15)}'"
    frames  = max(1, int(duration * 30))
    pts     = f"setpts={1/speed:.4f}*PTS,"
    return (
        f"scale=3840:2160:force_original_aspect_ratio=increase,"
        f"crop=3840:2160,"
        f"zoompan=z={z_expr}:x={x_expr}:y={y_expr}:d={frames}:s=1920x1080:fps=30,"
        f"{flip}{pts}"
        f"trim=duration={duration:.3f},"
        f"setpts=PTS-STARTPTS"
    )

# ── Render principal ──────────────────────────────────────────────────────────
def render(carpeta_str):
    carpeta   = pathlib.Path(carpeta_str).resolve()
    nombre    = carpeta.name

    # Archivos de entrada
    mp3_path  = carpeta / f"{nombre}.mp3"
    srt_path  = carpeta / f"{nombre}.srt"
    out_path  = carpeta / "output.mp4"
    fm_path   = carpeta / "flow_meta.json"

    if not mp3_path.exists():
        sys.exit(f"✗ No encontré {mp3_path}")
    if not fm_path.exists():
        sys.exit(f"✗ No encontré {fm_path}")

    flow_meta = json.loads(fm_path.read_text())
    audio_dur = get_duration(mp3_path)
    print(f"\n  Audio: {audio_dur:.1f}s ({audio_dur/60:.1f} min)")

    # Construir secuencia
    print("  Construyendo secuencia de clips...")
    seq = build_sequence(carpeta, flow_meta, audio_dur)
    total_video = sum(s["duration"] for s in seq)
    flow_count  = sum(1 for s in seq if s["type"] == "flow")
    print(f"  Secuencia: {len(seq)} slots ({flow_count} flow) → {total_video:.1f}s video")

    # Escribir lista de concat temporal
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, prefix="futbol_concat_") as fh:
        concat_file = fh.name

    try:
        _render_concat(seq, mp3_path, srt_path, out_path, audio_dur, concat_file)
    finally:
        pathlib.Path(concat_file).unlink(missing_ok=True)

def _render_concat(seq, mp3_path, srt_path, out_path, audio_dur, concat_file):
    """Procesa cada slot, luego concatena y mezcla con audio."""
    tmp_dir = pathlib.Path(tempfile.mkdtemp(prefix="futbol_tmp_"))
    clips_out = []

    print(f"\n  Procesando {len(seq)} slots...")
    for i, slot in enumerate(seq):
        ptype = slot["type"]
        path  = slot["path"]
        dur   = slot["duration"]
        out_c = tmp_dir / f"slot_{i:04d}.mp4"

        if ptype == "flow":
            vf = vfilter_flow(path, dur, seed=i)
        elif ptype == "clip":
            vf = vfilter_clip(path, dur, seed=i)
        else:  # image
            vf = vfilter_image(dur, seed=i)

        cmd = [
            "/opt/homebrew/bin/ffmpeg", "-hide_banner", "-loglevel", "error",
            "-nostdin", "-y",
            "-i", str(path),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-an",
            "-t", str(dur),
            str(out_c)
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=60)
        if out_c.exists() and out_c.stat().st_size > 1000:
            clips_out.append(out_c)
            if (i + 1) % 10 == 0:
                print(f"    {i+1}/{len(seq)} slots procesados")
        else:
            print(f"    ⚠ slot {i} falló ({path.name if hasattr(path,'name') else path}): {r.stderr.decode()[-100:]}")

    # Escribir lista de concat
    with open(concat_file, "w") as fh:
        for c in clips_out:
            fh.write(f"file '{c}'\n")

    print(f"\n  Concatenando {len(clips_out)} clips...")

    # Concat video
    tmp_vid = tmp_dir / "video_raw.mp4"
    r = subprocess.run([
        "/opt/homebrew/bin/ffmpeg", "-hide_banner", "-loglevel", "error",
        "-nostdin", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_file,
        "-c", "copy", str(tmp_vid)
    ], capture_output=True, timeout=1800)
    if not tmp_vid.exists():
        print("✗ Concat falló:", r.stderr.decode()[-200:])
        return

    print("  Mezclando audio + subtítulos...")

    # Mezcla final con audio y subtítulos
    vf_final = "scale=1920:1080"

    cmd_final = [
        "/opt/homebrew/bin/ffmpeg", "-hide_banner", "-loglevel", "error",
        "-nostdin", "-y",
        "-i", str(tmp_vid),
        "-i", str(mp3_path),
        "-vf", vf_final,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        str(out_path)
    ]
    r = subprocess.run(cmd_final, capture_output=True, timeout=3600)
    if out_path.exists():
        size_mb = out_path.stat().st_size / 1_048_576
        print(f"\n  ✓ output.mp4 → {size_mb:.0f} MB")
        print(f"  Ruta: {out_path}")
    else:
        print("✗ Render final falló:", r.stderr.decode()[-300:])

    # Limpieza
    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Uso: python3 render_futbol.py 'futbol/rene_higuita'")

    carpeta = pathlib.Path("/Users/anyelocuesta/Downloads/Canales") / sys.argv[1]
    if not carpeta.exists():
        carpeta = pathlib.Path(sys.argv[1])
    if not carpeta.exists():
        sys.exit(f"✗ No existe: {sys.argv[1]}")

    print(f"\n{'='*60}")
    print(f"  render_futbol.py — {carpeta.name}")
    print(f"{'='*60}")
    render(carpeta)
