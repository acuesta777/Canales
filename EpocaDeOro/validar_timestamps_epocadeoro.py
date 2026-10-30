#!/usr/bin/env python3
"""
Valida timestamps.json antes del render — canal La Verdad Dorada.
Detecta artistas con duración fuera del rango esperado (~230s cada uno).
"""
import sys, json, pathlib

folder    = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(".")
ts_file   = folder / "timestamps.json"
sec_file  = folder / "sections.json"

if not ts_file.exists():
    print("ERROR: No existe timestamps.json"); sys.exit(1)

timestamps = json.loads(ts_file.read_text())
sections   = json.loads(sec_file.read_text()) if sec_file.exists() else []
chars_map  = {s["label"]: s["char_end"] - s["char_start"] for s in sections}

VERDE = "\033[32m"; ROJO = "\033[31m"; AMARILLO = "\033[33m"; RESET = "\033[0m"

# Parámetros del canal: 8 artistas, ~230s cada uno, total ~33 min
DUR_ARTISTA_ESPERADA = 230
DUR_TOLERANCIA       = 60   # ±60s es aceptable

print(f"\n{'='*65}")
print(f"  VALIDADOR TIMESTAMPS — La Verdad Dorada")
print(f"{'='*65}\n")

errores    = 0
artistas   = 0
total_dur  = 0.0

for i, seg in enumerate(timestamps):
    label = seg["label"]
    name  = seg["name"]
    dur   = seg["duration"]
    chars = chars_map.get(label, 0)

    if seg["is_hook"] or seg["is_cierre"]:
        icon = "🎬" if seg["is_hook"] else "🔚"
        estado = f"{VERDE}✓{RESET}" if dur > 5 else f"{AMARILLO}⚠ MUY CORTO{RESET}"
        print(f"  {icon} {name:35s} {dur:6.1f}s  {estado}")
        total_dur += dur
        continue

    artistas  += 1
    total_dur += dur

    dur_min = DUR_ARTISTA_ESPERADA - DUR_TOLERANCIA
    dur_max = DUR_ARTISTA_ESPERADA + DUR_TOLERANCIA

    if dur < dur_min * 0.5:
        status = f"{ROJO}✗ MUY CORTO (esperado ~{DUR_ARTISTA_ESPERADA}s){RESET}"
        errores += 1
    elif dur > dur_max * 1.5:
        status = f"{ROJO}✗ MUY LARGO (esperado ~{DUR_ARTISTA_ESPERADA}s){RESET}"
        errores += 1
    elif dur < dur_min or dur > dur_max:
        status = f"{AMARILLO}⚠ REVISAR (esperado ~{DUR_ARTISTA_ESPERADA}s){RESET}"
    else:
        status = f"{VERDE}✓{RESET}"

    print(f"  [{artistas:02d}] {name:35s} {seg['start']:7.1f}s → {seg['end']:7.1f}s  ({dur:6.1f}s)  {status}")

print(f"\n  Total artistas: {artistas}/8")
print(f"  Duración total: {total_dur:.0f}s ({total_dur/60:.1f} min)")

if artistas != 8:
    print(f"  {AMARILLO}⚠ Se esperan 8 artistas, se encontraron {artistas}{RESET}")

print()
if errores:
    print(f"  {ROJO}✗ {errores} errores — corrige timestamps antes del render{RESET}\n")
    sys.exit(1)
else:
    print(f"  {VERDE}✓ Timestamps OK — puedes correr el render{RESET}\n")
