# BruinWatch

**Real-time UCLA course seat availability monitor.**

BruinWatch is a command-line tool that monitors the [UCLA Schedule of Classes](https://sa.ucla.edu/ro/Public/SOC) for open seats in your target courses. It polls live enrollment data, color-codes availability (green = open, red = full), and fires desktop notifications + system sounds the moment a spot opens up.

## Features

- **Five CLI commands** — `add`, `remove`, `list`, `status`, `run`
- **Multi-course watchlist** — persisted to `watchlist.json`
- **Lectures + discussions** — automatically fetches discussion/lab sections under each lecture
- **Color-coded output** — green for open, red for full (via `colorama`)
- **Desktop notifications** — push alerts via `plyer` (Windows, macOS, Linux)
- **System sound alerts** — audible beep when a seat opens
- **Countdown timer** — live countdown between poll cycles
- **Configurable interval** — `--interval` flag on `bruinwatch run`
- **Auto-retry** — resilient to transient network errors (3 retries with 10s delay)
- **No API key** — uses the same public endpoints as the SOC website

## Setup

```bash
# Clone the repo
git clone https://github.com/guynutman/BruinWatch.git
cd BruinWatch

# Create a virtual environment
python -m venv venv

# Activate it
# macOS / Linux:
source venv/bin/activate
# Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# Windows (CMD):
venv\Scripts\activate.bat

# Install dependencies
pip install -r requirements.txt

# Install bruinwatch as a CLI command (editable mode)
pip install -e .
```

After this, `bruinwatch` is available as a terminal command from anywhere inside the activated venv.

## Usage

### Add a course to your watchlist

```bash
bruinwatch add
```

Interactive prompt — you'll select a term, enter a subject area and course number. The course is validated against the UCLA API before being saved. Duplicates are rejected. You can add multiple courses in one session.

### Remove a course from your watchlist

```bash
bruinwatch remove
```

Shows a numbered list of your watched courses and lets you pick one to remove.

### List watched courses

```bash
bruinwatch list
```

```
  ────────────────────────────────────────────────────
  #    Subject        Number     Course Title
  ────────────────────────────────────────────────────
  1    COM SCI        33         33 - Introduction to Computer Organization
  2    MATH           31A        31A - Differential and Integral Calculus

  2 course(s) watched.
```

### Check status (single poll)

```bash
bruinwatch status
```

Polls every course once, prints a color-coded table, and exits.

### Monitor continuously

```bash
bruinwatch run
bruinwatch run --interval 120    # poll every 2 minutes
```

Polls all courses every 3 minutes (default) with a live countdown timer. Sends a desktop notification and plays a system sound when any seat opens.

## Example Output

```
════════════════════════════════════════════════════════════════════════
  [2026-02-27 14:30:00]  Polling 1 course(s)…
════════════════════════════════════════════════════════════════════════

  ────────────────────────────────────────────────────────────────────
  COM SCI 32 — 32 - Introduction to Computer Science II
  ────────────────────────────────────────────────────────────────────
  Section            Status     Enrolled       Spots Left   Waitlist
  ────────────────────────────────────────────────────────────────────
  Lec 1              Open       63/180         117          0/30          ← green
    Dis 1A           Open       52/60          8            0/10          ← green
    Dis 1B           Open       7/60           53           0/10          ← green
    Dis 1C           Open       4/60           56           0/10          ← green
    Dis 1D           Closed     0/0            0            N/A           ← red

  Next poll in 02:58 …
```

## Project Structure

```
BruinWatch/
├── bruinwatch/
│   ├── __init__.py      # Package version
│   ├── api.py           # UCLA API client
│   ├── storage.py       # Watchlist persistence (JSON)
│   ├── alert.py         # Color output, desktop notifications, sounds
│   ├── commands.py      # Logic for add, remove, list, status, run
│   └── cli.py           # Entry point, argparse routing
├── .gitignore
├── LICENSE
├── requirements.txt
├── pyproject.toml       # Makes bruinwatch installable as a CLI command
└── README.md
```

## Requirements

- Python 3.10+
- `requests` — HTTP client
- `colorama` — cross-platform colored terminal output
- `plyer` — cross-platform desktop notifications

## How It Works

BruinWatch uses UCLA's public Schedule of Classes endpoints:

1. **`CourseTitlesView`** — resolves a subject + catalog number into internal course tokens
2. **`GetCourseSummary`** (root level) — fetches lecture-level enrollment data
3. **`GetCourseSummary`** (sub-level) — fetches discussion/lab sections under each lecture

No authentication is needed; it uses the same public endpoints as the SOC website.

## Quick Start

```bash
python -m venv venv
source venv/bin/activate   # or .\venv\Scripts\Activate.ps1 on Windows
pip install -r requirements.txt
pip install -e .
bruinwatch add
bruinwatch list
bruinwatch status
bruinwatch run
```

## License

MIT
