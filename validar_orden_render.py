#!/usr/bin/env python3
"""
Valida que el orden de clips usado en el render coincide con el aprobado en el dashboard.

Uso:
    python3 validar_orden_render.py riqueza/fernando_casanova/
"""

import sys
import json
from pathlib import Path

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 validar_orden_render.py <nicho>/<personaje>/")
        sys.exit(1)

    carpeta = Path(sys.argv[1].rstrip("/"))
    orden_path = carpeta / "render_used_order.json"
    meta_path  = carpeta / "metadata.json"

    if not orden_path.exists():
        print(f"✗ No existe {orden_path}")
        print("  El render no terminó o es una versión antigua de render.py.")
        sys.exit(1)

    data = json.loads(orden_path.read_text())
    dashboard_order = data.get("clips_order_dashboard", [])
    render_order    = data.get("clips_used_render", [])
    recycled_start  = data.get("recycled_start", len(render_order))

    if not dashboard_order:
        # Leer directamente de metadata si no está en el archivo
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            dashboard_order = meta.get("clips_order", [])

    print(f"\n{'='*60}")
    print(f"  VALIDADOR DE ORDEN — {carpeta}")
    print(f"{'='*60}")
    print(f"  Dashboard (aprobados): {len(dashboard_order)} clips")
    print(f"  Render (usados):       {len(render_order)} clips")
    print(f"  Reciclados:            {len(render_order) - recycled_start}")

    if not dashboard_order:
        print("\n⚠️  clips_order vacío en metadata — el dashboard no guardó el orden.")
        sys.exit(1)

    # Comparar solo los clips NO reciclados contra el orden del dashboard
    first_pass = render_order[:recycled_start]

    errores = []
    for i, (esperado, real) in enumerate(zip(dashboard_order, first_pass)):
        if esperado != real:
            errores.append((i + 1, esperado, real))

    # Verificar que todos los del dashboard aparezcan (sin importar reciclados)
    usados_set   = set(render_order)
    esperados_set = set(dashboard_order)
    faltantes     = esperados_set - usados_set
    extras        = usados_set - esperados_set

    print()
    if not errores and not faltantes:
        print("✅ ORDEN CORRECTO — el render coincide exactamente con el dashboard")
        if extras:
            print(f"   (+ {len(extras)} clips reciclados fuera del orden original — normal)")
    else:
        print("❌ ORDEN INCORRECTO")
        if errores:
            print(f"\n  Primeros {min(10, len(errores))} desajustes de orden:")
            for pos, esp, real in errores[:10]:
                print(f"    Posición {pos:4d}: dashboard={esp}  render={real}")
        if faltantes:
            print(f"\n  Clips del dashboard que NO aparecen en el render ({len(faltantes)}):")
            for c in sorted(faltantes)[:10]:
                print(f"    {c}")
        if extras:
            print(f"\n  Clips en el render que NO están en el dashboard ({len(extras)}):")
            for c in sorted(extras)[:10]:
                print(f"    {c}")
        sys.exit(1)

    print()

if __name__ == "__main__":
    main()
