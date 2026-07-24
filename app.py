"""AppTech - FastAPI server.

WEB_APP_BASE_PREFIX (default: /apptech) controls the URL prefix so the app
sits correctly behind the nginx proxy on apptech.cisco.com.

Start:
    uvicorn app:app --host 0.0.0.0 --port 7997   # backend  (API / docs)
    uvicorn app:app --host 0.0.0.0 --port 7996   # frontend (HTML / static)
"""

import asyncio
import base64
import hashlib
import itertools
import json
import os
import queue
import re
import secrets
import threading
import traceback
from collections import deque
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

_APPTECH_ROOT = os.path.dirname(os.path.abspath(__file__))
BASE_PREFIX = os.getenv("WEB_APP_BASE_PREFIX", "").rstrip("/")

app = FastAPI(
    title="AppTech",
    docs_url=f"{BASE_PREFIX}/docs" if BASE_PREFIX else "/docs",
    openapi_url=f"{BASE_PREFIX}/openapi.json" if BASE_PREFIX else "/openapi.json",
    redoc_url=None,
)

app.mount(
    f"{BASE_PREFIX}/static",
    StaticFiles(directory=os.path.join(_APPTECH_ROOT, "static")),
    name="static",
)
app.mount(
    f"{BASE_PREFIX}/applications",
    StaticFiles(directory=os.path.join(_APPTECH_ROOT, "applications")),
    name="applications",
)


class _NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


app.add_middleware(_NoCacheMiddleware)


# === Debug log (in-memory ring buffer) ===
_DEBUG_LOG_MAX = 200
_debug_log_lock = threading.Lock()
_debug_log: deque = deque(maxlen=_DEBUG_LOG_MAX)
_debug_log_counter = itertools.count(1)


def debug_log(channel, **fields):
    """Append a structured debug entry. Safe to call from any thread."""
    entry = {
        "id": next(_debug_log_counter),
        "time": datetime.now().isoformat(timespec="seconds"),
        "channel": channel,
    }
    entry.update(fields)
    with _debug_log_lock:
        _debug_log.append(entry)
    try:
        preview = {
            k: (v if not isinstance(v, str) or len(v) < 300 else v[:300] + "…")
            for k, v in fields.items()
        }
        print(f"[debug:{channel}] {entry['time']} {preview}", flush=True)
    except Exception:
        pass
    return entry


@app.get(f"{BASE_PREFIX}/api/debug_log")
async def api_debug_log(since: int = 0):
    with _debug_log_lock:
        entries = [e for e in _debug_log if e["id"] > since]
        last_id = _debug_log[-1]["id"] if _debug_log else 0
    return {"ok": True, "entries": entries, "last_id": last_id}


@app.post(f"{BASE_PREFIX}/api/debug_log/clear")
async def api_debug_log_clear():
    with _debug_log_lock:
        _debug_log.clear()
    return {"ok": True}


# === Circuit Worker ===
# Playwright's sync API objects are bound to the thread that created them.
# All Circuit interactions are dispatched onto a single dedicated worker thread.
circuit_playwright = None
circuit_browser = None
circuit_context = None
circuit_page = None


class _CircuitWorker:
    """Single-threaded executor that owns the Playwright instance."""

    def __init__(self):
        self._jobs: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._loop, name="CircuitWorker", daemon=True)
        self._thread.start()

    def _loop(self):
        while True:
            fn, result_q = self._jobs.get()
            try:
                result_q.put(("ok", fn()))
            except BaseException as e:
                result_q.put(("err", (e, traceback.format_exc())))

    def run(self, fn, timeout=300):
        result_q: queue.Queue = queue.Queue(maxsize=1)
        self._jobs.put((fn, result_q))
        status, payload = result_q.get(timeout=timeout)
        if status == "ok":
            return payload
        exc, tb = payload
        print(f"[CircuitWorker] Task raised:\n{tb}")
        raise exc


circuit_worker = _CircuitWorker()


# === Frontend routes ===
@app.get(f"{BASE_PREFIX}/", include_in_schema=False)
@app.get(BASE_PREFIX or "/", include_in_schema=False)
async def login_page():
    return FileResponse(os.path.join(_APPTECH_ROOT, "templates", "login.html"))


@app.get(f"{BASE_PREFIX}/tools", include_in_schema=False)
async def tools_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/", status_code=302)


# === API: Port Load Calculator ===
@app.post(f"{BASE_PREFIX}/api/port_load")
async def api_port_load(request: Request):
    try:
        data = await request.json()
        port_speed_str = data.get("port_speed", "1G")
        tx_load = int(data.get("tx_load", 0))
        rx_load = int(data.get("rx_load", 0))
        if tx_load < 0 or tx_load > 255:
            return {"ok": False, "error": "TX load must be between 0 and 255"}
        if rx_load < 0 or rx_load > 255:
            return {"ok": False, "error": "RX load must be between 0 and 255"}
        port_speeds = {
            "100M": 100, "1G": 1000, "10G": 10000, "25G": 25000,
            "40G": 40000, "50G": 50000, "100G": 100000, "200G": 200000, "400G": 400000,
        }
        port_speed_mbps = port_speeds.get(port_speed_str, 1000)
        tx_percentage = (tx_load / 255) * 100
        rx_percentage = (rx_load / 255) * 100
        tx_speed_mbps = port_speed_mbps * (tx_load / 255)
        rx_speed_mbps = port_speed_mbps * (rx_load / 255)
        return {
            "ok": True,
            "result": {
                "port_speed": port_speed_str,
                "port_speed_mbps": port_speed_mbps,
                "tx_load": tx_load,
                "tx_percentage": tx_percentage,
                "tx_speed_mbps": tx_speed_mbps,
                "tx_speed_gbps": tx_speed_mbps / 1000,
                "rx_load": rx_load,
                "rx_percentage": rx_percentage,
                "rx_speed_mbps": rx_speed_mbps,
                "rx_speed_gbps": rx_speed_mbps / 1000,
            },
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# === API: Port Speed Calculator ===
@app.post(f"{BASE_PREFIX}/api/port_speed")
async def api_port_speed(request: Request):
    try:
        data = await request.json()
        speed = float(data.get("speed", 0))
        unit = data.get("unit", "Mbps")
        conversions = {
            "bps": speed,
            "Kbps": speed * 1_000,
            "Mbps": speed * 1_000_000,
            "Gbps": speed * 1_000_000_000,
            "Tbps": speed * 1_000_000_000_000,
        }
        base_bps = conversions.get(unit, 0)
        return {
            "ok": True,
            "result": {
                "bps": base_bps,
                "Kbps": base_bps / 1_000,
                "Mbps": base_bps / 1_000_000,
                "Gbps": base_bps / 1_000_000_000,
                "Tbps": base_bps / 1_000_000_000_000,
                "bytes_per_sec": base_bps / 8,
                "KB_per_sec": base_bps / 8_000,
                "MB_per_sec": base_bps / 8_000_000,
                "GB_per_sec": base_bps / 8_000_000_000,
            },
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# === API: Subnet Calculator ===
@app.post(f"{BASE_PREFIX}/api/subnet")
async def api_subnet(request: Request):
    try:
        data = await request.json()
        ip = data.get("ip", "")
        cidr = int(data.get("cidr", 24))
        octets = [int(x) for x in ip.split(".")]
        ip_int = (octets[0] << 24) + (octets[1] << 16) + (octets[2] << 8) + octets[3]
        mask_int = (0xFFFFFFFF << (32 - cidr)) & 0xFFFFFFFF
        mask_octets = [(mask_int >> 24) & 0xFF, (mask_int >> 16) & 0xFF,
                       (mask_int >> 8) & 0xFF, mask_int & 0xFF]
        network_int = ip_int & mask_int
        network_octets = [(network_int >> 24) & 0xFF, (network_int >> 16) & 0xFF,
                          (network_int >> 8) & 0xFF, network_int & 0xFF]
        wildcard_int = ~mask_int & 0xFFFFFFFF
        broadcast_int = network_int | wildcard_int
        broadcast_octets = [(broadcast_int >> 24) & 0xFF, (broadcast_int >> 16) & 0xFF,
                            (broadcast_int >> 8) & 0xFF, broadcast_int & 0xFF]
        first_ip_int = network_int + 1
        last_ip_int = broadcast_int - 1
        total_hosts = 2 ** (32 - cidr)
        usable_hosts = total_hosts - 2 if total_hosts > 2 else 0
        wildcard_octets = [(wildcard_int >> 24) & 0xFF, (wildcard_int >> 16) & 0xFF,
                           (wildcard_int >> 8) & 0xFF, wildcard_int & 0xFF]
        return {
            "ok": True,
            "result": {
                "network": ".".join(map(str, network_octets)),
                "subnet_mask": ".".join(map(str, mask_octets)),
                "wildcard_mask": ".".join(map(str, wildcard_octets)),
                "broadcast": ".".join(map(str, broadcast_octets)),
                "first_ip": ".".join(map(str, [(first_ip_int >> 24) & 0xFF,
                                               (first_ip_int >> 16) & 0xFF,
                                               (first_ip_int >> 8) & 0xFF,
                                               first_ip_int & 0xFF])),
                "last_ip": ".".join(map(str, [(last_ip_int >> 24) & 0xFF,
                                              (last_ip_int >> 16) & 0xFF,
                                              (last_ip_int >> 8) & 0xFF,
                                              last_ip_int & 0xFF])),
                "total_hosts": total_hosts,
                "usable_hosts": usable_hosts,
                "cidr": f"/{cidr}",
            },
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# === API: Diff Check ===
@app.post(f"{BASE_PREFIX}/api/diff")
async def api_diff(request: Request):
    try:
        import difflib
        data = await request.json()
        text1 = data.get("text1", "").splitlines(keepends=True)
        text2 = data.get("text2", "").splitlines(keepends=True)
        html_diff = difflib.HtmlDiff().make_table(
            text1, text2, fromdesc="Text 1", todesc="Text 2", context=True, numlines=3
        )
        unified = list(difflib.unified_diff(
            text1, text2, fromfile="Text 1", tofile="Text 2", lineterm=""
        ))
        return {"ok": True, "html_diff": html_diff, "unified_diff": "\n".join(unified)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# === API: JSON Pretty ===
@app.post(f"{BASE_PREFIX}/api/json_pretty")
async def api_json_pretty(request: Request):
    try:
        data = await request.json()
        json_input = data.get("json_input", "")
        indent = int(data.get("indent", 2))
        parsed = json.loads(json_input)
        return {"ok": True, "pretty_json": json.dumps(parsed, indent=indent, sort_keys=False)}
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"Invalid JSON: {str(e)}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# === API: Circuit Logs ===
LOG_CATEGORIES = {
    "circuit":  "circuit_responses",
    "local-ai": "local_ai_responses",
}


def _logs_root():
    return os.path.join(os.path.dirname(__file__), "circuit_logs")


def _resolve_logs_dir(category):
    root = _logs_root()
    if category and category in LOG_CATEGORIES:
        return os.path.join(root, LOG_CATEGORIES[category])
    return root


@app.get(f"{BASE_PREFIX}/api/circuit_logs")
async def get_circuit_logs(category: str = None):
    try:
        logs_dir = _resolve_logs_dir(category)
        if not os.path.exists(logs_dir):
            return {"ok": True, "logs": [], "category": category}
        log_files = []
        for filename in os.listdir(logs_dir):
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(logs_dir, filename)
            if not os.path.isfile(filepath):
                continue
            file_stat = os.stat(filepath)
            log_files.append({
                "filename": filename,
                "date": filename.replace("circuit_log_", "").replace(".json", ""),
                "size": file_stat.st_size,
                "modified": datetime.fromtimestamp(file_stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            })
        log_files.sort(key=lambda x: x["date"], reverse=True)
        return {"ok": True, "logs": log_files, "category": category}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get(f"{BASE_PREFIX}/api/circuit_logs/{{filename}}")
async def get_circuit_log_content(filename: str, category: str = None):
    try:
        if not filename.endswith(".json") or "/" in filename or "\\" in filename:
            return {"ok": False, "error": "Invalid filename"}
        logs_dir = _resolve_logs_dir(category)
        filepath = os.path.join(logs_dir, filename)
        if not os.path.exists(filepath):
            return {"ok": False, "error": "Log file not found"}
        with open(filepath, "r") as f:
            log_content = json.load(f)
        return {"ok": True, "content": log_content}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post(f"{BASE_PREFIX}/api/circuit_log")
async def save_circuit_log(request: Request):
    try:
        data = await request.json() or {}
        question = data.get("question", "")
        answer = data.get("answer", "")
        technology = data.get("technology", "")
        difficulty = data.get("difficulty", "")
        category = data.get("category", "circuit")
        model = data.get("model", "")
        if category not in LOG_CATEGORIES:
            category = "circuit"
        logs_dir = _resolve_logs_dir(category)
        os.makedirs(logs_dir, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        log_filepath = os.path.join(logs_dir, f"circuit_log_{today}.json")
        if os.path.exists(log_filepath):
            with open(log_filepath, "r") as f:
                log_data = json.load(f)
        else:
            log_data = {"date": today, "category": category, "entries": []}
        log_data["entries"].append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "technology": technology,
            "difficulty": difficulty,
            "model": model,
            "question": question,
            "answer": answer,
            "success": True,
        })
        with open(log_filepath, "w") as f:
            json.dump(log_data, f, indent=2)
        return {"ok": True, "message": "Log saved successfully", "category": category}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# === API: Circuit Credentials ===
def _creds_file():
    return os.path.join(os.path.dirname(__file__), "circuit_credentials.json")


@app.get(f"{BASE_PREFIX}/api/circuit_credentials")
async def get_circuit_credentials():
    try:
        creds_file = _creds_file()
        if not os.path.exists(creds_file):
            return {"success": True, "credentials": []}
        with open(creds_file, "r") as f:
            creds_data = json.load(f)
        return {"success": True, "credentials": [{"name": name} for name in creds_data]}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get(f"{BASE_PREFIX}/api/circuit_credentials/{{cred_name}}")
async def get_circuit_credential(cred_name: str):
    try:
        creds_file = _creds_file()
        if not os.path.exists(creds_file):
            return {"success": False, "error": "No saved credentials found"}
        with open(creds_file, "r") as f:
            creds_data = json.load(f)
        if cred_name not in creds_data:
            return {"success": False, "error": "Credential not found"}
        cred = creds_data[cred_name]
        password = base64.b64decode(cred["password"]).decode("utf-8")
        return {"success": True, "credential": {"username": cred["username"], "password": password}}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post(f"{BASE_PREFIX}/api/circuit_credentials")
async def save_circuit_credential(request: Request):
    try:
        data = await request.json()
        name = data.get("name", "").strip()
        username = data.get("username", "").strip()
        password = data.get("password", "").strip()
        if not name or not username or not password:
            return {"success": False, "error": "Name, username, and password are required"}
        creds_file = _creds_file()
        creds_data: dict = {}
        if os.path.exists(creds_file):
            with open(creds_file, "r") as f:
                creds_data = json.load(f)
        creds_data[name] = {
            "username": username,
            "password": base64.b64encode(password.encode("utf-8")).decode("utf-8"),
        }
        with open(creds_file, "w") as f:
            json.dump(creds_data, f, indent=2)
        return {"success": True, "message": "Credential saved successfully"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.delete(f"{BASE_PREFIX}/api/circuit_credentials/{{cred_name}}")
async def delete_circuit_credential(cred_name: str):
    try:
        creds_file = _creds_file()
        if not os.path.exists(creds_file):
            return {"success": False, "error": "No saved credentials found"}
        with open(creds_file, "r") as f:
            creds_data = json.load(f)
        if cred_name not in creds_data:
            return {"success": False, "error": "Credential not found"}
        del creds_data[cred_name]
        with open(creds_file, "w") as f:
            json.dump(creds_data, f, indent=2)
        return {"success": True, "message": "Credential deleted successfully"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# === Circuit AI question job (runs on CircuitWorker thread) ===
def _circuit_question_job(username, password, question):
    global circuit_playwright, circuit_browser, circuit_context, circuit_page
    from playwright.sync_api import sync_playwright
    import time

    if circuit_browser is None or circuit_page is None:
        circuit_playwright = sync_playwright().start()
        circuit_browser = circuit_playwright.chromium.launch(headless=False)
        circuit_context = circuit_browser.new_context()
        circuit_page = circuit_context.new_page()
        try:
            circuit_page.goto("https://circuit.cisco.com/app/home", timeout=30000)
            circuit_page.wait_for_load_state("networkidle", timeout=10000)
            if "duosecurity" in circuit_page.url.lower() or "login" in circuit_page.url.lower():
                email_field = circuit_page.locator('input[type="email"], input[type="text"]').first
                if email_field.count() > 0:
                    email_field.fill(username)
                    next_button = circuit_page.locator('button:has-text("Next"), button[type="submit"]').first
                    if next_button.count() > 0:
                        next_button.click()
                        circuit_page.wait_for_load_state("networkidle", timeout=15000)
                time.sleep(2)
                password_field = circuit_page.locator('input[type="password"]').first
                if password_field.count() > 0:
                    password_field.fill(password)
                    submit_button = circuit_page.locator(
                        'button[type="submit"], button:has-text("Sign In"), '
                        'button:has-text("Log In"), button:has-text("Submit")'
                    ).first
                    if submit_button.count() > 0:
                        submit_button.click()
                        circuit_page.wait_for_load_state("networkidle", timeout=20000)
                time.sleep(23)
        except Exception as auth_error:
            return {"ok": False, "error": f"Authentication failed: {str(auth_error)}"}

    try:
        try:
            circuit_page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        try:
            circuit_page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            pass

        def find_active_textarea_index():
            try:
                result = circuit_page.evaluate("""
                    () => {
                        const tas = Array.from(document.querySelectorAll('textarea'));
                        const candidates = [];
                        tas.forEach((ta, idx) => {
                            const rect = ta.getBoundingClientRect();
                            const style = window.getComputedStyle(ta);
                            const visible = rect.width > 20 && rect.height > 10
                                && style.display !== 'none'
                                && style.visibility !== 'hidden'
                                && style.opacity !== '0';
                            const usable = !ta.disabled && !ta.readOnly;
                            candidates.push({
                                idx, visible, usable, bottom: rect.bottom,
                                top: rect.top,
                                placeholder: ta.getAttribute('placeholder') || '',
                                className: ta.className || '',
                            });
                        });
                        return candidates;
                    }
                """)
            except Exception as e:
                print(f"find_active_textarea_index evaluate failed: {e}")
                return None, []
            if not result:
                return None, []
            visible_usable = [c for c in result if c["visible"] and c["usable"]]
            if visible_usable:
                return max(visible_usable, key=lambda c: c["bottom"])["idx"], result
            visible_only = [c for c in result if c["visible"]]
            if visible_only:
                return max(visible_only, key=lambda c: c["bottom"])["idx"], result
            return None, result

        search_input = None
        chosen_idx = None
        last_diag: list = []
        deadline = time.time() + 25
        while time.time() < deadline:
            chosen_idx, last_diag = find_active_textarea_index()
            if chosen_idx is not None:
                candidate = circuit_page.locator("textarea").nth(chosen_idx)
                try:
                    if candidate.is_visible():
                        search_input = candidate
                        break
                except Exception:
                    pass
            time.sleep(0.5)

        if search_input is None:
            try:
                circuit_page.screenshot(path="circuit_debug_fail.png")
            except Exception:
                pass
            return {
                "ok": False,
                "error": "Could not find an active Circuit input textarea.",
                "textareas_found": len(last_diag),
                "diagnostics": [
                    {
                        "idx": c["idx"], "visible": c["visible"], "usable": c["usable"],
                        "placeholder": c["placeholder"][:60], "className": c["className"][:80],
                    }
                    for c in last_diag
                ],
            }

        print(f"Found active textarea at index {chosen_idx} (of {len(last_diag)})")

        try:
            try:
                search_input.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass
            search_input.click()
            try:
                search_input.press("Control+a")
                search_input.press("Delete")
            except Exception:
                pass
            search_input.fill("")
            search_input.fill(question)
            current_value = ""
            try:
                current_value = search_input.input_value()
            except Exception:
                pass
            if current_value != question:
                print("Warning: Text mismatch. Retrying with type().")
                try:
                    search_input.fill("")
                    search_input.type(question, delay=20)
                except Exception as e_type:
                    return {"ok": False, "error": f"Found textarea but could not enter question: {str(e_type)}"}
        except Exception as fill_error:
            return {"ok": False, "error": f"Could not focus/fill textarea: {str(fill_error)}"}

        response_selectors = [
            'div[role="article"]', ".message-content", ".ai-response",
            ".response-content", '[data-testid*="response"]', '[data-testid*="message"]',
            'div[class*="response"]', 'div[class*="message"]',
        ]

        def snapshot_response_counts():
            counts = {}
            for sel in response_selectors:
                try:
                    counts[sel] = circuit_page.locator(sel).count()
                except Exception:
                    counts[sel] = 0
            return counts

        def snapshot_existing_texts():
            existing = set()
            for sel in response_selectors:
                try:
                    els = circuit_page.locator(sel).all()
                except Exception:
                    continue
                for el in els:
                    try:
                        txt = (el.inner_text() or "").strip()
                        if len(txt) > 20:
                            existing.add(txt)
                    except Exception:
                        continue
            return existing

        pre_counts = snapshot_response_counts()
        pre_texts = snapshot_existing_texts()
        print("Submitting question...")
        search_input.press("Enter")

        def get_latest_new_response_text():
            for sel in response_selectors:
                try:
                    els = circuit_page.locator(sel).all()
                except Exception:
                    continue
                start_idx = pre_counts.get(sel, 0)
                new_slice = els[start_idx:] if start_idx < len(els) else []
                for el in reversed(new_slice):
                    try:
                        if not el.is_visible():
                            continue
                        txt = (el.inner_text() or "").strip()
                        if len(txt) > 20 and txt != question.strip() and txt not in pre_texts:
                            return txt
                    except Exception:
                        continue
                for el in reversed(els):
                    try:
                        if not el.is_visible():
                            continue
                        txt = (el.inner_text() or "").strip()
                        if len(txt) > 20 and txt != question.strip() and txt not in pre_texts:
                            return txt
                    except Exception:
                        continue
            return None

        last_text = ""
        stable_since = None
        hard_deadline = time.time() + 90
        stability_window = 3.0
        ai_response = None
        while time.time() < hard_deadline:
            current = get_latest_new_response_text()
            if current:
                if current == last_text:
                    if stable_since is None:
                        stable_since = time.time()
                    elif time.time() - stable_since >= stability_window:
                        ai_response = current
                        break
                else:
                    last_text = current
                    stable_since = None
            time.sleep(0.5)

        if ai_response is None:
            ai_response = (
                last_text + "\n\n(Note: response may have been truncated — Circuit was still generating after 90s.)"
                if last_text
                else "Could not extract response from Circuit (no new content detected). Try again or check the Circuit window."
            )
        return {"ok": True, "question": question, "answer": ai_response}

    except Exception as inner_e:
        return {"ok": False, "error": f"Circuit automation error: {str(inner_e)}"}


# === API: Circuit Question ===
@app.post(f"{BASE_PREFIX}/api/circuit_question")
async def api_circuit_question(request: Request):
    try:
        data = await request.json() or {}
        username = data.get("username", "")
        password = data.get("password", "")
        question = data.get("question", "")
        if not username or not password:
            return {"ok": False, "error": "Username and password are required"}
        if not question:
            return {"ok": False, "error": "Question is required"}
        try:
            import playwright  # noqa: F401
        except ImportError:
            return {
                "ok": False,
                "error": "Playwright not installed. Run: pip install playwright && playwright install chromium",
            }
        result = await asyncio.to_thread(
            circuit_worker.run,
            lambda: _circuit_question_job(username, password, question),
            600,
        )
        # Log Q&A to circuit_logs/circuit_responses/
        try:
            log_dir = os.path.join(os.path.dirname(__file__), "circuit_logs", "circuit_responses")
            os.makedirs(log_dir, exist_ok=True)
            today = datetime.now().strftime("%Y-%m-%d")
            log_file = os.path.join(log_dir, f"circuit_log_{today}.json")
            entry = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "technology": "ask-question",
                "difficulty": "",
                "model": "",
                "question": question,
                "answer": result.get("answer", result.get("error", "")),
                "success": bool(result.get("ok", False)),
            }
            if os.path.exists(log_file):
                with open(log_file, "r") as f:
                    log_data = json.load(f)
                log_data["entries"].append(entry)
            else:
                log_data = {"date": today, "category": "circuit", "entries": [entry]}
            with open(log_file, "w") as f:
                json.dump(log_data, f, indent=2)
        except Exception as log_err:
            print(f"[circuit log] Failed to write log: {log_err}")
        return result
    except Exception as e:
        return {"ok": False, "error": f"Error: {str(e)}"}


# === API: Circuit Debug ===
# Long-blocking (Playwright + 30s sleep). FastAPI runs def routes in thread pool.
class _CredsRequest(BaseModel):
    username: str = ""
    password: str = ""


@app.post(f"{BASE_PREFIX}/api/circuit_debug")
def api_circuit_debug(data: _CredsRequest):
    try:
        from playwright.sync_api import sync_playwright
        import time

        username = data.username
        password = data.password
        if not username or not password:
            return {"ok": False, "error": "Username and password are required"}

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            try:
                page.goto("https://circuit.cisco.com/app/home", timeout=30000)
                page.wait_for_load_state("networkidle", timeout=10000)
                if "duosecurity" in page.url.lower() or "login" in page.url.lower():
                    email_field = page.locator('input[type="email"], input[type="text"]').first
                    if email_field.count() > 0:
                        email_field.fill(username)
                        next_button = page.locator('button:has-text("Next"), button[type="submit"]').first
                        if next_button.count() > 0:
                            next_button.click()
                            page.wait_for_load_state("networkidle", timeout=15000)
                    time.sleep(2)
                    password_field = page.locator('input[type="password"]').first
                    if password_field.count() > 0:
                        password_field.fill(password)
                        submit_button = page.locator(
                            'button[type="submit"], button:has-text("Sign In"), '
                            'button:has-text("Log In"), button:has-text("Submit")'
                        ).first
                        if submit_button.count() > 0:
                            submit_button.click()
                            page.wait_for_load_state("networkidle", timeout=20000)
                time.sleep(3)
                try:
                    allow_button = page.locator('button:has-text("Allow")').first
                    if allow_button.count() > 0 and allow_button.is_visible():
                        allow_button.click()
                        time.sleep(2)
                except Exception:
                    pass
                time.sleep(8)

                inputs_info = []
                for i, inp in enumerate(page.locator("input").all()):
                    try:
                        info = {"type": "input", "index": i, "visible": inp.is_visible(), "attributes": {}}
                        for attr in ["type", "name", "id", "class", "placeholder",
                                     "aria-label", "data-testid", "role"]:
                            try:
                                val = inp.get_attribute(attr)
                                if val:
                                    info["attributes"][attr] = val
                            except Exception:
                                pass
                        if info["visible"] or info["attributes"]:
                            inputs_info.append(info)
                    except Exception:
                        pass
                for i, ta in enumerate(page.locator("textarea").all()):
                    try:
                        info = {"type": "textarea", "index": i, "visible": ta.is_visible(), "attributes": {}}
                        for attr in ["name", "id", "class", "placeholder", "aria-label", "data-testid", "role"]:
                            try:
                                val = ta.get_attribute(attr)
                                if val:
                                    info["attributes"][attr] = val
                            except Exception:
                                pass
                        if info["visible"] or info["attributes"]:
                            inputs_info.append(info)
                    except Exception:
                        pass
                for i, ed in enumerate(page.locator('[contenteditable="true"]').all()):
                    try:
                        info = {"type": "contenteditable", "index": i,
                                "visible": ed.is_visible(), "attributes": {}}
                        for attr in ["class", "id", "aria-label", "data-testid", "role"]:
                            try:
                                val = ed.get_attribute(attr)
                                if val:
                                    info["attributes"][attr] = val
                            except Exception:
                                pass
                        if info["visible"] or info["attributes"]:
                            inputs_info.append(info)
                    except Exception:
                        pass

                screenshot_b64 = base64.b64encode(page.screenshot(full_page=True)).decode("utf-8")
                current_url = page.url
                time.sleep(30)
                browser.close()
                return {
                    "ok": True,
                    "url": current_url,
                    "inputs_found": len(inputs_info),
                    "inputs": inputs_info,
                    "screenshot": screenshot_b64,
                    "message": "Browser was kept open for 30 seconds for manual inspection",
                }
            except Exception as e:
                browser.close()
                return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# === API: Circuit Close ===
@app.post(f"{BASE_PREFIX}/api/circuit_close")
async def api_circuit_close():
    def _close():
        global circuit_playwright, circuit_browser, circuit_context, circuit_page
        if circuit_browser is not None:
            try:
                circuit_browser.close()
            except Exception:
                pass
            circuit_browser = None
            circuit_context = None
            circuit_page = None
        if circuit_playwright is not None:
            try:
                circuit_playwright.stop()
            except Exception:
                pass
            circuit_playwright = None
        return {"ok": True, "message": "Circuit browser closed successfully"}

    try:
        return await asyncio.to_thread(circuit_worker.run, _close, 30)
    except Exception as e:
        return {"ok": False, "error": str(e)}


# === API: Circuit Open Browser ===
@app.post(f"{BASE_PREFIX}/api/circuit_open_browser")
async def api_circuit_open_browser(request: Request):
    data = await request.json() or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()

    def _open():
        global circuit_playwright, circuit_browser, circuit_context, circuit_page
        from playwright.sync_api import sync_playwright
        import time

        already_open = circuit_browser is not None and circuit_page is not None

        if not already_open:
            circuit_playwright = sync_playwright().start()
            circuit_browser = circuit_playwright.chromium.launch(headless=False)
            circuit_context = circuit_browser.new_context()
            circuit_page = circuit_context.new_page()
            circuit_page.goto("https://circuit.cisco.com/app/home", timeout=30000)
            try:
                circuit_page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
        else:
            try:
                circuit_page.bring_to_front()
            except Exception:
                pass
            try:
                circuit_page.evaluate("window.focus()")
            except Exception:
                pass
            if "circuit.cisco.com" not in (circuit_page.url or ""):
                circuit_page.goto("https://circuit.cisco.com/app/home", timeout=30000)
                try:
                    circuit_page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
            return {"ok": True, "message": "Browser window brought to front", "refocused": True}

        if username and password:
            try:
                email_locator = circuit_page.locator('input[aria-label="Email Address"][type="email"]')
                if email_locator.count() == 0:
                    email_locator = circuit_page.locator('input[type="email"], input[type="text"]').first
                if email_locator.count() > 0:
                    email_locator.fill(username)
                    time.sleep(0.4)
                    next_btn = circuit_page.locator('button[type="button"]:has-text("Next")')
                    if next_btn.count() == 0:
                        next_btn = circuit_page.locator('button:has-text("Next"), button[type="submit"]').first
                    if next_btn.count() > 0:
                        next_btn.click()
                        try:
                            circuit_page.wait_for_load_state("networkidle", timeout=15000)
                        except Exception:
                            pass
                    time.sleep(1.5)
                password_field = circuit_page.locator('input[type="password"]').first
                if password_field.count() > 0:
                    password_field.fill(password)
                    time.sleep(0.4)
                    submit_btn = circuit_page.locator(
                        'button[type="submit"], button:has-text("Sign In"), '
                        'button:has-text("Log In"), button:has-text("Submit")'
                    ).first
                    if submit_btn.count() > 0:
                        submit_btn.click()
                        try:
                            circuit_page.wait_for_load_state("networkidle", timeout=20000)
                        except Exception:
                            pass
            except Exception as auth_err:
                return {"ok": True, "message": f"Browser opened (credential fill error: {auth_err})"}

        return {"ok": True, "message": "Browser opened", "refocused": False}

    try:
        return await asyncio.to_thread(circuit_worker.run, _open, 120)
    except Exception as e:
        return {"ok": False, "error": str(e)}


# === API: Circuit Status ===
@app.get(f"{BASE_PREFIX}/api/circuit_status")
async def api_circuit_status():
    def _status():
        connected = circuit_browser is not None and circuit_page is not None
        url = None
        if connected:
            try:
                url = circuit_page.url
            except Exception:
                connected = False
        return {"ok": True, "connected": connected, "url": url}

    try:
        return await asyncio.to_thread(circuit_worker.run, _status, 10)
    except Exception as e:
        return {"ok": False, "connected": False, "error": str(e)}


# === Profile Management ===
def _profile_file():
    profile_dir = os.path.join(os.path.dirname(__file__), "profiles")
    os.makedirs(profile_dir, exist_ok=True)
    return os.path.join(profile_dir, "default.json")


def _load_profile():
    try:
        pf = _profile_file()
        if os.path.exists(pf):
            with open(pf, "r") as f:
                return json.load(f)
    except Exception as e:
        debug_log("profile", action="load", error=str(e))
    return {
        "categories": [{"id": "misc", "name": "Miscellaneous", "color": "#2d5aa0"}],
        "assignments": {},
        "order": [],
        "columns": 3,
    }


def _save_profile(profile_data):
    try:
        with open(_profile_file(), "w") as f:
            json.dump(profile_data, f, indent=2)
        return True
    except Exception as e:
        debug_log("profile", action="save", error=str(e))
        return False


def _default_dashboard_profile():
    return {
        "categories": [{"id": "misc", "name": "Miscellaneous", "color": "#2d5aa0"}],
        "assignments": {},
        "order": [],
        "columns": 3,
    }


# Legacy global profile endpoints (kept for compatibility)
@app.get(f"{BASE_PREFIX}/api/profile/load")
async def api_profile_load():
    try:
        return {"ok": True, "profile": _load_profile()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post(f"{BASE_PREFIX}/api/profile/save")
async def api_profile_save(request: Request):
    try:
        data = await request.json()
        profile_data = {
            "categories": data.get("categories", [{"id": "misc", "name": "Miscellaneous", "color": "#2d5aa0"}]),
            "assignments": data.get("assignments", {}),
            "order": data.get("order", []),
            "columns": data.get("columns", 3),
        }
        if _save_profile(profile_data):
            return {"ok": True, "message": "Profile saved"}
        return {"ok": False, "error": "Failed to save profile"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# Per-user dashboard profile (tabs, categories, assignments, column count)
@app.get(f"{BASE_PREFIX}/api/users/{{username}}/profile")
async def api_get_user_profile(username: str):
    try:
        profile = _load_user(username.lower())
        if not profile:
            return {"ok": False, "error": "User not found"}
        return {"ok": True, "profile": profile.get("dashboard_profile", _default_dashboard_profile())}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post(f"{BASE_PREFIX}/api/users/{{username}}/profile")
async def api_save_user_profile(username: str, request: Request):
    try:
        data = await request.json()
        profile = _load_user(username.lower())
        if not profile:
            return {"ok": False, "error": "User not found"}
        dp = {
            "categories": data.get("categories", [{"id": "misc", "name": "Miscellaneous", "color": "#2d5aa0"}]),
            "assignments": data.get("assignments", {}),
            "order": data.get("order", []),
            "columns": data.get("columns", 3),
        }
        if "activeTab" in data:
            dp["activeTab"] = data["activeTab"]
        profile["dashboard_profile"] = dp
        _save_user(profile)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# === User Profile Management ===
_RESERVED_USERNAMES = {
    "api", "static", "applications", "docs", "openapi.json",
    "tools", "favicon.ico", "robots.txt",
}
_USERNAME_RE = re.compile(r'^[a-zA-Z0-9_-]{2,32}$')


def _user_profiles_dir():
    d = os.path.join(_APPTECH_ROOT, "user_profiles")
    os.makedirs(d, exist_ok=True)
    return d


def _user_profile_path(username: str):
    return os.path.join(_user_profiles_dir(), f"{username}.json")


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"{salt}:{h.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, h_hex = stored.split(":", 1)
        h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
        return h.hex() == h_hex
    except Exception:
        return False


def _load_user(username: str):
    path = _user_profile_path(username)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def _save_user(profile: dict):
    with open(_user_profile_path(profile["username"]), "w") as f:
        json.dump(profile, f, indent=2)


@app.post(f"{BASE_PREFIX}/api/users/create")
async def api_users_create(request: Request):
    try:
        data = await request.json()
        username = (data.get("username") or "").strip().lower()
        password = data.get("password") or ""
        if not _USERNAME_RE.match(username):
            return {"ok": False, "error": "Username must be 2-32 chars (letters, numbers, _ -)"}
        if username in _RESERVED_USERNAMES:
            return {"ok": False, "error": "That username is reserved."}
        if len(password) < 4:
            return {"ok": False, "error": "Password must be at least 4 characters."}
        if _load_user(username):
            return {"ok": False, "error": f'Username "{username}" is already taken.'}
        profile = {
            "username": username,
            "password": _hash_password(password),
            "tools": [],
            "created": datetime.now().isoformat(timespec="seconds"),
        }
        _save_user(profile)
        return {"ok": True, "username": username}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post(f"{BASE_PREFIX}/api/users/login")
async def api_users_login(request: Request):
    try:
        data = await request.json()
        username = (data.get("username") or "").strip().lower()
        password = data.get("password") or ""
        profile = _load_user(username)
        if not profile or not _verify_password(password, profile["password"]):
            return {"ok": False, "error": "Invalid username or password."}
        return {"ok": True, "username": username}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get(f"{BASE_PREFIX}/api/users/{{username}}/tools")
async def api_get_user_tools(username: str):
    try:
        profile = _load_user(username.lower())
        if not profile:
            return {"ok": False, "error": "User not found"}
        return {"ok": True, "tools": profile.get("tools", [])}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post(f"{BASE_PREFIX}/api/users/{{username}}/tools")
async def api_save_user_tools(username: str, request: Request):
    try:
        data = await request.json()
        tools = data.get("tools", [])
        profile = _load_user(username.lower())
        if not profile:
            return {"ok": False, "error": "User not found"}
        profile["tools"] = tools
        _save_user(profile)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get(f"{BASE_PREFIX}/api/users")
async def api_list_users():
    try:
        d = _user_profiles_dir()
        users = []
        for f in os.listdir(d):
            if f.endswith(".json"):
                users.append(f[:-5])
        return {"ok": True, "users": sorted(users)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# === Per-user frontend routes (must be last — path params match anything) ===
_RESERVED_PATH_PREFIXES = {"api", "static", "applications", "docs", "tools", "openapi.json"}


@app.get(f"{BASE_PREFIX}/{{username}}", include_in_schema=False)
async def user_dashboard(username: str):
    if username in _RESERVED_PATH_PREFIXES or not _USERNAME_RE.match(username):
        from fastapi import HTTPException
        raise HTTPException(status_code=404)
    return FileResponse(os.path.join(_APPTECH_ROOT, "templates", "dashboard.html"))


@app.get(f"{BASE_PREFIX}/{{username}}/tools", include_in_schema=False)
async def user_tools(username: str):
    if username in _RESERVED_PATH_PREFIXES or not _USERNAME_RE.match(username):
        from fastapi import HTTPException
        raise HTTPException(status_code=404)
    return FileResponse(os.path.join(_APPTECH_ROOT, "templates", "tools.html"))


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "7997"))
    uvicorn.run(app, host="0.0.0.0", port=port)
