"""Polling, state diffing, and notification dispatch.

The business logic layer: poll, diff, react. Composes client + parser +
models without knowing how any of them work internally -- it asks for a
string, hands it to a parser, and gets objects back.

Deliberately ignorant of what a notification *is*. The callback is
injected, so this module never imports plyer, platform, or winsound:
deciding *when* to alert is business logic, deciding *what an alert does*
is policy that belongs to the caller.
"""

import time
from collections.abc import Callable
from datetime import datetime

from bruinwatch import parser
from bruinwatch.client import SOCClient
from bruinwatch.models import Course, CourseSnapshot, SectionStatus

DEFAULT_POLL_INTERVAL = 180

# Called when a section opens that was not open on the previous poll.
# Args: course display name, seats available, section label.
NotifyCallback = Callable[[str, int, str], None]


class Watcher:
    """Polls courses and reports sections that have newly opened.

    Holds the previous poll's snapshots so it can diff against them; that
    state is the reason this is a class rather than a function.
    """

    def __init__(
        self,
        client: SOCClient,
        courses: list[Course],
        notify: NotifyCallback | None = None,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
    ) -> None:
        """Store dependencies and start with no previous state.

        A None notify means "poll but stay quiet", which is what makes the
        watcher usable in tests and dry runs.
        """

    def poll_once(self) -> list[CourseSnapshot]:
        """Fetch every watched course and fire notifications for new opens.

        Returns one snapshot per course, in watchlist order. A course whose
        request fails is skipped rather than aborting the whole cycle: one
        flaky endpoint should not silence the others.
        """

    def run(self) -> None:
        """Poll forever, sleeping poll_interval between cycles.

        Blocks until interrupted. Catches KeyboardInterrupt so Ctrl+C is a
        clean exit rather than a traceback.
        """

    def _snapshot_course(self, course: Course) -> CourseSnapshot:
        """Fetch and parse one course into a snapshot.

        Walks both levels: the root token yields lectures, and each
        lecture's sub token yields its discussions or labs.
        """

    def _newly_open(self, snapshot: CourseSnapshot) -> list[SectionStatus]:
        """Sections open now that were not open on the previous poll.

        A section counts as newly open if it is open now AND was either
        closed or absent last time -- which is what stops a section that
        stays open from re-alerting on every cycle.
        """
