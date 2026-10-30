#!/usr/bin/env python3
"""
Borra carpetas de proyectos de video con más de 30 días de antigüedad.
Corre el último día del mes. Solo toca carpetas que tienen un MP4 (proyecto terminado).
"""

import shutil
from pathlib import Path
from datetime import datetime, timedelta

BASE = Path("/Users/anyelocuesta/Downloads/Canales")
LOG_FILE = BASE / "logs" / "borrar_proyectos_viejos.log"
DIAS = 30

EXCLUIR = {
    "_config", "_jsonytapi", "_logs", "_memory", "_musica", "__pycache__",
    "logs", "memory", "referencias", "config",
}


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_FILE.parent.mkdir(exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def es_ultimo_dia_del_mes() -> bool:
    manana = datetime.now() + timedelta(days=1)
    return manana.day == 1


def antiguedad_dias(folder: Path) -> float:
    """Días desde la última modificación de la carpeta."""
    return (datetime.now().timestamp() - folder.stat().st_mtime) / 86400


def tiene_mp4(folder: Path) -> bool:
    return any(folder.glob("*.mp4"))


def detectar_canales() -> list[Path]:
    canales = []
    for item in sorted(BASE.iterdir()):
        if not item.is_dir():
            continue
        if item.name in EXCLUIR or item.name.startswith(".") or item.name.startswith("_"):
            continue
        if any(sub.is_dir() and tiene_mp4(sub) for sub in item.iterdir()):
            canales.append(item)
    return canales


def main(dry_run=False, forzar=False):
    if not forzar and not es_ultimo_dia_del_mes():
        print(f"Hoy no es el último día del mes. Usa --forzar para ejecutar igual.")
        return

    modo = "DRY-RUN" if dry_run else "REAL"
    log(f"=== Borrar proyectos >30 días [{modo}] ===")

    total_liberado = 0
    borrados = 0
    limite = datetime.now() - timedelta(days=DIAS)

    for canal in detectar_canales():
        for proyecto in sorted(canal.iterdir()):
            if not proyecto.is_dir():
                continue
            if not tiene_mp4(proyecto):
                continue
            dias = antiguedad_dias(proyecto)
            if dias < DIAS:
                continue

            tamaño = sum(f.stat().st_size for f in proyecto.rglob("*") if f.is_file())
            mb = round(tamaño / 1_000_000)
            nombre = f"{canal.name}/{proyecto.name}"

            if dry_run:
                log(f"  [{nombre}] {dias:.0f} días — borraría {mb} MB")
            else:
                shutil.rmtree(proyecto)
                total_liberado += mb
                borrados += 1
                log(f"  ✓ [{nombre}] {dias:.0f} días — liberado {mb} MB")

    if not dry_run:
        log(f"=== Total: {borrados} carpetas borradas, {total_liberado:,} MB liberados ===")
    else:
        log("=== Fin dry-run. Usa --ejecutar para aplicar. ===")


if __name__ == "__main__":
    import sys
    dry = "--ejecutar" not in sys.argv
    forzar = "--forzar" in sys.argv
    main(dry_run=dry, forzar=forzar)
