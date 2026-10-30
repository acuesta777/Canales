#!/usr/bin/env python3
"""
render_familias.py — Wrapper de render para canal Familias de Riquezas
Uso: python3 render_familias.py familias/[slug]/
"""
import sys, subprocess, pathlib

script_dir = pathlib.Path(__file__).parent
carpeta = sys.argv[1] if len(sys.argv) > 1 else None

if not carpeta:
    print("Uso: python3 render_familias.py familias/[slug]/")
    sys.exit(1)

subprocess.run(
    [sys.executable, str(script_dir / "render_timeline.py"), carpeta, "--canal", "familias"] + sys.argv[2:],
    check=True
)
