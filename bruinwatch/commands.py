"""
bruinwatch.commands — Logic for each CLI command.

Each ``cmd_*`` function is the sole entry-point called by ``cli.py``.
All user-facing error handling lives here — API exceptions are caught and
printed as friendly messages rather than tracebacks.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from typing import Any

from colorama import Fore, Style

from bruinwatch.api import (
    APIError,
    CourseNotFoundError,
    create_session,
    fetch_available_terms,
    fetch_enrollment,
    get_course_summary,
)
from bruinwatch.storage import load_watchlist, add_course, remove_course
from bruinwatch.alert import print_status_table, trigger_alert


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _pick_term(session) -> tuple[str, str]:
    """Interactive term picker.  Returns ``(term_cd, term_name)``."""
    terms = fetch_available_terms(session)
    if not terms:
        print("Error: could not fetch available terms from UCLA SOC.")
        sys.exit(1)
    print("\nAvailable terms:")
    for i, t in enumerate(terms, 1):
        print(f"  [{i}] {t['name']}")
    while True:
        choice = input("\nSelect a term number [1]: ").strip() or "1"
        if choice.isdigit() and 1 <= int(choice) <= len(terms):
            idx = int(choice) - 1
            return terms[idx]["code"], terms[idx]["name"]
        print("Invalid selection. Try again.")


def _poll_watchlist(
    session, watchlist: list[dict[str, Any]], *, alert: bool = False,
) -> None:
    """Fetch enrollment for every course and print a status table.

    If *alert* is ``True``, fire desktop + audio alerts when seats are open.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'═' * 72}")
    print(f"  [{now}]  Polling {len(watchlist)} course(s)…")
    print(f"{'═' * 72}")

    results: list[dict[str, Any]] = []
    alerted = False

    for entry in watchlist:
        try:
            sections = get_course_summary(session, entry["course_data"])
        except APIError as exc:
            print(f"  {Fore.YELLOW}[!] {entry['subject']} {entry['course_number']}: {exc}{Style.RESET_ALL}")
            continue

        result = {
            "subject": entry["subject"],
            "course_number": entry["course_number"],
            "course_title": entry["course_title"],
            "sections": sections,
        }
        results.append(result)

        # Fire alert for the first open seat found (once per poll cycle)
        if alert and not alerted:
            for lec in sections:
                if lec["spots_left"] > 0:
                    trigger_alert(
                        f"{entry['subject']} {entry['course_number']} — {entry['course_title']}",
                        lec["spots_left"],
                        lec["section_label"],
                    )
                    alerted = True
                    break
                for dis in lec.get("discussions", []):
                    if dis["spots_left"] > 0:
                        trigger_alert(
                            f"{entry['subject']} {entry['course_number']} — {entry['course_title']}",
                            dis["spots_left"],
                            f"{lec['section_label']} > {dis['section_label']}",
                        )
                        alerted = True
                        break
                if alerted:
                    break

    if results:
        print_status_table(results)


# ─── Commands ────────────────────────────────────────────────────────────────

def cmd_add() -> None:
    """``bruinwatch add`` — interactive prompt to add a course."""
    print(f"\nConnecting to UCLA SOC…")
    session = create_session()

    # Let the user pick a term
    term_cd, term_name = _pick_term(session)
    print(f"→ Selected term: {term_name} ({term_cd})")

    added_courses: list[dict] = []

    while True:
        # Prompt for subject area
        while True:
            subject = input("\nEnter subject area (e.g. COM SCI, MATH, PHYSICS): ").strip().upper()
            if subject:
                break
            print("Subject area cannot be empty.")

        # Prompt for course number
        while True:
            course_number = input("Enter course number (e.g. 32, 131, M51A): ").strip().upper()
            if course_number:
                break
            print("Course number cannot be empty.")

        print(f"\nValidating {subject} {course_number} for {term_name}…")
        try:
            info = fetch_enrollment(session, term_cd, subject, course_number)
        except CourseNotFoundError:
            print(f"  {Fore.RED}✗ No course found for {subject} {course_number} in {term_name}.{Style.RESET_ALL}")
            print(f"    Check the subject area / number on: https://sa.ucla.edu/ro/Public/SOC")
            more = input("\nTry another course? (y/n) [n]: ").strip().lower()
            if more == "y":
                continue
            break
        except APIError as exc:
            print(f"  {Fore.RED}✗ API error: {exc}{Style.RESET_ALL}")
            more = input("\nTry another course? (y/n) [n]: ").strip().lower()
            if more == "y":
                continue
            break

        added = add_course(
            subject=subject,
            course_number=course_number,
            course_title=info["course_title"],
            term_cd=term_cd,
            course_data=info["course_data"],
        )
        if not added:
            print(f"  {Fore.YELLOW}⚠ {subject} {course_number} is already in your watchlist.{Style.RESET_ALL}")
        else:
            print(f"  {Fore.GREEN}✓ Added: {info['course_title']}{Style.RESET_ALL}")
            added_courses.append({
                "subject": subject,
                "course_number": course_number,
                "course_title": info["course_title"],
                "sections": info["sections"],
            })

        more = input("\nAdd another course? (y/n) [n]: ").strip().lower()
        if more != "y":
            break

    # Show a snapshot of all newly added courses at the end
    if added_courses:
        print_status_table(added_courses)


def cmd_list() -> None:
    """``bruinwatch list``"""
    watchlist = load_watchlist()
    if not watchlist:
        print("\nYour watchlist is empty.")
        print("  Add a course with:  bruinwatch add")
        return

    print(f"\n  {'─' * 52}")
    print(f"  {'#':<4} {'Subject':<14} {'Number':<10} {'Course Title':<28}")
    print(f"  {'─' * 52}")
    for i, entry in enumerate(watchlist, 1):
        print(
            f"  {i:<4} {entry['subject']:<14} {entry['course_number']:<10} "
            f"{entry['course_title']:<28}"
        )
    print(f"\n  {len(watchlist)} course(s) watched.")


def cmd_remove() -> None:
    """``bruinwatch remove`` — interactive prompt to remove a course."""
    watchlist = load_watchlist()
    if not watchlist:
        print("\nYour watchlist is empty. Nothing to remove.")
        return

    print(f"\n  {'─' * 52}")
    print(f"  {'#':<4} {'Subject':<14} {'Number':<10} {'Course Title':<28}")
    print(f"  {'─' * 52}")
    for i, entry in enumerate(watchlist, 1):
        print(
            f"  {i:<4} {entry['subject']:<14} {entry['course_number']:<10} "
            f"{entry['course_title']:<28}"
        )
    print()

    while True:
        choice = input("Enter the number of the course to remove (or 'q' to cancel): ").strip()
        if choice.lower() == "q":
            print("  Cancelled.")
            return
        if choice.isdigit() and 1 <= int(choice) <= len(watchlist):
            idx = int(choice) - 1
            entry = watchlist[idx]
            removed = remove_course(
                entry["subject"], entry["course_number"], entry["term_cd"],
            )
            if removed:
                print(f"  {Fore.GREEN}✓ Removed: {entry['subject']} {entry['course_number']} — {entry['course_title']}{Style.RESET_ALL}")
            else:
                print(f"  {Fore.RED}✗ Could not remove course.{Style.RESET_ALL}")
            return
        print(f"  Invalid selection. Enter a number between 1 and {len(watchlist)}.")


def cmd_status() -> None:
    """``bruinwatch status``  — single poll, no looping, no alerts."""
    watchlist = load_watchlist()
    if not watchlist:
        print("\nYour watchlist is empty. Add courses first with `bruinwatch add`.")
        sys.exit(1)

    session = create_session()
    _poll_watchlist(session, watchlist, alert=False)


def cmd_run(interval: int = 180) -> None:
    """``bruinwatch run [--interval N]``  — continuous polling with alerts."""
    watchlist = load_watchlist()
    if not watchlist:
        print("\nYour watchlist is empty. Add courses first with `bruinwatch add`.")
        sys.exit(1)

    print("=" * 60)
    print("  BruinWatch — UCLA Course Seat Availability Monitor")
    print("=" * 60)
    print(f"\n  Monitoring {len(watchlist)} course(s):")
    for entry in watchlist:
        print(f"    • {entry['subject']} {entry['course_number']} — {entry['course_title']}")
    print(f"  Polling every {interval} seconds.  Press Ctrl+C to stop.")
    print(f"{'─' * 60}")

    session = create_session()

    try:
        while True:
            _poll_watchlist(session, watchlist, alert=True)

            # Countdown to next poll
            for remaining in range(interval, 0, -1):
                mins, secs = divmod(remaining, 60)
                print(
                    f"\r  Next poll in {mins:02d}:{secs:02d} …",
                    end="", flush=True,
                )
                time.sleep(1)
            print("\r" + " " * 40 + "\r", end="")  # clear countdown line

    except KeyboardInterrupt:
        print(f"\n\n{'─' * 60}")
        print("  BruinWatch stopped. Good luck with enrollment!")
        print(f"{'─' * 60}")

