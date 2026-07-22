# Hello Circuit - Cisco Circuit AI Integration Setup

## Overview
The Hello Circuit tool integrates with [Cisco Circuit](https://circuit.cisco.com) to provide AI-powered network learning questions directly from Cisco's AI platform.

## Prerequisites
- Active Cisco Circuit account (circuit.cisco.com)
- Python 3.7 or higher
- Flask application running

## Installation Steps

### 1. Install Required Dependencies
```bash
# Navigate to your AppTech directory
cd "/Users/jokirkpa/Projects/Idea Factory/AppTech"

# Install Python packages
pip install -r requirements.txt

# Install Playwright browsers (required for web automation)
playwright install chromium
```

### 2. Verify Installation
```bash
# Check if Playwright is installed correctly
python3 -c "from playwright.sync_api import sync_playwright; print('Playwright installed successfully!')"
```

### 3. Start the Flask Server
```bash
python3 app.py
```

The server will start on `http://0.0.0.0:5002`

## Using Hello Circuit

1. **Open AppTech Dashboard** in your browser: `http://localhost:5002`

2. **Click on "Hello Circuit"** tool card (blue gradient with robot icon 🤖)

3. **Enter Circuit Credentials**:
   - Circuit Username/Email: Your Cisco Circuit login
   - Circuit Password: Your Circuit password
   - **Optional**: Check "Save these credentials" to save for future use
     - Enter a descriptive name (e.g., "Work Account", "Personal")
     - Credentials are saved locally and encrypted with basic encoding
     - Select from saved credentials dropdown in future sessions
     - Delete saved credentials using the 🗑️ Delete button
   - ⚠️ Saved credentials are stored locally in `circuit_credentials.json` (excluded from git)

4. **Configure Question Settings**:
   - **Technology/Topic**: Choose from routing, switching, ACI, datacenter, security, etc.
   - **Difficulty**: Beginner, Intermediate, Advanced, or Mixed
   - **Frequency**: How often to generate new questions (5 min, 10 min, 30 min, hourly, or manual)

5. **Start Questions**: Click "Start Questions" to begin
   - First question will be requested immediately
   - Subsequent questions will appear based on your frequency setting
   - Use "Get Question Now" for on-demand questions

6. **View Answers**: Click "Reveal Answer" to see the AI's response

7. **View Logs**: Click "📋 View Logs" to access your question history
   - Logs are organized by date (one file per day)
   - Click any log file to view all questions and answers from that day
   - Logs include timestamp, technology, difficulty, question, and answer
   - Logs are saved locally in the `circuit_logs/` directory

## How It Works

1. **Backend Automation**: The Flask server uses Playwright to:
   - Navigate to circuit.cisco.com
   - Authenticate with your credentials
   - Submit questions to Circuit's AI search
   - Extract and return the AI's response

2. **Topic-Based Prompts**: Generated questions are tailored to your selected technology area and difficulty level

3. **Scheduled Learning**: Questions can be automatically generated at your chosen frequency to maintain consistent learning

4. **Daily Logging**: All questions and answers are automatically saved to daily log files
   - Each day gets its own log file (e.g., `circuit_log_2026-04-09.json`)
   - Logs include full question/answer history with timestamps
   - Browse and review past questions through the log viewer
   - Logs stored in `circuit_logs/` directory (excluded from git)

## Troubleshooting

### Error: "Playwright not installed"
- Run: `pip install playwright && playwright install chromium`

### Error: "Could not find search/AI input field"
- Circuit's UI may have changed
- The backend may need selector updates (see `app.py`, line ~260)

### Error: Login Failed
- Verify your Circuit credentials
- Check if Circuit requires 2FA (currently not supported)
- Try logging in manually at circuit.cisco.com first

### Slow Response Times
- Circuit AI responses may take 5-10 seconds
- Network latency can affect performance
- Headless browser automation adds overhead

## Security Notes

- ⚠️ Your Circuit credentials are sent to the Flask backend for authentication
- **Saved Credentials**: 
  - Stored locally in `circuit_credentials.json` (excluded from git)
  - Passwords are encoded with base64 (basic protection, not encryption)
  - File should have restricted permissions (readable only by you)
  - Consider using OS-level encryption for the credentials file
  - Not recommended for highly sensitive environments
- Authentication uses headless browser (no visible window)
- Consider using environment variables for credentials if running in production

## Advanced Configuration

### Adjusting Timeouts
Edit `/app.py` at line ~260 to modify browser timeouts:
```python
page.goto('https://circuit.cisco.com/app/home', timeout=60000)  # 60 seconds
```

### Updating UI Selectors
If Circuit's interface changes, update selectors in `/app.py`:
```python
search_selectors = [
    'input[placeholder*="search" i]',
    'textarea[placeholder*="ask" i]',
    # Add new selectors here
]
```

### Running in Visible Mode (for debugging)
Change `headless=True` to `headless=False` in `/app.py` line ~247:
```python
browser = p.chromium.launch(headless=False)  # Shows browser window
```

### Managing Log Files
Log files are stored in `circuit_logs/` directory:
- **View logs**: Use the "View Logs" button in the Hello Circuit modal
- **Location**: `circuit_logs/circuit_log_YYYY-MM-DD.json`
- **Format**: JSON with entries array containing timestamp, technology, difficulty, question, and answer
- **Cleanup**: Manually delete old log files if needed (they are excluded from git)
- **Backup**: Copy files from `circuit_logs/` directory to preserve history

Example log structure:
```json
{
  "date": "2026-04-09",
  "entries": [
    {
      "timestamp": "2026-04-09 14:30:00",
      "technology": "routing",
      "difficulty": "intermediate",
      "question": "What is the difference between...",
      "answer": "OSPF uses different LSA types...",
      "success": true
    }
  ]
}
```

## Future Enhancements

- [ ] Add support for Circuit 2FA/MFA
- [ ] Cache session cookies to avoid repeated logins
- [ ] Add more specific question types
- [ ] Export question/answer history to CSV/PDF
- [ ] Integration with study progress tracking
- [ ] Search functionality within logs
- [ ] Statistics dashboard (questions per day, topics covered, etc.)
- [ ] Log export/import for backup/sharing
- [ ] Filter logs by technology or difficulty

## Support

For issues related to:
- **Circuit Platform**: Contact Cisco Support
- **AppTech Tool**: Check repository issues or open a new issue
- **Playwright**: Visit https://playwright.dev/python/docs/intro

---

**Note**: This tool is for educational purposes. Ensure compliance with Cisco's Terms of Service when using automated access to Circuit.
