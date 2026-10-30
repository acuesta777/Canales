#!/usr/bin/env python3
"""
verificar_video.py — Verifica que el video final no tenga frames congelados ni duracion incorrecta.
Uso: python3 verificar_video.py <carpeta_video> [--canal CANAL]
"""
import sys, json, subprocess, pathlib

FFPROBE = "/opt/homebrew/bin/ffprobe"

def probe_packets(video_path):
    r = subprocess.run([
        FFPROBE, "-v", "quiet", "-select_streams", "v:0",
        "-show_packets", "-of", "json", str(video_path)
    ], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return json.loads(r.stdout).get("packets", [])

def get_duration(path):
    r = subprocess.run([
        FFPROBE, "-v", "quiet", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path)
    ], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except:
        return None

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 verificar_video.py <carpeta_video> [--canal CANAL]")
        sys.exit(1)

    carpeta = pathlib.Path(sys.argv[1])
    nombre = carpeta.name

    # Buscar video final
    video = carpeta / f"{nombre}_final.mp4"
    audio = carpeta / f"{nombre}.mp3"

    if not video.exists():
        print(f"❌ No existe video: {video}")
        sys.exit(1)

    print(f"Verificando: {video.name}")
    ok = True

    # 1. Verificar frames congelados
    print("\n[1] Frames congelados (packets con duration > 0.5s)...")
    pkts = probe_packets(video)
    if pkts is None:
        print("  ❌ No se pudo leer el video")
        ok = False
    else:
        bad = [(float(p.get("pts_time", 0)), float(p.get("duration_time", 0)))
               for p in pkts if float(p.get("duration_time", 0)) > 0.5]
        if bad:
            print(f"  ❌ {len(bad)} packet(s) con frames congelados:")
            for pts, dur in bad[:5]:
                print(f"     PTS={pts:.1f}s  duración={dur:.2f}s  ← CONGELADO")
            ok = False
        else:
            total = len(pkts)
            print(f"  ✓ {total} packets, ninguno congelado")

    # 1b. Verificar frames reales del stream de video (detecta video stream truncado)
    print("\n[1b] Frames reales del stream de video...")
    r2 = subprocess.run([
        FFPROBE, "-v", "quiet", "-select_streams", "v:0",
        "-show_entries", "stream=nb_frames,duration",
        "-of", "default=nw=1", str(video)
    ], capture_output=True, text=True)
    stream_dur = None
    nb_frames = None
    for line in r2.stdout.splitlines():
        if line.startswith("nb_frames="):
            try: nb_frames = int(line.split("=")[1])
            except: pass
        if line.startswith("duration="):
            try: stream_dur = float(line.split("=")[1])
            except: pass
    if nb_frames and stream_dur:
        fps_real = nb_frames / stream_dur if stream_dur > 0 else 0
        print(f"  ✓ {nb_frames} frames reales, stream={stream_dur/60:.2f}min ({fps_real:.1f}fps)")
    else:
        print("  ⚠ No se pudo leer nb_frames del stream")

    # 2. Verificar duración video vs audio
    print("\n[2] Duración video vs audio...")
    vid_dur = get_duration(video)
    aud_dur = get_duration(audio) if audio.exists() else None

    if vid_dur is None:
        print("  ❌ No se pudo medir duración del video")
        ok = False
    elif aud_dur is None:
        print(f"  ⚠ Audio no encontrado. Video: {vid_dur/60:.2f} min")
    else:
        diff = abs(vid_dur - aud_dur)
        if diff > 5:
            print(f"  ❌ Diferencia: video={vid_dur/60:.2f}min vs audio={aud_dur/60:.2f}min (Δ={diff:.1f}s)")
            ok = False
        else:
            print(f"  ✓ Video={vid_dur/60:.2f}min  Audio={aud_dur/60:.2f}min  Δ={diff:.1f}s")
        # Verificar que el stream de video cubre la misma duración que el audio
        if stream_dur and aud_dur:
            stream_diff = abs(stream_dur - aud_dur)
            if stream_diff > 10:
                print(f"  ❌ Stream de video truncado: {stream_dur/60:.2f}min vs audio {aud_dur/60:.2f}min — video se congelará en min {stream_dur/60:.1f}")
                ok = False
            else:
                print(f"  ✓ Stream de video cubre {stream_dur/60:.2f}min (completo)")

    # 3. Verificar fps
    print("\n[3] Frame rate del video...")
    r = subprocess.run([
        FFPROBE, "-v", "quiet", "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate,avg_frame_rate",
        "-of", "default", str(video)
    ], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if "frame_rate" in line:
            k, v = line.split("=")
            if v and v != "0/0":
                # Evaluar fracción
                parts = v.strip().split("/")
                if len(parts) == 2 and int(parts[1]) > 0:
                    fps_val = int(parts[0]) / int(parts[1])
                    if abs(fps_val - 30) > 1:
                        print(f"  ❌ {k}={v} ({fps_val:.2f} fps) — esperado 30fps")
                        ok = False
                    else:
                        print(f"  ✓ {k}={v} ({fps_val:.2f} fps)")

    print()
    if ok:
        print("✅ VIDEO OK — listo para subir")
        sys.exit(0)
    else:
        print("❌ VIDEO CON PROBLEMAS — no subir hasta corregir")
        sys.exit(1)

if __name__ == "__main__":
    main()
