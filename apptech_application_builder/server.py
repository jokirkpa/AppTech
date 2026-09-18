#!/usr/bin/env python3
"""
AppTech Local Builder — zero-dependency local server.

Serves a minimal simulation of the AppTech dashboard so you can build a tool
locally (with Claude, in VS Code) and see it exactly as it will appear on the
live site. Tools live in ./applications/ as self-contained .html files and are
1:1 compatible with the live site's applications/ folder.

Requirements: Python 3 only. No pip installs, no Node, nothing else.

    python3 server.py     # then open http://localhost:5050
"""

import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).parent.resolve()
APPS_DIR = BASE_DIR / "applications"

# Port: default 5050. Override with `PORT=9000 python3 server.py` or
# `python3 server.py 9000`. If the chosen port is busy, we try the next few.
PORT = int(os.environ.get("PORT") or (sys.argv[1] if len(sys.argv) > 1 else 5050))

# Make sure the tools folder exists so a fresh clone still runs.
APPS_DIR.mkdir(exist_ok=True)

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif":  "image/gif",
    ".svg":  "image/svg+xml",
    ".ico":  "image/x-icon",
}

# Same @tool discovery regex the live site uses (see console.py: api_tools_list).
# Keeping it identical guarantees: if a tool shows up here, the live site finds it too.
_TOOL_MARKER_RE = re.compile(r"<!--\s*@tool\s+(\{.*?\})\s*-->")

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


def discover_tools():
    """Scan applications/*.html for the @tool marker on the first line."""
    tools = []
    for fpath in sorted(APPS_DIR.glob("*.html")):
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                first_line = f.readline(2048)
            m = _TOOL_MARKER_RE.search(first_line)
            if not m:
                continue
            meta = json.loads(m.group(1))
            meta["file"] = fpath.name
            tools.append(meta)
        except Exception:
            # A malformed tool file should never take down the whole listing.
            continue
    return tools


def apps_max_mtime():
    """Newest mtime across all tool files, in milliseconds — used for live reload."""
    latest = 0.0
    for fpath in APPS_DIR.glob("*.html"):
        try:
            latest = max(latest, fpath.stat().st_mtime)
        except OSError:
            pass
    return int(latest * 1000)


class BuilderHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} - {fmt % args}")

    # ── response helpers ─────────────────────────────────────────────
    def _cors(self):
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)

    def _send_json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, file_path):
        if not file_path.exists() or not file_path.is_file():
            self._send_404()
            return
        mime = MIME_TYPES.get(file_path.suffix.lower(), "application/octet-stream")
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        # Never cache tool files — the live-reload loop relies on fresh fetches.
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def _send_404(self):
        body = b"404 Not Found"
        self.send_response(404)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    # ── routing ──────────────────────────────────────────────────────
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", ""):
            self._send_file(BASE_DIR / "dashboard.html")
            return
        if path == "/api/tools/list":
            self._send_json(200, {"ok": True, "tools": discover_tools()})
            return
        if path == "/api/changed":
            self._send_json(200, {"ok": True, "mtime": apps_max_mtime()})
            return

        # Everything else is a static file relative to BASE_DIR.
        relative = path.lstrip("/")
        file_path = (BASE_DIR / relative).resolve()
        # Security: never serve anything outside this folder.
        try:
            file_path.relative_to(BASE_DIR)
        except ValueError:
            self._send_404()
            return
        self._send_file(file_path)


def run():
    # Try the chosen port, then a few after it, so a busy port doesn't crash
    # with a raw traceback on someone's machine.
    last_err = None
    for port in range(PORT, PORT + 10):
        try:
            server = HTTPServer(("", port), BuilderHandler)
        except OSError as e:
            last_err = e
            continue
        print(f"AppTech Local Builder running at http://localhost:{port}")
        if port != PORT:
            print(f"(port {PORT} was busy, using {port} instead)")
        print(f"Serving tools from: {APPS_DIR}")
        print("Press Ctrl+C to stop.\n")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
        return
    print(f"Could not start: ports {PORT}-{PORT + 9} are all in use ({last_err}).")
    print("Free a port or set another one: PORT=9000 python3 server.py")
    sys.exit(1)


if __name__ == "__main__":
    run()
