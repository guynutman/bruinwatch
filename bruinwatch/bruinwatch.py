"""Command-line entry point: gather input, wire the modules, run the loop.

Deliberately thin. The other four modules do the work; this one decides
policy -- which term, which courses, what an alert actually does.

By convention this is the ONLY module that imports plyer, platform, or
winsound, the only one that calls input(), and the only one with a
__main__ guard. Keeping those here is what lets the rest of the package be
tested with no terminal, no display, and no sound device.
"""

import argparse
import contextlib
import platform
import subprocess
import sys
import warnings

from bruinwatch import parser
from bruinwatch.client import SOCClient, SOCError
from bruinwatch.models import Course, CourseSnapshot
from bruinwatch.watcher import (
    DEFAULT_POLL_INTERVAL,
    NotifyCallback,
    ReportCallback,
    Watcher,
)

try:
    # plyer warns once per call when dbus or notify-send is missing (common
    # under WSL and bare containers). The printed alert is the reliable
    # channel, so the noise is suppressed rather than shown every poll.
    warnings.filterwarnings("ignore", module="plyer")
    from plyer import notification as desktop_notify
except ImportError:  # optional dependency -- degrade to sound only
    desktop_notify = None

# ANSI colours. Windows terminals need a nudge before they honour these,
# and anything piped to a file should not be littered with escape codes.
if platform.system() == "Windows":  # pragma: no cover - platform specific
    # Older Windows consoles ignore ANSI codes until VT100 processing is
    # switched on explicitly.
    with contextlib.suppress(Exception):
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)

_USE_COLOUR = sys.stdout.isatty()
GREEN = "\033[92m" if _USE_COLOUR else ""
RED = "\033[91m" if _USE_COLOUR else ""
DIM = "\033[2m" if _USE_COLOUR else ""
RESET = "\033[0m" if _USE_COLOUR else ""


def colour(text: str, code: str) -> str:
    """Wrap text in an ANSI colour, or return it unchanged when piped."""
    return f"{code}{text}{RESET}" if code else text


def _disable_colour() -> None:
    """Blank the colour codes, for --no-colour."""
    global GREEN, RED, DIM, RESET
    GREEN = RED = DIM = RESET = ""


def build_notify_callback() -> NotifyCallback:
    """Build the platform-appropriate alert function.

    Returns a closure so Watcher can call it without knowing what it does.
    Every platform-specific branch in the program lives inside here.
    """
    system = platform.system()

    def play_sound() -> None:
        """Best-effort audible alert; falls back to the terminal bell.

        The players are looked up on PATH (noqa S607) rather than pinned to
        absolute paths: their location varies across distributions, and a
        missing player already falls through to the terminal bell.
        """
        try:
            if system == "Darwin":
                subprocess.run(
                    ["afplay", "/System/Library/Sounds/Glass.aiff"],
                    check=False,
                    timeout=5,
                )
                return
            if system == "Windows":
                import winsound

                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                return
            if system == "Linux":
                subprocess.run(
                    ["paplay", "/usr/share/sounds/freedesktop/stereo/bell.oga"],
                    check=False,
                    timeout=5,
                )
                return
        except (OSError, subprocess.SubprocessError, ImportError):
            pass  # no audio device, or the tool is missing -- fall through

        print("\a", end="", flush=True)

    def notify(course_name: str, seats: int, section_label: str) -> None:
        message = f"{section_label}: {seats} seat(s) open"
        print(colour(f"  >>> {course_name} - {message}", GREEN))

        if desktop_notify is not None:
            # Notification is a best-effort side channel and plyer raises
            # different types per platform. The print above is the reliable
            # path, so a failed popup is ignored rather than allowed to kill
            # the poll loop.
            with contextlib.suppress(Exception):
                desktop_notify.notify(
                    title="BruinWatch - Seat Available!",
                    message=f"{course_name}\n{message}",
                    app_name="BruinWatch",
                    timeout=10,
                )

        play_sound()

    return notify


def build_report_callback() -> ReportCallback:
    """Build the per-poll status table renderer.

    Open sections are green and full ones red, so the state of a whole
    watchlist is readable at a glance rather than only when it changes.
    """

    def report(snapshot: CourseSnapshot) -> None:
        heading = f"{snapshot.course.display_name} - {snapshot.course.title or ''}"
        print(f"\n  {heading.strip(' -')}")

        if not snapshot.sections:
            print(colour("    (no sections returned)", DIM))
            return

        for section in snapshot.sections:
            seats = section.seats_available
            enrolled = f"{section.enrolled}/{section.capacity}"
            waitlist = (
                f"{section.waitlisted}/{section.waitlist_capacity}"
                if section.waitlist_capacity
                else "-"
            )
            line = (
                f"    {section.label:<10} {section.status_text:<12} "
                f"{enrolled:>9} enrolled  {seats:>3} open  wl {waitlist}"
            )
            print(colour(line, GREEN if section.is_open else RED))

    return report


def choose_term(client: SOCClient) -> tuple[str, str]:
    """Prompt for a term. Returns (term_code, term_name).

    Exits if UCLA returns no terms, since nothing downstream can proceed.
    """
    try:
        terms = parser.parse_available_terms(client.fetch_terms_page())
    except SOCError as exc:
        sys.exit(f"Could not reach UCLA's Schedule of Classes: {exc}")

    if not terms:
        sys.exit("No terms found. UCLA may have changed their page layout.")

    print("\nAvailable terms:")
    for index, (_, name) in enumerate(terms, start=1):
        print(f"  [{index}] {name}")

    while True:
        choice = input(f"\nSelect a term [1-{len(terms)}], default 1: ").strip()
        if not choice:
            return terms[0]
        if choice.isdigit() and 1 <= int(choice) <= len(terms):
            return terms[int(choice) - 1]
        print("  Not a valid choice.")


def choose_courses(client: SOCClient, term_cd: str) -> list[Course]:
    """Prompt for courses, validating each against UCLA before accepting.

    Validation resolves the model token GetCourseSummary needs, so a
    Course leaves this function ready to poll. Returns at least one course
    or exits.
    """
    courses: list[Course] = []

    while True:
        subject = input("\nSubject area (e.g. COM SCI, MATH): ").strip()
        catalog_number = input("Course number (e.g. 111, 32A, M51A): ").strip()

        if not subject or not catalog_number:
            print("  Both fields are required.")
            continue

        course = _resolve_course(client, term_cd, subject, catalog_number)
        if course is not None:
            courses.append(course)
            print(f"  Added: {course.display_name} - {course.title}")

        if input("\nWatch another course? (y/n): ").strip().lower() != "y":
            break

    if not courses:
        sys.exit("No courses to watch. Exiting.")

    return courses


def _resolve_course(
    client: SOCClient, term_cd: str, subject: str, catalog_number: str
) -> Course | None:
    """Look one course up, returning it with its model token resolved.

    Returns None on any failure -- unknown course, or UCLA unreachable --
    so the caller can re-prompt rather than crash.
    """
    print(f"  Checking {subject} {catalog_number}...")
    try:
        html = client.fetch_course_titles(term_cd, subject, catalog_number)
    except SOCError as exc:
        print(f"  Lookup failed: {exc}")
        return None

    tokens = parser.parse_model_tokens(html)
    if not tokens:
        print(f"  No course found for {subject} {catalog_number} in this term.")
        return None

    return Course(
        subject_area=subject.strip().upper(),
        catalog_number=catalog_number.strip().upper(),
        model_token=tokens[0],
        title=parser.parse_course_title(html),
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Every option has an interactive fallback, so the tool stays usable
    with no flags at all while also being scriptable and cron-able.
    """
    parser_ = argparse.ArgumentParser(
        prog="bruinwatch",
        description="Monitor UCLA's Schedule of Classes for open seats.",
        epilog=(
            "examples:\n"
            "  bruinwatch\n"
            '  bruinwatch --term 26F --course "COM SCI M51A"\n'
            '  bruinwatch -t 26F -c "MATH 61" -c "COM SCI 111" --interval 300\n'
            "  bruinwatch -t 26F -c 'COM SCI 111' --once\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser_.add_argument(
        "-t",
        "--term",
        metavar="CODE",
        help="term code, e.g. 26F (prompts if omitted)",
    )
    parser_.add_argument(
        "-c",
        "--course",
        action="append",
        metavar="NAME",
        dest="courses",
        help='course to watch, e.g. "COM SCI M51A" (repeatable; prompts if omitted)',
    )
    parser_.add_argument(
        "-i",
        "--interval",
        type=int,
        default=DEFAULT_POLL_INTERVAL,
        metavar="SEC",
        help=f"seconds between polls (default: {DEFAULT_POLL_INTERVAL})",
    )
    parser_.add_argument(
        "--once",
        action="store_true",
        help="poll a single time and exit, instead of looping",
    )
    parser_.add_argument(
        "--no-colour",
        "--no-color",
        action="store_true",
        dest="no_colour",
        help="disable ANSI colour even when attached to a terminal",
    )
    parser_.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="suppress the per-poll status table; show alerts only",
    )
    return parser_.parse_args(argv)


def split_course_argument(raw: str) -> tuple[str, str] | None:
    """Split "COM SCI M51A" into ("COM SCI", "M51A").

    The catalog number is the last whitespace-separated token, because
    subject areas themselves contain spaces. Returns None if the argument
    has no separator to split on.
    """
    parts = raw.strip().rsplit(maxsplit=1)
    if len(parts) != 2:
        return None
    return parts[0].upper(), parts[1].upper()


def resolve_courses(client: SOCClient, term_cd: str, specs: list[str]) -> list[Course]:
    """Resolve --course arguments, exiting if any of them fails.

    Non-interactive callers get a hard failure rather than a silent
    watchlist that is missing entries they asked for.
    """
    courses: list[Course] = []

    for spec in specs:
        split = split_course_argument(spec)
        if split is None:
            sys.exit(f'Could not parse course {spec!r}. Expected e.g. "COM SCI 111".')

        subject, catalog_number = split
        course = _resolve_course(client, term_cd, subject, catalog_number)
        if course is None:
            sys.exit(f"Could not find {subject} {catalog_number} in term {term_cd}.")
        courses.append(course)

    return courses


def main(argv: list[str] | None = None) -> None:
    """Wire the modules together and hand control to the watcher."""
    args = parse_args(argv)

    if args.no_colour:
        _disable_colour()

    print("=" * 60)
    print("  BruinWatch - UCLA course seat monitor")
    print("=" * 60)

    if desktop_notify is None:
        print("  [info] pip install plyer for desktop notifications.")

    try:
        client = SOCClient()
    except Exception as exc:  # noqa: BLE001 -- top-level guard
        # Anything at all here means we cannot start; report it to the
        # user instead of dumping a traceback.
        sys.exit(f"Could not open a session with UCLA SOC: {exc}")

    # Each option falls back to a prompt, so the tool works with no flags
    # at all and equally well fully specified from a cron entry.
    if args.term:
        term_cd, term_name = args.term.upper(), args.term.upper()
    else:
        term_cd, term_name = choose_term(client)
    print(f"\nWatching {term_name} ({term_cd}).")

    if args.courses:
        courses = resolve_courses(client, term_cd, args.courses)
    else:
        courses = choose_courses(client, term_cd)

    watcher = Watcher(
        client,
        courses,
        notify=build_notify_callback(),
        poll_interval=args.interval,
        report=None if args.quiet else build_report_callback(),
    )

    print(f"\n{'-' * 60}")
    print(f"  Monitoring {len(courses)} course(s), every {args.interval}s.")
    for course in courses:
        print(f"    - {course.display_name}: {course.title}")
    if not args.once:
        print(colour("  Press Ctrl+C at any time to stop monitoring.", DIM))
    print(f"{'-' * 60}")

    if args.once:
        watcher.poll_once()
    else:
        watcher.run()


if __name__ == "__main__":
    main()
