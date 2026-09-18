"""AppTech - Console (FastAPI server).

WEB_APP_BASE_PREFIX (default: /apptech) controls the URL prefix so the app
sits correctly behind the nginx proxy on apptech.cisco.com.

Start:
    uvicorn console:app --host 0.0.0.0 --port 7997   # backend  (API / docs)
    uvicorn console:app --host 0.0.0.0 --port 7996   # frontend (HTML / static)
"""

import hashlib
import itertools
import json
import os
import re
import secrets
import threading
from collections import deque
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
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


# === Frontend routes ===
@app.get(f"{BASE_PREFIX}/", include_in_schema=False)
@app.get(BASE_PREFIX or "/", include_in_schema=False)
async def login_page():
    return FileResponse(os.path.join(_APPTECH_ROOT, "templates", "login.html"))


@app.get(f"{BASE_PREFIX}/tools", include_in_schema=False)
async def tools_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/", status_code=302)


# === API: Tool Discovery ===
@app.get(f"{BASE_PREFIX}/api/tools/list")
async def api_tools_list():
    apps_dir = os.path.join(_APPTECH_ROOT, "applications")
    tools = []
    try:
        for fname in sorted(os.listdir(apps_dir)):
            if not fname.endswith(".html"):
                continue
            fpath = os.path.join(apps_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    first_line = f.readline(1024)
                import re as _re
                m = _re.search(r'<!--\s*@tool\s+(\{.*?\})\s*-->', first_line)
                if m:
                    import json as _json
                    meta = _json.loads(m.group(1))
                    meta["file"] = fname
                    tools.append(meta)
            except Exception:
                pass
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "tools": tools}


# === API: Quicker AI ===
_QUICKER_AI_URL   = os.getenv("QUICKER_AI_URL", "http://localhost:7120/sovct/api/v1/ai/chat")
_QUICKER_AI_TOKEN = os.getenv("QUICKER_AI_TOKEN", "")
_QUICKER_AI_SYSTEM = (
    "You are a Cisco network engineering expert. "
    "Generate a network engineering training question and a detailed answer. "
    "Respond ONLY with valid JSON containing exactly two fields: "
    "\"question\" (the question text) and \"answer\" (the detailed answer). "
    "No markdown, no extra keys."
)

_QUICKER_AI_CHAT_SYSTEM = (
    "You are a knowledgeable Cisco network engineering assistant. "
    "Answer the user's questions conversationally and helpfully. "
    "Keep responses concise unless the user asks for detail."
)


@app.post(f"{BASE_PREFIX}/api/ai_question")
async def api_ai_question(request: Request):
    try:
        import httpx
        data = await request.json() or {}
        prompt = data.get("prompt", "")
        if not prompt:
            return {"ok": False, "error": "Prompt is required"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                _QUICKER_AI_URL,
                headers={
                    "Content-Type": "application/json",
                    "X-Internal-Token": _QUICKER_AI_TOKEN,
                },
                json={
                    "messages": [
                        {"role": "system", "content": _QUICKER_AI_SYSTEM},
                        {"role": "user",   "content": prompt},
                    ],
                    "json_mode": True,
                    "max_tokens": 600,
                },
            )
        resp.raise_for_status()
        ai_result = resp.json()
        content = json.loads(ai_result.get("content", "{}"))
        question = content.get("question", "")
        answer   = content.get("answer", "")
        if not question or not answer:
            return {"ok": False, "error": "AI returned an unexpected format"}
        return {"ok": True, "question": question, "answer": answer,
                "model": ai_result.get("model", ""), "tokens": ai_result.get("tokens_used", {})}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# === Token usage — stored inside each user's profile ===

def _add_tokens(username: str, tokens: dict):
    month_key = datetime.now().strftime("%Y-%m")
    profile = _load_user(username)
    if not profile:
        return tokens
    usage = profile.setdefault("token_usage", {})
    month_data = usage.setdefault(month_key, {"total": 0, "input": 0, "output": 0})
    month_data["total"]  += tokens.get("total",  0)
    month_data["input"]  += tokens.get("input",  0)
    month_data["output"] += tokens.get("output", 0)
    _save_user(profile)
    return month_data

@app.get(f"{BASE_PREFIX}/api/token_usage")
async def api_get_token_usage(username: str = ""):
    month_key = datetime.now().strftime("%Y-%m")
    profile = _load_user(username) if username else None
    month_data = (profile or {}).get("token_usage", {}).get(month_key, {"total": 0, "input": 0, "output": 0})
    return {"ok": True, "month": month_key, "usage": month_data}


# === API: Quicker AI free-form chat ===
@app.post(f"{BASE_PREFIX}/api/ai_chat")
async def api_ai_chat(request: Request):
    try:
        import httpx
        data = await request.json() or {}
        message  = data.get("message", "").strip()
        model    = data.get("model") or None
        username = data.get("username", "")
        if not message:
            return {"ok": False, "error": "Message is required"}
        payload = {
            "messages": [
                {"role": "system", "content": _QUICKER_AI_CHAT_SYSTEM},
                {"role": "user",   "content": message},
            ],
            "max_tokens": 600,
        }
        if model:
            payload["model"] = model
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                _QUICKER_AI_URL,
                headers={"Content-Type": "application/json", "X-Internal-Token": _QUICKER_AI_TOKEN},
                json=payload,
            )
        resp.raise_for_status()
        result  = resp.json()
        tokens  = result.get("tokens_used") or {}
        ai_text = result.get("content", "")
        model_name = result.get("model", "")
        month_total = _add_tokens(username, tokens) if username else tokens
        _log_chat_entry(username, message, ai_text, model_name, tokens)
        return {
            "ok": True,
            "response": ai_text,
            "model": model_name,
            "tokens": tokens,
            "month_total": month_total,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# === Profile Management ===
def _default_dashboard_profile():
    return {
        "categories": [{"id": "misc", "name": "Miscellaneous", "color": "#2d5aa0"}],
        "assignments": {},
        "order": [],
        "columns": 3,
    }


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


def _user_dir(username: str) -> str:
    d = os.path.join(_user_profiles_dir(), username)
    os.makedirs(d, exist_ok=True)
    return d


def _user_profile_path(username: str) -> str:
    return os.path.join(_user_dir(username), f"{username}.json")


def _user_chat_logs_dir(username: str) -> str:
    d = os.path.join(_user_dir(username), "quicker_chat_logs")
    os.makedirs(d, exist_ok=True)
    return d


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
    new_path = _user_profile_path(username)
    if os.path.exists(new_path):
        with open(new_path) as f:
            return json.load(f)
    # Migrate from legacy flat structure: user_profiles/<username>.json
    legacy_path = os.path.join(_user_profiles_dir(), f"{username}.json")
    if os.path.exists(legacy_path):
        with open(legacy_path) as f:
            data = json.load(f)
        _save_user(data)          # writes to new folder path
        os.remove(legacy_path)    # remove the old flat file
        return data
    return None


def _save_user(profile: dict):
    path = _user_profile_path(profile["username"])
    with open(path, "w") as f:
        json.dump(profile, f, indent=2)


def _log_chat_entry(username: str, user_msg: str, ai_response: str, model: str, tokens: dict):
    """Append a Q&A exchange to the user's daily Quicker AI chat log."""
    if not username:
        return
    try:
        today    = datetime.now().strftime("%Y-%m-%d")
        now_time = datetime.now().strftime("%I:%M %p")
        log_dir  = _user_chat_logs_dir(username)
        log_file = os.path.join(log_dir, f"{today}.md")
        daily_tokens_file = os.path.join(log_dir, "_daily_tokens.json")

        # Accumulate daily token counts
        daily = {}
        if os.path.exists(daily_tokens_file):
            with open(daily_tokens_file) as f:
                daily = json.load(f)
        day = daily.setdefault(today, {"total": 0, "input": 0, "output": 0})
        day["total"]  += tokens.get("total", 0)
        day["input"]  += tokens.get("input", 0)
        day["output"] += tokens.get("output", 0)
        with open(daily_tokens_file, "w") as f:
            json.dump(daily, f, indent=2)

        # Preserve existing conversation entries (everything after the header block)
        existing = ""
        if os.path.exists(log_file):
            with open(log_file) as f:
                content = f.read()
            # Split on first "---" separator to skip the regenerated header
            parts = content.split("---\n", 1)
            if len(parts) > 1:
                existing = "---\n" + parts[1]

        # Build refreshed header
        header = (
            f"# Quicker AI — {today}\n\n"
            f"**Total tokens today:** {day['total']:,}  "
            f"({day['input']:,} in / {day['output']:,} out)\n\n"
        )

        # Build new entry
        entry = (
            f"---\n\n"
            f"**{now_time}** | {model}\n\n"
            f"**You:** {user_msg}\n\n"
            f"**Quicker AI:** {ai_response}\n\n"
        )

        with open(log_file, "w") as f:
            f.write(header + existing + entry)
    except Exception:
        pass


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


@app.post(f"{BASE_PREFIX}/api/users/{{username}}/change-password")
async def api_change_password(username: str, request: Request):
    try:
        data = await request.json()
        current_password = data.get("current_password") or ""
        new_password = data.get("new_password") or ""
        if len(new_password) < 4:
            return {"ok": False, "error": "Password must be at least 4 characters."}
        profile = _load_user(username.lower())
        if not profile:
            return {"ok": False, "error": "User not found."}
        if not _verify_password(current_password, profile["password"]):
            return {"ok": False, "error": "Current password is incorrect."}
        profile["password"] = _hash_password(new_password)
        _save_user(profile)
        return {"ok": True}
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
        for entry in os.scandir(d):
            if entry.is_dir():
                profile = os.path.join(entry.path, f"{entry.name}.json")
                if os.path.exists(profile):
                    users.append(entry.name)
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
    uvicorn.run("console:app", host="0.0.0.0", port=port)
