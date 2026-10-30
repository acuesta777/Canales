#!/usr/bin/env python3
"""
Verifica que cada flow_NNN_zp.mp4 tenga la duración exacta del timeline.json.
Uso: python3 validar_flow_clips.py riqueza/alberto_del_rio/
"""
import json, subprocess, sys, pathlib

FFPROBE = "/opt/homebrew/bin/ffprobe"

def get_duration(path):
    r = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None

def fmt(s):
    m = int(s) // 60
    sec = s % 60
    return f"{m:02d}:{sec:05.2f}"

def main():
    base = pathlib.Path("/Users/anyelocuesta/Downloads/Canales")
    personaje_dir = base / sys.argv[1].rstrip("/")
    timeline_f = personaje_dir / "05-montaje" / "timeline.json"
    img_dir = personaje_dir / "03-imagenes"

    data = json.loads(timeline_f.read_text(encoding="utf-8"))
    segments = data.get("visual_timeline", [])

    ok = 0
    errors = []

    print(f"\n{'SEG':>3}  {'INICIO':>7}  {'FIN':>7}  {'ESPERADO':>9}  {'REAL':>9}  {'DIFF':>7}  ESTADO")
    print("-" * 72)

    for seg in segments:
        sid      = seg.get("segment_id")
        start_s  = seg.get("start_seconds", 0)
        end_s    = seg.get("end_seconds", 0)
        expected = round(end_s - start_s, 3)
        clip     = img_dir / f"flow_{sid:03d}_zp.mp4"

        if not clip.exists():
            errors.append(f"SEG {sid:02d}: FALTA el archivo {clip.name}")
            print(f"{sid:>3}  {fmt(start_s):>7}  {fmt(end_s):>7}  {expected:>9.3f}s  {'---':>9}  {'---':>7}  ✗ FALTA")
            continue

        real = get_duration(clip)
        if real is None:
            errors.append(f"SEG {sid:02d}: no se pudo leer duración de {clip.name}")
            print(f"{sid:>3}  {fmt(start_s):>7}  {fmt(end_s):>7}  {expected:>9.3f}s  {'ERR':>9}  {'---':>7}  ✗ ERROR")
            continue

        diff = abs(real - expected)
        status = "✓ OK" if diff <= 0.1 else f"✗ DIFF {diff:+.3f}s"
        if diff > 0.1:
            errors.append(f"SEG {sid:02d}: esperado {expected:.3f}s  real {real:.3f}s  (diff {diff:+.3f}s)")
        else:
            ok += 1

        print(f"{sid:>3}  {fmt(start_s):>7}  {fmt(end_s):>7}  {expected:>9.3f}s  {real:>9.3f}s  {diff:>+7.3f}s  {status}")

    print("-" * 72)
    print(f"\n{ok}/{len(segments)} clips correctos")
    if errors:
        print("\nERRORES:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    else:
        print("✓ Todos los clips tienen la duración exacta del timeline.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 validar_flow_clips.py <nicho>/<personaje>/")
        sys.exit(1)
    main()
