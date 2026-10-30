#!/usr/bin/env python3
"""
generar_hook_timeline_epocadeoro.py — Genera el timeline visual del hook.

Lee timestamps.json para saber:
  - Duración exacta del hook (0s → inicio primer artista)
  - Lista de artistas del video (en orden)

Divide la duración del hook en N segmentos iguales (uno por artista)
y genera hook_timeline.json.

Uso:
  python3 generar_hook_timeline_epocadeoro.py "Video-001/"
"""

import sys, json, math, re, pathlib

VERDE    = "\033[92m"
ROJO     = "\033[91m"
AMARILLO = "\033[93m"
NEGRITA  = "\033[1m"
RESET    = "\033[0m"


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)

    folder = pathlib.Path(sys.argv[1])
    ts_path = folder / "timestamps.json"

    if not ts_path.exists():
        sys.exit(f"[ERROR] No existe: {ts_path}\nCorre primero timestamps_epocadeoro.py")

    ts = json.loads(ts_path.read_text(encoding="utf-8"))

    # Extraer hook y artistas
    hook = next((s for s in ts if s.get("is_hook") or "HOOK" in s["label"].upper()), None)
    artistas = [s for s in ts if not s.get("is_hook") and not s.get("is_cierre")]

    if not hook:
        sys.exit("[ERROR] No encontré sección HOOK en timestamps.json")
    if not artistas:
        sys.exit("[ERROR] No encontré artistas en timestamps.json")

    hook_start = hook["start"]
    hook_end   = hook["end"]
    hook_dur   = hook_end - hook_start
    n          = len(artistas)
    seg_dur    = round(hook_dur / n, 2)

    print(f"\n{NEGRITA}{'='*58}")
    print(f"  HOOK TIMELINE — La Verdad Dorada")
    print(f"  Hook: {hook_start:.1f}s → {hook_end:.1f}s ({hook_dur:.1f}s)")
    print(f"  Artistas: {n} | Segmento por artista: {seg_dur:.1f}s")
    print(f"{'='*58}{RESET}\n")

    segments = []
    for i, art in enumerate(artistas):
        seg_start = round(hook_start + i * seg_dur, 2)
        seg_end   = round(seg_start + seg_dur, 2)
        # Último segmento llega exacto al fin del hook
        if i == n - 1:
            seg_end = hook_end

        nombre_display = art.get("name") or re.sub(r"^\d+_", "", art["label"]).replace("_", " ").upper()

        seg = {
            "idx":     i + 1,
            "nombre":  nombre_display,
            "start":   seg_start,
            "end":     seg_end,
            "dur":     round(seg_end - seg_start, 2),
            "foto":    None,   # se rellena en buscar_fotos_hook.py
        }
        segments.append(seg)
        print(f"  [{i+1:02d}] {nombre_display:<30} {seg_start:.1f}s → {seg_end:.1f}s ({seg['dur']:.1f}s)")

    out = {
        "hook_start": hook_start,
        "hook_end":   hook_end,
        "hook_dur":   round(hook_dur, 2),
        "n_artistas": n,
        "segments":   segments,
    }

    out_path = folder / "hook_timeline.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))

    print(f"\n  {VERDE}✓ hook_timeline.json guardado{RESET}")
    print(f"  Siguiente: buscar_fotos_hook.py --desde-timeline\n")


if __name__ == "__main__":
    main()
