"""Tests for polling, state diffing, and notification dispatch.

These need no mocking library. Watcher takes its client as a constructor
argument, so a five-line class with the one method it calls is enough --
that is dependency injection paying for itself.
"""

from unittest.mock import patch

import pytest

from bruinwatch.client import SOCError
from bruinwatch.models import Course
from bruinwatch.watcher import Watcher

# --- HTML builders -----------------------------------------------------------
#
# Minimal GetCourseSummary fragments. Real fixtures cover parsing; these
# exist only to drive the watcher through open/closed transitions.

SECTION_TEMPLATE = (
    '<div id="{sid}_X-section"><p><a href="x">{label}</a></p></div>'
    '<div id="{sid}_X-status_data"><p>{status}</p></div>'
)


def section(sid="1", label="Lec 1", *, enrolled=10, capacity=100, status="Open"):
    return SECTION_TEMPLATE.format(
        sid=sid, label=label, status=f"{status}<br />{enrolled} of {capacity} Enrolled"
    )


OPEN_LECTURE = section()
FULL_LECTURE = section(enrolled=100, capacity=100, status="Closed")


# --- Test doubles ------------------------------------------------------------


class FakeClient:
    """Serves canned summary HTML, one page per call, and records tokens."""

    def __init__(self, *pages: str):
        self.pages = list(pages)
        self.tokens: list[dict] = []

    def fetch_course_summary(self, model_token: dict) -> str:
        self.tokens.append(model_token)
        # Repeat the last page once exhausted, so a test can poll N times
        # without spelling out N identical pages.
        return self.pages.pop(0) if len(self.pages) > 1 else self.pages[0]


class BrokenClient:
    """Fails the way a real outage does, after retries are exhausted."""

    def fetch_course_summary(self, model_token: dict) -> str:
        raise SOCError("simulated outage")


@pytest.fixture
def course():
    return Course("COM SCI", "111", {"IsRoot": True}, "Operating Systems")


@pytest.fixture
def alerts():
    """Collect (course_name, seats, label) tuples from the callback."""
    return []


def make_watcher(client, course, alerts=None, **kwargs):
    notify = None if alerts is None else lambda *args: alerts.append(args)
    return Watcher(client, [course], notify=notify, **kwargs)


# --- poll_once: snapshots ----------------------------------------------------


def test_poll_once_returns_one_snapshot_per_course(course):
    watcher = make_watcher(FakeClient(OPEN_LECTURE), course)
    snapshots = watcher.poll_once()

    assert len(snapshots) == 1
    assert snapshots[0].course is course


def test_snapshot_records_parsed_sections(course):
    watcher = make_watcher(FakeClient(OPEN_LECTURE), course)
    snapshot = watcher.poll_once()[0]

    assert [s.label for s in snapshot.sections] == ["Lec 1"]
    assert snapshot.sections[0].seats_available == 90


def test_snapshot_sections_are_a_tuple(course):
    # CourseSnapshot is frozen; a list field would make that a lie.
    watcher = make_watcher(FakeClient(OPEN_LECTURE), course)
    assert isinstance(watcher.poll_once()[0].sections, tuple)


def test_snapshot_is_timestamped(course):
    watcher = make_watcher(FakeClient(OPEN_LECTURE), course)
    before = watcher.poll_once()[0].fetched_at
    after = watcher.poll_once()[0].fetched_at
    assert after >= before


def test_passes_the_courses_token_to_the_client(course):
    client = FakeClient(OPEN_LECTURE)
    make_watcher(client, course).poll_once()

    assert client.tokens[0] == {"IsRoot": True}


# --- poll_once: two-level fetching -------------------------------------------


def test_follows_sub_tokens_to_fetch_labs(course):
    # The lecture page carries a sub token; its page carries the labs.
    lecture_page = OPEN_LECTURE + ('AddToCourseData("x",{"IsRoot":false,"Path":"1_X"})')
    lab_page = section(sid="2", label="Lab 1A")

    client = FakeClient(lecture_page, lab_page)
    snapshot = make_watcher(client, course).poll_once()[0]

    assert [s.label for s in snapshot.sections] == ["Lec 1", "Lab 1A"]
    assert len(client.tokens) == 2
    assert client.tokens[1]["IsRoot"] is False


def test_sections_are_flat_not_nested(course):
    # Lectures and labs land in one sequence, so open_sections() just works.
    lecture_page = OPEN_LECTURE + 'AddToCourseData("x",{"IsRoot":false})'
    lab_page = section(sid="2", label="Lab 1A")

    snapshot = make_watcher(FakeClient(lecture_page, lab_page), course).poll_once()[0]
    assert len(snapshot.open_sections()) == 2


# --- state diffing: the reason Watcher is a class ----------------------------


def test_alerts_on_the_first_poll(course, alerts):
    # Starting empty means an already-open seat is not missed at startup.
    make_watcher(FakeClient(OPEN_LECTURE), course, alerts).poll_once()
    assert alerts == [("COM SCI 111", 90, "Lec 1")]


def test_does_not_realert_while_a_section_stays_open(course, alerts):
    watcher = make_watcher(FakeClient(OPEN_LECTURE), course, alerts)
    watcher.poll_once()
    alerts.clear()

    watcher.poll_once()
    watcher.poll_once()

    assert alerts == []


def test_does_not_alert_for_a_closed_section(course, alerts):
    make_watcher(FakeClient(FULL_LECTURE), course, alerts).poll_once()
    assert alerts == []


def test_alerts_when_a_closed_section_opens(course, alerts):
    watcher = make_watcher(FakeClient(FULL_LECTURE, OPEN_LECTURE), course, alerts)
    watcher.poll_once()
    assert alerts == []

    watcher.poll_once()
    assert alerts == [("COM SCI 111", 90, "Lec 1")]


def test_realerts_after_a_section_closes_and_reopens(course, alerts):
    watcher = make_watcher(
        FakeClient(OPEN_LECTURE, FULL_LECTURE, OPEN_LECTURE), course, alerts
    )
    watcher.poll_once()  # open   -> alert
    watcher.poll_once()  # closed -> silent
    watcher.poll_once()  # open   -> alert again

    assert len(alerts) == 2


def test_closed_section_with_free_seats_does_not_alert(course, alerts):
    # UCLA sometimes shows spare seats on an administratively closed
    # section; models.is_open is the single authority on that.
    page = section(enrolled=10, capacity=100, status="Closed")
    make_watcher(FakeClient(page), course, alerts).poll_once()

    assert alerts == []


def test_tracks_sections_independently(course, alerts):
    both_full = section(status="Closed", enrolled=100) + section(
        sid="2", label="Lab 1A", status="Closed", enrolled=60, capacity=60
    )
    one_open = section(status="Closed", enrolled=100) + section(
        sid="2", label="Lab 1A", enrolled=10, capacity=60
    )

    watcher = make_watcher(FakeClient(both_full, one_open), course, alerts)
    watcher.poll_once()
    watcher.poll_once()

    assert [label for _, _, label in alerts] == ["Lab 1A"]


def test_notification_carries_current_seat_count(course, alerts):
    page = section(enrolled=95, capacity=120)
    make_watcher(FakeClient(page), course, alerts).poll_once()

    assert alerts[0][1] == 25


# --- notification is optional ------------------------------------------------


def test_polls_silently_without_a_callback(course):
    # notify=None is what makes dry runs and these tests possible.
    watcher = Watcher(FakeClient(OPEN_LECTURE), [course], notify=None)
    assert len(watcher.poll_once()) == 1


# --- error isolation ---------------------------------------------------------


def test_failed_course_is_skipped_not_raised(course, alerts):
    watcher = make_watcher(BrokenClient(), course, alerts)
    assert watcher.poll_once() == []
    assert alerts == []


def test_one_failing_course_does_not_silence_the_others():
    """A flaky endpoint for one course must not cost us the rest."""

    class HalfBrokenClient:
        def __init__(self):
            self.calls = 0

        def fetch_course_summary(self, model_token):
            self.calls += 1
            if self.calls == 1:
                raise SOCError("first course is down")
            return OPEN_LECTURE

    alerts: list = []
    watcher = Watcher(
        HalfBrokenClient(),
        [Course("COM SCI", "111", {}, None), Course("MATH", "32A", {}, None)],
        notify=lambda *args: alerts.append(args),
    )
    snapshots = watcher.poll_once()

    assert len(snapshots) == 1
    assert snapshots[0].course.display_name == "MATH 32A"
    assert [name for name, _, _ in alerts] == ["MATH 32A"]


def test_failed_fetch_does_not_overwrite_previous_state(course, alerts):
    """A failure must not be recorded as "closed", or recovery re-alerts."""

    class FlakyClient:
        def __init__(self):
            self.calls = 0

        def fetch_course_summary(self, model_token):
            self.calls += 1
            if self.calls == 2:
                raise SOCError("blip")
            return OPEN_LECTURE

    watcher = make_watcher(FlakyClient(), course, alerts)
    watcher.poll_once()  # open -> alert
    alerts.clear()

    watcher.poll_once()  # fails -> state untouched
    watcher.poll_once()  # still open -> must stay silent

    assert alerts == []


# --- run ---------------------------------------------------------------------


def test_run_polls_on_each_cycle_and_exits_cleanly(course, alerts):
    watcher = make_watcher(FakeClient(OPEN_LECTURE), course, alerts, poll_interval=0)

    # Break out of the infinite loop on the third sleep.
    with patch(
        "bruinwatch.watcher.time.sleep",
        side_effect=[None, None, KeyboardInterrupt()],
    ) as sleep:
        watcher.run()  # must return, not propagate

    assert sleep.call_count == 3


def test_run_sleeps_for_the_configured_interval(course):
    watcher = make_watcher(FakeClient(OPEN_LECTURE), course, poll_interval=42)

    with patch(
        "bruinwatch.watcher.time.sleep", side_effect=KeyboardInterrupt()
    ) as sleep:
        watcher.run()

    sleep.assert_called_once_with(42)
