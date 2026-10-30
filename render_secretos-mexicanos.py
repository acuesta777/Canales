#!/usr/bin/env python3
"""Wrapper de render para el canal Secretos Mexicanos.
Uso: python3 render_secretos-mexicanos.py secretos-mexicanos/<slug>/
"""
import sys, subprocess, pathlib, json

script_dir = pathlib.Path(__file__).parent
carpeta = sys.argv[1] if len(sys.argv) > 1 else None

if not carpeta:
    print("Uso: python3 render_secretos-mexicanos.py secretos-mexicanos/<slug>/")
    sys.exit(1)

subprocess.run(
    [sys.executable, str(script_dir / "render_timeline.py"), carpeta,
     "--canal", "secretos-mexicanos"] + sys.argv[2:],
    check=True
)

# Actualizar cola_nocturna.json si el _final.mp4 existe
try:
    carpeta_path = pathlib.Path(carpeta)
    personaje = carpeta_path.name or carpeta_path.parent.name
    final_mp4 = next(carpeta_path.glob("*_final.mp4"), None)
    if final_mp4 and final_mp4.exists():
        cola_path = script_dir / "cola_nocturna.json"
        if cola_path.exists():
            cola = json.loads(cola_path.read_text(encoding="utf-8"))
            for entry in cola:
                if entry.get("personaje") == personaje and entry.get("estado") == "pendiente":
                    entry["estado"] = "completado"
            cola_path.write_text(json.dumps(cola, indent=2, ensure_ascii=False))
            print(f"✅ cola_nocturna.json actualizado: {personaje} → completado")
except Exception as e:
    print(f"⚠️  No se pudo actualizar cola_nocturna.json: {e}")
