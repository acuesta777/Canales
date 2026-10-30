#!/bin/bash
# Uso: ./run_timeout.sh <segundos> <etiqueta> <comando...>
# Si el comando excede el timeout: lo mata, alerta Telegram + macOS y sale con código 124.

TIMEOUT=$1
LABEL=$2
shift 2

# Ejecutar con timeout (compatible macOS sin coreutils)
"$@" &
CMD_PID=$!
(
  sleep "$TIMEOUT"
  if kill -0 $CMD_PID 2>/dev/null; then
    kill -TERM $CMD_PID 2>/dev/null
    sleep 2
    kill -KILL $CMD_PID 2>/dev/null
    echo "TIMEOUT_FIRED"
  fi
) &
WATCHER_PID=$!
wait $CMD_PID
EXIT=$?
kill $WATCHER_PID 2>/dev/null
wait $WATCHER_PID 2>/dev/null

# Si el proceso fue matado externamente, simular exit 124
if [ $EXIT -gt 128 ] || grep -q "TIMEOUT_FIRED" /tmp/timeout_$$.tmp 2>/dev/null; then
  EXIT=124
fi

if [ $EXIT -eq 124 ]; then
    MSG="⚠️ TIMEOUT: '$LABEL' superó ${TIMEOUT}s y fue cancelado automáticamente."
    echo "$MSG"
fi

exit $EXIT
