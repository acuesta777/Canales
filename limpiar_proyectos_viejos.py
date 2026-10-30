#!/usr/bin/env python3
"""
Limpia proyectos de video ya subidos: conserva solo el MP4 final.
Solo actúa en carpetas que tienen upload_info.json (= ya subidas a YouTube).
Aplica a TODOS los canales (subcarpetas de BASE que contengan proyectos).
"""

import os
import shutil
import json
from pathlib import Path
from datetime import datetime

BASE = Path("/Users/anyelocuesta/Downloads/Canales")

# Carpetas raíz que NO son canales de video (scripts, config, utilidades)
EXCLUIR = {
    "_config", "_jsonytapi", "_logs", "_memory", "_musica", "__pycache__",
    "logs", "memory", "referencias", "config",
}

def detectar_canales() -> list[Path]:
    """Retorna subcarpetas de BASE que parecen canales con proyectos de video."""
    canales = []
    for item in sorted(BASE.iterdir()):
        if not item.is_dir():
            continue
        if item.name in EXCLUIR or item.name.startswith(".") or item.name.startswith("_"):
            continue
        # Es canal si tiene al menos una subcarpeta con MP4
        tiene_proyectos = any(
            list(sub.glob("*.mp4"))
            for sub in item.iterdir()
            if sub.is_dir()
        )
        if tiene_proyectos:
            canales.append(item)
    return canales
LOG_FILE = BASE / "logs" / "limpieza_proyectos.log"


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_FILE.parent.mkdir(exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def mejor_mp4(folder: Path) -> Path | None:
    """Elige el MP4 final más relevante en la raíz del proyecto (ignora vacíos)."""
    # resolve() sigue symlinks; ignorar si el target no existe o está vacío
    mp4s = []
    for f in folder.glob("*.mp4"):
        try:
            real = f.resolve()
            if real.exists() and real.stat().st_size > 0:
                mp4s.append(real)
        except Exception:
            continue
    if not mp4s:
        return None
    # Prioridad: *_final.mp4 > output_vhs_v* (mayor versión) > output.mp4 > cualquier otro
    finales = [f for f in mp4s if "_final" in f.name]
    if finales:
        return sorted(finales)[-1]
    vhs = [f for f in mp4s if "output_vhs_v" in f.name]
    if vhs:
        return sorted(vhs)[-1]
    outputs = [f for f in mp4s if f.name == "output.mp4"]
    if outputs:
        return outputs[0]
    return sorted(mp4s)[-1]


def limpiar_proyecto(proyecto: Path, dry_run=False) -> dict:
    mp4 = mejor_mp4(proyecto)
    if not mp4:
        return {"skip": "sin MP4"}

    # Calcular espacio antes
    tamaño_antes = sum(f.stat().st_size for f in proyecto.rglob("*") if f.is_file())

    if dry_run:
        # Solo reportar sin borrar
        archivos = list(proyecto.rglob("*"))
        a_borrar = [f for f in archivos if f.is_file() and f != mp4]
        return {
            "mp4_conservar": mp4.name,
            "archivos_a_borrar": len(a_borrar),
            "espacio_liberable_mb": round((tamaño_antes - mp4.stat().st_size) / 1_000_000),
        }

    # Mover MP4 a lugar seguro, limpiar carpeta, devolver MP4
    tmp_mp4 = BASE / f"_tmp_limpieza_{mp4.name}"
    shutil.move(str(mp4), str(tmp_mp4))

    # Borrar todo lo que queda en la carpeta
    for item in list(proyecto.iterdir()):
        try:
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        except Exception as e:
            log(f"  ERROR borrando {item}: {e}")

    # Devolver MP4
    shutil.move(str(tmp_mp4), str(proyecto / mp4.name))

    tamaño_despues = (proyecto / mp4.name).stat().st_size
    liberado_mb = round((tamaño_antes - tamaño_despues) / 1_000_000)

    return {
        "mp4_conservado": mp4.name,
        "liberado_mb": liberado_mb,
    }


def main(dry_run=False):
    modo = "DRY-RUN" if dry_run else "REAL"
    log(f"=== Limpieza proyectos viejos [{modo}] ===")

    total_liberado = 0
    proyectos_limpiados = 0

    for canal_path in detectar_canales():
        for proyecto in sorted(canal_path.iterdir()):
            if not proyecto.is_dir():
                continue
            resultado = limpiar_proyecto(proyecto, dry_run=dry_run)
            nombre = f"{canal_path.name}/{proyecto.name}"
            if "skip" in resultado:
                continue
            if dry_run:
                log(f"  [{nombre}] conservaría '{resultado['mp4_conservar']}' — liberaría {resultado['espacio_liberable_mb']} MB")
            else:
                mb = resultado.get("liberado_mb", 0)
                total_liberado += mb
                proyectos_limpiados += 1
                log(f"  ✓ [{nombre}] conservado '{resultado['mp4_conservado']}' — liberado {mb} MB")

    if not dry_run:
        log(f"=== Total: {proyectos_limpiados} proyectos, {total_liberado:,} MB liberados ===")
    else:
        log("=== Fin dry-run. Ejecutar con --ejecutar para aplicar. ===")


if __name__ == "__main__":
    import sys
    dry = "--ejecutar" not in sys.argv
    main(dry_run=dry)
