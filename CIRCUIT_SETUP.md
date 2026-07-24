# Circuit AI Integration Setup

## Overview

The Circuit AI tool integrates with [Cisco Circuit](https://circuit.cisco.com) to provide AI-powered network learning questions directly from Cisco's AI platform. It runs as part of the AppTech dev server at **apptech.cisco.com**.

## Prerequisites

- Active Cisco Circuit account (circuit.cisco.com)
- Playwright installed on the server: `pip install playwright && playwright install chromium`

## How It Works

The backend uses Playwright to automate a headless Chromium browser that:
1. Navigates to circuit.cisco.com
2. Authenticates with your saved credentials
3. Submits questions to Circuit's AI search
4. Extracts and returns the AI response

## Using Circuit AI

### 1. Save Credentials

Open **User Settings** (⚙️) → **Credentials** and save your Circuit login. Credentials are stored in `circuit_credentials.json` on the server (excluded from git). Passwords are base64-encoded — avoid storing credentials you use elsewhere.

### 2. Configure and Start

In the Circuit AI panel inside the dashboard:
- Select **Technology/Topic** (routing, switching, ACI, datacenter, security, etc.)
- Select **Difficulty** (Beginner, Intermediate, Advanced, Mixed)
- Set **Frequency** (5 min, 10 min, 30 min, hourly, or manual)
- Click **Start Questions**

### 3. View Responses

- Click **Reveal Answer** to see the AI's response
- Click **View Logs** to browse question history organised by date

## Logs

Question/answer history is saved to `circuit_logs/` on the server:
- One file per day: `circuit_log_YYYY-MM-DD.json`
- Includes timestamp, technology, difficulty, question, and answer
- Excluded from git; delete old files manually if needed

## Troubleshooting

**"Playwright not installed"** — Run `pip install playwright && playwright install chromium` on the server.

**"Could not find search/AI input field"** — Circuit's UI may have changed; update selectors in `app.py` around the `circuit_question_job` function.

**Login failed** — Verify credentials in User Settings. Circuit 2FA is not currently supported.

**Slow responses** — Circuit AI responses typically take 5–10 seconds; headless browser automation adds overhead.

## Advanced Configuration

**Adjust browser timeouts** — Edit `app.py` in `_circuit_question_job`:
```python
page.goto('https://circuit.cisco.com/app/home', timeout=60000)  # 60 seconds
```

**Update UI selectors** — If Circuit's interface changes, update selectors in `app.py`:
```python
search_selectors = [
    'input[placeholder*="search" i]',
    'textarea[placeholder*="ask" i]',
]
```

## Security Notes

- Circuit credentials are sent to the backend for Playwright-based authentication
- Credentials are stored in `circuit_credentials.json` with base64 encoding (not true encryption)
- Not recommended for highly sensitive accounts
