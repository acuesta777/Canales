#!/usr/bin/env python3
"""Wrapper del harvester para el canal Secretos Mexicanos.
Llama al harvester genérico con --source flow y el ZIP más reciente de veo-folder-1.
Uso: python3 harvester_secretos.py secretos-mexicanos/<slug>/
"""
import sys, subprocess, pathlib, glob

script_dir = pathlib.Path(__file__).parent
carpeta = sys.argv[1] if len(sys.argv) > 1 else None

if not carpeta:
    print("Uso: python3 harvester_secretos.py secretos-mexicanos/<slug>/")
    sys.exit(1)

# Auto-detectar ZIP más reciente en veo-folder-1
veo_dir = pathlib.Path.home() / "Downloads" / "veo-folder-1"
zips = sorted(glob.glob(str(veo_dir / "*.zip")),
              key=lambda p: pathlib.Path(p).stat().st_mtime, reverse=True)

extra_args = list(sys.argv[2:])

if zips:
    zip_path = zips[0]
    print(f"  ZIP auto-detectado: {zip_path}", flush=True)
    if "--zip" not in extra_args:
        extra_args = ["--zip", zip_path] + extra_args
elif "--source" not in extra_args:
    # Sin ZIP: usar flow mode para que ai33pro cubra faltantes
    extra_args = ["--source", "flow"] + extra_args

subprocess.run(
    [sys.executable, str(script_dir / "harvester_timeline.py"), carpeta,
     "--canal", "secretos-mexicanos"] + extra_args,
    check=True
)
