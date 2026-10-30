#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  night_runner.sh — Cola nocturna de renders
#  Uso: bash night_runner.sh
#  Notificaciones al celular via ntfy.sh (gratis, sin cuenta)
#  Para recibir notifs: instalar app ntfy en el celular y
#  suscribirse al canal: canales-render-TUNOMBRE
# ─────────────────────────────────────────────────────────────

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
QUEUE_FILE="$BASE_DIR/night_queue.json"
LOG_FILE="$BASE_DIR/_logs/night_render_$(date +%Y%m%d_%H%M%S).log"
PYTHON="$(which python3)"

# ── Configura tu topic ntfy (único, difícil de adivinar) ──────
NTFY_TOPIC="canales-render-anyelo-2024"
# Para celular: instala app ntfy → suscríbete a: $NTFY_TOPIC
# ─────────────────────────────────────────────────────────────

mkdir -p "$BASE_DIR/_logs"

log() {
  local msg="$1"
  local ts="$(date '+%H:%M:%S')"
  echo "[$ts] $msg" | tee -a "$LOG_FILE"
}

notify() {
  local title="$1"
  local msg="$2"
  local priority="${3:-default}"  # min/low/default/high/urgent
  # Notificación Mac (siempre)
  osascript -e "display notification \"$msg\" with title \"$title\"" 2>/dev/null
  # Notificación celular via ntfy
  curl -s \
    -H "Title: $title" \
    -H "Priority: $priority" \
    -H "Tags: clapper" \
    -d "$msg" \
    "https://ntfy.sh/$NTFY_TOPIC" > /dev/null 2>&1 || true
}

get_queue_length() {
  "$PYTHON" -c "
import json, sys
try:
    q = json.load(open('$QUEUE_FILE'))
    pending = [x for x in q.get('queue',[]) if x.get('status') == 'pending']
    print(len(pending))
except: print(0)
"
}

get_next_item() {
  "$PYTHON" -c "
import json
q = json.load(open('$QUEUE_FILE'))
for item in q.get('queue', []):
    if item.get('status') == 'pending':
        print(json.dumps(item))
        break
"
}

mark_item() {
  local item_id="$1"
  local status="$2"
  local output="$3"
  "$PYTHON" - <<EOF
import json, datetime
q = json.load(open('$QUEUE_FILE'))
for item in q['queue']:
    if item['id'] == '$item_id':
        item['status'] = '$status'
        item['finished_at'] = datetime.datetime.now().isoformat()
        item['output'] = '''$output'''
        break
with open('$QUEUE_FILE', 'w') as f:
    json.dump(q, f, indent=2, ensure_ascii=False)
EOF
}

# ── Verificar cola ────────────────────────────────────────────
TOTAL=$(get_queue_length)
if [ "$TOTAL" -eq 0 ]; then
  log "⚠️  La cola está vacía. Agrega proyectos desde el dashboard."
  echo ""
  echo "Cola vacía. Usa el botón '🌙 Cola nocturna' en el dashboard."
  exit 0
fi

log "═══════════════════════════════════════════════"
log "🌙 COLA NOCTURNA — $TOTAL render(s) en cola"
log "═══════════════════════════════════════════════"

notify "🌙 Render nocturno iniciado" "$TOTAL video(s) en cola" "default"

SUCCESS=0
FAILED=0
START_GLOBAL=$(date +%s)

# ── Loop principal ─────────────────────────────────────────────
while true; do
  ITEM_JSON=$(get_next_item)
  [ -z "$ITEM_JSON" ] && break

  ITEM_ID=$(echo "$ITEM_JSON" | "$PYTHON" -c "import json,sys; print(json.load(sys.stdin)['id'])")
  NOMBRE=$(echo "$ITEM_JSON" | "$PYTHON" -c "import json,sys; print(json.load(sys.stdin)['nombre'])")
  CARPETA=$(echo "$ITEM_JSON" | "$PYTHON" -c "import json,sys; print(json.load(sys.stdin)['carpeta'])")
  RENDER_SCRIPT=$(echo "$ITEM_JSON" | "$PYTHON" -c "import json,sys; print(json.load(sys.stdin).get('render_script','render.py'))")

  log ""
  log "▶️  Iniciando: $NOMBRE"
  log "   Carpeta: $CARPETA"
  log "   Script:  $RENDER_SCRIPT"

  notify "▶️ Iniciando render" "$NOMBRE" "low"

  # Marcar como en progreso
  "$PYTHON" - <<EOF
import json, datetime
q = json.load(open('$QUEUE_FILE'))
for item in q['queue']:
    if item['id'] == '$ITEM_ID':
        item['status'] = 'running'
        item['started_at'] = datetime.datetime.now().isoformat()
        break
with open('$QUEUE_FILE', 'w') as f:
    json.dump(q, f, indent=2, ensure_ascii=False)
EOF

  START_ITEM=$(date +%s)

  # ── Correr render con caffeinate (evita que Mac se duerma) ──
  RENDER_LOG="$BASE_DIR/_logs/render_${NOMBRE//[^a-zA-Z0-9]/_}_$(date +%H%M%S).log"

  caffeinate -i "$PYTHON" "$BASE_DIR/$RENDER_SCRIPT" "$CARPETA" 2>&1 | tee -a "$RENDER_LOG" | tee -a "$LOG_FILE"
  RENDER_EXIT="${PIPESTATUS[0]}"

  END_ITEM=$(date +%s)
  DURATION=$(( (END_ITEM - START_ITEM) / 60 ))

  if [ "$RENDER_EXIT" -eq 0 ]; then
    SUCCESS=$((SUCCESS + 1))
    log "✅ Completado: $NOMBRE (${DURATION} min)"
    mark_item "$ITEM_ID" "done" "OK - ${DURATION} min"
    notify "✅ Render completado" "$NOMBRE — ${DURATION} min" "default"
  else
    FAILED=$((FAILED + 1))
    # Capturar últimas líneas del error
    LAST_ERROR=$(tail -5 "$RENDER_LOG" | tr '\n' ' ')
    log "❌ ERROR en: $NOMBRE (exit $RENDER_EXIT)"
    log "   $LAST_ERROR"
    mark_item "$ITEM_ID" "error" "EXIT $RENDER_EXIT: $LAST_ERROR"
    notify "❌ ERROR en render" "$NOMBRE: $LAST_ERROR" "high"
    # Continúa con el siguiente — no para por un error
  fi
done

# ── Resumen final ─────────────────────────────────────────────
END_GLOBAL=$(date +%s)
TOTAL_MIN=$(( (END_GLOBAL - START_GLOBAL) / 60 ))

log ""
log "═══════════════════════════════════════════════"
log "🏁 COLA COMPLETA — ${TOTAL_MIN} min totales"
log "   ✅ Exitosos: $SUCCESS"
log "   ❌ Errores:  $FAILED"
log "═══════════════════════════════════════════════"

if [ "$FAILED" -eq 0 ]; then
  notify "🏁 Cola nocturna completa" "✅ $SUCCESS videos listos — ${TOTAL_MIN} min" "high"
else
  notify "🏁 Cola nocturna completa" "✅ $SUCCESS ok · ❌ $FAILED errores — ${TOTAL_MIN} min" "urgent"
fi

echo ""
echo "Log completo: $LOG_FILE"
