#!/usr/bin/env python3
"""
Valida timestamps.json antes del render.
Detecta secciones con duración fuera del rango esperado.
"""
import sys, json, pathlib

folder = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(".")
ts_file = folder / "timestamps.json"
sections_file = folder / "sections.json"

if not ts_file.exists():
    print("ERROR: No existe timestamps.json"); sys.exit(1)

timestamps = json.loads(ts_file.read_text())
sections   = json.loads(sections_file.read_text()) if sections_file.exists() else []
chars_map  = {s["label"]: s["char_end"] - s["char_start"] for s in sections}

VERDE = "\033[32m"; ROJO = "\033[31m"; AMARILLO = "\033[33m"; RESET = "\033[0m"

print(f"\n{'='*60}")
print(f"  VALIDADOR DE TIMESTAMPS — {folder.name}")
print(f"{'='*60}\n")

errores = 0
for i, seg in enumerate(timestamps):
    label = seg["label"]
    name  = seg["name"]
    dur   = seg["duration"]
    chars = chars_map.get(label, 0)

    if seg["is_hook"] or seg["is_cierre"]:
        print(f"  {'🎬' if seg['is_hook'] else '🔚'} {name:30s} {dur:6.1f}s  {'✓' if dur > 5 else '⚠ MUY CORTO'}")
        continue

    # Duración esperada basada en chars (TTS ~14-16 chars/s)
    dur_min = chars / 18 if chars else 60
    dur_max = chars / 10 if chars else 300

    if dur < dur_min * 0.5:
        status = f"{ROJO}✗ MUY CORTO (esperado ~{dur_min:.0f}s){RESET}"
        errores += 1
    elif dur > dur_max * 1.5:
        status = f"{ROJO}✗ MUY LARGO (esperado ~{dur_min:.0f}s){RESET}"
        errores += 1
    elif dur < dur_min * 0.7 or dur > dur_max * 1.2:
        status = f"{AMARILLO}⚠ REVISAR (esperado ~{dur_min:.0f}s){RESET}"
    else:
        status = f"{VERDE}✓{RESET}"

    print(f"  [{i:02d}] {name:30s} {seg['start']:7.1f}s → {seg['end']:7.1f}s  ({dur:6.1f}s)  {status}")

print()
if errores:
    print(f"  {ROJO}✗ {errores} errores — corrige timestamps antes de render{RESET}\n")
    sys.exit(1)
else:
    print(f"  {VERDE}✓ Timestamps OK — puedes correr el render{RESET}\n")
