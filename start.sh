#!/usr/bin/env bash
# Start AppTech behind nginx on apptech.cisco.com
# nginx routes /api/* → :7997 and / → :7996

# WEB_APP_BASE_PREFIX is unset; app runs at root /

# Load .env (QUICKER_AI_TOKEN, etc.) if present, without clobbering
# variables already set in the environment (e.g. by docker-compose).
if [ -f .env ]; then
  while IFS='=' read -r key value; do
    [[ -z "$key" || "$key" == \#* ]] && continue
    if [ -z "${!key}" ]; then
      export "$key=$value"
    fi
  done < .env
fi

# Backend: serves API, /docs, /openapi.json
uvicorn console:app --host 0.0.0.0 --port 7997 --reload &
BACKEND_PID=$!

# Frontend: serves dashboard HTML, static files, application tools
uvicorn console:app --host 0.0.0.0 --port 7996 --reload &
FRONTEND_PID=$!

echo "AppTech started"
echo "  Backend  PID $BACKEND_PID → :7997"
echo "  Frontend PID $FRONTEND_PID → :7996"
echo ""
echo "  Docs: https://apptech.cisco.com/docs"
echo "  App:  https://apptech.cisco.com"
echo ""
echo "Press Ctrl+C to stop both processes."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT INT TERM
wait
