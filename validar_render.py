#!/usr/bin/env python3
"""
validar_render.py <carpeta>
Valida el video final renderizado:
  1. Orden de clips YT == orden del dashboard
  2. Ningún segmento flow sin archivo (negro)
  3. Sin frames congelados (misma imagen >1.5s)
"""
import sys, json, subprocess, tempfile, shutil
from pathlib import Path

VERDE  = "\033[92m"
ROJO   = "\033[91m"
AMARILLO = "\033[93m"
RESET  = "\033[0m"

FFMPEG  = "ffmpeg"
FFPROBE = "ffprobe"

def ok(msg):   print(f"  {VERDE}✓{RESET} {msg}")
def warn(msg): print(f"  {AMARILLO}⚠{RESET} {msg}")
def err(msg):  print(f"  {ROJO}⛔{RESET} {msg}")


def check_orden(carpeta: Path) -> bool:
    """Verifica que clips_order del dashboard == clips usados en render."""
    order_file = carpeta / "render_used_order.json"
    if not order_file.exists():
        warn("render_used_order.json no encontrado — skip check orden")
        return True
    data = json.loads(order_file.read_text())
    dashboard = data.get("clips_order_dashboard", [])
    render    = data.get("clips_used_render", [])

    # Solo comparamos los primeros N del render (antes del reciclado)
    recycled_start = data.get("recycled_start", len(render))
    render_first   = render[:recycled_start]

    if dashboard == render_first:
        ok(f"Orden clips YT: {len(dashboard)} clips — OK")
        return True
    else:
        err(f"ORDEN DISTINTO al dashboard")
        for i, (d, r) in enumerate(zip(dashboard, render_first)):
            if d != r:
                err(f"  Posición {i+1}: dashboard={d}  render={r}")
        if len(dashboard) != len(render_first):
            err(f"  Longitud diferente: dashboard={len(dashboard)}  render={len(render_first)}")
        return False


def check_negros(carpeta: Path) -> bool:
    """Verifica que ningún segmento flow del timeline carece de archivo."""
    tl_path = carpeta / "05-montaje" / "timeline.json"
    if not tl_path.exists():
        warn("timeline.json no encontrado — skip check negros")
        return True
    tl = json.loads(tl_path.read_text())
    segs = tl.get("visual_timeline", tl.get("timeline", list(tl.values())[0]))
    img_dir = carpeta / "03-imagenes"

    missing = []
    for s in segs:
        src = s.get("source", "")
        if src in ("yt", "yt_clip"):
            continue
        sid = s["segment_id"]
        f1 = img_dir / f"flow_{sid:04d}_zp.mp4"
        f2 = img_dir / f"flow_{sid:04d}.mp4"
        if not f1.exists() and not f2.exists():
            missing.append(f"seg{sid:02d} [{src}] {s.get('start_seconds')}s→{s.get('end_seconds')}s")

    if missing:
        for m in missing:
            err(f"Archivo faltante: {m}")
        return False
    ok(f"Archivos flow: todos presentes ({len([s for s in segs if s.get('source') not in ('yt','yt_clip')])} segmentos)")
    return True


def check_congelados(video_path: Path, threshold: float = 0.003, max_frozen_s: float = 1.5) -> bool:
    """
    Detecta frames congelados usando el filtro freezedetect de ffmpeg.
    threshold: diferencia mínima entre frames (0.003 es muy sensible)
    max_frozen_s: duración máxima permitida de freeze antes de reportar
    """
    if not video_path.exists():
        err(f"Video no encontrado: {video_path.name}")
        return False

    cmd = [
        FFMPEG, "-hide_banner", "-i", str(video_path),
        "-vf", f"freezedetect=n={threshold}:d={max_frozen_s}",
        "-map", "0:v", "-f", "null", "-"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    output = result.stderr

    freezes = []
    start = None
    for line in output.splitlines():
        if "freeze_start" in line:
            try:
                start = float(line.split("freeze_start:")[1].split()[0])
            except Exception:
                pass
        elif "freeze_end" in line and start is not None:
            try:
                duration = float(line.split("freeze_duration:")[1].split()[0])
                freezes.append((start, start + duration, duration))
            except Exception:
                pass
            start = None

    if freezes:
        for fs, fe, fd in freezes:
            err(f"Frame congelado: {fs:.1f}s → {fe:.1f}s ({fd:.1f}s)")
        return False
    ok(f"Frames congelados: ninguno detectado (umbral {max_frozen_s}s)")
    return True


def main():
    if len(sys.argv) < 2:
        print("Uso: python3 validar_render.py <carpeta_video>")
        sys.exit(1)

    carpeta = Path(sys.argv[1])
    if not carpeta.is_absolute():
        carpeta = Path.cwd() / carpeta

    # Detectar video final
    videos = sorted(carpeta.glob("*_final.mp4"))
    if not videos:
        print(f"{ROJO}No se encontró *_final.mp4 en {carpeta}{RESET}")
        sys.exit(1)
    video = videos[-1]

    print(f"\n{'═'*62}")
    print(f"  VALIDADOR RENDER — {carpeta.name}")
    print(f"  Video: {video.name}")
    print(f"{'═'*62}")

    results = []
    print("\n[1/3] Orden de clips YT vs dashboard...")
    results.append(check_orden(carpeta))

    print("\n[2/3] Segmentos flow sin archivo (negros)...")
    results.append(check_negros(carpeta))

    print("\n[3/3] Frames congelados...")
    results.append(check_congelados(video))

    print(f"\n{'═'*62}")
    if all(results):
        print(f"  {VERDE}✓ RENDER VÁLIDO — listo para subir{RESET}")
    else:
        fallos = results.count(False)
        print(f"  {ROJO}⛔ {fallos} check(s) fallaron — corregir antes de subir{RESET}")
    print(f"{'═'*62}\n")

    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
