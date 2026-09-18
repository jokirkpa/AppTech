#!/bin/bash
# AppTech Local Builder launcher (macOS / Linux)
cd "$(dirname "$0")"

PORT=5050
echo "Starting AppTech Local Builder on http://localhost:$PORT"

python3 server.py &
SERVER_PID=$!

# Give the server a moment, then try to open a browser.
sleep 1
URL="http://localhost:$PORT"
if command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1
elif command -v open >/dev/null 2>&1; then open "$URL" >/dev/null 2>&1
fi

# Keep the server in the foreground; Ctrl+C stops it.
wait $SERVER_PID
