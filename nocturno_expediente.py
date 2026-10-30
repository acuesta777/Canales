#!/usr/bin/env python3
"""
nocturno_expediente.py — Pipeline nocturno para el canal Expediente de Famosos.

Modos de uso:
    python3 nocturno_expediente.py              # pipeline completo (TTS→SRT→timeline→imágenes)
    python3 nocturno_expediente.py --solo-render  # solo render (después de aprobar en dashboard)
    python3 nocturno_expediente.py --desde grupo_audaz  # empieza desde ese personaje
    python3 nocturno_expediente.py --dry-run    # muestra pasos sin ejecutar

Personajes configurados:
    los_teen_tops, grupo_audaz, los_tigres_del_norte
"""

import sys, os, subprocess, time, json, argparse
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE   = Path(__file__).parent
NICHO  = "riqueza"

QUEUE = [
    {"personaje": "los_teen_tops"},
    {"personaje": "grupo_audaz"},
    {"personaje": "los_tigres_del_norte"},
]

TIMEOUTS = {
    "tts":      300,
    "srt":      360,
    "timeline": 300,
    "imagenes": 1800,
    "render":   3600,
}

# ── notificaciones macOS ───────────────────────────────────────────────────────

def notify(title, message, sound=True):
    snd = "with sound" if sound else "without sound"
    script = f'display notification "{message}" with title "{title}" {snd}'
    try:
        subprocess.run(["osascript", "-e", script], timeout=5, capture_output=True)
    except Exception:
        pass

def log(msg, icon=""):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {icon} {msg}", flush=True)

# ── runner ─────────────────────────────────────────────────────────────────────

def run_step(name, cmd, timeout, personaje):
    log_path = BASE / "logs" / f"{name}_{personaje}.log"
    log_path.parent.mkdir(exist_ok=True)
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    try:
        result = subprocess.run(
            cmd, timeout=timeout, capture_output=True, text=True, env=env, cwd=str(BASE)
        )
        with open(log_path, "a") as f:
            f.write(result.stdout or "")
            f.write(result.stderr or "")
        if result.returncode != 0:
            out = (result.stderr or result.stdout or "")[-500:]
            return False, f"exit {result.returncode}: {out}"
        return True, ""
    except subprocess.TimeoutExpired:
        return False, f"timeout {timeout}s"
    except Exception as e:
        return False, str(e)

# ── verificaciones ─────────────────────────────────────────────────────────────

def carpeta(personaje):
    return BASE / NICHO / personaje

def verificar_guion(personaje):
    txt = carpeta(personaje) / f"{personaje}.txt"
    if not txt.exists():
        return False, 0
    chars = len(txt.read_text())
    return 24000 <= chars <= 26000, chars

def verificar_audio(personaje):
    mp3 = carpeta(personaje) / f"{personaje}.mp3"
    return mp3.exists() and mp3.stat().st_size > 100_000

def verificar_srt(personaje):
    srt = carpeta(personaje) / f"{personaje}.srt"
    return srt.exists() and srt.stat().st_size > 1000

def verificar_timeline(personaje):
    tl = carpeta(personaje) / "05-montaje" / "timeline.json"
    return tl.exists()

def verificar_imagenes(personaje):
    if not verificar_timeline(personaje):
        return 0, 0
    tl = json.loads((carpeta(personaje) / "05-montaje" / "timeline.json").read_text())
    segs = tl.get("visual_timeline", [])
    img_dir = carpeta(personaje) / "03-imagenes"
    listos = [s for s in segs if (img_dir / f"flow_{s['segment_id']:04d}_zp.mp4").exists()]
    return len(listos), len(segs)

def verificar_video(personaje):
    mp4 = carpeta(personaje) / f"{personaje}_final.mp4"
    return mp4.exists() and mp4.stat().st_size > 10_000_000

def verificar_clips(personaje):
    clips_dir = carpeta(personaje) / "clips"
    if not clips_dir.exists():
        return 0
    return len(list(clips_dir.glob("*.mp4")))

# ── pasos ──────────────────────────────────────────────────────────────────────

def paso_tts(personaje):
    cmd = [sys.executable, "tts_single.py", f"{NICHO}/{personaje}/"]
    return run_step("tts", cmd, TIMEOUTS["tts"], personaje)

def paso_srt(personaje):
    cmd = [sys.executable, "srt_single.py", f"{NICHO}/{personaje}/"]
    return run_step("srt", cmd, TIMEOUTS["srt"], personaje)

def paso_timeline(personaje):
    cmd = [sys.executable, "generar_timeline_riqueza.py", f"{NICHO}/{personaje}/"]
    return run_step("timeline", cmd, TIMEOUTS["timeline"], personaje)

def paso_imagenes(personaje):
    cmd = [sys.executable, "imagen_ai33pro.py", f"{NICHO}/{personaje}/"]
    return run_step("imagenes", cmd, TIMEOUTS["imagenes"], personaje)

def paso_render(personaje):
    cmd = [sys.executable, "render.py", f"{NICHO}/{personaje}/"]
    return run_step("render", cmd, TIMEOUTS["render"], personaje)

# ── pipeline por personaje ─────────────────────────────────────────────────────

def procesar(personaje, dry_run=False, solo_render=False):
    log(f"{'─'*60}")
    log(f"INICIANDO: {NICHO}/{personaje}", "▶")
    notify("Expediente", f"Iniciando {personaje}")

    errores = []

    def intentar(nombre, fn, verificacion=None):
        if verificacion and verificacion():
            log(f"  {nombre}: ya existe — saltando", "✓")
            return True
        if dry_run:
            log(f"  {nombre}: [dry-run]", "·")
            return True
        log(f"  {nombre}: iniciando…", "⏳")
        t0 = time.time()
        ok, err = fn()
        elapsed = time.time() - t0
        if ok:
            log(f"  {nombre}: ✓ ({elapsed:.0f}s)", "✅")
        else:
            log(f"  {nombre}: ✗ {err}", "❌")
            notify("Expediente ❌", f"{personaje}: falló en {nombre}")
            errores.append((nombre, err))
        return ok

    if solo_render:
        meta = carpeta(personaje) / "metadata.json"
        if not meta.exists():
            log(f"  render: ✗ sin metadata.json — no aprobado en dashboard", "❌")
            errores.append(("render", "sin metadata"))
            return False, errores
        if not intentar("render", lambda: paso_render(personaje)):
            return False, errores
        notify("Expediente ✅", f"{personaje}: render completado")
        return True, errores

    # Verificar guion
    ok_g, chars = verificar_guion(personaje)
    if chars == 0:
        log(f"  guion: ✗ faltante — crear {personaje}.txt primero", "❌")
        errores.append(("guion", "faltante"))
        return False, errores
    elif not ok_g:
        log(f"  guion: ⚠ {chars} chars fuera de rango, continuando", "⚠️")
    else:
        log(f"  guion: ✓ ({chars} chars)", "✅")

    # Verificar clips
    n_clips = verificar_clips(personaje)
    if n_clips < 50:
        log(f"  clips: ⚠ solo {n_clips} clips — considera bajar más", "⚠️")
    else:
        log(f"  clips: ✓ ({n_clips} clips)", "✅")

    if not intentar("tts",      lambda: paso_tts(personaje),      verificacion=lambda: verificar_audio(personaje)):
        return False, errores
    if not intentar("srt",      lambda: paso_srt(personaje),      verificacion=lambda: verificar_srt(personaje)):
        return False, errores
    if not intentar("timeline", lambda: paso_timeline(personaje), verificacion=lambda: verificar_timeline(personaje)):
        return False, errores

    # Imágenes
    listos, total = verificar_imagenes(personaje)
    if listos >= total > 0:
        log(f"  imagenes: ya existen ({listos}/{total}) — saltando", "✓")
    else:
        log(f"  imagenes: iniciando AI33… ({listos}/{total} listos)", "⏳")
        t0 = time.time()
        ok_img, err_img = paso_imagenes(personaje)
        elapsed = time.time() - t0
        listos2, total2 = verificar_imagenes(personaje)
        if ok_img:
            log(f"  imagenes: ✓ ({listos2}/{total2}, {elapsed:.0f}s)", "✅")
        else:
            log(f"  imagenes: ⚠ {listos2}/{total2} listos ({elapsed:.0f}s)", "⚠️")
            errores.append(("imagenes", err_img))

    return True, errores

# ── main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Pipeline nocturno — Expediente de Famosos")
    parser.add_argument("--solo-render", action="store_true",
                        help="Solo render (ejecutar después de aprobar en dashboard)")
    parser.add_argument("--desde",      metavar="PERSONAJE",
                        help="Empezar desde este personaje")
    parser.add_argument("--solo",       metavar="PERSONAJE",
                        help="Procesar solo este personaje")
    parser.add_argument("--dry-run",    action="store_true",
                        help="Mostrar pasos sin ejecutar")
    args = parser.parse_args()

    cola = QUEUE[:]
    if args.solo:
        cola = [e for e in QUEUE if e["personaje"] == args.solo]
        if not cola:
            print(f"Personaje '{args.solo}' no encontrado. Disponibles: {[e['personaje'] for e in QUEUE]}")
            sys.exit(1)
    elif args.desde:
        nombres = [e["personaje"] for e in QUEUE]
        if args.desde not in nombres:
            print(f"Personaje '{args.desde}' no encontrado. Disponibles: {nombres}")
            sys.exit(1)
        idx = nombres.index(args.desde)
        cola = QUEUE[idx:]

    modo = "SOLO-RENDER" if args.solo_render else "PREPARAR"
    log(f"=== Expediente de Famosos — {modo} ===", "🎬")
    log(f"Personajes en cola: {[e['personaje'] for e in cola]}")

    resumen = []
    if args.solo_render and len(cola) > 1:
        # Renders en paralelo — todos a la vez
        log(f"Modo paralelo: {len(cola)} renders simultáneos", "⚡")
        def _render_one(entrada):
            p = entrada["personaje"]
            ok, errs = procesar(p, dry_run=args.dry_run, solo_render=True)
            return {"personaje": p, "ok": ok, "errores": errs}
        with ThreadPoolExecutor(max_workers=len(cola)) as ex:
            futuros = {ex.submit(_render_one, e): e["personaje"] for e in cola}
            for fut in as_completed(futuros):
                resumen.append(fut.result())
    else:
        for entrada in cola:
            personaje = entrada["personaje"]
            ok, errores = procesar(personaje, dry_run=args.dry_run, solo_render=args.solo_render)
            resumen.append({"personaje": personaje, "ok": ok, "errores": errores})

    # Resumen final
    log(f"\n{'='*60}")
    log("RESUMEN FINAL", "📊")
    exitos = 0
    for r in resumen:
        ico = "✅" if r["ok"] else "❌"
        log(f"  {ico} {r['personaje']}")
        for nombre, err in r["errores"]:
            log(f"      ✗ {nombre}: {err[:80]}")
        if r["ok"]:
            exitos += 1

    if args.solo_render:
        notify("Expediente ✅", f"Renders completados: {exitos}/{len(resumen)}")
    else:
        notify(
            "Expediente — Listo para dashboard",
            f"{exitos}/{len(resumen)} personajes listos. Abre el dashboard y aprueba."
        )
        log("\n🚀 Pipeline completado. Pasos siguientes:", "")
        log("   1. Abre el dashboard: python3 dashboard.py (puerto 5001)")
        log("   2. Revisa y aprueba clips para cada personaje")
        log("   3. Cuando estés listo: python3 nocturno_expediente.py --solo-render")

if __name__ == "__main__":
    main()
