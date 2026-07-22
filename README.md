# AppTech - Network Engineering Tools

A collection of useful network engineering utilities in a web-based dashboard.

## Features

### 🚀 Current Tools

1. **Port Speed Calculator** - Convert between different network speed units (bps, Kbps, Mbps, Gbps, Tbps)
2. **Subnet Calculator** - Calculate subnet details including network address, broadcast, and usable IP range
3. **Diff Check** - Compare two text blocks and highlight differences line-by-line
4. **Coming Soon** - More tools will be added

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the application:
```bash
python app.py
```

3. Open your browser to:
```
http://localhost:5002
```

## Usage

- Click on any tool card to open its modal
- Fill in the required information
- Click the calculate/compare button
- View results in the same modal
- Press ESC or click outside the modal to close

## Tech Stack

- **Backend**: Flask (Python)
- **Frontend**: Vanilla JavaScript, HTML5, CSS3
- **Port**: 5002 (different from Blockbuster which runs on 5001)

## Future Enhancements

- VLAN Calculator
- MAC Address Lookup
- BGP Path Analysis
- Configuration Diff Tool
- And more...
