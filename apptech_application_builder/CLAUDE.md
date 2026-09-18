# AppTech Application Builder — guide for Claude

This project is a **local, offline, visual-only preview of the AppTech dashboard**
(apptech.cisco.com) — no login screen, no `/tools` page, no accounts. The user runs it
to build a *tool* — a single self-contained `.html` file — with your help, sees it
rendered exactly as it will look on the live site, and then uploads that same file to
apptech.cisco.com.

Your job: **build compliant tool files in `applications/`.** A tool that follows the
contract below will render correctly in the local preview AND drop straight into the
live site with zero changes.

`applications/test1.html`–`test4.html` are fixed placeholder "Test Project" cards that
ship with the builder so the dashboard grid isn't empty on first run. **Don't edit or
delete them** — build new tools as new files alongside them.

## The workflow

1. The user describes a tool idea.
2. You create/edit a single file `applications/<name>.html`.
3. The local server auto-detects the change; the preview at `http://localhost:5050`
   reloads it live (no restart, no manual refresh needed).
4. When it works, the user uploads that file on the live site: **Download Tools →
   Upload Tool**.

If the server isn't running, tell the user to run `./start.sh` (macOS/Linux) or
`start.bat` (Windows), or `python3 server.py`. Requirements: **Python 3 only.** The
whole folder is portable — it works the same wherever it's copied to (Desktop, USB,
etc.) on Windows or Mac.

## The tool contract (follow exactly)

A tool is ONE `.html` file with three parts: an optional `<style>`, the modal markup,
and an optional `<script>`. It must satisfy all of the following:

1. **First line is the discovery marker** (this is how the site finds the tool):
   ```html
   <!-- @tool {"id":"myThingModal","name":"🔧 My Thing","description":"What it does","author":"username"} -->
   ```
   - `id` must be unique and end in `Modal` by convention.
   - `name` may start with an emoji — the dashboard uses it as the card icon.
   - Valid JSON, all on the first line.

2. **Root element uses the shared modal classes, and its `id` equals the marker `id`:**
   ```html
   <div id="myThingModal" class="modal-overlay">
     <div class="modal" onclick="event.stopPropagation()">
       <div class="modal-header">
         <h2>🔧 My Thing</h2>
         <button class="close-btn" onclick="closeModal('myThingModal')">&times;</button>
       </div>
       <div class="modal-body">
         <!-- your tool UI here -->
       </div>
     </div>
   </div>
   ```

3. **Use the shared classes the dashboard provides — do NOT redefine them:**
   | Class | Purpose |
   |-------|---------|
   | `.modal-overlay` / `.modal` | tool root + card (required, as above) |
   | `.modal-header` / `.close-btn` / `.modal-body` | header + body (required) |
   | `.form-group` (wraps `label` + `input`/`select`/`textarea`) | form fields |
   | `.btn` | buttons |
   | `.result-box` / `.result-row` / `.result-label` / `.result-value` | result tables |
   | `.error-message` | red error banner |
   | `.tab-btn` (+`.active`) / `.tab-content` (+`.active`) | tabbed UIs |

4. **Shared JS the dashboard provides — you may call these:**
   - `openModal(id)` — open a tool (rarely needed inside a tool).
   - `closeModal(id)` — close it (wire this to the `.close-btn`).
   - `window._toolOnOpen[id] = function(){ … }` — optional hook run **every time** the
     tool opens; use it to reset/init state. Register it like:
     ```js
     window._toolOnOpen = window._toolOnOpen || {};
     window._toolOnOpen['myThingModal'] = function () { /* init */ };
     ```

## Rules

- **Self-contained.** No external files, no CDNs, no `<link>`/`<img src=http…>`, no
  build step. Everything (HTML + CSS + JS) lives in the one file. It must work offline.
- **Namespace everything.** Multiple tools load into the same page. Prefix your
  element IDs, CSS classes, and JS function names (e.g. `ex…`, `myThing…`) so they
  never collide with another tool or with the shared classes above.
- **Marker `id` == `modal-overlay` `id`.** They must match or the tool won't open.
- **One file per tool**, named `applications/<something>.html`.
- **Don't** add a login, settings, navigation, or a full `<html>`/`<body>` document —
  a tool is just the marker + `<style>` + the `modal-overlay` div + `<script>`.
- Put tool-specific CSS in the tool's own `<style>`; put logic in its own `<script>`.

## Reference

- `applications/example_tool.html` — a complete, working template. Copy it as a
  starting point for a new tool.
- The preview loads a tool by fetching its file, injecting its `<style>`/`<script>`,
  and moving its `.modal` into the active panel — the same mechanism the live site
  uses. So if it works in the preview, it works on the site.
