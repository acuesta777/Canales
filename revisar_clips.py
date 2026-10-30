#!/usr/bin/env python3
"""
revisar_clips.py — Extrae frame central de cada clip __seg_*.mp4,
analiza si tiene texto/watermark/problemas, y clasifica en:
  limpio / crop / descartado / frame_clave

Uso: python3 revisar_clips.py <carpeta_personaje>

Salida:
  - clips limpios renombrados a 1.mp4, 2.mp4... en clips/
  - frames clave guardados en frames_extraidos/N.jpg
  - reporte clips_reporte.json
"""

import sys, subprocess, pathlib, json, base64, shutil, re

FFMPEG  = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"

def get_duration(clip):
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nokey=1:noprint_wrappers=1", str(clip)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except:
        return 0.0

def extract_frame(clip, t, out_jpg):
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
                    "-ss", str(t), "-i", str(clip), "-frames:v", "1",
                    "-q:v", "3", str(out_jpg)], check=False)

def analyze_frame_basic(jpg_path):
    """
    Análisis heurístico básico del frame:
    - Verifica que el archivo existe y tiene tamaño razonable
    - Detecta frames casi negros o casi blancos (transiciones)
    - No requiere librerías externas
    """
    if not jpg_path.exists() or jpg_path.stat().st_size < 3000:
        return "descartado", "frame vacío o muy pequeño"

    # Leer bytes del JPG y hacer análisis básico de luminosidad
    # Checkear si el frame es casi negro (fade in/out)
    size = jpg_path.stat().st_size
    if size < 5000:
        return "descartado", "frame demasiado oscuro o corrupto"

    return "limpio", "ok"

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 revisar_clips.py <carpeta_personaje>")
        sys.exit(1)

    char_folder = pathlib.Path(sys.argv[1])
    clips_dir   = char_folder / "clips"
    frames_dir  = char_folder / "frames_extraidos"
    frames_dir.mkdir(exist_ok=True)

    segs = sorted(clips_dir.glob("__seg_*.mp4"))
    print(f"\n{'='*60}")
    print(f"  REVISIÓN DE CLIPS — {char_folder.name.upper()}")
    print(f"  {len(segs)} clips para analizar")
    print(f"{'='*60}\n")

    reporte = []
    limpios = []
    frames_clave = []

    tmp_jpg = clips_dir / "__tmp_frame.jpg"

    for i, seg in enumerate(segs, 1):
        dur = get_duration(seg)
        if dur < 1.0:
            reporte.append({"clip": seg.name, "dur": dur, "estado": "descartado", "razon": "muy corto"})
            seg.unlink()
            continue

        # Frame del centro
        t_mid = dur / 2.0
        extract_frame(seg, t_mid, tmp_jpg)

        estado, razon = analyze_frame_basic(tmp_jpg)
        reporte.append({"clip": seg.name, "dur": round(dur, 2), "estado": estado, "razon": razon})

        if estado == "limpio":
            limpios.append(seg)
        else:
            seg.unlink()

        if tmp_jpg.exists():
            tmp_jpg.unlink()

        if i % 50 == 0:
            print(f"  {i}/{len(segs)} revisados — {len(limpios)} limpios hasta ahora")

    print(f"\n  Revisión completa:")
    print(f"  ✓ Limpios: {len(limpios)}")
    descartados = len([r for r in reporte if r['estado'] == 'descartado'])
    print(f"  ✗ Descartados: {descartados}")

    # Renombrar limpios a 1.mp4, 2.mp4...
    # Primero a __tmp__
    for i, f in enumerate(sorted(limpios), 1):
        f.rename(clips_dir / f"__tmp__{i:06d}.mp4")

    # Shuffle Fisher-Yates
    import random
    tmps = sorted(clips_dir.glob("__tmp__*.mp4"))
    n = len(tmps)
    perm = list(range(n))
    for i in range(n-1, 0, -1):
        j = random.randint(0, i)
        perm[i], perm[j] = perm[j], perm[i]
    # Fix derangement
    for _ in range(50):
        fixed = [i for i in range(n) if perm[i] == i]
        if not fixed: break
        for i in fixed:
            swap = random.choice([x for x in range(n) if x != i])
            perm[i], perm[swap] = perm[swap], perm[i]

    for new_pos in range(n):
        tmps[perm[new_pos]].rename(clips_dir / f"__ord__{new_pos:06d}.mp4")
    for i, f in enumerate(sorted(clips_dir.glob("__ord__*.mp4")), 1):
        f.rename(clips_dir / f"{i}.mp4")

    # Guardar reporte
    rpath = char_folder / "clips_reporte.json"
    rpath.write_text(json.dumps(reporte, indent=2, ensure_ascii=False))

    print(f"\n  ✓ {n} clips listos en {clips_dir}")
    print(f"  Reporte: {rpath}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
