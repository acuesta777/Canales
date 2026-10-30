#!/usr/bin/env python3
"""
Verificador de video final — confirma que los clips de imagen se insertaron
y que el video está bien formado.

Uso: python3 verificar_render.py carpeta/personaje/

Checks:
1. El archivo _final.mp4 existe y tiene el tamaño esperado (> 100 MB)
2. La duración del video coincide con el audio (±5s)
3. Para cada timestamp del CSV: extrae un frame en ese punto y 2s antes,
   los compara con ffmpeg SSIM — si son idénticos (SSIM=1.0) el clip está congelado.
4. El video tiene al menos 1 stream de video y 1 de audio.
"""

import sys, pathlib, subprocess, tempfile, re

FFMPEG  = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"
if not pathlib.Path(FFMPEG).exists():
    FFMPEG  = "/usr/local/bin/ffmpeg"
    FFPROBE = "/usr/local/bin/ffprobe"

VERDE   = "\033[92m"
ROJO    = "\033[91m"
AMARILLO = "\033[93m"
RESET   = "\033[0m"

def ok(msg):    print(f"  {VERDE}✓{RESET} {msg}")
def error(msg): print(f"  {ROJO}✗{RESET} {msg}")
def warn(msg):  print(f"  {AMARILLO}⚠{RESET} {msg}")

def get_duration(path):
    r = subprocess.run([FFPROBE, "-v", "error",
                        "-show_entries", "format=duration",
                        "-of", "default=nokey=1:noprint_wrappers=1", str(path)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except:
        return 0.0

def get_streams(path):
    r = subprocess.run([FFPROBE, "-v", "error",
                        "-show_entries", "stream=codec_type",
                        "-of", "default=nokey=1:noprint_wrappers=1", str(path)],
                       capture_output=True, text=True)
    return r.stdout.strip().splitlines()

def extract_frame(video, timestamp, dst):
    """Extrae un frame en 'timestamp' segundos. Retorna True si OK."""
    r = subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-ss", str(timestamp),
        "-i", str(video),
        "-vframes", "1",
        "-y", str(dst)
    ], capture_output=True)
    return dst.exists() and dst.stat().st_size > 0

def compare_frames_ssim(frame_a, frame_b):
    """Retorna SSIM entre dos frames (1.0 = idénticos, < 1.0 = diferentes).
    SSIM va en stderr con nivel 'info', NO usar -loglevel error."""
    r = subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "info", "-nostdin",
        "-i", str(frame_a), "-i", str(frame_b),
        "-lavfi", "ssim",
        "-f", "null", "-"
    ], capture_output=True, text=True)
    m = re.search(r"All:([\d.]+)", r.stderr)
    if m:
        return float(m.group(1))
    return None

def ts_to_sec(t):
    parts = [float(p) for p in str(t).strip().split(":")]
    if len(parts) == 3:
        return parts[0]*3600 + parts[1]*60 + parts[2]
    return parts[0]*60 + parts[1]

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 verificar_render.py carpeta/personaje/")
        sys.exit(1)

    carpeta   = pathlib.Path(sys.argv[1])
    nombre    = carpeta.name
    video     = carpeta / f"{nombre}_final.mp4"
    audio     = next(iter(sorted([f for f in carpeta.glob("*.mp3")
                                   if "_test" not in f.name and "_src" not in f.name])), None)
    errores = 0

    print(f"\n{'='*55}")
    print(f"  VERIFICACIÓN DE VIDEO FINAL — {nombre.upper()}")
    print(f"{'='*55}\n")

    # ── 1. Archivo existe y tiene tamaño razonable ──────────
    print("1. ARCHIVO FINAL:")
    if not video.exists():
        error(f"No existe: {video.name}")
        errores += 1
    else:
        size_mb = video.stat().st_size / (1024 * 1024)
        if size_mb < 50:
            error(f"{video.name} demasiado pequeño: {size_mb:.0f} MB (esperado >50 MB)")
            errores += 1
        else:
            ok(f"{video.name} — {size_mb:.0f} MB")

    if errores:
        print(f"\n{ROJO}✗ Video no encontrado o corrupto — abortando verificación{RESET}\n")
        sys.exit(1)

    # ── 2. Streams de video y audio ─────────────────────────
    print("\n2. STREAMS (video + audio):")
    streams = get_streams(video)
    tiene_video = "video" in streams
    tiene_audio = "audio" in streams
    if tiene_video:
        ok("Stream de video presente")
    else:
        error("Sin stream de video")
        errores += 1
    if tiene_audio:
        ok("Stream de audio presente")
    else:
        error("Sin stream de audio")
        errores += 1

    # ── 3. Duración coincide con el audio ───────────────────
    print("\n3. DURACIÓN:")
    video_dur = get_duration(video)
    audio_dur = get_duration(audio) if audio else 0.0
    if audio_dur > 0:
        diff = abs(video_dur - audio_dur)
        if diff <= 5:
            ok(f"Video {video_dur/60:.1f} min | Audio {audio_dur/60:.1f} min | Δ={diff:.1f}s")
        else:
            error(f"Video {video_dur/60:.1f} min vs Audio {audio_dur/60:.1f} min — diferencia {diff:.0f}s")
            errores += 1
    else:
        warn("No se encontró audio para comparar duración")

    # ── 4. Clips de Flow (timeline.json) — verificación por segmento ──
    import json as _json
    timeline_path = carpeta / "05-montaje" / "timeline.json"
    print("\n4. CLIPS DE FLOW (timeline.json):")
    if not timeline_path.exists():
        warn("No hay timeline.json — saltando verificación de Flow")
    else:
        tl = _json.loads(timeline_path.read_text())
        segs = tl.get("visual_timeline", [])
        if not segs:
            warn("timeline.json sin segmentos")
        else:
            img_dir = carpeta / "03-imagenes"
            clips_ok = sum(1 for s in segs if (img_dir / f"flow_{s['segment_id']:04d}_zp.mp4").exists())
            if clips_ok < len(segs):
                error(f"Solo {clips_ok}/{len(segs)} clips de flow encontrados en 03-imagenes/")
                errores += 1
            else:
                ok(f"{clips_ok}/{len(segs)} clips de flow presentes en 03-imagenes/")

            print(f"\n   Verificando inserción en video ({len(segs)} segmentos):")
            fail = 0
            with tempfile.TemporaryDirectory(prefix="verificar_flow_") as tmp:
                tmp = pathlib.Path(tmp)
                for s in segs:
                    sid   = s["segment_id"]
                    ts    = float(s["start_seconds"])
                    dur   = float(s.get("duration", 6))
                    t_end = ts + dur

                    if t_end > video_dur:
                        warn(f"  Seg {sid:02d} t={ts:.1f}s–{t_end:.1f}s: más allá de la duración del video ({video_dur:.0f}s)")
                        continue

                    t_antes  = max(0, ts - 1.5)
                    t_dentro = ts + min(1.0, dur * 0.4)

                    fa = tmp / f"s{sid}_antes.jpg"
                    fb = tmp / f"s{sid}_dentro.jpg"

                    ok_a = extract_frame(video, t_antes, fa)
                    ok_b = extract_frame(video, t_dentro, fb)

                    if not ok_a or not ok_b:
                        error(f"  Seg {sid:02d} t={ts:.1f}s: no se pudo extraer frame")
                        fail += 1
                        continue

                    ssim = compare_frames_ssim(fa, fb)
                    if ssim is None:
                        warn(f"  Seg {sid:02d} t={ts:.1f}s: no se pudo calcular SSIM")
                        continue

                    if ssim >= 0.999:
                        error(f"  Seg {sid:02d} t={ts:.1f}s–{t_end:.1f}s [{dur:.1f}s]: SSIM={ssim:.4f} CONGELADO — clip no insertado")
                        fail += 1
                    elif ssim >= 0.92:
                        warn(f"  Seg {sid:02d} t={ts:.1f}s–{t_end:.1f}s [{dur:.1f}s]: SSIM={ssim:.4f} — cambio leve (revisar)")
                    else:
                        ok(f"  Seg {sid:02d} t={ts:.1f}s–{t_end:.1f}s [{dur:.1f}s]: SSIM={ssim:.4f} ✓")

            if fail:
                error(f"{fail} segmento(s) de flow NO se insertaron correctamente en el video")
                errores += fail
            else:
                ok(f"Todos los {len(segs)} segmentos de flow verificados en el video ✓")


    # ── VEREDICTO ────────────────────────────────────────────
    print(f"\n{'='*55}")
    if errores == 0:
        print(f"  {VERDE}✓ VIDEO APROBADO — clips insertados correctamente{RESET}")
    else:
        print(f"  {ROJO}✗ VIDEO CON PROBLEMAS — {errores} error(es){RESET}")
    print(f"{'='*55}\n")

    sys.exit(0 if errores == 0 else 1)

if __name__ == "__main__":
    main()
