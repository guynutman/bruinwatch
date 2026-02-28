"""
bruinwatch.cli — Entry point and argument parsing.

After ``pip install -e .``, the ``bruinwatch`` command routes here via the
``[project.scripts]`` entry in ``pyproject.toml``.
"""

from __future__ import annotations

import argparse
import sys

from bruinwatch import __version__
from bruinwatch.commands import (
    cmd_add, cmd_list, cmd_remove, cmd_status, cmd_run,
    cmd_notifications, cmd_discussions,
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="bruinwatch",
        description="BruinWatch — UCLA Course Seat Availability Monitor",
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")

    # ── bruinwatch add ──
    subparsers.add_parser(
        "add",
        help="Add a course to your watchlist (interactive prompt)",
    )

    # ── bruinwatch remove ──
    subparsers.add_parser(
        "remove",
        help="Remove a course from your watchlist",
    )

    # ── bruinwatch list ──
    subparsers.add_parser("list", help="Show all watched courses")

    # ── bruinwatch status ──
    subparsers.add_parser(
        "status", help="Poll all watched courses once and display results",
    )

    # ── bruinwatch notifications ──
    subparsers.add_parser(
        "notifications",
        help="Toggle desktop + sound notifications on/off",
    )

    # ── bruinwatch discussions ──
    subparsers.add_parser(
        "discussions",
        help="Toggle discussion/lab section alerts on/off",
    )

    # ── bruinwatch run ──
    run_parser = subparsers.add_parser(
        "run",
        help="Continuously monitor watched courses with alerts",
    )
    run_parser.add_argument(
        "--interval",
        type=int,
        default=180,
        metavar="SECONDS",
        help="Seconds between poll cycles (default: 180)",
    )

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    try:
        if args.command == "add":
            cmd_add()
        elif args.command == "remove":
            cmd_remove()
        elif args.command == "list":
            cmd_list()
        elif args.command == "status":
            cmd_status()
        elif args.command == "notifications":
            cmd_notifications()
        elif args.command == "discussions":
            cmd_discussions()
        elif args.command == "run":
            cmd_run(interval=args.interval)
    except KeyboardInterrupt:
        print("\n")


if __name__ == "__main__":
    main()
