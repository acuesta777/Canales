#!/bin/bash
# Lanza dashboard_secretos_mexicanos.py solo si el puerto 5003 está libre
if lsof -ti:5003 >/dev/null 2>&1; then
  echo "⚠️  Puerto 5003 ya ocupado — dashboard ya corriendo, no se relanza"
  exit 0
fi
lsof -ti:5003 | xargs kill -9 2>/dev/null; sleep 1
PYTHONUNBUFFERED=1 python3 /Users/anyelocuesta/Downloads/Canales/dashboard_secretos_mexicanos.py > /Users/anyelocuesta/Downloads/Canales/logs/dashboard_secretos.log 2>&1 &
echo "Dashboard PID $!"
until lsof -ti:5003 >/dev/null 2>&1; do sleep 2; done
echo "✅ Dashboard corriendo en :5003"
