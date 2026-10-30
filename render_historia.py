#!/usr/bin/env python3
"""
render_historia.py — Wrapper de render_timeline.py para Canal Historia Animada.
Uso: python3 render_historia.py historia/[slug]/
"""
import sys, subprocess, pathlib

script_dir = pathlib.Path(__file__).parent
render     = script_dir / "render_timeline.py"
carpeta    = sys.argv[1] if len(sys.argv) > 1 else None

if not carpeta:
    print("Uso: python3 render_historia.py historia/[slug]/")
    sys.exit(1)

extra = sys.argv[2:]
cmd = [sys.executable, str(render), carpeta, "--canal", "historia"] + extra
subprocess.run(cmd, check=True)
