#!/bin/bash
cd "$(dirname "$0")"
echo "Starting AppTech Application Builder on http://localhost:8765"
python3 server.py &
sleep 1
# Try to open browser
if command -v xdg-open &>/dev/null; then xdg-open http://localhost:8765
elif command -v open &>/dev/null; then open http://localhost:8765
fi
wait
