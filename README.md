# AppTech

A shared network engineering tool dashboard hosted at **apptech.cisco.com**.

---

## Overview

AppTech is a web-based platform where network engineers can open, use, and share tools — all running in the browser without any local installation. Tools are self-contained HTML files that load on demand inside the dashboard.

---

## Getting Started

### Login

Navigate to `apptech.cisco.com`. You will land on the login page.

- **Sign in** with an existing username and password.
- **Create a new account** by clicking "Create one" and choosing a username (2–32 characters: letters, numbers, `_`, `-`) and a password (minimum 4 characters).

After logging in you are redirected to your personal dashboard at `apptech.cisco.com/<username>`.

---

## User Dashboard

Your dashboard lives at `apptech.cisco.com/<username>`.

### Tool Grid

The left sidebar shows all available tools as cards. Click any card to open that tool in the panel on the right. Only one tool is active at a time — switching tools closes the current one and opens the new one.

Tools can be organised into **categories**. Each category has a colour swatch and appears as a tab in the bar at the top of the sidebar. The gear icon (⚙) in any open tool's header lets you assign it to a category.

### Available Tools

| Tool | Description |
|------|-------------|
| **Port Speed Calculator** | Convert network speed units and calculate Rx/Tx load percentages for switch ports |
| **Subnet Calculator** | Calculate subnet details and check for overlapping subnets |
| **TCPDUMP Builder** | Build tcpdump filter commands for General and ARP traffic |
| **Time/Date Calculator** | Timezone comparison, date arithmetic, and date-to-date difference |
| **Hex Converter** | Convert between hex, IPv4, IPv6, and MAC address formats |
| **Pretty Text** | Format and pretty-print JSON and XML |
| **Ping Graph** | Parse ping output and display latency over time |
| **Log Analyzer** | Search, filter, highlight, and find/replace within log output |
| **Diff Check** | Side-by-side line diff between two text blocks |
| **ACI Contract Trainer** | Build and visualise ACI zoning rule tables and contracts |
| **Column Sorter** | Sort and reorder delimited column data |

### Header Buttons

| Button | Action |
|--------|--------|
| **🌐 Download Tools** | Opens your personal Download Tools page in a new tab (`/<username>/tools`) |
| **⚙️ User Settings** | Opens the settings panel (profile, credentials, categories) |

### User Settings

- **Profile Management** — create additional profiles, log out, or navigate directly to your Download Tools page.
- **Credentials** — store named credentials (used by tools like Circuit AI).
- **Categories** — create, rename, colour, and delete tool categories; drag tools between categories in Sort mode.

---

## Download Tools

`apptech.cisco.com/<username>/tools`

This page lists all tools available for your profile and lets you contribute new ones.

### Upload a Tool

1. Click **↑ Upload Tool** in the top-right corner.
2. Fill in the **Tool Name** and **Description**.
3. Select an `.html` file — the file is previewed in the panel on the right so you can test it before submitting.
4. Click **+ Add to Download Tools** to submit.

Tools are self-contained HTML files. The author field is auto-populated from your logged-in username.

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend framework | FastAPI (Python) |
| ASGI server | uvicorn |
| Reverse proxy | nginx |
| Browser automation | Playwright (Circuit AI feature) |
| Frontend | Vanilla JS, HTML5, CSS3 |

### Process Model

Two uvicorn processes run behind nginx:

| Process | Port | Serves |
|---------|------|--------|
| Frontend | 7996 | Dashboard HTML, static files, application tools |
| Backend | 7997 | API routes (`/api/*`), `/docs`, `/openapi.json` |

nginx routes requests between them; the app itself runs at root `/`.

### Running Locally

```bash
pip install -r requirements.txt
playwright install chromium      # only needed for the Circuit AI feature

bash start.sh
```

The app will be available at `http://localhost:7996`.

### User Profiles

User accounts are stored as JSON files in `user_profiles/`. Passwords are hashed with PBKDF2-SHA256 (salted, 100,000 iterations). There is no session token or cookie — the username is stored in `localStorage` on the client and sent with API requests.

### API

FastAPI's interactive docs are available at `/docs` (served on port 7997).
