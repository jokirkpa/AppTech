# AppTech Application Builder

A tiny, offline, **visual-only** mirror of the [apptech.cisco.com](https://apptech.cisco.com)
dashboard.

Use it to **build your own AppTech tool locally** — with Claude, in VS Code — and see it
rendered exactly as it will appear on the live site. When it's ready, upload the single
HTML file you made and it becomes a shared tool for everyone.

There's no login screen, no `/tools` page, no settings, and no accounts here — just the
dashboard grid and the tool you're building. It's a preview, not a functional copy of
the site.

---

## Portable — run it from anywhere

This whole folder is self-contained (Python 3 stdlib only, no installs). Copy
`apptech_application_builder/` to your Desktop — Windows or Mac — or anywhere else, and
it runs the same way from there.

## Requirements

- **Python 3** — that's it. No `pip install`, no Node, no other dependencies.
- A browser.
- (Recommended) **VS Code** with **Claude** to build tools by describing what you want.

---

## Run it

**macOS / Linux**
```bash
./start.sh
```

**Windows**
```bat
start.bat
```

**Or directly, anywhere**
```bash
python3 server.py
```

Then open **http://localhost:5050**. You'll see the dashboard populated with 5 cards:
**Test Project 1–4** (fixed placeholders that ship with the builder, just so the grid
isn't empty — they're not meant to be edited) and the **Example Tool** — click any card
to open it in the panel, just like the real site.

---

## Build a tool (the workflow)

1. **Open this folder in VS Code.** Claude reads `CLAUDE.md`, so it already knows the
   exact tool format AppTech expects.
2. **Describe your idea to Claude** — e.g. *"build a tool that converts a subnet mask to
   CIDR."* Claude creates a new file in **`applications/`**, alongside the 4 fixed test
   projects — it won't touch those, they're just there for visual reference.
3. **Watch it appear.** The preview at http://localhost:5050 auto-detects new and changed
   files — a new card shows up, and edits to an open tool reload live (no refresh needed).
4. **Iterate** with Claude until it looks and works right.
5. **Publish.** On apptech.cisco.com go to **Download Tools → Upload Tool** and select
   your `applications/<your_tool>.html` file. No edits required — the local file is
   already in the exact format the site expects.

The quickest start: copy `applications/example_tool.html`, rename it, and change the
first-line marker + the modal `id` to match. See `CLAUDE.md` for the full contract.

---

## What a tool is

A tool is a **single self-contained `.html` file** in `applications/`. Its first line is a
marker the dashboard uses to discover it:

```html
<!-- @tool {"id":"myThingModal","name":"🔧 My Thing","description":"What it does","author":"you"} -->
```

…followed by the tool's markup (a `<div class="modal-overlay">…`), an optional `<style>`,
and an optional `<script>`. The dashboard supplies the shared styling (buttons, forms,
tabs, modals) and the `openModal` / `closeModal` helpers — your file just uses them.

Full details and rules: **[`CLAUDE.md`](./CLAUDE.md)**.

---

## Files

| Path | What it is |
|------|------------|
| `server.py` | Zero-dependency local web server (Python stdlib). |
| `dashboard.html` | The dashboard **preview** — mirrors the live site's look & behavior. |
| `applications/` | Your tool files live here. **1:1 compatible with the live site's `applications/`.** |
| `applications/example_tool.html` | A working starter tool — copy it to begin. |
| `applications/test1.html`…`test4.html` | Fixed placeholder "Test Project" cards — ship as-is, not meant to be edited. |
| `CLAUDE.md` | The tool contract, written for Claude (and you). |

---

## Notes

- The preview uses the **same tool-discovery rule** as the live site, so if a tool shows
  up here, the site will find it too.
- Nothing leaves your machine — the server is local and read-only over your files.
- To use a different port, edit `PORT` near the top of `server.py`.

---

## How it works

This is a from-scratch, minimal re-implementation of the two things the live site does
that matter for building a tool: **discovering tools** and **loading one into a panel**.
Everything else about the real dashboard — login, the `/tools` redirect, settings, other
users' tools, Circuit AI — is intentionally left out. There's no route for any of that
in `server.py`, by design: this is a visual preview, not a functional clone.

### `server.py` — zero-dependency backend

A single-file server built on Python's stdlib `http.server`. It exposes three things:

| Route | Behavior |
|-------|----------|
| `GET /` | Serves `dashboard.html`. |
| `GET /api/tools/list` | Scans `applications/*.html`, reads just the **first line** of each file, and matches it against `<!-- @tool {...} -->` — the exact regex `console.py`'s `api_tools_list` uses on the live site. Returns the parsed JSON metadata (`id`, `name`, `description`, `author`) plus the filename. A malformed tool is skipped, not fatal. |
| `GET /api/changed` | Returns the newest mtime (in ms) across every file in `applications/`. The dashboard polls this every 1.5s to detect edits — that's the entire "live reload" mechanism, no websockets or file-watching needed. |
| `GET /<anything else>` | Serves that path as a static file relative to the project folder (used for `applications/<tool>.html` itself), with a path-traversal check so nothing outside the folder is servable. |

No pip installs, no build step — this is why `start.sh` / `start.bat` can just call
`python3 server.py` directly.

### `dashboard.html` — the tool-panel engine

This is a trimmed copy of the live dashboard's shared CSS (`.modal`, `.btn`,
`.form-group`, `.tab-btn`, etc. — see `CLAUDE.md` for the full contract) plus a small
JS engine that reproduces exactly how the live site loads a tool:

1. **`renderCards()`** hits `/api/tools/list` and draws one card per tool in the sidebar.
2. **Clicking a card** calls `loadAndOpenTool(file, id)`, which `fetch`es the tool's raw
   `.html` and parses it with `DOMParser` (not `innerHTML` — a template literal in a
   tool's `<script>` containing something like `</div>` would truncate `innerHTML`
   parsing early, but `DOMParser` handles it correctly).
3. The parsed document's `<style>` and `<script>` tags are pulled out and appended to
   the real page's `<head>` (scripts don't execute automatically when parsed this way,
   so they're recreated as new `<script>` elements to force execution). What's left —
   the `.modal-overlay` div — is dropped into a hidden holding container.
4. **`openModal(id)`** moves that tool's `.modal` into the visible `activeToolPanel` and
   fires the tool's registered `window._toolOnOpen[id]` hook, if any. `closeModal(id)`
   moves it back out. These two functions plus the `_toolOnOpen` registry are the entire
   contract a tool file can rely on — matching what the live site provides.
5. **Live reload**: `pollChanges()` polls `/api/changed` every 1.5s. When the mtime
   changes, it purges the currently-loaded tool (removes its injected `<style>`/
   `<script>`/DOM node) and reloads it fresh via step 2–4 — so edits show up without a
   manual refresh, and without ever restarting the Python process.

Because steps 2–4 are the *same* fetch-parse-inject mechanism the live site uses to open
a tool, a `.html` file that opens correctly here needs zero changes to work on
apptech.cisco.com — that's the guarantee this whole preview exists to provide.

### Everything else

- `applications/example_tool.html` is the annotated reference for the tool contract
  itself (marker format, required structure, shared classes, namespacing rules) — see
  `CLAUDE.md` for the full written-out contract Claude follows when building a tool here.
- There is no build step, bundler, or dependency graph anywhere in this folder — by
  design, since the goal is for this whole directory to be relocatable as a standalone
  download later, independent of the rest of this repo.
