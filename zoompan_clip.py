#!/usr/bin/env python3
"""
zoompan_clip.py — Convierte imagen JPG/PNG a clip MP4 con zoompan correcto.

Fórmula verificada: z='1.5' fijo + pan rotativo. NUNCA incremental desde z=1.0
(se ve en cámara lenta) ni resolución intermedia 480x270 (movimiento imperceptible).

Uso:
    python3 zoompan_clip.py imagen.jpg clip.mp4 --dur 7.5
    python3 zoompan_clip.py imagen.jpg clip.mp4 --dur 8.0 --dir right
    python3 zoompan_clip.py carpeta/*.jpg clips/ --dur 7.5   # batch
"""

import argparse, pathlib, subprocess, sys

FFMPEG = "/opt/homebrew/bin/ffmpeg"
FPS    = 25
ZOOM   = 1.5   # z=1.5 fijo — pan visible ~16.7% del frame; 1.15 era imperceptible (~6.5%)

# Expresiones x/y por dirección (on = frame actual, {f} = total frames)
DIRS = {
    "right":    ("(iw-iw/zoom)*0.5*(on/{f})",    "ih/2-(ih/zoom/2)"),
    "left":     ("(iw-iw/zoom)*0.5*(1-on/{f})",  "ih/2-(ih/zoom/2)"),
    "down":     ("iw/2-(iw/zoom/2)",          "(ih-ih/zoom)*0.5*(on/{f})"),
    "up":       ("iw/2-(iw/zoom/2)",          "(ih-ih/zoom)*0.5*(1-on/{f})"),
    "diag_dr":  ("(iw-iw/zoom)*0.5*(on/{f})",    "(ih-ih/zoom)*0.5*(on/{f})"),
    "diag_ul":  ("(iw-iw/zoom)*0.5*(1-on/{f})",  "(ih-ih/zoom)*0.5*(1-on/{f})"),
    "diag_dl":  ("(iw-iw/zoom)*0.5*(on/{f})",    "(ih-ih/zoom)*0.5*(1-on/{f})"),
    "diag_ur":  ("(iw-iw/zoom)*0.5*(1-on/{f})",  "(ih-ih/zoom)*0.5*(on/{f})"),
}
DIR_CYCLE = ["right", "left", "down", "up", "diag_dr", "diag_ul", "diag_dl", "diag_ur"]


ZOOMPAN_MASTER_DUR = 4.0  # todos los zoompan se generan a esta duración; el render recorta al tiempo real

def make_zoompan(src: pathlib.Path, dst: pathlib.Path, dur: float,
                 direction: str = None, index: int = 0,
                 zoom: float = ZOOM, fps: int = FPS,
                 preset: str = "ultrafast", crf: int = 23) -> bool:
    """
    Genera un clip MP4 con zoompan a partir de una imagen estática.

    Args:
        src:       imagen fuente (JPG/PNG)
        dst:       mp4 de salida
        dur:       duración en segundos
        direction: right/left/down/up/diag_dr/diag_ul/diag_dl/diag_ur
                   Si None → usa DIR_CYCLE[index % 8]
        index:     índice para rotación automática de dirección
        zoom:      factor de zoom fijo (default 1.5)
        fps:       frames por segundo (default 25)
        preset:    preset libx264
        crf:       calidad (menor = mejor)

    Returns:
        True si éxito, False si error
    """
    if not src.exists():
        print(f"  ERROR: no existe {src}", file=sys.stderr)
        return False

    dst.parent.mkdir(parents=True, exist_ok=True)

    if direction is None:
        direction = DIR_CYCLE[index % len(DIR_CYCLE)]
    if direction not in DIRS:
        print(f"  ERROR: dirección '{direction}' no válida. Opciones: {list(DIRS)}", file=sys.stderr)
        return False

    frames = int(dur * fps)
    x_t, y_t = DIRS[direction]
    x_expr = x_t.replace("{f}", str(frames))
    y_expr = y_t.replace("{f}", str(frames))

    vf = (
        f"scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,"
        f"zoompan=z='{zoom}':x='{x_expr}':y='{y_expr}'"
        f":d={frames}:s=1920x1080:fps={fps},setsar=1:1"
    )

    cmd = [
        FFMPEG, "-y",
        "-loop", "1", "-framerate", str(fps), "-i", str(src),
        "-vf", vf,
        "-t", str(dur),
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-an",
        str(dst)
    ]

    r = subprocess.run(cmd, capture_output=True, timeout=180)
    if r.returncode != 0:
        print(f"  ERROR ffmpeg: {r.stderr[-300:].decode(errors='replace')}", file=sys.stderr)
        return False
    return True


def main():
    ap = argparse.ArgumentParser(description="Zoompan correcto: z=1.5 fijo + pan rotativo")
    ap.add_argument("sources", nargs="+", help="Imagen(es) fuente JPG/PNG")
    ap.add_argument("output",  help="Archivo .mp4 de salida o carpeta (batch)")
    ap.add_argument("--dur",   type=float, default=4.0, help="Duración en segundos (default 4.0)")
    ap.add_argument("--dir",   choices=list(DIRS), default=None,
                    help="Dirección del pan. Default: rotativa automática")
    ap.add_argument("--zoom",  type=float, default=ZOOM, help=f"Factor zoom fijo (default {ZOOM})")
    ap.add_argument("--fps",   type=int,   default=FPS,  help=f"FPS (default {FPS})")
    ap.add_argument("--crf",   type=int,   default=23,   help="CRF libx264 (default 23)")
    ap.add_argument("--preset",default="ultrafast",      help="Preset libx264 (default ultrafast)")
    ap.add_argument("--suffix",default="_zp",            help="Sufijo para batch (default _zp)")
    args = ap.parse_args()

    sources = [pathlib.Path(s) for s in args.sources]
    output  = pathlib.Path(args.output)

    # Modo batch: varias fuentes o output es carpeta
    if len(sources) > 1 or output.is_dir() or (not output.suffix):
        output.mkdir(parents=True, exist_ok=True)
        ok = err = 0
        for i, src in enumerate(sources):
            dst = output / (src.stem + f"{args.suffix}.mp4")
            d   = args.dir or DIR_CYCLE[i % len(DIR_CYCLE)]
            print(f"  [{i+1}/{len(sources)}] {src.name} → {dst.name} ({d}, {args.dur}s) …", end=" ", flush=True)
            if make_zoompan(src, dst, args.dur, direction=d, zoom=args.zoom,
                            fps=args.fps, preset=args.preset, crf=args.crf):
                print("✓"); ok += 1
            else:
                print("✗"); err += 1
        print(f"\n  {ok} generados, {err} errores")
    else:
        # Modo single
        d = args.dir or DIR_CYCLE[0]
        print(f"  {sources[0].name} → {output.name} ({d}, {args.dur}s) …", end=" ", flush=True)
        if make_zoompan(sources[0], output, args.dur, direction=d, zoom=args.zoom,
                        fps=args.fps, preset=args.preset, crf=args.crf):
            print("✓")
        else:
            sys.exit(1)


if __name__ == "__main__":
    main()
