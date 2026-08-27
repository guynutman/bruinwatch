"""Data shapes for BruinWatch. Standard library only — no I/O, no parsing."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

# Revisit once fixtures exist — UCLA's full status vocabulary is unknown.
CLOSED_PREFIXES = ("closed", "cancelled")


class SectionKind(str, Enum):
    """What type of meeting a section is."""

    LECTURE = "Lecture"
    DISCUSSION = "Discussion"
    LAB = "Lab"


@dataclass(frozen=True)
class SectionStatus:
    """Enrollment state of a single section at one point in time."""

    section_id: str
    label: str  # UCLA's display label, e.g. "Lec 1", "Dis 1A"
    kind: SectionKind
    enrolled: int
    capacity: int
    waitlisted: int
    waitlist_capacity: int | None  # None = no waitlist exists for this section
    status_text: str  # UCLA's raw label: "Open", "Closed", ...

    @property
    def seats_available(self) -> int:
        """Seats free right now. Never negative (UCLA can over-enroll)."""
        return max(0, self.capacity - self.enrolled)

    @property
    def is_open(self) -> bool:
        """True only if seats are free AND UCLA does not mark it closed.

        Checks both because UCLA sometimes reports spare seats on a
        section that is administratively closed.
        """
        if self.seats_available <= 0:
            return False
        return not self.status_text.strip().casefold().startswith(CLOSED_PREFIXES)


@dataclass(frozen=True)
class Course:
    """A course the user wants to watch."""

    subject_area: str  # "COM SCI"
    catalog_number: str  # "111" — as typed, not zero-padded
    model_token: dict | None = None  # opaque token from CourseTitlesView
    title: str | None = None  # resolved from CourseTitlesView

    @property
    def display_name(self) -> str:
        """e.g. 'COM SCI 111'"""
        return f"{self.subject_area} {self.catalog_number}"


@dataclass(frozen=True)
class CourseSnapshot:
    """Immutable point-in-time record of one course's sections."""

    course: Course
    sections: tuple[SectionStatus, ...]
    fetched_at: datetime

    @property
    def has_open_seats(self) -> bool:
        """True if any section has open seats."""
        return any(section.is_open for section in self.sections)

    def open_sections(self) -> list[SectionStatus]:
        """Every section currently open, in original order."""
        return [section for section in self.sections if section.is_open]
