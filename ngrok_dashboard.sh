#!/bin/bash
# Lanza ngrok al dashboard y manda la URL por WhatsApp
# Uso: ./ngrok_dashboard.sh [puerto]

PUERTO=${1:-5001}
PHONE="+50760904076"
APIKEY="REEMPLAZAR_CON_TU_APIKEY"  # <-- pega aquí el key de CallMeBot

# Matar ngrok previo
pkill -f "ngrok http" 2>/dev/null
sleep 1

# Verificar que el dashboard esté corriendo
if ! lsof -ti:$PUERTO > /dev/null 2>&1; then
  echo "⚠️  Dashboard no está corriendo en puerto $PUERTO"
  echo "Lanza primero: python3 dashboard.py --port $PUERTO"
  exit 1
fi

# Lanzar ngrok
ngrok http $PUERTO --log=stdout > /tmp/ngrok_dashboard.log 2>&1 &
sleep 4

# Extraer URL
NGROK_URL=$(grep -o "https://[a-zA-Z0-9._-]*\.ngrok-free\.app" /tmp/ngrok_dashboard.log | head -1)
if [ -z "$NGROK_URL" ]; then
  echo "❌ No se pudo obtener URL de ngrok"
  cat /tmp/ngrok_dashboard.log
  exit 1
fi

# Construir URL completa del dashboard
DASHBOARD_URL="${NGROK_URL}/aprobar/riqueza/"

echo "✅ ngrok activo: $NGROK_URL"
echo "📲 Mandando link por WhatsApp..."

# Mandar por WhatsApp via CallMeBot
MSG="Dashboard listo: ${DASHBOARD_URL}"
curl -s "https://api.callmebot.com/whatsapp.php?phone=${PHONE}&text=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$MSG")&apikey=${APIKEY}" > /dev/null

echo "✅ Link mandado a WhatsApp: $DASHBOARD_URL"
