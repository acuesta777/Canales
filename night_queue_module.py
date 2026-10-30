"""
night_queue_module.py
Módulo que se importa en cada dashboard para agregar soporte de cola nocturna.

Uso en cualquier dashboard:
    from night_queue_module import register_night_queue_routes, night_queue_button_html
    register_night_queue_routes(app, BASE_DIR, RENDER_SCRIPT="render.py")

Luego en el HTML del dashboard, insertar:
    {night_queue_button_html()}
junto al botón de "Aprobar todos".
"""
import json, uuid, datetime, pathlib

QUEUE_FILE_NAME = "night_queue.json"


def _get_queue_path(base_dir):
    return pathlib.Path(base_dir) / QUEUE_FILE_NAME


def _load_queue(base_dir):
    p = _get_queue_path(base_dir)
    if not p.exists():
        return {"queue": [], "history": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"queue": [], "history": []}


def _save_queue(base_dir, data):
    p = _get_queue_path(base_dir)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def register_night_queue_routes(app, base_dir, render_script="render.py"):
    """Registra los endpoints de cola nocturna en el app Flask dado."""
    from flask import request, jsonify

    @app.route("/api/night_queue/add", methods=["POST"])
    def night_queue_add():
        data = request.get_json(force=True)
        personaje = data.get("personaje", "").strip()
        nombre = data.get("nombre", personaje).strip()
        carpeta = data.get("carpeta", "").strip()
        render_sc = data.get("render_script", render_script)

        if not personaje or not carpeta:
            return jsonify({"ok": False, "error": "Faltan datos"}), 400

        q = _load_queue(base_dir)

        # Evitar duplicados en cola pendiente
        for item in q["queue"]:
            if item["carpeta"] == carpeta and item["status"] == "pending":
                return jsonify({"ok": True, "already": True,
                                "msg": f"'{nombre}' ya está en la cola nocturna"})

        item = {
            "id": str(uuid.uuid4())[:8],
            "nombre": nombre,
            "personaje": personaje,
            "carpeta": carpeta,
            "render_script": render_sc,
            "status": "pending",
            "added_at": datetime.datetime.now().isoformat(),
            "started_at": None,
            "finished_at": None,
            "output": None,
        }
        q["queue"].append(item)
        _save_queue(base_dir, q)
        return jsonify({"ok": True, "already": False,
                        "msg": f"'{nombre}' agregado a la cola nocturna ✓",
                        "total": len([x for x in q["queue"] if x["status"] == "pending"])})

    @app.route("/api/night_queue/remove", methods=["POST"])
    def night_queue_remove():
        data = request.get_json(force=True)
        carpeta = data.get("carpeta", "").strip()
        q = _load_queue(base_dir)
        before = len(q["queue"])
        q["queue"] = [x for x in q["queue"]
                      if not (x["carpeta"] == carpeta and x["status"] == "pending")]
        _save_queue(base_dir, q)
        removed = before - len(q["queue"])
        return jsonify({"ok": True, "removed": removed})

    @app.route("/api/night_queue/status")
    def night_queue_status():
        q = _load_queue(base_dir)
        pending = [x for x in q["queue"] if x["status"] == "pending"]
        running = [x for x in q["queue"] if x["status"] == "running"]
        done = [x for x in q["queue"] if x["status"] == "done"]
        errors = [x for x in q["queue"] if x["status"] == "error"]
        return jsonify({
            "ok": True,
            "pending": len(pending),
            "running": len(running),
            "done": len(done),
            "errors": len(errors),
            "items": q["queue"],
        })

    @app.route("/api/night_queue/clear", methods=["POST"])
    def night_queue_clear():
        q = _load_queue(base_dir)
        # Solo borra los pendientes — mantiene historial
        q["queue"] = [x for x in q["queue"] if x["status"] != "pending"]
        _save_queue(base_dir, q)
        return jsonify({"ok": True})

    return app


# ── HTML / JS del botón — pegar en la plantilla del dashboard ──────────────────

def night_queue_button_html(personaje_var="PERSONAJE", carpeta_var=None):
    """
    Retorna el HTML+JS del botón de cola nocturna.
    personaje_var: nombre de la variable JS que contiene el personaje/slug del video.
    """
    return r"""
<!-- ── Botón Cola Nocturna ─────────────────────────────────── -->
<button id="btn-night-queue"
  onclick="toggleNightQueue()"
  style="background:#1a1040;color:#b39ddb;border:1px solid #7c4dff;
         padding:8px 18px;border-radius:8px;font-size:13px;font-weight:600;
         cursor:pointer;transition:all .2s;white-space:nowrap">
  🌙 Cola nocturna
</button>

<script>
(function(){
  async function checkNightStatus() {
    try {
      const r = await fetch('/api/night_queue/status');
      const d = await r.json();
      const btn = document.getElementById('btn-night-queue');
      if (!btn) return;
      // Ver si este personaje está en la cola
      const inQueue = d.items && d.items.some(
        x => x.personaje === PERSONAJE && x.status === 'pending'
      );
      if (inQueue) {
        btn.textContent = '🌙 En cola nocturna ✓';
        btn.style.background = '#0d2b0d';
        btn.style.color = '#69f0ae';
        btn.style.border = '1px solid #00c853';
        btn.dataset.inQueue = '1';
        const total = d.pending;
        if (total > 1) btn.title = `${total} videos en la cola nocturna`;
      } else {
        btn.textContent = '🌙 Cola nocturna';
        btn.style.background = '#1a1040';
        btn.style.color = '#b39ddb';
        btn.style.border = '1px solid #7c4dff';
        btn.dataset.inQueue = '0';
        if (d.pending > 0) btn.title = `${d.pending} video(s) ya en cola`;
      }
    } catch(e) {}
  }

  window.toggleNightQueue = async function() {
    const btn = document.getElementById('btn-night-queue');
    const inQueue = btn && btn.dataset.inQueue === '1';

    if (inQueue) {
      if (!confirm('¿Quitar este video de la cola nocturna?')) return;
      const r = await fetch('/api/night_queue/remove', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({carpeta: PERSONAJE})
      });
      const d = await r.json();
      if (d.ok) toast('Removido de la cola nocturna', '#555');
    } else {
      // Verificar que está aprobado antes de agregar
      const nombre = document.title.replace('Dashboard — ','').trim() || PERSONAJE;
      const r = await fetch('/api/night_queue/add', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({
          personaje: PERSONAJE,
          nombre: nombre,
          carpeta: PERSONAJE
        })
      });
      const d = await r.json();
      if (d.ok) {
        const msg = d.already
          ? d.msg
          : `🌙 Agregado a la cola nocturna (${d.total} en total)`;
        toast(msg, d.already ? '#555' : '#1b5e20', 5000);
      } else {
        alert('Error: ' + d.error);
      }
    }
    setTimeout(checkNightStatus, 300);
  };

  // Verificar estado al cargar y cada 30s
  checkNightStatus();
  setInterval(checkNightStatus, 30000);
})();
</script>
"""
