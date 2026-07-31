#!/usr/bin/env python3
"""
AppTech Application Builder - Local HTTP Server
Zero dependencies: Python stdlib only.
"""

import json
import os
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).parent.resolve()
APPS_DIR = BASE_DIR / "apps"
PORT = 8765

# Ensure apps directory exists
APPS_DIR.mkdir(exist_ok=True)

# Initialize meta.json if missing
META_FILE = APPS_DIR / "meta.json"
if not META_FILE.exists():
    default_meta = {
        "1": {"name": "Test Slot 1", "description": "Test tool 1", "icon": "🧪", "author": ""},
        "2": {"name": "Test Slot 2", "description": "Test tool 2", "icon": "🧪", "author": ""},
        "3": {"name": "Test Slot 3", "description": "Test tool 3", "icon": "🧪", "author": ""},
        "4": {"name": "Test Slot 4", "description": "Test tool 4", "icon": "🧪", "author": ""},
    }
    META_FILE.write_text(json.dumps(default_meta, indent=2, ensure_ascii=False), encoding="utf-8")

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".ico":  "image/x-icon",
    ".svg":  "image/svg+xml",
}

# Matches the modal id every real AppTech tool uses as its root element,
# regardless of attribute order: <div id="fooModal" class="modal-overlay"> etc.
_MODAL_ID_RE = re.compile(
    r'<div\s+(?:id="([^"]+)"\s+class="modal-overlay"'
    r'|class="modal-overlay"\s+id="([^"]+)")'
)
_TOOL_MARKER_RE = re.compile(r'^<!--\s*@tool\s+\{.*?\}\s*-->\r?\n?', re.DOTALL)


def _extract_modal_id(content: str, fallback: str) -> str:
    m = _MODAL_ID_RE.search(content)
    if m:
        return m.group(1) or m.group(2)
    return fallback


def _strip_existing_marker(content: str) -> str:
    return _TOOL_MARKER_RE.sub("", content, count=1)


CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


class BuilderHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress default logging noise; print clean lines instead
        print(f"  {self.address_string()} - {format % args}")

    def _send_cors_headers(self):
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)

    def _send_json(self, code: int, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, file_path: Path):
        if not file_path.exists():
            self._send_404()
            return
        suffix = file_path.suffix.lower()
        mime = MIME_TYPES.get(suffix, "application/octet-stream")
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(data)

    def _send_404(self):
        body = b"404 Not Found"
        self.send_response(404)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/" or path == "":
            self._send_file(BASE_DIR / "index.html")
        elif path == "/preview":
            self._send_file(BASE_DIR / "preview.html")
        elif path == "/api/meta":
            self._handle_get_meta()
        else:
            # Strip leading slash and resolve relative to BASE_DIR
            relative = path.lstrip("/")
            file_path = (BASE_DIR / relative).resolve()
            # Security: ensure the resolved path is inside BASE_DIR
            try:
                file_path.relative_to(BASE_DIR)
            except ValueError:
                self._send_404()
                return
            self._send_file(file_path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/save":
            self._handle_save()
        else:
            body = b"Not Found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(body)

    def _handle_get_meta(self):
        try:
            data = json.loads(META_FILE.read_text(encoding="utf-8"))
            self._send_json(200, data)
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _handle_save(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))

            slot = str(payload.get("slot", "1"))
            if slot not in ("1", "2", "3", "4"):
                self._send_json(400, {"error": "slot must be 1–4"})
                return

            name        = str(payload.get("name", f"Test Slot {slot}"))
            description = str(payload.get("description", ""))
            icon        = str(payload.get("icon", "🧪"))
            author      = str(payload.get("author", ""))
            content     = str(payload.get("content", ""))

            # Embed the @tool marker AppTech's main dashboard needs to
            # discover this tool (see console.py's /api/tools/list) and to
            # open its modal by id (see dashboard.html's loadAndOpenTool).
            content = _strip_existing_marker(content)
            tool_id = _extract_modal_id(content, fallback=f"builderSlot{slot}Modal")
            marker = "<!-- @tool " + json.dumps(
                {"id": tool_id, "name": name, "description": description, "author": author},
                ensure_ascii=False,
            ) + " -->\n"

            # Write HTML file
            html_path = APPS_DIR / f"test{slot}.html"
            html_path.write_text(marker + content, encoding="utf-8")

            # Update meta.json
            meta = {}
            if META_FILE.exists():
                meta = json.loads(META_FILE.read_text(encoding="utf-8"))
            meta[slot] = {
                "name":        name,
                "description": description,
                "icon":        icon,
                "author":      author,
            }
            META_FILE.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

            self._send_json(200, {"ok": True, "slot": slot, "file": f"apps/test{slot}.html"})
            print(f"  Saved slot {slot} → {html_path.name}")
        except json.JSONDecodeError as e:
            self._send_json(400, {"error": f"JSON parse error: {e}"})
        except Exception as e:
            self._send_json(500, {"error": str(e)})


def run():
    server = HTTPServer(("", PORT), BuilderHandler)
    print(f"AppTech Application Builder running at http://localhost:{PORT}")
    print("Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    run()
