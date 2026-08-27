"""Tests for command-line argument handling.

Only the pure parts are covered here: argument parsing and the course-spec
split. The prompting functions need a terminal and the notify callback
needs a sound device, which is exactly why they live in this module and
nothing else imports them.
"""

import pytest

from bruinwatch.bruinwatch import parse_args, split_course_argument
from bruinwatch.watcher import DEFAULT_POLL_INTERVAL

# --- defaults ----------------------------------------------------------------


def test_no_arguments_leaves_everything_to_prompts():
    args = parse_args([])
    assert args.term is None
    assert args.courses is None
    assert args.interval == DEFAULT_POLL_INTERVAL
    assert not args.once
    assert not args.quiet


# --- term --------------------------------------------------------------------


@pytest.mark.parametrize("flag", ["-t", "--term"])
def test_term_accepts_short_and_long_flags(flag):
    assert parse_args([flag, "26F"]).term == "26F"


# --- courses -----------------------------------------------------------------


def test_course_flag_is_repeatable():
    # action="append" is what lets one invocation watch a whole watchlist.
    args = parse_args(["-c", "COM SCI 111", "-c", "MATH 61"])
    assert args.courses == ["COM SCI 111", "MATH 61"]


def test_single_course_still_produces_a_list():
    assert parse_args(["--course", "COM SCI 111"]).courses == ["COM SCI 111"]


# --- interval ----------------------------------------------------------------


def test_interval_is_parsed_as_an_int():
    args = parse_args(["--interval", "300"])
    assert args.interval == 300
    assert isinstance(args.interval, int)


def test_non_numeric_interval_is_rejected():
    with pytest.raises(SystemExit):
        parse_args(["--interval", "soon"])


# --- flags -------------------------------------------------------------------


def test_once_and_quiet_are_boolean_flags():
    args = parse_args(["--once", "--quiet"])
    assert args.once
    assert args.quiet


def test_colour_flag_accepts_both_spellings():
    assert parse_args(["--no-colour"]).no_colour
    assert parse_args(["--no-color"]).no_colour


# --- split_course_argument ---------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("COM SCI 111", ("COM SCI", "111")),
        # Subject areas contain spaces, so the split has to come from the
        # right: the catalog number is the last token, never the first.
        ("COM SCI M51A", ("COM SCI", "M51A")),
        ("EC ENGR M16", ("EC ENGR", "M16")),
        ("MATH 61", ("MATH", "61")),
        ("com sci 111", ("COM SCI", "111")),  # normalised to upper
        ("  MATH   61  ", ("MATH", "61")),  # tolerant of spacing
    ],
)
def test_split_course_argument(raw, expected):
    assert split_course_argument(raw) == expected


@pytest.mark.parametrize("raw", ["MATH", "111", "", "   "])
def test_split_returns_none_without_a_separator(raw):
    # Reported to the user as a parse error rather than guessed at.
    assert split_course_argument(raw) is None
