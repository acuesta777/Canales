#!/usr/bin/env python3
"""
generar_meta_mono.py — Genera dashboard_meta.json para Formato 2 (single-artista).

Lee clips de clips_ref/ y hook_timeline.json para construir el meta que
espera dashboard_farandula.py.

Uso:
    python3 Farandula/generar_meta_mono.py "Farandula/LUCHA VILLA/"
"""

import sys, json, pathlib, subprocess

FFPROBE = "/opt/homebrew/bin/ffprobe"
SHOT_DUR = 7.5

def get_duration(path):
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nokey=1:noprint_wrappers=1", str(path)],
            capture_output=True, text=True, timeout=10
        )
        return round(float(r.stdout.strip()), 2)
    except Exception:
        return 5.0

def get_dims(path):
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=10
        )
        w, h = r.stdout.strip().split(",")
        return int(w), int(h)
    except Exception:
        return 1920, 1080

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 generar_meta_mono.py 'Farandula/NOMBRE CARPETA/'")
        sys.exit(1)

    carpeta = pathlib.Path(sys.argv[1]).resolve()
    clips_dir = carpeta / "clips_ref"
    mp3_path  = carpeta / "audio.mp3"
    meta_out  = carpeta / "dashboard_meta.json"

    if not clips_dir.exists():
        print(f"ERROR: No existe {clips_dir}")
        print("Extrae los clips del video de referencia primero.")
        sys.exit(1)

    # Duración total del audio
    audio_dur = get_duration(mp3_path) if mp3_path.exists() else 0.0
    print(f"Audio: {audio_dur:.1f}s ({audio_dur/60:.1f} min)")

    # Recoger todos los clips de clips_ref/
    clips_files = sorted([
        f for f in clips_dir.glob("*.mp4")
        if not f.name.endswith("_zp.mp4")
    ])
    print(f"Clips en clips_ref/: {len(clips_files)}")

    if not clips_files:
        print("ERROR: No hay clips en clips_ref/")
        sys.exit(1)

    # Calcular slots necesarios
    import math
    n_slots = math.ceil(audio_dur / SHOT_DUR) if audio_dur > 0 else len(clips_files)
    print(f"Slots necesarios: {n_slots}")

    # Construir clips dict (recicla clips si hay menos que slots)
    clips_dict = {}
    for slot in range(n_slots):
        clip_path = clips_files[slot % len(clips_files)]
        dur = get_duration(clip_path)
        w, h = get_dims(clip_path)
        clips_dict[str(slot)] = {
            "slot":       slot,
            "estado":     "pendiente",
            "tipo":       "video",
            "path":       str(clip_path),
            "orig_name":  clip_path.name,
            "reciclado":  slot >= len(clips_files),
            "duration":   dur,
            "slot_start": round(slot * SHOT_DUR, 2),
            "slot_end":   round((slot + 1) * SHOT_DUR, 2),
            "srt_text":   "",
            "width":      w,
            "height":     h,
            "fuente":     "clips_ref",
        }

    meta = {
        "00_HOOK": {
            "nombre":   "HOOK",
            "is_hook":  True,
            "duration": 0.0,
        },
        "01_LUCHA VILLA": {
            "nombre":      "Lucha Villa",
            "is_hook":     False,
            "duration":    audio_dur,
            "icloud_name": "clips_ref",
            "clips":       clips_dict,
        }
    }

    meta_out.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    print(f"✓ dashboard_meta.json generado → {meta_out}")
    print(f"  {n_slots} slots | {len(clips_files)} clips únicos")

if __name__ == "__main__":
    main()
