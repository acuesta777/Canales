#!/usr/bin/env python3
"""
pipeline_farandula.py — Orquestador automático del canal Farandula.

Pasos:
  1. tts_farandula.py     → audio.mp3 + sections.json
  2. srt_single.py        → audio.srt (full, 9999s)
  3. timestamps_farandula.py → timestamps.json
  4. harvester_farandula.py  → fotos/clips en iCloud (Brave → Flow)
  5. render_farandula.py     → output.mp4

Único input: carpeta del video (debe tener los .txt numerados).

Uso:
  python3 pipeline_farandula.py "VIVIENDO DE FAVOR TELEVISA/"
  python3 pipeline_farandula.py "VIVIENDO DE FAVOR TELEVISA/" --desde harvester
  python3 pipeline_farandula.py "VIVIENDO DE FAVOR TELEVISA/" --desde render
"""

import sys, subprocess, pathlib, time

HERE    = pathlib.Path(__file__).parent
CANALES = HERE.parent

PASOS = ["tts", "srt", "timestamps", "harvester", "render"]

VERDE    = "\033[92m"
ROJO     = "\033[91m"
AMARILLO = "\033[93m"
NEGRITA  = "\033[1m"
RESET    = "\033[0m"

def banner(texto):
    print(f"\n{NEGRITA}{'='*60}")
    print(f"  {texto}")
    print(f"{'='*60}{RESET}\n")

def correr(descripcion, cmd, timeout=3600):
    print(f"{AMARILLO}▶ {descripcion}{RESET}")
    t0 = time.time()
    r = subprocess.run(cmd, timeout=timeout)
    elapsed = time.time() - t0
    if r.returncode != 0:
        print(f"{ROJO}✗ FALLÓ: {descripcion} ({elapsed:.0f}s){RESET}")
        sys.exit(r.returncode)
    print(f"{VERDE}✓ OK: {descripcion} ({elapsed:.0f}s){RESET}\n")

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 pipeline_farandula.py <carpeta_video> [--desde PASO]")
        print("Pasos: tts, srt, timestamps, harvester, render")
        sys.exit(1)

    folder = pathlib.Path(sys.argv[1])
    if not folder.is_dir():
        print(f"ERROR: {folder} no existe")
        sys.exit(1)

    # Detectar desde qué paso arrancar
    desde = "tts"
    if "--desde" in sys.argv:
        idx = sys.argv.index("--desde")
        desde = sys.argv[idx + 1].lower()
        if desde not in PASOS:
            print(f"ERROR: paso '{desde}' no válido. Opciones: {', '.join(PASOS)}")
            sys.exit(1)

    ejecutar = PASOS[PASOS.index(desde):]

    banner(f"PIPELINE FARANDULA — {folder.name}")
    print(f"  Pasos a ejecutar: {' → '.join(p.upper() for p in ejecutar)}\n")

    py = sys.executable

    # ── Paso 1: TTS ────────────────────────────────────────────────────────────
    if "tts" in ejecutar:
        mp3 = folder / "audio.mp3"
        if mp3.exists():
            print(f"{VERDE}  audio.mp3 ya existe — saltando TTS{RESET}\n")
        else:
            correr(
                "TTS → audio.mp3 (Alberto Rodriguez)",
                [py, str(HERE / "tts_farandula.py"), str(folder)],
                timeout=600
            )

    # ── Paso 2: SRT completo ──────────────────────────────────────────────────
    if "srt" in ejecutar:
        srt = folder / "audio.srt"
        if srt.exists():
            # Verificar que sea el SRT completo (más de 20 min)
            content = srt.read_text(encoding="utf-8")
            if "20:" in content or "21:" in content or "22:" in content or "23:" in content or "24:" in content or "25:" in content or "26:" in content or "27:" in content:
                print(f"{VERDE}  audio.srt completo ya existe — saltando SRT{RESET}\n")
            else:
                print(f"{AMARILLO}  SRT incompleto (< 20 min) — regenerando...{RESET}")
                srt.unlink()
                correr(
                    "SRT completo (full audio)",
                    [py, str(CANALES / "srt_single.py"), str(folder / "audio.mp3"),
                     "--canal", "farandula"],
                    timeout=360
                )
        else:
            correr(
                "SRT completo (full audio)",
                [py, str(CANALES / "srt_single.py"), str(folder / "audio.mp3"),
                 "--canal", "farandula"],
                timeout=360
            )

    # ── Paso 3: Timestamps ────────────────────────────────────────────────────
    if "timestamps" in ejecutar:
        correr(
            "Timestamps por artista",
            [py, str(HERE / "timestamps_farandula.py"), str(folder)],
            timeout=60
        )

    # ── Paso 4: Harvester ─────────────────────────────────────────────────────
    if "harvester" in ejecutar:
        correr(
            "Harvester — fotos de artistas (Brave → Flow)",
            [py, str(HERE / "harvester_farandula.py"), str(folder)],
            timeout=7200  # 2h: puede necesitar esperar Flow
        )

    # ── Paso 5: Render ────────────────────────────────────────────────────────
    if "render" in ejecutar:
        correr(
            "Render final → output.mp4",
            [py, str(HERE / "render_farandula.py"), str(folder)],
            timeout=7200
        )

    # ── Resumen ───────────────────────────────────────────────────────────────
    out = folder / "output.mp4"
    if out.exists():
        size_mb = out.stat().st_size / 1024 / 1024
        print(f"\n{NEGRITA}{VERDE}{'='*60}")
        print(f"  ✅ PIPELINE COMPLETO")
        print(f"  {out.name}  {size_mb:.0f} MB")
        print(f"  {out}")
        print(f"{'='*60}{RESET}\n")
        print("  Siguiente: subir con youtube_upload.py (privado)")
    else:
        print(f"\n{ROJO}  ⚠ output.mp4 no encontrado — revisar logs{RESET}")

if __name__ == "__main__":
    main()
