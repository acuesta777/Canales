#!/usr/bin/env python3
"""Genera flow_XXXX_zp.mp4 para cada segmento del timeline de camilo-sesto-doble-vida."""
import json, pathlib, sys, os
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from zoompan_clip import make_zoompan, DIR_CYCLE

BASE = pathlib.Path("secretos-mexicanos/camilo-sesto-doble-vida")
IMG_DIR = BASE / "03-imagenes"
OUT_DIR = BASE / "03-imagenes"
TL = BASE / "05-montaje" / "timeline.json"

tl = json.load(open(TL))
segs = tl["visual_timeline"]

# Verificar duplicados ANTES de procesar
from collections import defaultdict
_check = defaultdict(list)
for f in sorted(IMG_DIR.glob("*.jpeg")):
    num = int(f.name.split("_")[0])
    _check[num].append(f.name)
_dupes = {k: v for k, v in _check.items() if len(v) > 1}
if _dupes:
    print("\n⚠️  DUPLICADOS DETECTADOS — revisá antes de continuar:")
    for num, files in sorted(_dupes.items()):
        print(f"  {num:03d}: {files}")
    print("\nElimina los duplicados y volvé a correr el script.")
    sys.exit(1)

# Seleccionar primera imagen por número de segmento
from collections import defaultdict
imgs = defaultdict(list)
for f in sorted(IMG_DIR.glob("*.jpeg")):
    num = int(f.name.split("_")[0])
    imgs[num].append(f)

# Preferir "Cinematic" (más genérico, sin caras reales)
def pick(num):
    candidates = imgs.get(num, [])
    for c in candidates:
        if "Cinematic" in c.name:
            return c
    return candidates[0] if candidates else None

ok = err = 0
for seg in segs:
    seg_id = seg["segment_id"]
    dur = float(seg["duration"])
    src = pick(seg_id)
    if src is None:
        # Reutilizar la última si no hay suficientes imágenes
        all_nums = sorted(imgs.keys())
        fallback_num = all_nums[(seg_id - 1) % len(all_nums)]
        src = pick(fallback_num)
    dst = OUT_DIR / f"flow_{seg_id:04d}_zp.mp4"
    direction = DIR_CYCLE[(seg_id - 1) % len(DIR_CYCLE)]
    print(f"  [{seg_id:02d}/28] {src.name[:50]} → {dst.name} ({direction}, {dur}s) …", end=" ", flush=True)
    if make_zoompan(src, dst, dur, direction=direction, index=seg_id-1):
        print("✓"); ok += 1
    else:
        print("✗"); err += 1

print(f"\n✅ {ok} generados, {err} errores")
