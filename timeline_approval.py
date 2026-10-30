#!/usr/bin/env python3
"""
timeline_approval.py — Servidor de aprobación de segmentos reutilizable.

Uso desde cualquier canal:

    from timeline_approval import run_approval, upload_to_baserow, BASEROW_DEFAULTS

    approved, fuente = run_approval(
        segments    = all_segments,
        video_name  = "Mi Video",
        carpeta     = carpeta,
        trigger_colors = {
            "DINERO": "#10b981",
            "POBREZA": "#f59e0b",
            # ... los triggers del canal
        },
        port = 5099,   # opcional, default 5099
    )
    if not approved:
        sys.exit(0)

    if fuente == "flow":
        pass  # Upload a Baserow lo hace harvester_timeline.py
    elif fuente == "ai33pro":
        generate_ai33pro(approved, carpeta)
    elif fuente == "muapi":
        generate_muapi(approved, carpeta)
"""

import json, sys, time, pathlib, subprocess

# ── Baserow defaults (sobrescribibles por canal) ──────────────────────────────
BASEROW_DEFAULTS = {
    "token":    "4QrZH5MkTLHKtGqTG97Gz2yQTAIhknMq",
    "table_id": "1100194",
    "api_base": "https://api.baserow.io/api",
}

# ── Colores por defecto (el canal puede pasar los suyos) ─────────────────────
DEFAULT_TRIGGER_COLORS = {
    "DINERO":       "#10b981",
    "POBREZA":      "#f59e0b",
    "CIUDAD":       "#3b82f6",
    "PRENSA":       "#8b5cf6",
    "HOSPITAL":     "#ef4444",
    "CINE":         "#ec4899",
    "RADIO":        "#06b6d4",
    "CONCIERTO":    "#a855f7",
    "ACCIDENTE":    "#dc2626",
    "MONEY":        "#10b981",
    "PROPERTY":     "#f97316",
    "PLACE":        "#3b82f6",
    "POSSESSIONS":  "#a855f7",
    "TRAICION":     "#ef4444",
    "SECRETO":      "#8b5cf6",
    "PODER":        "#f59e0b",
    "CRIMEN":       "#dc2626",
    "CAIDA":        "#64748b",
}


def _fmt_time(secs):
    secs = int(round(secs))
    m = secs // 60
    s = secs % 60
    return f"{m}:{s:02d}"


def _resolve_color(trigger_type, trigger_colors):
    t = trigger_type.upper()
    if t in trigger_colors:
        return trigger_colors[t]
    # coincidencia parcial (ej "CIUDAD / LUGAR MEXICO" → "CIUDAD")
    for key, color in trigger_colors.items():
        if key in t:
            return color
    return "#6366f1"


def _build_page(segments, video_name, trigger_colors, carpeta=None):
    rows_html = ""
    display_num = 0
    for s in segments:
        if len(s.get("ia_prompt", "").strip()) < 10:
            continue  # sin prompt (o demasiado corto) → no mostrar en tablero
        display_num += 1
        ttype = s.get("trigger_type", "")
        color = _resolve_color(ttype, trigger_colors)
        desc  = (s.get("scene_description") or s.get("scene_description_es") or s.get("ia_prompt", ""))[:65]
        badge = ttype.lower().replace(" / ", " · ").replace("_", " ")
        rows_html += (
            f'<tr data-id="{s["segment_id"]}" data-start="{s["start_seconds"]}" style="cursor:pointer">'
            f'<td class="check-col"><input type="checkbox" checked></td>'
            f'<td>{display_num}</td>'
            f'<td>{_fmt_time(s["start_seconds"])}</td>'
            f'<td>{_fmt_time(s["end_seconds"])}</td>'
            f'<td>{int(round(s["duration"]))}s</td>'
            f'<td><span class="badge" style="background:{color}">{badge}</span></td>'
            f'<td style="color:#cbd5e1;font-size:.8rem;max-width:200px">{(s.get("scene_description") or s.get("scene_description_es") or "")[:65]}</td>'
            f'<td class="prompt-text" data-prompt="{s.get("ia_prompt","").strip().replace(chr(34), "&quot;")}" style="color:#e2e8f0;font-size:.8rem;max-width:360px;word-break:break-word">{(s.get("escena_es") or s.get("ia_prompt","").strip())[:120]}</td>'
            f'</tr>\n'
        )

    total = len(segments)
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Aprobar Timeline — {video_name}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f172a;color:#e2e8f0;padding:24px 32px}}
h1{{font-size:1.2rem;font-weight:700;margin-bottom:4px;color:#f8fafc}}
.sub{{color:#94a3b8;font-size:.82rem;margin-bottom:20px}}
table{{width:100%;border-collapse:collapse;font-size:.85rem}}
th{{text-align:left;padding:8px 12px;background:#1e293b;color:#94a3b8;font-weight:600;border-bottom:1px solid #334155;white-space:nowrap}}
td{{padding:7px 12px;border-bottom:1px solid #1e293b;vertical-align:middle}}
tr:hover td{{background:#1e293b66}}
tr.disabled td{{opacity:.35;text-decoration:line-through}}
.badge{{display:inline-block;padding:2px 9px;border-radius:999px;font-size:.72rem;font-weight:700;color:#fff;white-space:nowrap}}
.check-col{{width:40px;text-align:center}}
input[type=checkbox]{{width:17px;height:17px;accent-color:#6366f1;cursor:pointer}}
.footer{{margin-top:24px;display:flex;align-items:flex-end;gap:32px;flex-wrap:wrap}}
.fuente-group{{display:flex;gap:10px;align-items:center;flex-wrap:wrap}}
.fuente-group label{{display:flex;align-items:center;gap:6px;font-size:.87rem;cursor:pointer;padding:8px 16px;border-radius:8px;border:2px solid #334155;transition:.15s}}
.fuente-group label:has(input:checked){{border-color:#6366f1;background:#1e293b}}
.fuente-group input[type=radio]{{accent-color:#6366f1;width:15px;height:15px}}
.btn{{padding:11px 28px;background:#6366f1;color:#fff;border:none;border-radius:8px;font-size:.95rem;font-weight:700;cursor:pointer;white-space:nowrap}}
.btn:hover{{background:#4f46e5}}
.btn:disabled{{background:#475569;cursor:not-allowed}}
.status{{color:#94a3b8;font-size:.82rem;margin-top:6px}}
</style>
</head>
<body>
<h1>Timeline · {video_name}</h1>
<p class="sub"><span id="cnt">{total}</span> de {total} segmentos activos &nbsp;·&nbsp; Desmarca los que NO quieres generar</p>
{'<div style="margin-bottom:16px"><audio id="mainAudio" controls style="width:100%;border-radius:8px;accent-color:#6366f1" src="/audio"></audio></div>' if carpeta else ''}
<table>
<thead><tr>
  <th class="check-col">✓</th>
  <th>Seg</th><th>Inicio</th><th>Fin</th><th>Dur</th><th>Trigger</th><th>Narración</th><th>Imagen generada</th>
</tr></thead>
<tbody id="tbody">
{rows_html}
</tbody>
</table>
<div class="footer">
  <div>
    <p style="font-size:.78rem;color:#94a3b8;margin-bottom:8px;font-weight:600;text-transform:uppercase;letter-spacing:.05em">Fuente de imágenes</p>
    <div class="fuente-group">
      <label><input type="radio" name="fuente" value="flow" checked> 🌊 Flow (Baserow)</label>
      <label><input type="radio" name="fuente" value="ai33pro"> ⚡ ai33pro</label>
      <label><input type="radio" name="fuente" value="muapi"> 🎨 muapi</label>
    </div>
  </div>
  <div style="display:flex;flex-direction:column;gap:8px;align-items:flex-start">
    <div style="display:flex;gap:10px;flex-wrap:wrap">
      <button class="btn" id="btnCopyAll" style="background:#0f766e" onclick="copiarTodosPrompts()">📋 Copiar TODOS los prompts</button>
      <button class="btn" id="btnCopy" style="background:#475569" onclick="copiarPrompts()">📋 Copiar seleccionados</button>
      <button class="btn" id="btnAprobar" style="background:#6366f1" onclick="aprobar()">✅ Aprobar</button>
      <button class="btn" id="btnBaserow" style="background:#b45309" onclick="subirBaserow()">⬆ Subir a Baserow</button>
      <button class="btn" id="btnFlowMCP" style="background:#7c3aed" onclick="generarFlowMCP()">🤖 Flow MCP</button>
    </div>
    <p class="status" id="status"></p>
  </div>
</div>
<script>
const rows  = document.querySelectorAll('#tbody tr');
const total = {total};

function upd(){{
  const n = [...rows].filter(r=>r.querySelector('input[type=checkbox]').checked).length;
  document.getElementById('cnt').textContent = n;
}}
rows.forEach(r=>{{
  r.querySelector('input[type=checkbox]').addEventListener('change',()=>{{
    r.classList.toggle('disabled', !r.querySelector('input[type=checkbox]').checked);
    upd();
  }});
  r.addEventListener('click', e=>{{
    if(e.target.type==='checkbox') return;
    const t = parseFloat(r.dataset.start||0);
    const audio = document.getElementById('mainAudio');
    if(audio && !isNaN(t)){{ audio.currentTime=t; audio.play(); }}
  }});
}});

async function copiarTodosPrompts(){{
  const ids = [...rows].map(r=>+r.dataset.id);
  const btnC = document.getElementById('btnCopyAll');
  const st   = document.getElementById('status');
  btnC.disabled = true; btnC.textContent = 'Copiando…';
  let res, data;
  try{{
    res  = await fetch('/prompts', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{ids}})}});
    data = await res.json();
  }} catch(e){{
    btnC.disabled=false; btnC.textContent='📋 Copiar TODOS los prompts';
    st.textContent = '❌ Error al contactar el servidor'; return;
  }}
  const textToCopy = data.text || data.txt_text || '';
  const extraInfo  = data.txt_path ? ' (guardado en ' + data.txt_path + ')' : '';
  const ta = document.createElement('textarea');
  ta.value = textToCopy;
  ta.style.cssText = 'position:fixed;top:-9999px;left:-9999px';
  document.body.appendChild(ta);
  ta.focus(); ta.select();
  let ok = false;
  try{{ ok = document.execCommand('copy'); }} catch(_){{}}
  document.body.removeChild(ta);
  if(!ok){{ try{{ await navigator.clipboard.writeText(textToCopy); ok=true; }} catch(_){{}} }}
  btnC.disabled=false;
  if(ok){{
    btnC.textContent='✅ Copiados';
    st.textContent = data.count + ' prompts copiados al portapapeles' + extraInfo;
    setTimeout(()=>{{ btnC.textContent='📋 Copiar TODOS los prompts'; }}, 2500);
  }} else {{
    btnC.textContent='📋 Copiar TODOS los prompts';
    st.textContent = '⚠ No se pudo copiar automáticamente' + extraInfo;
  }}
}}

async function copiarPrompts(){{
  const ids = [...rows].filter(r=>r.querySelector('input[type=checkbox]').checked).map(r=>+r.dataset.id);
  const btnC = document.getElementById('btnCopy');
  const st   = document.getElementById('status');
  btnC.disabled = true; btnC.textContent = 'Copiando…';
  let res, data;
  try{{
    res  = await fetch('/prompts', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{ids}})}});
    data = await res.json();
  }} catch(e){{
    btnC.disabled=false; btnC.textContent='📋 Copiar prompts';
    st.textContent = '❌ Error al contactar el servidor'; return;
  }}
  const textToCopy2 = data.text || data.txt_text || '';
  const extraInfo2  = data.txt_path ? ' (guardado en ' + data.txt_path + ')' : '';
  const ta2 = document.createElement('textarea');
  ta2.value = textToCopy2;
  ta2.style.cssText = 'position:fixed;top:-9999px;left:-9999px';
  document.body.appendChild(ta2);
  ta2.focus(); ta2.select();
  let ok = false;
  try{{ ok = document.execCommand('copy'); }} catch(_){{}}
  document.body.removeChild(ta2);
  if(!ok){{ try{{ await navigator.clipboard.writeText(textToCopy2); ok=true; }} catch(_){{}} }}
  btnC.disabled=false;
  if(ok){{
    btnC.textContent='✅ Copiados';
    st.textContent = data.count + ' prompts copiados al portapapeles' + extraInfo2;
    setTimeout(()=>{{ btnC.textContent='📋 Copiar prompts'; }}, 2500);
  }} else {{
    btnC.textContent='📋 Copiar prompts';
    st.textContent = '⚠ No se pudo copiar automáticamente' + extraInfo2;
  }}
}}

async function aprobar(){{
  const checked_ids = [...rows].filter(r=>r.querySelector('input[type=checkbox]').checked).map(r=>+r.dataset.id);
  const yt_ids      = [...rows].filter(r=>!r.querySelector('input[type=checkbox]').checked).map(r=>+r.dataset.id);
  const fuente      = document.querySelector('input[name=fuente]:checked').value;
  const btn         = document.getElementById('btnAprobar');
  btn.disabled = true; btn.textContent = 'Guardando…';
  document.getElementById('status').textContent = 'Guardando selección…';
  const res = await fetch('/save', {{
    method:'POST', headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{ids: checked_ids, yt_ids, fuente}})
  }});
  if(res.ok){{
    btn.textContent = '✅ Aprobado';
    document.getElementById('status').textContent =
      checked_ids.length + ' con imagen (' + fuente + ') · ' + yt_ids.length + ' con clip YT — estado guardado';
  }} else {{
    btn.disabled = false; btn.textContent = '✅ Aprobar';
    document.getElementById('status').textContent = '❌ Error al guardar';
  }}
}}

async function generarFlowMCP(){{
  const ids = [...rows].filter(r=>r.querySelector('input[type=checkbox]').checked).map(r=>+r.dataset.id);
  const btn = document.getElementById('btnFlowMCP');
  const st  = document.getElementById('status');
  if(ids.length === 0){{ st.textContent = '⚠ No hay segmentos seleccionados'; return; }}
  btn.disabled = true; btn.textContent = 'Lanzando…';
  st.textContent = 'Iniciando generación con Flow MCP…';
  const res  = await fetch('/generate_flow_mcp', {{
    method:'POST', headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{ids}})
  }});
  const data = await res.json();
  if(res.ok && data.ok){{
    btn.disabled = false; btn.textContent = '🤖 Flow MCP';
    st.textContent = '✅ Cola guardada (' + data.count + ' segmentos) — en tu Claude escribe: procesa flow_mcp_queue';
  }} else {{
    btn.disabled = false; btn.textContent = '🤖 Flow MCP';
    st.textContent = '❌ ' + (data.error || 'Error al lanzar Flow MCP');
  }}
}}

async function subirBaserow(){{
  const btn = document.getElementById('btnBaserow');
  const st  = document.getElementById('status');
  btn.disabled = true; btn.textContent = 'Subiendo…';
  st.textContent = 'Borrando Baserow y subiendo segmentos aprobados…';
  const res = await fetch('/upload_baserow', {{method:'POST'}});
  const data = await res.json();
  if(res.ok && data.ok){{
    btn.textContent = '✅ Subido';
    st.textContent = data.count + ' segmentos subidos a Baserow';
  }} else {{
    btn.disabled = false; btn.textContent = '⬆ Subir a Baserow';
    st.textContent = '❌ ' + (data.error || 'Error al subir');
  }}
}}
</script>
</body></html>"""


def run_approval(segments, video_name, carpeta=None, trigger_colors=None, port=5099):
    """
    Lanza la página de aprobación y devuelve (approved_segments, fuente).
    fuente es "flow", "ai33pro" o "muapi".
    Devuelve (None, None) si el usuario cancela.
    """
    import threading, webbrowser, subprocess as _sp
    # Matar cualquier proceso que tenga el puerto ocupado (fix raíz)
    try:
        pids = _sp.check_output(["lsof", "-t", f"-i:{port}"], text=True).split()
        for pid in pids:
            _sp.call(["kill", "-9", pid])
        if pids:
            time.sleep(0.5)
    except Exception:
        pass
    try:
        from flask import Flask as _Flask, request as _req, jsonify as _jsonify, Response as _Resp
    except ImportError:
        print("  ⚠ Flask no disponible — aprobando todos los segmentos sin revisión.")
        return segments, "flow"

    colors  = {**DEFAULT_TRIGGER_COLORS, **(trigger_colors or {})}
    page    = _build_page(segments, video_name, colors, carpeta=carpeta)
    _app    = _Flask(f"approval_{port}")
    _result = {"segments": None, "fuente": "flow", "done": threading.Event()}
    seg_by_id = {s["segment_id"]: s for s in segments}

    @_app.route("/")
    def index():
        return _Resp(page, mimetype="text/html")

    @_app.route("/audio")
    def serve_audio():
        if carpeta is None:
            return _Resp("no audio", status=404)
        import os
        from flask import send_file
        folder = pathlib.Path(carpeta)
        # Preferir audio.mp3 explícito; si no, el primero alfabético
        explicit = folder / "audio.mp3"
        if explicit.exists():
            return send_file(str(explicit), mimetype="audio/mpeg")
        mp3s = sorted(folder.glob("*.mp3"))
        if not mp3s:
            return _Resp("no mp3", status=404)
        return send_file(str(mp3s[0]), mimetype="audio/mpeg")

    @_app.route("/prompts", methods=["POST"])
    def get_prompts():
        data = _req.get_json()
        ids  = set(data.get("ids", []))
        # Si el cliente pide "todos" (btnCopyAll envía todos los IDs del DOM),
        # ignorar los IDs del cliente y devolver todos los del servidor — evita
        # que un DOM cacheado de otra sesión traiga IDs de otro personaje.
        use_all = not ids or ids == set(seg_by_id.keys())
        if use_all:
            valid_ids = sorted(seg_by_id.keys())
        else:
            valid_ids = sorted(ids & set(seg_by_id.keys()))
        lines = [
            seg_by_id[i].get("ia_prompt", "").strip()
            for i in valid_ids
            if seg_by_id[i].get("ia_prompt", "").strip()
        ]
        text = "\n\n".join(lines)
        # si son más de 50000 chars → guardar a txt ADEMÁS de devolver el texto
        resp = {"text": text, "count": len(lines)}
        if len(text) > 50000:
            txt_path = pathlib.Path(carpeta) / "05-montaje" / "prompts_aprobados.txt" if carpeta else pathlib.Path("prompts_aprobados.txt")
            txt_path.parent.mkdir(parents=True, exist_ok=True)
            txt_path.write_text(text, encoding="utf-8")
            resp["txt_path"] = str(txt_path)
        return _jsonify(resp)

    # archivo persistente de selección
    state_file = (pathlib.Path(carpeta) / "05-montaje" / "aprobados.json") if carpeta else pathlib.Path("aprobados.json")

    @_app.route("/save", methods=["POST"])
    def save():
        data      = _req.get_json()
        ids       = set(data.get("ids", []))
        yt_ids    = set(data.get("yt_ids", []))
        fuente    = data.get("fuente", "flow")
        approved  = [seg_by_id[i] for i in sorted(ids)    if i in seg_by_id]
        yt_segs   = [{**seg_by_id[i], "source": "yt"} for i in sorted(yt_ids) if i in seg_by_id]
        state     = {"fuente": fuente, "approved_ids": sorted(ids), "yt_ids": sorted(yt_ids)}
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
        _result["segments"] = approved
        _result["yt_segs"]  = yt_segs
        _result["fuente"]   = fuente
        _result["done"].set()
        return _jsonify({"ok": True})

    @_app.route("/generate_flow_mcp", methods=["POST"])
    def generate_flow_mcp_route():
        data = _req.get_json()
        ids  = set(data.get("ids", []))
        segs = [seg_by_id[i] for i in sorted(ids) if i in seg_by_id and seg_by_id[i].get("ia_prompt", "").strip()]
        if not segs:
            return _jsonify({"ok": False, "error": "No hay segmentos con prompt"}), 400
        try:
            generate_flow_mcp(segs, str(carpeta) if carpeta else ".")
            return _jsonify({"ok": True, "count": len(segs)})
        except Exception as e:
            return _jsonify({"ok": False, "error": str(e)}), 500

    @_app.route("/upload_baserow", methods=["POST"])
    def upload_baserow_route():
        if not state_file.exists():
            return _jsonify({"ok": False, "error": "Primero haz clic en Aprobar"}), 400
        state    = json.loads(state_file.read_text())
        approved = [seg_by_id[i] for i in state.get("approved_ids", []) if i in seg_by_id]
        try:
            upload_to_baserow(approved, str(carpeta) if carpeta else ".", **BASEROW_DEFAULTS)
            return _jsonify({"ok": True, "count": len(approved)})
        except Exception as e:
            return _jsonify({"ok": False, "error": str(e)}), 500

    import logging
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)

    srv = threading.Thread(
        target=lambda: _app.run(port=port, debug=False, use_reloader=False),
        daemon=True,
    )
    srv.start()
    time.sleep(0.8)

    print(f"\n  🌐 Aprobación en http://localhost:{port}")
    print(f"     Selecciona segmentos, elige fuente y haz clic en 'Aprobar'\n")
    webbrowser.open(f"http://localhost:{port}")
    _result["done"].wait()
    return _result["segments"], _result["fuente"], _result.get("yt_segs", [])


# ── Generadores ───────────────────────────────────────────────────────────────

def upload_to_baserow(approved, carpeta, token, table_id, api_base, **_):
    """Sube segmentos aprobados a Baserow (borra filas previas)."""
    def curl(method, path, data=None):
        cmd = ["curl", "-s", "-X", method, api_base + path,
               "-H", f"Authorization: Token {token}",
               "-H", "Content-Type: application/json"]
        if data:
            cmd += ["-d", json.dumps(data)]
        out = subprocess.check_output(cmd, timeout=30)
        return json.loads(out) if out.strip() else {}

    existing = curl("GET", f"/database/rows/table/{table_id}/?user_field_names=true&size=200")
    for row in existing.get("results", []):
        curl("DELETE", f"/database/rows/table/{table_id}/{row['id']}/")

    for seg in approved:
        ia_p  = (seg.get("ia_prompt") or "").strip()
        sid   = seg.get("segment_id", 0)
        desc  = seg.get("scene_description") or seg.get("scene_description_es") or ""
        veo_p = f"[{sid}] Slow cinematic zoom in. {desc}"
        curl("POST", f"/database/rows/table/{table_id}/?user_field_names=true",
             data={"Image Prompt": ia_p, "VEO Prompt": veo_p, "Mode": "Imagegen", "Status": "pending"})

    print(f"  ✅ {len(approved)} segmentos subidos a Baserow")


def generate_ai33pro(approved, carpeta):
    """Genera imágenes con ai33pro para cada segmento aprobado."""
    script = pathlib.Path(__file__).parent / "imagen_ai33pro.py"
    for seg in approved:
        subprocess.Popen([sys.executable, str(script), str(carpeta), "--seg", str(seg["segment_id"])])
    print(f"  ✅ ai33pro lanzado para {len(approved)} segmentos")


def generate_flow_mcp(approved, carpeta, mode="image"):
    """Guarda cola JSON para que Claude la procese con el MCP google-flow."""
    output_dir = pathlib.Path(carpeta) / "03-imagenes" if carpeta and carpeta != "." else pathlib.Path.home() / "Downloads" / "veo-folder-1"
    output_dir.mkdir(parents=True, exist_ok=True)

    queue = {
        "canal": str(pathlib.Path(carpeta).parent.name) if carpeta else "",
        "proyecto": str(pathlib.Path(carpeta).name) if carpeta else "",
        "output_dir": str(output_dir),
        "mode": mode,  # "image" o "video"
        "total": len(approved),
        "segmentos": [
            {"segment_id": seg["segment_id"], "ia_prompt": seg.get("ia_prompt", "").strip()}
            for seg in approved
        ]
    }

    queue_path = pathlib.Path(carpeta) / "05-montaje" / "flow_mcp_queue.json" if carpeta else pathlib.Path("flow_mcp_queue.json")
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n  🤖 Cola Flow MCP guardada: {queue_path}")
    print(f"     {len(approved)} segmentos listos para generar")
    print(f"\n  ▶ En tu Claude, escribe:")
    print(f"     procesa flow_mcp_queue en {queue_path}")


def generate_muapi(approved, carpeta):
    """Genera imágenes con muapi para cada segmento aprobado."""
    script = pathlib.Path(__file__).parent / "imagen_muapi.py"
    if script.exists():
        for seg in approved:
            subprocess.Popen([sys.executable, str(script), str(carpeta), "--seg", str(seg["segment_id"])])
        print(f"  ✅ muapi lanzado para {len(approved)} segmentos")
    else:
        print("  ⚠ imagen_muapi.py no encontrado — usando ai33pro como fallback")
        generate_ai33pro(approved, carpeta)
