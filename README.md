# BruinWatch

**Real-time UCLA course seat availability monitor.**

BruinWatch is a lightweight Python terminal app that monitors the [UCLA Schedule of Classes](https://sa.ucla.edu/ro/Public/SOC) for open seats in your target courses. It polls the registrar's live enrollment data every 3 minutes, color-codes availability at a glance (green = open, red = full), and fires off desktop notifications + system sounds the moment a spot opens up.

## Features

- **Multi-course watchlist** — monitor as many courses as you want in a single session
- **Lectures + discussions** — automatically fetches discussion/lab sections under each lecture
- **Color-coded output** — green rows for sections with open seats, red for full/closed
- **Desktop notifications** — push alerts via `plyer` (Windows, macOS, Linux)
- **System sound alerts** — audible beep when a seat opens
- **Auto-retry** — resilient to transient network errors with configurable retry logic
- **Zero config** — no API keys, no tokens, no login required

## Quick Start

```bash
# Clone the repo
git clone https://github.com/<your-username>/BruinWatch.git
cd BruinWatch

# (Optional) Create a virtual environment
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # macOS / Linux

# Install dependencies
pip install -r requirements.txt

# Run
python bruinwatch.py
```

You'll be prompted to select a term, enter a subject area (e.g. `COM SCI`) and course number (e.g. `32`), and optionally add more courses. BruinWatch then polls every 3 minutes and alerts you when seats open.

## Example Output

```
══════════════════════════════════════════════════════════════════════════
  [2026-02-26 14:30:00]  Polling 1 course(s)...
══════════════════════════════════════════════════════════════════════════

  ────────────────────────────────────────────────────────────────────────
  COM SCI 32 — 32 - Introduction to Computer Science II
  ────────────────────────────────────────────────────────────────────────
  Section          Status     Enrolled       Spots Left   Waitlist
  ────────────────────────────────────────────────────────────────
  Lec 1            Open       63/180         117          0/30          ← green
    Dis 1A         Open       52/60          8            0/10          ← green
    Dis 1B         Open       7/60           53           0/10          ← green
    Dis 1C         Open       4/60           56           0/10          ← green
    Dis 1D         Closed     0/0            0            N/A           ← red
```

## Requirements

- Python 3.10+
- `requests` — HTTP client
- `plyer` (optional) — cross-platform desktop notifications

## How It Works

BruinWatch reverse-engineers UCLA's public Schedule of Classes API:

1. **`CourseTitlesView`** — resolves a subject + catalog number into internal course tokens
2. **`GetCourseSummary`** (root) — fetches lecture-level enrollment data
3. **`GetCourseSummary`** (sub-level) — fetches discussion/lab sections under each lecture

No authentication is needed; it uses the same public endpoints as the SOC website.

## Configuration

| Constant        | Default | Description                        |
|-----------------|---------|------------------------------------|
| `POLL_INTERVAL` | `180`   | Seconds between poll cycles        |
| `RETRY_DELAY`   | `10`    | Seconds between retries on failure |
| `MAX_RETRIES`   | `3`     | Max retries per poll cycle         |

Edit these at the top of `bruinwatch.py`.

## License

MIT
