#!/usr/bin/env python3
"""
run_night_queue.py — Ejecutor de la cola nocturna.

Lee night_queue.json, corre render.py por cada ítem pendiente,
envía notificaciones al celular vía ntfy.sh, y previene hibernación de la Mac.

Uso:
    python3 run_night_queue.py
    python3 run_night_queue.py --dry-run   # muestra qué correría sin ejecutar
"""

import json, sys, subprocess, time, datetime, argparse
from pathlib import Path

# ── config ────────────────────────────────────────────────────────────────────

BASE         = Path(__file__).parent
QUEUE_FILE   = BASE / "night_queue.json"
NTFY_TOPIC   = "la de claude"          # tu topic en ntfy.sh
NTFY_URL     = f"https://ntfy.sh/{NTFY_TOPIC.replace(' ', '%20')}"
RENDER_TIMEOUT = 3600 * 2              # 2h máx por render (safeguard)

# ── helpers ───────────────────────────────────────────────────────────────────

def ts():
    return datetime.datetime.now().strftime("%H:%M:%S")

def log(msg, icon=""):
    print(f"[{ts()}] {icon}  {msg}", flush=True)

def notify(title, message, priority="default", tags=""):
    """Envía push al celular vía ntfy.sh."""
    try:
        headers = [
            "-H", f"Title: {title}",
            "-H", f"Priority: {priority}",
        ]
        if tags:
            headers += ["-H", f"Tags: {tags}"]
        subprocess.run(
            ["curl", "-s", "-X", "POST", NTFY_URL,
             *headers,
             "-d", message],
            timeout=10, capture_output=True
        )
    except Exception as e:
        log(f"ntfy falló: {e}", "⚠")

def notify_mac(title, message):
    """Notificación macOS también, por si acaso."""
    try:
        script = f'display notification "{message}" with title "{title}" with sound'
        subprocess.run(["osascript", "-e", script], timeout=5, capture_output=True)
    except Exception:
        pass

def load_queue():
    if not QUEUE_FILE.exists():
        return {"queue": [], "history": []}
    try:
        return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"queue": [], "history": []}

def save_queue(data):
    QUEUE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def update_item(data, item_id, **fields):
    for item in data["queue"]:
        if item["id"] == item_id:
            item.update(fields)
            break
    save_queue(data)

def move_to_history(data, item_id):
    item = next((x for x in data["queue"] if x["id"] == item_id), None)
    if item:
        data["queue"].remove(item)
        data.setdefault("history", []).append(item)
    save_queue(data)

# ── runner ────────────────────────────────────────────────────────────────────

def run_cmd(cmd: list, timeout: int, dry_run: bool) -> tuple[bool, str]:
    log(f"Ejecutando: {' '.join(cmd)}", "▶")
    if dry_run:
        log("(dry-run — no se ejecuta)", "🔸")
        return True, "dry-run ok"
    try:
        result = subprocess.run(cmd, cwd=str(BASE), timeout=timeout,
                                capture_output=True, text=True)
        out = (result.stdout + result.stderr)[-800:]
        return result.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, f"TIMEOUT después de {timeout}s"
    except Exception as e:
        return False, str(e)

def run_render(carpeta: str, render_script: str, dry_run: bool) -> tuple[bool, str]:
    return run_cmd(["python3", render_script, carpeta], RENDER_TIMEOUT, dry_run)

def run_verificar(carpeta: str, dry_run: bool) -> tuple[bool, str]:
    ok1, o1 = run_cmd(["python3", "verificar_render.py", carpeta], 60, dry_run)
    ok2, o2 = run_cmd(["python3", "validar_orden_render.py", carpeta], 60, dry_run)
    return ok1 and ok2, o1 + "\n" + o2

def run_upload(carpeta: str, canal: str, dry_run: bool) -> tuple[bool, str]:
    return run_cmd(
        ["python3", "youtube_upload.py", carpeta,
         "--headless", "--canal", f"{canal}.json", "--privacidad", "private"],
        300, dry_run
    )

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    data = load_queue()
    pending = [x for x in data["queue"] if x["status"] == "pending"]

    if not pending:
        log("Cola vacía — nada que hacer.", "💤")
        sys.exit(0)

    total = len(pending)
    log(f"Cola nocturna: {total} video(s) pendiente(s)", "🌙")
    notify(
        "🌙 Cola nocturna iniciada",
        f"{total} video(s) en cola — empezando ahora",
        priority="default", tags="moon"
    )
    notify_mac("🌙 Cola nocturna", f"{total} video(s) — empezando")

    # caffeinate: evita que la Mac hiberne mientras corre
    caff = None
    if not args.dry_run:
        try:
            caff = subprocess.Popen(["caffeinate", "-i", "-s"])
            log(f"caffeinate activo (PID {caff.pid}) — Mac no hibernará", "☕")
        except Exception as e:
            log(f"caffeinate no disponible: {e}", "⚠")

    exitos = []
    fallos = []

    for idx, item in enumerate(pending, 1):
        nombre   = item.get("nombre", item["personaje"])
        carpeta  = item["carpeta"]
        rscript  = item.get("render_script", "render.py")
        item_id  = item["id"]

        log(f"[{idx}/{total}] {nombre} — {carpeta}", "🎬")
        notify(
            f"🎬 Iniciando {nombre}",
            f"Video {idx}/{total}: {carpeta}",
            priority="low", tags="clapper"
        )

        update_item(data, item_id,
                    status="running",
                    started_at=datetime.datetime.now().isoformat())

        canal  = item.get("canal", "").strip()
        t0     = time.time()

        # ── PASO 1: render ──────────────────────────────────────────────
        ok, output = run_render(carpeta, rscript, args.dry_run)
        elapsed = int(time.time() - t0)
        mins, secs = elapsed // 60, elapsed % 60

        if not ok:
            fallos.append(nombre)
            log(f"❌ {nombre} — render falló ({mins}m {secs}s)", "❌")
            log(f"   {output[-200:]}")
            notify(f"❌ Render falló: {nombre}",
                   f"Error en render después de {mins}m {secs}s",
                   priority="high", tags="x,warning")
            notify_mac(f"❌ {nombre}", "Render falló — continuando")
            update_item(data, item_id, status="error",
                        finished_at=datetime.datetime.now().isoformat(),
                        output=output[-300:])
            move_to_history(data, item_id)
            data = load_queue()
            continue

        log(f"✅ Render OK en {mins}m {secs}s", "✅")
        notify(f"✅ Render listo: {nombre}", f"Completado en {mins}m {secs}s",
               priority="low", tags="clapper")

        # ── PASO 2: verificar ───────────────────────────────────────────
        log(f"[{idx}/{total}] {nombre} — verificando render", "🔍")
        vok, vout = run_verificar(carpeta, args.dry_run)
        if not vok:
            log(f"⚠ {nombre} — verificación con advertencias", "⚠")
            notify(f"⚠ Verificación: {nombre}", "Render con advertencias — revisa",
                   priority="default", tags="warning")

        # ── PASO 3: upload ──────────────────────────────────────────────
        upload_pack = None
        for candidate in [BASE / carpeta / "upload_pack.json",
                          BASE / carpeta / "07-metadatos" / "upload_pack.json"]:
            if candidate.exists():
                upload_pack = candidate
                break

        if canal and upload_pack:
            log(f"[{idx}/{total}] {nombre} — subiendo a {canal}", "📤")
            notify(f"📤 Subiendo: {nombre}", f"Canal: {canal}", priority="low", tags="arrow_up")
            uok, uout = run_upload(carpeta, canal, args.dry_run)
            if uok:
                log(f"✅ {nombre} subido a {canal}", "✅")
                notify(f"✅ Subido: {nombre}", f"Privado en {canal} ✓",
                       priority="default", tags="youtube")
                notify_mac(f"✅ {nombre}", f"Subido a {canal}")
            else:
                log(f"⚠ {nombre} — upload falló: {uout[-150:]}", "⚠")
                notify(f"⚠ Upload falló: {nombre}", uout[-100:],
                       priority="high", tags="warning")
                notify_mac(f"⚠ {nombre}", "Upload falló — render OK")
        elif canal and not upload_pack:
            log(f"ℹ {nombre} — sin upload_pack.json, render listo para subida manual", "ℹ")
            notify(f"🎬 Render listo: {nombre}",
                   f"Falta upload_pack.json — súbelo manualmente a {canal}",
                   priority="default", tags="white_check_mark")
            notify_mac(f"🎬 {nombre}", "Render OK — falta upload_pack.json")
        else:
            log(f"ℹ {nombre} — sin canal asignado, render listo para subida manual", "ℹ")
            notify(f"🎬 Render listo: {nombre}", "Video listo — súbelo cuando quieras",
                   priority="low", tags="white_check_mark")

        exitos.append(nombre)
        update_item(data, item_id,
                    status="done",
                    finished_at=datetime.datetime.now().isoformat(),
                    output=output[-300:])

        move_to_history(data, item_id)
        data = load_queue()  # recargar por si el dashboard modificó la cola

    # resumen final
    resumen = f"{len(exitos)} OK · {len(fallos)} con error"
    if fallos:
        detalle = f"Fallaron: {', '.join(fallos)}"
        priority = "high"
        tags = "warning"
    else:
        detalle = "Todos los renders completados sin errores"
        priority = "default"
        tags = "tada"

    log(f"Cola terminada — {resumen}", "🏁")
    log(detalle, "")
    notify(
        f"🏁 Cola nocturna terminada",
        f"{resumen}\n{detalle}",
        priority=priority, tags=tags
    )
    notify_mac("🏁 Cola nocturna", f"{resumen}")

    if caff:
        caff.terminate()
        log("caffeinate detenido — Mac puede hibernar", "☕")

if __name__ == "__main__":
    main()
