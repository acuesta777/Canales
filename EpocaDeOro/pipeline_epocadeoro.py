#!/usr/bin/env python3
"""
pipeline_epocadeoro.py — Orquestador del canal La Verdad Dorada.

Pasos:
  1. tts_epocadeoro.py          → audio.mp3 + sections.json
  2. srt_single.py              → audio.srt (full)
  3. timestamps_epocadeoro.py   → timestamps.json
  3b. validar_timestamps_epocadeoro.py → validación duración por artista
  4. harvester_clips_epocadeoro.py → dashboard_meta.json (clips por artista)
  5. dashboard_epocadeoro.py    → aprobación manual en http://localhost:5005
     [PAUSA — usuario aprueba en el navegador]
  6. render_epocadeoro.py       → output.mp4

Uso:
  python3 pipeline_epocadeoro.py "Video-001 Murieron en la Miseria/"
  python3 pipeline_epocadeoro.py "Video-001/" --desde srt
  python3 pipeline_epocadeoro.py "Video-001/" --desde render
"""

import sys, subprocess, pathlib, time

HERE    = pathlib.Path(__file__).parent
CANALES = HERE.parent

PASOS = ["tts", "srt", "timestamps", "harvester", "dashboard", "render"]

VERDE    = "\033[92m"
ROJO     = "\033[91m"
AMARILLO = "\033[93m"
NEGRITA  = "\033[1m"
RESET    = "\033[0m"

def banner(texto):
    print(f"\n{NEGRITA}{'='*65}")
    print(f"  {texto}")
    print(f"{'='*65}{RESET}\n")

def correr(descripcion, cmd, timeout=3600):
    print(f"{AMARILLO}▶ {descripcion}{RESET}")
    t0 = time.time()
    r  = subprocess.run(cmd, timeout=timeout)
    elapsed = time.time() - t0
    if r.returncode != 0:
        print(f"{ROJO}✗ FALLÓ: {descripcion} ({elapsed:.0f}s){RESET}")
        sys.exit(r.returncode)
    print(f"{VERDE}✓ OK: {descripcion} ({elapsed:.0f}s){RESET}\n")

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 pipeline_epocadeoro.py <carpeta_video> [--desde PASO]")
        print("Pasos: tts, srt, timestamps, harvester, dashboard, render")
        sys.exit(1)

    folder = pathlib.Path(sys.argv[1])
    if not folder.is_dir():
        print(f"ERROR: {folder} no existe o no es una carpeta")
        sys.exit(1)

    desde = "tts"
    if "--desde" in sys.argv:
        idx   = sys.argv.index("--desde")
        desde = sys.argv[idx + 1].lower()
        if desde not in PASOS:
            print(f"ERROR: paso '{desde}' no válido. Opciones: {', '.join(PASOS)}")
            sys.exit(1)

    ejecutar = PASOS[PASOS.index(desde):]

    banner(f"PIPELINE LA VERDAD DORADA — {folder.name}")
    print(f"  Pasos: {' → '.join(p.upper() for p in ejecutar)}\n")

    py = sys.executable

    # ── Paso 1: TTS ────────────────────────────────────────────────────────────
    if "tts" in ejecutar:
        mp3 = folder / "audio.mp3"
        if mp3.exists() and mp3.stat().st_size > 10000:
            print(f"{VERDE}  audio.mp3 ya existe — saltando TTS{RESET}\n")
        else:
            correr(
                "TTS → audio.mp3",
                [py, str(HERE / "tts_epocadeoro.py"), str(folder)],
                timeout=600
            )

    # ── Paso 2: SRT ───────────────────────────────────────────────────────────
    if "srt" in ejecutar:
        srt = folder / "audio.srt"
        if srt.exists():
            content = srt.read_text(encoding="utf-8")
            # Verificar que el SRT sea completo (>30 min)
            completo = any(f"{m}:" in content for m in ["30","31","32","33","34","35"])
            if completo:
                print(f"{VERDE}  audio.srt completo ya existe — saltando{RESET}\n")
            else:
                print(f"{AMARILLO}  SRT incompleto — regenerando...{RESET}")
                srt.unlink()
                correr(
                    "SRT completo (full audio)",
                    [py, str(CANALES / "srt_single.py"), str(folder / "audio.mp3"),
                     "--canal", "epocadeoro"],
                    timeout=420
                )
        else:
            correr(
                "SRT completo (full audio)",
                [py, str(CANALES / "srt_single.py"), str(folder / "audio.mp3"),
                 "--canal", "epocadeoro"],
                timeout=420
            )

    # ── Paso 3: Timestamps ────────────────────────────────────────────────────
    if "timestamps" in ejecutar:
        correr(
            "Timestamps por artista",
            [py, str(HERE / "timestamps_epocadeoro.py"), str(folder)],
            timeout=60
        )
        # Validación inmediata
        correr(
            "Validar timestamps",
            [py, str(HERE / "validar_timestamps_epocadeoro.py"), str(folder)],
            timeout=30
        )

    # ── Paso 4: Harvester ─────────────────────────────────────────────────────
    if "harvester" in ejecutar:
        correr(
            "Harvester — pre-seleccionar clips por artista",
            [py, str(HERE / "harvester_clips_epocadeoro.py"), str(folder)],
            timeout=300
        )

    # ── Paso 5: Dashboard ─────────────────────────────────────────────────────
    if "dashboard" in ejecutar:
        print(f"{AMARILLO}▶ Dashboard de aprobación{RESET}")
        print(f"  Abre: http://localhost:5005")
        print(f"  Aprueba/rechaza los clips en el navegador.")
        print(f"\n  {NEGRITA}Presiona ENTER cuando hayas aprobado todos los clips.{RESET}")

        # Lanzar dashboard en background
        import subprocess as sp, os
        proc = sp.Popen(
            [py, str(HERE / "dashboard_epocadeoro.py"), str(folder)],
            stdout=sp.DEVNULL, stderr=sp.DEVNULL
        )
        time.sleep(2)
        input()  # Esperar confirmación del usuario

        proc.terminate()
        print(f"{VERDE}✓ Dashboard cerrado{RESET}\n")

    # ── Paso 6: Render ────────────────────────────────────────────────────────
    if "render" in ejecutar:
        correr(
            "Render final → output.mp4",
            [py, str(HERE / "render_epocadeoro.py"), str(folder)],
            timeout=7200
        )

    # ── Resumen ───────────────────────────────────────────────────────────────
    out = folder / "output.mp4"
    if out.exists():
        size_mb = out.stat().st_size / 1024 / 1024
        print(f"\n{NEGRITA}{VERDE}{'='*65}")
        print(f"  ✅ PIPELINE COMPLETO — La Verdad Dorada")
        print(f"  {out.name}  {size_mb:.0f} MB")
        print(f"  {out}")
        print(f"{'='*65}{RESET}\n")
        print("  Siguiente: subir privado con youtube_upload.py")
    else:
        print(f"\n{ROJO}  ⚠ output.mp4 no encontrado — revisar logs{RESET}")


if __name__ == "__main__":
    main()
