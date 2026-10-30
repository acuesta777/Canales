#!/usr/bin/env python3
"""
filtrar_clips.py — Detecta clips con subtítulos/texto quemado y los separa.

Analiza la franja inferior de cada clip (donde van los subs) buscando
píxeles muy brillantes sobre fondo oscuro (texto blanco = subtítulos).
Los clips limpios quedan en clips/ y los sucios van a clips_descartados/.

Uso:
    python3 filtrar_clips.py futbol/lamine_yamal/
    python3 filtrar_clips.py futbol/lamine_yamal/ --umbral 0.06   (más estricto)
    python3 filtrar_clips.py futbol/lamine_yamal/ --solo-reporte   (no mueve nada)
"""

import sys, subprocess, json, pathlib, shutil

FFMPEG  = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"
if not pathlib.Path(FFMPEG).exists():
    FFMPEG  = "/usr/local/bin/ffmpeg"
    FFPROBE = "/usr/local/bin/ffprobe"

VERDE    = "\033[92m"
ROJO     = "\033[91m"
AMARILLO = "\033[93m"
RESET    = "\033[0m"

# Umbral por defecto: fracción del área inferior con píxeles muy brillantes
# 0.08 = 8% de píxeles con brillo >230/255 en la franja inferior → sospechoso
UMBRAL_DEFAULT = 0.08

def analizar_clip(clip_path, umbral):
    """
    Extrae 3 frames del clip, analiza la franja inferior (20% del alto).
    Cuenta píxeles muy brillantes (texto blanco sobre fondo oscuro).
    Retorna True si el clip parece limpio, False si tiene subtítulos.
    """
    try:
        # Extraer 3 frames: al 10%, 50%, 90% de la duración
        r = subprocess.run([
            FFPROBE, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=nokey=1:noprint_wrappers=1",
            str(clip_path)
        ], capture_output=True, text=True, timeout=10)
        dur = float(r.stdout.strip())

        scores = []
        for frac in [0.1, 0.5, 0.9]:
            t = dur * frac
            # Extraer frame, recortar franja inferior 20%, medir píxeles brillantes
            r2 = subprocess.run([
                FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
                "-ss", str(t), "-i", str(clip_path),
                "-vframes", "1",
                "-vf", "crop=iw:ih*0.20:0:ih*0.80,format=gray,geq=lum_expr='if(gt(lum(X\\,Y)\\,230)\\,255\\,0)'",
                "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"
            ], capture_output=True, timeout=15)

            if r2.returncode != 0 or not r2.stdout:
                continue

            raw = r2.stdout
            total = len(raw)
            if total == 0:
                continue
            bright = sum(1 for b in raw if b > 200)
            scores.append(bright / total)

        if not scores:
            return True  # no se pudo analizar → asumir limpio

        score_max = max(scores)
        return score_max < umbral

    except Exception as e:
        print(f"    {AMARILLO}⚠{RESET} Error analizando {clip_path.name}: {e}")
        return True  # en caso de error, asumir limpio


def main():
    if len(sys.argv) < 2:
        print("Uso: python3 filtrar_clips.py <carpeta_video> [--umbral 0.08] [--solo-reporte]")
        sys.exit(1)

    carpeta    = pathlib.Path(sys.argv[1])
    clips_dir  = carpeta / "clips"
    descartados_dir = carpeta / "clips_descartados"

    umbral      = UMBRAL_DEFAULT
    solo_reporte = "--solo-reporte" in sys.argv
    if "--umbral" in sys.argv:
        umbral = float(sys.argv[sys.argv.index("--umbral") + 1])

    if not clips_dir.exists():
        print(f"ERROR: No existe {clips_dir}"); sys.exit(1)

    clips = sorted(
        [f for f in clips_dir.glob("*.mp4")],
        key=lambda x: int(x.stem) if x.stem.isdigit() else 0
    )

    if not clips:
        print("No hay clips en la carpeta"); sys.exit(0)

    print(f"\n{'═'*60}")
    print(f"  FILTRADOR DE CLIPS — {carpeta.name.upper()}")
    print(f"{'═'*60}")
    print(f"  Clips a analizar : {len(clips)}")
    print(f"  Umbral subtítulos: {umbral:.2f} ({umbral*100:.0f}% píxeles brillantes)")
    print(f"  Modo             : {'solo reporte' if solo_reporte else 'mover descartados'}")
    print()

    limpios    = []
    con_subs   = []

    for i, clip in enumerate(clips, 1):
        print(f"  [{i:03d}/{len(clips)}] {clip.name}...", end=" ", flush=True)
        limpio = analizar_clip(clip, umbral)
        if limpio:
            limpios.append(clip)
            print(f"{VERDE}✓ limpio{RESET}")
        else:
            con_subs.append(clip)
            print(f"{ROJO}✗ subtítulos{RESET}")

    print(f"\n{'─'*60}")
    print(f"  Limpios    : {len(limpios)}")
    print(f"  Con subs   : {len(con_subs)}")
    print(f"  Total      : {len(clips)}")

    if not solo_reporte and con_subs:
        descartados_dir.mkdir(exist_ok=True)
        for clip in con_subs:
            shutil.move(str(clip), str(descartados_dir / clip.name))
        print(f"\n  {VERDE}✓{RESET} {len(con_subs)} clips movidos a clips_descartados/")
        print(f"  {len(limpios)} clips limpios quedan en clips/")
    elif solo_reporte:
        print(f"\n  Modo reporte — no se movió nada.")
        if con_subs:
            print(f"  Clips con subtítulos:")
            for c in con_subs:
                print(f"    · {c.name}")

    print(f"{'═'*60}\n")


if __name__ == "__main__":
    main()
