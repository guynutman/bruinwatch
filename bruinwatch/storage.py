"""
bruinwatch.storage — Persist the watched-course list to a JSON file.

The watchlist is stored at ``<project_root>/watchlist.json``.  Each entry
is a dict with keys:

    subject, course_number, course_title, term_cd, course_data
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# Store watchlist.json next to the installed package (i.e. the repo root).
# When installed with ``pip install -e .`` the package lives inside the repo,
# so ``__file__`` resolves inside bruinwatch/.  Go up one level to reach the
# repo root.
_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "watchlist.json"


def _watchlist_path() -> Path:
    """Return the path to the watchlist file, respecting an env-var override."""
    override = os.environ.get("BRUINWATCH_WATCHLIST")
    if override:
        return Path(override)
    return _DEFAULT_PATH


# ─── Read / Write ────────────────────────────────────────────────────────────

def load_watchlist() -> list[dict[str, Any]]:
    """Load and return the watchlist.  Returns ``[]`` if the file is missing."""
    p = _watchlist_path()
    if not p.exists():
        return []
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        return []
    return data


def save_watchlist(courses: list[dict[str, Any]]) -> None:
    """Write *courses* to the watchlist file."""
    p = _watchlist_path()
    with p.open("w", encoding="utf-8") as f:
        json.dump(courses, f, indent=2, ensure_ascii=False)


# ─── Mutations ───────────────────────────────────────────────────────────────

def _course_key(entry: dict[str, Any]) -> tuple[str, str, str]:
    """Unique identity of a watchlist entry (subject, number, term)."""
    return (
        entry["subject"].upper(),
        entry["course_number"].upper(),
        entry["term_cd"],
    )


def add_course(
    subject: str,
    course_number: str,
    course_title: str,
    term_cd: str,
    course_data: dict[str, Any],
) -> bool:
    """Add a course to the watchlist.  Returns *False* if already present."""
    courses = load_watchlist()
    new_key = (subject.upper(), course_number.upper(), term_cd)
    for existing in courses:
        if _course_key(existing) == new_key:
            return False  # duplicate
    courses.append({
        "subject": subject,
        "course_number": course_number,
        "course_title": course_title,
        "term_cd": term_cd,
        "course_data": course_data,
    })
    save_watchlist(courses)
    return True


def remove_course(subject: str, course_number: str, term_cd: str) -> bool:
    """Remove a course from the watchlist.  Returns *False* if not found."""
    courses = load_watchlist()
    key = (subject.upper(), course_number.upper(), term_cd)
    before = len(courses)
    courses = [c for c in courses if _course_key(c) != key]
    if len(courses) == before:
        return False
    save_watchlist(courses)
    return True


# ─── Settings ────────────────────────────────────────────────────────────────

_SETTINGS_PATH = Path(__file__).resolve().parent.parent / "settings.json"


def load_settings() -> dict[str, Any]:
    """Load settings.  Returns defaults if the file is missing."""
    defaults: dict[str, Any] = {"notifications": True, "discuss_alerts": True}
    if not _SETTINGS_PATH.exists():
        return defaults
    try:
        with _SETTINGS_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {**defaults, **data}
    except Exception:
        pass
    return defaults


def save_settings(settings: dict[str, Any]) -> None:
    """Write *settings* to the settings file."""
    with _SETTINGS_PATH.open("w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
