#!/usr/bin/env python3
"""Lanzador de timeline_approval para cualquier carpeta."""
import json, sys
from pathlib import Path
from timeline_approval import run_approval, upload_to_baserow, BASEROW_DEFAULTS

carpeta = sys.argv[1].rstrip('/')
tl_path = Path(carpeta) / "05-montaje" / "timeline.json"
tl = json.load(open(tl_path))
segs = tl["visual_timeline"]

video_name = Path(carpeta).name.replace("_", " ").title()
print(f"Cargando {len(segs)} segmentos de {carpeta}...")

approved, fuente = run_approval(
    segs,
    video_name,
    carpeta=carpeta,
    port=5099,
)

if approved:
    print(f"\n✓ {len(approved)} segmentos aprobados — timeline.json guardado.")
else:
    print("✗ Sin aprobados")
