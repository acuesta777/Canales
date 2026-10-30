#!/usr/bin/env python3
"""
Lanza un proceso y muestra notificación del sistema cuando termina o falla.
Uso: python3 notificar.py "título" comando [args...]
"""
import sys, subprocess, time, os

titulo = sys.argv[1]
cmd    = sys.argv[2:]

print(f"⏳ {titulo} — iniciando...")
t0 = time.time()
r  = subprocess.run(cmd)
dt = int(time.time() - t0)
mins = dt // 60
segs = dt % 60

if r.returncode == 0:
    msg = f"✅ {titulo} completado en {mins}m{segs}s"
    emoji = "✅"
else:
    msg = f"❌ {titulo} FALLÓ (código {r.returncode}) en {mins}m{segs}s"
    emoji = "❌"

print(f"\n{msg}")

# Notificación macOS
os.system(f'osascript -e \'display notification "{msg}" with title "Pipeline Farandula" sound name "Glass"\'')
