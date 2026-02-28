"""
bruinwatch.commands — Logic for each CLI command.

Each ``cmd_*`` function is the sole entry-point called by ``cli.py``.
All user-facing error handling lives here — API exceptions are caught and
printed as friendly messages rather than tracebacks.
"""

from __future__ import annotations

import platform
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
from bruinwatch.storage import load_watchlist, add_course, remove_course, load_settings, save_settings
from bruinwatch.alert import print_status_table, trigger_alert

# ─── Key-press detection (cross-platform) ────────────────────────────────────

if platform.system() == "Windows":
    import msvcrt

    def _key_pressed() -> str | None:
        """Return the pressed key as a string, or ``None``."""
        if msvcrt.kbhit():
            return msvcrt.getch().decode("utf-8", errors="ignore").lower()
        return None
else:
    import select
    import tty
    import termios

    def _key_pressed() -> str | None:
        """Return the pressed key as a string, or ``None``."""
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            rlist, _, _ = select.select([sys.stdin], [], [], 0)
            if rlist:
                return sys.stdin.read(1).lower()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        return None


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
    session,
    watchlist: list[dict[str, Any]],
    *,
    alert: bool = False,
    discuss_alerts: bool = True,
    show_discussions: bool = True,
    prev_open: set[str] | None = None,
) -> set[str]:
    """Fetch enrollment for every course and print a status table.

    If *alert* is ``True``, fire desktop + audio alerts only when a section
    transitions from closed → open (i.e. not already in *prev_open*).
    If *discuss_alerts* is ``False``, discussion openings won't trigger alerts.

    Returns the set of section keys that are currently open, so the caller
    can pass it back on the next cycle.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'═' * 72}")
    print(f"  [{now}]  Polling {len(watchlist)} course(s)…")
    print(f"{'═' * 72}")

    results: list[dict[str, Any]] = []
    currently_open: set[str] = set()
    if prev_open is None:
        prev_open = set()

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

        course_label = f"{entry['subject']} {entry['course_number']}"

        for lec in sections:
            lec_key = f"{course_label}|{lec['section_label']}"
            if lec["spots_left"] > 0:
                currently_open.add(lec_key)
                if alert and lec_key not in prev_open:
                    trigger_alert(
                        f"{course_label} — {entry['course_title']}",
                        lec["spots_left"],
                        lec["section_label"],
                    )
            for dis in lec.get("discussions", []):
                dis_key = f"{course_label}|{lec['section_label']}>{dis['section_label']}"
                if dis["spots_left"] > 0:
                    currently_open.add(dis_key)
                    if alert and discuss_alerts and dis_key not in prev_open:
                        trigger_alert(
                            f"{course_label} — {entry['course_title']}",
                            dis["spots_left"],
                            f"{lec['section_label']} > {dis['section_label']}",
                        )

    if results:
        print_status_table(results, show_discussions=show_discussions)

    return currently_open


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
    discuss = load_settings().get("discuss_alerts", True)
    _poll_watchlist(session, watchlist, show_discussions=discuss)


def cmd_notifications() -> None:
    """``bruinwatch notifications`` — toggle notifications on/off."""
    settings = load_settings()
    current = settings.get("notifications", True)
    status_str = f"{Fore.GREEN}ON{Style.RESET_ALL}" if current else f"{Fore.RED}OFF{Style.RESET_ALL}"
    print(f"\n  Notifications are currently: {status_str}")
    print(f"  (Desktop alerts + sound)\n")
    choice = input("  Toggle notifications? (y/n) [n]: ").strip().lower()
    if choice == "y":
        settings["notifications"] = not current
        save_settings(settings)
        new_str = f"{Fore.GREEN}ON{Style.RESET_ALL}" if settings["notifications"] else f"{Fore.RED}OFF{Style.RESET_ALL}"
        print(f"  Notifications set to: {new_str}")
    else:
        print("  No changes made.")


def cmd_discussions() -> None:
    """``bruinwatch discussions`` — toggle discussion alerts on/off."""
    settings = load_settings()
    current = settings.get("discuss_alerts", True)
    status_str = f"{Fore.GREEN}ON{Style.RESET_ALL}" if current else f"{Fore.RED}OFF{Style.RESET_ALL}"
    print(f"\n  Discussion alerts are currently: {status_str}")
    print(f"  When OFF, only lecture openings trigger notifications.\n")
    choice = input("  Toggle discussion alerts? (y/n) [n]: ").strip().lower()
    if choice == "y":
        settings["discuss_alerts"] = not current
        save_settings(settings)
        new_str = f"{Fore.GREEN}ON{Style.RESET_ALL}" if settings["discuss_alerts"] else f"{Fore.RED}OFF{Style.RESET_ALL}"
        print(f"  Discussion alerts set to: {new_str}")
    else:
        print("  No changes made.")


def cmd_run(interval: int = 180) -> None:
    """``bruinwatch run [--interval N]``  — continuous polling with alerts."""
    watchlist = load_watchlist()
    if not watchlist:
        print("\nYour watchlist is empty. Add courses first with `bruinwatch add`.")
        sys.exit(1)

    settings = load_settings()
    notify = settings.get("notifications", True)
    discuss = settings.get("discuss_alerts", True)

    print("=" * 60)
    print("  BruinWatch — UCLA Course Seat Availability Monitor")
    print("=" * 60)
    print(f"\n  Monitoring {len(watchlist)} course(s):")
    for entry in watchlist:
        print(f"    • {entry['subject']} {entry['course_number']} — {entry['course_title']}")
    notif_str = f"{Fore.GREEN}ON{Style.RESET_ALL}" if notify else f"{Fore.RED}OFF{Style.RESET_ALL}"
    disc_str = f"{Fore.GREEN}ON{Style.RESET_ALL}" if discuss else f"{Fore.RED}OFF{Style.RESET_ALL}"
    print(f"  Notifications: {notif_str}  |  Discussion alerts: {disc_str}")
    print(f"  Polling every {interval} seconds.")
    print(f"  Press 'q' to stop monitoring  |  Ctrl+C to exit")
    print(f"{'─' * 60}")

    session = create_session()
    prev_open: set[str] = set()

    try:
        while True:
            prev_open = _poll_watchlist(
                session, watchlist,
                alert=notify, discuss_alerts=discuss,
                show_discussions=discuss, prev_open=prev_open,
            )

            # Countdown to next poll — check for 'q' each second
            stopped = False
            for remaining in range(interval, 0, -1):
                mins, secs = divmod(remaining, 60)
                print(
                    f"\r  Next poll in {mins:02d}:{secs:02d}  (press 'q' to stop) …",
                    end="", flush=True,
                )
                time.sleep(1)
                key = _key_pressed()
                if key == "q":
                    stopped = True
                    break
            print("\r" + " " * 50 + "\r", end="")  # clear countdown line

            if stopped:
                break

    except KeyboardInterrupt:
        pass

    print(f"\n{'─' * 60}")
    print("  BruinWatch stopped. Good luck with enrollment!")
