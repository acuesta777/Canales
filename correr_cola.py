#!/usr/bin/env python3
"""
correr_cola.py — Ejecuta todos los videos pendientes en cola_nocturna.json.

Uso:
    python3 correr_cola.py              # corre todos los pendientes
    python3 correr_cola.py --dry-run    # muestra qué correría sin ejecutar
"""
import sys, json, subprocess, time
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).parent
COLA_PATH = BASE / "cola_nocturna.json"
TIMEOUT = 3600  # segundos por render

def notify(title, msg):
    try:
        subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "{title}" with sound'], timeout=5, capture_output=True)
    except Exception:
        pass

def ts():
    return datetime.now().strftime("%H:%M:%S")

dry_run = "--dry-run" in sys.argv

if not COLA_PATH.exists():
    print("⚠️  cola_nocturna.json no existe.")
    sys.exit(1)

cola = json.loads(COLA_PATH.read_text(encoding="utf-8"))
pendientes = [e for e in cola if e.get("estado") == "pendiente"]

if not pendientes:
    print("✅ No hay videos pendientes en la cola.")
    sys.exit(0)

print(f"\n{'='*60}")
print(f"  COLA NOCTURNA — {len(pendientes)} pendiente(s)")
print(f"  Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
if dry_run:
    print("  MODO: dry-run (no ejecuta nada)")
print(f"{'='*60}\n")

resumen = []

for i, entry in enumerate(pendientes, 1):
    personaje = entry["personaje"]
    canal     = entry["canal"]
    render_script = entry.get("render_script", "render_timeline.py")
    carpeta   = entry["carpeta"]
    log_name  = f"render_{personaje.replace('-', '_')}"

    print(f"[{ts()}] [{i}/{len(pendientes)}] {canal}/{personaje}")

    if dry_run:
        print(f"  → python3 {render_script} {carpeta}")
        resumen.append({"personaje": personaje, "ok": None})
        continue

    cmd = ["bash", "run_timeout.sh", str(TIMEOUT), log_name,
           "python3", render_script, carpeta]

    t0 = time.time()
    try:
        result = subprocess.run(cmd, cwd=BASE)
        ok = result.returncode == 0
    except Exception as e:
        print(f"  ❌ Error ejecutando: {e}")
        ok = False

    elapsed = int(time.time() - t0)
    mins = elapsed // 60
    segs = elapsed % 60

    if ok:
        print(f"[{ts()}]   ✅ {personaje} completado en {mins}m {segs}s")
        notify("✅ Render completado", f"{personaje} listo ({mins}m {segs}s)")
    else:
        print(f"[{ts()}]   ❌ {personaje} falló ({mins}m {segs}s) — ver logs/render_{log_name}.log")
        notify("❌ Render falló", f"{personaje} — ver log")

    resumen.append({"personaje": personaje, "ok": ok, "tiempo": f"{mins}m {segs}s"})

# Resumen final
print(f"\n{'='*60}")
print(f"  RESUMEN — {datetime.now().strftime('%H:%M:%S')}")
print(f"{'='*60}")
for r in resumen:
    if r["ok"] is None:
        icon = "🔵"
        extra = "(dry-run)"
    elif r["ok"]:
        icon = "✅"
        extra = r.get("tiempo", "")
    else:
        icon = "❌"
        extra = r.get("tiempo", "") + " — FALLÓ"
    print(f"  {icon} {r['personaje']}  {extra}")

ok_count  = sum(1 for r in resumen if r["ok"] is True)
fail_count = sum(1 for r in resumen if r["ok"] is False)
if not dry_run:
    print(f"\n  ✅ {ok_count} completados  |  ❌ {fail_count} fallidos")
    notify("Cola nocturna finalizada", f"{ok_count} OK · {fail_count} fallidos")
print(f"{'='*60}\n")
