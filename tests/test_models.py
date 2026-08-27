"""Tests for the data shapes and their derived properties.

These are pure unit tests: no network, no fixtures, no mocks. Everything
here exercises logic that lives in exactly one place in the codebase --
the seat arithmetic and the definition of "open".
"""

from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from bruinwatch.models import Course, CourseSnapshot, SectionKind, SectionStatus

# --- Helpers -----------------------------------------------------------------
#
# SectionStatus takes eight fields. Spelling all eight out in every test buries
# the one field the test is actually about, so these factories supply sane
# defaults and let each test override only what it cares about.
#
# The defaults describe a comfortably OPEN section (10 of 100, status "Open"),
# so every test overrides *toward* the condition it wants to check.


def make_section(**overrides) -> SectionStatus:
    """Build a SectionStatus with open-section defaults."""
    defaults = {
        "section_id": "1",
        "label": "Lec 1",
        "kind": SectionKind.LECTURE,
        "enrolled": 10,
        "capacity": 100,
        "waitlisted": 0,
        "waitlist_capacity": None,
        "status_text": "Open",
    }
    return SectionStatus(**{**defaults, **overrides})


def make_snapshot(*sections: SectionStatus) -> CourseSnapshot:
    """Build a CourseSnapshot wrapping the given sections."""
    return CourseSnapshot(
        course=Course(subject_area="COM SCI", catalog_number="111"),
        sections=sections,
        fetched_at=datetime(2026, 8, 23, 12, 0, 0),
    )


# --- SectionStatus.seats_available -------------------------------------------


def test_seats_available_counts_free_seats():
    assert make_section(enrolled=10, capacity=100).seats_available == 90


def test_seats_available_is_zero_when_full():
    assert make_section(enrolled=100, capacity=100).seats_available == 0


def test_seats_available_is_never_negative():
    # UCLA reports enrolled > capacity on over-enrolled sections. Naive
    # subtraction would yield -5 and read as "negative seats available".
    assert make_section(enrolled=105, capacity=100).seats_available == 0


# --- SectionStatus.is_open ---------------------------------------------------


def test_is_open_when_seats_free_and_status_open():
    assert make_section(enrolled=10, capacity=100, status_text="Open").is_open


def test_is_open_false_when_full():
    assert not make_section(enrolled=100, capacity=100, status_text="Open").is_open


def test_is_open_false_when_closed_despite_free_seats():
    # The case that justifies checking BOTH arithmetic and status text.
    # Seats appear free, but the section is administratively closed --
    # alerting here would send the user to a section they cannot join.
    section = make_section(enrolled=10, capacity=100, status_text="Closed")
    assert section.seats_available == 90
    assert not section.is_open


# Parametrize over the closed-status variants rather than looping inside one
# test: pytest reports each case as its own named test, so a failure on only
# "CLOSED" points straight at the casefold() call instead of at a loop body.
@pytest.mark.parametrize(
    "status_text",
    [
        "Closed",
        "Closed by Petition",  # exercises startswith(), not ==
        "CLOSED",  # exercises casefold()
        " Cancelled ",  # exercises strip()
        "Cancelled",
    ],
)
def test_is_open_false_for_closed_variants(status_text):
    assert not make_section(status_text=status_text).is_open


@pytest.mark.parametrize("status_text", ["Open", "Waitlist", "Tentative"])
def test_is_open_true_for_non_closed_statuses(status_text):
    # Anything UCLA does not call closed, with free seats, counts as open.
    assert make_section(status_text=status_text).is_open


# --- Course ------------------------------------------------------------------


def test_display_name_joins_subject_and_number():
    course = Course(subject_area="COM SCI", catalog_number="111")
    assert course.display_name == "COM SCI 111"


def test_course_token_and_title_default_to_none():
    # Unresolved until CourseTitlesView is queried; None is meaningful state.
    course = Course(subject_area="MATH", catalog_number="32A")
    assert course.model_token is None
    assert course.title is None


# --- CourseSnapshot ----------------------------------------------------------


def test_empty_snapshot_has_no_open_seats():
    # A failed poll yields zero sections; this must be falsy, not an error.
    snapshot = make_snapshot()
    assert not snapshot.has_open_seats
    assert snapshot.open_sections() == []


def test_has_open_seats_true_if_any_section_open():
    closed = make_section(section_id="1", enrolled=100, capacity=100)
    open_one = make_section(section_id="2", enrolled=10, capacity=100)
    assert make_snapshot(closed, open_one).has_open_seats


def test_has_open_seats_false_when_all_sections_full():
    full_a = make_section(section_id="1", enrolled=100, capacity=100)
    full_b = make_section(section_id="2", enrolled=200, capacity=200)
    assert not make_snapshot(full_a, full_b).has_open_seats


def test_open_sections_preserves_order_and_filters():
    first = make_section(section_id="1", label="Lec 1", enrolled=10, capacity=100)
    closed = make_section(section_id="2", label="Lec 2", enrolled=100, capacity=100)
    third = make_section(section_id="3", label="Lec 3", enrolled=20, capacity=100)

    result = make_snapshot(first, closed, third).open_sections()

    assert [s.section_id for s in result] == ["1", "3"]


# --- Immutability ------------------------------------------------------------
#
# The frozen contract is load-bearing: watcher.py holds the previous snapshot
# to diff against the next one. If a snapshot could be mutated after capture,
# the diff would compare an object against itself and never fire an alert.


def test_section_status_is_frozen():
    section = make_section()
    with pytest.raises(FrozenInstanceError):
        section.enrolled = 99


def test_course_snapshot_is_frozen():
    snapshot = make_snapshot(make_section())
    with pytest.raises(FrozenInstanceError):
        snapshot.course = None
