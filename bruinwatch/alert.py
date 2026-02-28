"""
bruinwatch.alert — Terminal alerts, system sounds, and color-coded output.

Uses **colorama** so ANSI codes work correctly on every platform, including
older Windows terminals.
"""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path
from typing import Any

from colorama import Fore, Style, init as colorama_init

# Initialise colorama once on import (autoreset keeps each print independent).
colorama_init(autoreset=True)

try:
    from plyer import notification as _desktop_notify
except ImportError:
    _desktop_notify = None

_SOUND_PATH = Path(__file__).resolve().parent / "sounds" / "sparkle.mp3"


# ─── System sound ────────────────────────────────────────────────────────────

def _play_sound() -> None:
    """Play the bundled notification sound."""
    try:
        system = platform.system()
        if system == "Windows":
            # WPF MediaPlayer supports MP3 natively
            ps = (
                'Add-Type -AssemblyName presentationCore; '
                '$p = New-Object System.Windows.Media.MediaPlayer; '
                f'$p.Open("{_SOUND_PATH}"); '
                '$p.Play(); '
                'Start-Sleep -Seconds 3; '
                '$p.Close()'
            )
            subprocess.Popen(
                ["powershell", "-WindowStyle", "Hidden", "-Command", ps],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        elif system == "Darwin":
            subprocess.Popen(
                ["afplay", str(_SOUND_PATH)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        elif system == "Linux":
            subprocess.Popen(
                ["mpg123", "-q", str(_SOUND_PATH)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            print("\a")
    except Exception:
        print("\a")


# ─── Desktop notification ───────────────────────────────────────────────────

def _desktop_notification(title: str, message: str) -> None:
    if _desktop_notify is None:
        return
    try:
        _desktop_notify.notify(
            title=title,
            message=message,
            app_name="BruinWatch",
            timeout=10,
        )
    except Exception:
        pass


# ─── Public API ──────────────────────────────────────────────────────────────

def trigger_alert(course_name: str, seats_remaining: int, section_info: str) -> None:
    """Fire a desktop notification + system sound for an open seat."""
    _desktop_notification(
        title="BruinWatch — Seat Available!",
        message=f"{course_name}\n{section_info}: {seats_remaining} spot(s) open",
    )
    _play_sound()


def _format_row(
    label: str,
    status: str,
    enrolled_str: str,
    spots: int,
    wl_str: str,
    *,
    color: str,
) -> str:
    """Return a single color-coded table row."""
    line = (
        f"  {label:<18} {status:<10} {enrolled_str:<14} "
        f"{str(spots):<12} {wl_str:<12}"
    )
    return f"{color}{line}{Style.RESET_ALL}"


def print_status_table(
    courses_data: list[dict[str, Any]],
    *,
    show_discussions: bool = True,
) -> None:
    """Print a color-coded status table for a list of course result dicts.

    Each item in *courses_data* must have keys:
        ``subject``, ``course_number``, ``course_title``, ``sections``
    where ``sections`` is the list returned by ``api.get_course_summary``.
    """
    for course in courses_data:
        label = f"{course['subject']} {course['course_number']}"
        print(f"\n  {'─' * 68}")
        print(f"  {label} — {course['course_title']}")
        print(f"  {'─' * 68}")
        print(
            f"  {'Section':<18} {'Status':<10} {'Enrolled':<14} "
            f"{'Spots Left':<12} {'Waitlist':<12}"
        )
        print(f"  {'─' * 68}")

        for lec in course["sections"]:
            enrolled_str = f"{lec['enrolled']}/{lec['capacity']}"
            wl = (
                f"{lec['waitlist_taken']}/{lec['waitlist_capacity']}"
                if lec["waitlist_capacity"] > 0 else "N/A"
            )
            color = Fore.GREEN if lec["spots_left"] > 0 else Fore.RED
            print(_format_row(
                lec["section_label"], lec["status"],
                enrolled_str, lec["spots_left"], wl, color=color,
            ))

            if show_discussions:
                for dis in lec.get("discussions", []):
                    d_enrolled = f"{dis['enrolled']}/{dis['capacity']}"
                    d_wl = (
                        f"{dis['waitlist_taken']}/{dis['waitlist_capacity']}"
                        if dis["waitlist_capacity"] > 0 else "N/A"
                    )
                    d_color = Fore.GREEN if dis["spots_left"] > 0 else Fore.RED
                    print(_format_row(
                        "  " + dis["section_label"], dis["status"],
                        d_enrolled, dis["spots_left"], d_wl, color=d_color,
                    ))
