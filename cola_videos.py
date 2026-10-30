#!/usr/bin/env python3
"""
cola_videos.py — Orquestador nocturno para el pipeline de riqueza.

Ejecuta una cola de videos en secuencia, con:
  - Timeout por paso
  - Notificaciones macOS al completar/fallar cada paso
  - Fallback multi-modelo + muapi.ai para imágenes
  - Reporte final con resumen de éxitos/fallos

Uso:
    python3 cola_videos.py                     # usa QUEUE definida abajo
    python3 cola_videos.py --dry-run           # muestra pasos sin ejecutar
    python3 cola_videos.py --desde PERSONAJE   # empieza desde ese personaje
    python3 cola_videos.py --solo PERSONAJE    # solo ese personaje

Cola: editar la lista QUEUE al final del archivo.
"""

import sys, os, subprocess, time, json, shutil, argparse, io, pickle
from pathlib import Path
from datetime import datetime

# ── configuración ─────────────────────────────────────────────────────────────

BASE = Path(__file__).parent

# Timeouts por paso (segundos)
TIMEOUTS = {
    "clips":    900,
    "tts":      300,
    "srt":      360,
    "timeline": 300,
    "imagenes": 1800,   # puede tardar mucho si hay fallback chain completo
    "render":   3600,
}

MUAPI_KEY_FILE = Path.home() / ".muapi_key"
AI33_KEY_FILE  = Path.home() / ".ai33_key"

# ── notificaciones macOS ───────────────────────────────────────────────────────

def notify(title, message, sound=True):
    """Notificación macOS via osascript."""
    snd = "with sound" if sound else "without sound"
    script = f'display notification "{message}" with title "{title}" {snd}'
    try:
        subprocess.run(["osascript", "-e", script], timeout=5, capture_output=True)
    except Exception:
        pass

def log(msg, icon=""):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {icon} {msg}", flush=True)


def verificar_token_youtube(canal_json: str) -> tuple[bool, str]:
    """
    Verifica que el token OAuth del canal esté vigente.
    Retorna (ok, mensaje).
    """
    tokens_dir = BASE / "_jsonytapi" / "tokens"
    canal_stem = Path(canal_json).stem
    token_file = tokens_dir / f"{canal_stem}.pickle"

    if not token_file.exists():
        return False, f"token no encontrado para {canal_json}"

    try:
        with open(token_file, "rb") as f:
            creds = pickle.load(f)
    except Exception as e:
        return False, f"error leyendo token: {e}"

    if creds.valid:
        return True, "token vigente"

    if creds.expired and creds.refresh_token:
        # Intentar refresh silencioso
        try:
            import google.auth.transport.requests as _greq
            creds.refresh(_greq.Request())
            # Guardar token renovado
            with open(token_file, "wb") as f:
                pickle.dump(creds, f)
            return True, "token renovado automáticamente"
        except Exception as e:
            err = str(e)
            if "invalid_grant" in err:
                return False, "token revocado por Google (invalid_grant) — requiere re-autorización manual"
            return False, f"error al renovar: {err}"

    return False, "token expirado sin refresh_token — requiere re-autorización manual"

# ── runner de subprocesos ──────────────────────────────────────────────────────

def run_step(name, cmd, timeout, log_file=None):
    """
    Corre un comando con timeout. Retorna (ok, salida).
    ok=True si returncode==0 y no hay timeout.
    """
    log_path = None
    if log_file:
        log_path = BASE / "logs" / log_file
        log_path.parent.mkdir(exist_ok=True)

    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    try:
        result = subprocess.run(
            cmd, timeout=timeout, capture_output=(log_path is not None),
            text=True, env=env, cwd=str(BASE)
        )
        if log_path:
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

# ── pasos del pipeline ─────────────────────────────────────────────────────────

def paso_clips(nicho, personaje, url):
    cmd = [sys.executable, "clips.py", url, f"{nicho}/{personaje}/"]
    return run_step("clips", cmd, TIMEOUTS["clips"], f"clips_{personaje}.log")

def paso_tts(nicho, personaje):
    cmd = [sys.executable, "tts_single.py", f"{nicho}/{personaje}/"]
    return run_step("tts", cmd, TIMEOUTS["tts"], f"tts_{personaje}.log")

def paso_srt(nicho, personaje):
    cmd = [sys.executable, "srt_single.py", f"{nicho}/{personaje}/"]
    return run_step("srt", cmd, TIMEOUTS["srt"], f"srt_{personaje}.log")

def paso_timeline(nicho, personaje):
    script = "generar_timeline_futbol.py" if nicho == "futbol" else "generar_timeline_riqueza.py"
    cmd = [sys.executable, script, f"{nicho}/{personaje}/"]
    return run_step("timeline", cmd, TIMEOUTS["timeline"], f"timeline_{personaje}.log")

def paso_imagenes(nicho, personaje):
    """
    Genera imágenes con AI33 Pro. Si algún segmento falla tras agotar el
    fallback chain de AI33, intenta muapi.ai como última opción.
    Retorna (ok, n_fallidos) — ok=True si todos los segmentos quedaron generados.
    """
    carpeta = f"{nicho}/{personaje}/"
    cmd = [sys.executable, "imagen_ai33pro.py", carpeta]
    ok, err = run_step("imagenes", cmd, TIMEOUTS["imagenes"], f"imagenes_{personaje}.log")

    # Aunque ok, verificar cuántos clips existen vs. cuántos necesitamos
    timeline_path = BASE / nicho / personaje / "05-montaje" / "timeline.json"
    img_dir = BASE / nicho / personaje / "03-imagenes"
    if not timeline_path.exists():
        return ok, 0

    tl = json.loads(timeline_path.read_text())
    segs = tl.get("visual_timeline", [])
    faltantes = [s for s in segs if not (img_dir / f"flow_{s['segment_id']:04d}_zp.mp4").exists()]

    if not faltantes:
        return True, 0

    log(f"AI33 falló {len(faltantes)} segs — intentando muapi.ai", "⚠️")
    notify("Cola videos", f"{personaje}: intentando muapi para {len(faltantes)} segs fallidos")

    n_recuperados = 0
    for seg in faltantes:
        recuperado = _generar_muapi(seg, img_dir)
        if recuperado:
            n_recuperados += 1
        else:
            log(f"  SEG {seg['segment_id']:02d}: muapi también falló", "✗")

    aun_faltantes = [s for s in segs if not (img_dir / f"flow_{s['segment_id']:04d}_zp.mp4").exists()]

    if aun_faltantes:
        log(f"Siguen faltando {len(aun_faltantes)} segs — render continuará sin ellos", "⚠️")
        return False, len(aun_faltantes)
    return True, 0

def _generar_muapi(seg, img_dir):
    """Genera una imagen via muapi.ai (flux-schnell) y la convierte a zoompan mp4."""
    import urllib.request, urllib.error, tempfile
    key_file = MUAPI_KEY_FILE
    if not key_file.exists():
        return False
    key = key_file.read_text().strip()

    prompt = seg.get("ia_prompt") or seg.get("ia_prompt_en") or seg.get("prompt_or_query", "")
    duration = seg.get("duration", 6.0)
    seg_id = seg["segment_id"]
    out_path = img_dir / f"flow_{seg_id:04d}_zp.mp4"

    # Iniciar tarea en muapi
    payload = json.dumps({
        "model": "flux-schnell",
        "prompt": prompt,
        "width": 1344, "height": 768,   # ~16:9
        "num_outputs": 1,
        "output_format": "jpeg",
    }).encode()
    req = urllib.request.Request(
        "https://muapi.ai/api/v1/images/generate",
        data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
    except Exception as e:
        log(f"  SEG {seg_id:02d} muapi request falló: {e}", "✗")
        return False

    request_id = resp.get("request_id") or resp.get("id")
    if not request_id:
        log(f"  SEG {seg_id:02d} muapi no devolvió request_id", "✗")
        return False

    # Polling muapi
    img_url = None
    for _ in range(30):
        time.sleep(4)
        try:
            poll = urllib.request.Request(
                f"https://muapi.ai/api/v1/images/generate/{request_id}",
                headers={"Authorization": f"Bearer {key}"},
            )
            with urllib.request.urlopen(poll, timeout=15) as r:
                data = json.loads(r.read())
            status = data.get("status", "")
            if status == "succeeded":
                imgs = data.get("output") or data.get("images") or []
                img_url = imgs[0] if imgs else None
                break
            if status in ("failed", "error"):
                break
        except Exception:
            pass

    if not img_url:
        return False

    # Descargar y zoompan
    sys.path.insert(0, str(BASE))
    try:
        from zoompan_clip import make_zoompan
    except ImportError:
        return False

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
        tmp = tf.name
    try:
        dl_cmd = ["curl", "-s", "-L", "-o", tmp, img_url]
        r = subprocess.run(dl_cmd, timeout=30, capture_output=True)
        if r.returncode != 0 or Path(tmp).stat().st_size < 1000:
            return False
        ok = make_zoompan(Path(tmp), out_path, duration, index=seg_id)
        return ok
    except Exception:
        return False
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass

def paso_render(nicho, personaje):
    script = "render_futbol.py" if nicho == "futbol" else "render.py"
    cmd = [sys.executable, script, f"{nicho}/{personaje}/"]
    return run_step("render", cmd, TIMEOUTS["render"], f"render_{personaje}.log")

# ── verificaciones de salida ───────────────────────────────────────────────────

def verificar_guion(nicho, personaje):
    """Retorna (ok, chars) sin correr validador (más rápido para la cola)."""
    txt = BASE / nicho / personaje / f"{personaje}.txt"
    if not txt.exists():
        return False, 0
    chars = len(txt.read_text())
    ok = 24500 <= chars <= 26500 if nicho != "futbol" else 14000 <= chars <= 18000
    return ok, chars

def verificar_audio(nicho, personaje):
    mp3 = BASE / nicho / personaje / f"{personaje}.mp3"
    return mp3.exists() and mp3.stat().st_size > 100_000

def verificar_srt(nicho, personaje):
    srt = BASE / nicho / personaje / f"{personaje}.srt"
    return srt.exists() and srt.stat().st_size > 1000

def verificar_video(nicho, personaje):
    mp4 = BASE / nicho / personaje / f"{personaje}_final.mp4"
    return mp4.exists() and mp4.stat().st_size > 10_000_000

def verificar_clips_existentes(nicho, personaje):
    clips_dir = BASE / nicho / personaje / "clips"
    if not clips_dir.exists():
        return 0
    return len(list(clips_dir.glob("*.mp4")))

# ── procesador de un video ─────────────────────────────────────────────────────

def paso_auto_approve(nicho, personaje):
    """Llama al endpoint de auto-aprobación del dashboard."""
    import urllib.request, urllib.error
    url = f"http://localhost:5001/api/cola_auto_approve/{nicho}/{personaje}/"
    try:
        req = urllib.request.Request(url, data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        if data.get("ok"):
            return True, f"{data.get('clips_order', 0)} clips en orden"
        return False, "endpoint devolvió ok=false"
    except Exception as e:
        return False, f"dashboard no responde: {e}"


def procesar_video(entrada, dry_run=False, auto_aprobacion=False):
    nicho     = entrada["nicho"]
    personaje = entrada["personaje"]
    url       = entrada.get("url", "")
    omitir    = set(entrada.get("omitir_pasos", []))

    log(f"{'─'*60}")
    log(f"INICIANDO: {nicho}/{personaje}", "▶")
    notify("Cola videos", f"Iniciando {personaje}")

    pasos_intentados = 0
    errores = []

    def intentar(nombre, fn, *args, verificacion=None):
        nonlocal pasos_intentados
        if nombre in omitir:
            log(f"  {nombre}: omitido por config", "⏭")
            return True
        if verificacion and verificacion():
            log(f"  {nombre}: ya existe — saltando", "✓")
            return True
        pasos_intentados += 1
        if dry_run:
            log(f"  {nombre}: [dry-run]", "·")
            return True
        log(f"  {nombre}: iniciando…", "⏳")
        t0 = time.time()
        ok, err = fn(*args)
        elapsed = time.time() - t0
        if ok:
            log(f"  {nombre}: ✓ ({elapsed:.0f}s)", "✅")
        else:
            log(f"  {nombre}: ✗ {err}", "❌")
            notify("Cola videos ❌", f"{personaje}: falló en {nombre}: {err[:80]}")
            errores.append((nombre, err))
        return ok

    # ── PASO 1: clips ──────────────────────────────────────────────────────────
    n_clips = verificar_clips_existentes(nicho, personaje)
    if not intentar("clips", paso_clips, nicho, personaje, url,
                    verificacion=lambda: n_clips >= 50):
        return False, errores

    # ── PASO 2: guion — no se genera automáticamente (requiere Claude) ─────────
    ok_g, chars = verificar_guion(nicho, personaje)
    if chars == 0:
        # Guion inexistente — sí es crítico
        msg = "guion faltante"
        log(f"  guion: ✗ {msg}", "❌")
        notify("Cola videos ❌", f"{personaje}: {msg}")
        errores.append(("guion", msg))
        return False, errores
    elif not ok_g:
        # Fuera de rango — advertencia pero continúa
        log(f"  guion: ⚠ {chars} chars fuera de rango ideal, continuando igual", "⚠️")
    else:
        log(f"  guion: ✓ ({chars} chars)", "✅")

    # ── PASO 3: TTS ────────────────────────────────────────────────────────────
    if not intentar("tts", paso_tts, nicho, personaje,
                    verificacion=lambda: verificar_audio(nicho, personaje)):
        return False, errores

    # ── PASO 4: SRT ────────────────────────────────────────────────────────────
    if not intentar("srt", paso_srt, nicho, personaje,
                    verificacion=lambda: verificar_srt(nicho, personaje)):
        return False, errores

    # ── PASO 5: timeline ───────────────────────────────────────────────────────
    timeline_path = BASE / nicho / personaje / "05-montaje" / "timeline.json"
    if not intentar("timeline", paso_timeline, nicho, personaje,
                    verificacion=lambda: timeline_path.exists()):
        return False, errores

    # ── PASO 6: imágenes (con fallback muapi) ─────────────────────────────────
    if "imagenes" not in omitir:
        pasos_intentados += 1
        if not dry_run:
            log("  imagenes: iniciando AI33…", "⏳")
            t0 = time.time()
            ok_img, n_faltantes = paso_imagenes(nicho, personaje)
            elapsed = time.time() - t0
            if ok_img:
                log(f"  imagenes: ✓ ({elapsed:.0f}s)", "✅")
            else:
                msg = f"{n_faltantes} segs sin imagen tras todos los fallbacks"
                log(f"  imagenes: ⚠ {msg} — continuando con render", "⚠️")
                errores.append(("imagenes", msg))
                # No se interrumpe — el render sigue con los clips que hay
        else:
            log("  imagenes: [dry-run]", "·")

    # ── PASO 6.5: auto-aprobación (modo legacy sin dashboard) ────────────────
    if auto_aprobacion:
        if not intentar("auto_approve", paso_auto_approve, nicho, personaje):
            return False, errores

    # ── PASO 7: render ─────────────────────────────────────────────────────────
    # Verificar que clips_order esté guardado (aprobación manual o auto)
    meta_path = BASE / nicho / personaje / "metadata.json"
    _m_check = {}
    if meta_path.exists():
        try: _m_check = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception: pass
    if not _m_check.get("clips_order"):
        msg = "clips_order vacío — abre el dashboard y aprueba los clips primero"
        log(f"  render: ✗ {msg}", "❌")
        errores.append(("render", msg))
        return False, errores

    if not intentar("render", paso_render, nicho, personaje,
                    verificacion=lambda: verificar_video(nicho, personaje)):
        return False, errores

    # ── PASO 8: subida YouTube (si hay canal configurado) ─────────────────────
    canal = entrada.get("canal")
    if canal and "render" not in omitir:
        if not dry_run:
            log(f"  upload: subiendo a {canal}…", "⏳")
            t0 = time.time()
            cmd_up = [
                sys.executable, str(BASE / "youtube_upload.py"),
                f"{nicho}/{personaje}/",
                "--headless", "--canal", canal, "--privacidad", "private"
            ]
            try:
                result = subprocess.run(cmd_up, capture_output=True, text=True,
                                        timeout=300, cwd=str(BASE))
                elapsed = time.time() - t0
                if result.returncode == 0:
                    log(f"  upload: ✓ ({elapsed:.0f}s)", "✅")
                else:
                    err = (result.stderr or result.stdout or "")[:200]
                    log(f"  upload: ✗ {err}", "❌")
                    errores.append(("upload", err))
            except subprocess.TimeoutExpired:
                log("  upload: ✗ timeout 300s", "❌")
                errores.append(("upload", "timeout"))
        else:
            log(f"  upload: [dry-run] → {canal}", "·")

    # ── éxito ──────────────────────────────────────────────────────────────────
    log(f"COMPLETADO: {nicho}/{personaje}", "✅")
    notify("Cola videos ✅", f"{personaje}: video listo en {nicho}/")
    return True, errores

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Orquestador nocturno de videos")
    parser.add_argument("--dry-run",          action="store_true", help="Mostrar pasos sin ejecutar")
    parser.add_argument("--desde",            metavar="PERSONAJE",  help="Empezar desde este personaje")
    parser.add_argument("--solo",             metavar="PERSONAJE",  help="Procesar solo este personaje")
    parser.add_argument("--auto-aprobacion",  action="store_true", help="Aprobar clips automáticamente sin dashboard")
    parser.add_argument("--preparar",         action="store_true", help="Solo prepara hasta imágenes y muestra URLs de dashboards — sin render")
    parser.add_argument("--solo-render",      action="store_true", help="Solo renderiza — asume que los dashboards ya fueron aprobados")
    args = parser.parse_args()

    # ── COLA — editar aquí ──────────────────────────────────────────────────────
    QUEUE = [
        {
            "nicho":        "riqueza",
            "personaje":    "oscar_pulido",
            "url":          "https://www.youtube.com/watch?v=J3xG8TjAbBU",
            "canal":        "Fama Y Caida.json",   # canal YouTube destino
            "omitir_pasos": ["clips", "tts", "srt"],
        },
        # Ejemplo de nueva entrada:
        # {
        #     "nicho":        "riqueza",
        #     "personaje":    "nombre_artista",
        #     "url":          "https://www.youtube.com/watch?v=XXXXXXXXXX",
        #     "canal":        "Fama Y Caida.json",
        #     "omitir_pasos": [],
        # },
    ]
    # ───────────────────────────────────────────────────────────────────────────

    if not QUEUE:
        print("⚠️  QUEUE está vacía. Edita cola_videos.py y agrega videos a la lista QUEUE.")
        sys.exit(0)

    # Filtrar cola
    cola = QUEUE
    if args.solo:
        cola = [e for e in QUEUE if e["personaje"] == args.solo]
    elif args.desde:
        nombres = [e["personaje"] for e in QUEUE]
        if args.desde not in nombres:
            print(f"Personaje '{args.desde}' no encontrado en la cola.")
            sys.exit(1)
        idx = nombres.index(args.desde)
        cola = QUEUE[idx:]

    print(f"\n{'='*60}")
    print(f"  COLA DE VIDEOS — {len(cola)} entradas")
    print(f"  Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if args.dry_run:
        print("  MODO: dry-run (no ejecuta nada)")
    if args.preparar:
        print("  MODO: --preparar (clips→tts→srt→timeline→imagenes, sin render)")
    if args.solo_render:
        print("  MODO: --solo-render (solo render, respeta orden del dashboard)")
    print(f"{'='*60}\n")

    resumen = []
    t_inicio_global = time.time()

    for i, entrada in enumerate(cola, 1):
        personaje = entrada["personaje"]
        nicho = entrada["nicho"]
        print(f"\n[{i}/{len(cola)}] {nicho}/{personaje}")
        t0 = time.time()

        if args.solo_render:
            # Solo render — omitir todo lo demás
            entrada_render = dict(entrada)
            entrada_render["omitir_pasos"] = ["clips", "tts", "srt", "timeline", "imagenes"]
            ok, errores_v = procesar_video(entrada_render, dry_run=args.dry_run, auto_aprobacion=False)
        elif args.preparar:
            # Preparar hasta imágenes — omitir render y auto_approve
            entrada_prep = dict(entrada)
            omitir_base = list(entrada_prep.get("omitir_pasos", []))
            entrada_prep["omitir_pasos"] = omitir_base + ["render"]
            ok, errores_v = procesar_video(entrada_prep, dry_run=args.dry_run, auto_aprobacion=False)
        else:
            ok, errores_v = procesar_video(entrada, dry_run=args.dry_run, auto_aprobacion=args.auto_aprobacion)

        elapsed = time.time() - t0
        resumen.append({
            "personaje": personaje,
            "ok": ok,
            "tiempo": elapsed,
            "errores": errores_v,
        })

    # Después de --preparar: verificar tokens + mostrar URLs de dashboards
    if args.preparar:
        print(f"\n{'='*60}")
        print("  ✅ PREPARACIÓN COMPLETA")
        print(f"{'='*60}")

        # Verificar tokens de todos los canales
        canales_con_token = {}
        tokens_ok = True
        for entrada in cola:
            canal = entrada.get("canal")
            if canal and canal not in canales_con_token:
                ok_tok, msg_tok = verificar_token_youtube(canal)
                canales_con_token[canal] = (ok_tok, msg_tok)
                icon = "✅" if ok_tok else "❌"
                print(f"  {icon} Token {canal}: {msg_tok}")
                if not ok_tok:
                    tokens_ok = False

        if not tokens_ok:
            print()
            print("  ⚠️  HAY TOKENS VENCIDOS — renueva antes de dormir:")
            for canal, (ok_tok, _) in canales_con_token.items():
                if not ok_tok:
                    print(f"     python3 youtube_upload.py --canal {canal} --renovar-token")
            notify("🔑 Token YouTube vencido", "Renueva el token antes de dormir — ver terminal", sound=True)
        else:
            notify("Cola videos ✅", f"Tokens OK · aprueba los {len(cola)} dashboards", sound=False)

        print()
        print("  Abre cada dashboard y aprueba los clips:")
        for entrada in cola:
            nicho = entrada["nicho"]
            personaje = entrada["personaje"]
            print(f"  → http://localhost:5001/aprobar/{nicho}/{personaje}/")
        print(f"\n  Cuando todos estén aprobados, corre:")
        print(f"  python3 cola_videos.py --solo-render")
        print(f"{'='*60}\n")
        return

    # ── reporte final ──────────────────────────────────────────────────────────
    total = time.time() - t_inicio_global
    ok_count = sum(1 for r in resumen if r["ok"])
    fail_count = len(resumen) - ok_count

    print(f"\n{'='*60}")
    print(f"  REPORTE FINAL — {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}")
    print(f"  ✅ Completados : {ok_count}/{len(resumen)}")
    print(f"  ❌ Con errores : {fail_count}/{len(resumen)}")
    print(f"  Tiempo total  : {int(total//3600)}h {int((total%3600)//60)}m")
    print()
    for r in resumen:
        icon = "✅" if r["ok"] else "❌"
        t = f"{int(r['tiempo']//60)}m {int(r['tiempo']%60)}s"
        print(f"  {icon} {r['personaje']:<30} {t}")
        for paso, err in r["errores"]:
            print(f"       ✗ {paso}: {err[:80]}")
    print(f"{'='*60}\n")

    # Guardar reporte en JSON
    report_path = BASE / "logs" / f"cola_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(resumen, indent=2, ensure_ascii=False))
    print(f"Reporte guardado en: {report_path}")

    notify(
        "Cola videos terminada",
        f"{ok_count}/{len(resumen)} exitosos · {int(total//60)}m total",
        sound=True
    )

if __name__ == "__main__":
    main()
