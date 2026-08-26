"""Pure functions turning UCLA SOC HTML into model objects.

No network, no state, no side effects. Every function takes a string and
returns data, which is what makes this module testable against fixtures.
"""

import json
import re

from bruinwatch.models import SectionKind, SectionStatus

# --- Patterns ----------------------------------------------------------------
# Each pattern is compiled once and carries the markup it matches, because an
# uncommented regex is write-only code.

# Term options on the SOC landing page. The value is a term code (two digits
# plus a letter or digit); the element text is the human-readable name:
#     <option class="select_term" value="26F" data-yearText="Fall 2026">Fall 2026</option>
# [^>]* absorbs any extra attributes -- the current term carries selected="selected".
TERM_OPTION_RE = re.compile(
    r'<option[^>]*\bvalue="(?P<code>\d{2}[A-Z0-9])"[^>]*>(?P<name>[^<]+)</option>'
)

def parse_course_title(html: str) -> str | None:
    """Extract the course title from CourseTitlesView HTML.

    e.g. "111 - Operating Systems Principles". Returns None if absent.
    """


def parse_model_tokens(html: str) -> list[dict]:
    """Root-level AddToCourseData objects from CourseTitlesView HTML.

    These opaque tokens are what GetCourseSummary requires. Only entries
    with IsRoot true.
    """


def parse_sub_tokens(html: str) -> list[dict]:
    """Non-root AddToCourseData objects from GetCourseSummary HTML.

    Tokens for fetching the discussion/lab sub-level.
    """


def parse_sections(html: str) -> list[SectionStatus]:
    """Parse enrollment data from GetCourseSummary HTML.

    The core parser. Returns [] if the HTML contains no sections.
    """


def parse_available_terms(html: str) -> list[tuple[str, str]]:
    """(term_code, term_name) pairs from the SOC landing page.

    e.g. [("26F", "Fall 2026"), ("26S", "Spring 2026")]
    """


def parse_available_terms(html: str) -> list[tuple[str, str]]:
    """(term_code, term_name) pairs from the SOC landing page.

    e.g. [("26F", "Fall 2026"), ("26S", "Spring 2026")]

    Duplicates are dropped, keeping first-seen order: UCLA renders the same
    term in more than one <select> on the page.
    """
    terms: list[tuple[str, str]] = []
    seen: set[str] = set()

    for match in TERM_OPTION_RE.finditer(html):
        code = match.group("code")
        name = match.group("name").strip()
        if code in seen or not name:
            continue
        seen.add(code)
        terms.append((code, name))

    return terms
