#!/usr/bin/env python3
"""
Asegura que los clips YT de una carpeta v2+ tengan orden diferente a la referencia.
Uso: python3 shuffle_clips_diferente.py <carpeta_nueva> <carpeta_referencia>
Ejemplo: python3 shuffle_clips_diferente.py riqueza/eliseo_robles_v2/clips riqueza/eliseo_robles/clips
"""
import sys, random
from pathlib import Path

def get_order(folder: Path) -> list[str]:
    return sorted(
        [f.name for f in folder.iterdir() if not f.name.startswith('_') and f.suffix == '.mp4'],
        key=lambda x: int(x.replace('.mp4', ''))
    )

def shuffle_diferente(target: Path, reference: Path, max_intentos: int = 20) -> None:
    clips = sorted(
        [f for f in target.iterdir() if not f.name.startswith('_') and f.suffix == '.mp4'],
        key=lambda x: int(x.stem)
    )
    ref_order = get_order(reference)

    if len(clips) == 0:
        print(f"[ERROR] No hay clips en {target}")
        sys.exit(1)

    indices = list(range(1, len(clips) + 1))

    for intento in range(max_intentos):
        random.shuffle(indices)
        new_names = [f"{i}.mp4" for i in indices]
        current_names = [f.name for f in clips]

        if new_names != ref_order and new_names != current_names:
            # Renombrar a tmp primero
            for i, f in enumerate(clips):
                f.rename(target / f'_tmp_{i:04d}.mp4')
            tmp_clips = sorted(target.glob('_tmp_*.mp4'))
            for new_num, f in zip(indices, tmp_clips):
                f.rename(target / f'{new_num}.mp4')
            print(f"[OK] {len(clips)} clips reordenados en {target} (intento {intento+1})")
            return

    print(f"[WARN] No se encontró orden diferente en {max_intentos} intentos — usando último shuffle")
    for i, f in enumerate(clips):
        f.rename(target / f'_tmp_{i:04d}.mp4')
    tmp_clips = sorted(target.glob('_tmp_*.mp4'))
    for new_num, f in zip(indices, tmp_clips):
        f.rename(target / f'{new_num}.mp4')

def main():
    if len(sys.argv) < 3:
        print("Uso: python3 shuffle_clips_diferente.py <carpeta_nueva> <carpeta_referencia>")
        sys.exit(1)

    target = Path(sys.argv[1])
    reference = Path(sys.argv[2])

    if not target.exists():
        print(f"[ERROR] Carpeta destino no existe: {target}")
        sys.exit(1)
    if not reference.exists():
        print(f"[ERROR] Carpeta referencia no existe: {reference}")
        sys.exit(1)

    shuffle_diferente(target, reference)

if __name__ == '__main__':
    main()
