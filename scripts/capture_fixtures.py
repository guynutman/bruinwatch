#!/usr/bin/env python3
"""Capture raw HTML from UCLA's Schedule of Classes into fixtures/.

Scaffolding, not part of the package. Run it once to freeze real responses
so parser.py can be built and tested without touching the network.

Usage:
    python scripts/capture_fixtures.py 26F "COM SCI" 0111

Note the catalog number must already be zero-padded ("0111", not "111").
Once client.py exists, this script should be rewritten to use it so the
capture path and the production path cannot drift apart.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests

# --- Endpoints ---------------------------------------------------------------

SOC_URL = "https://sa.ucla.edu/ro/Public/SOC"
COURSE_TITLES_URL = f"{SOC_URL}/Results/CourseTitlesView"
COURSE_SUMMARY_URL = f"{SOC_URL}/Results/GetCourseSummary"

# SOC serves bare HTML fragments to AJAX callers and a ~517KB page to everyone
# else, so X-Requested-With is what keeps these fixtures small and parseable.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": SOC_URL,
}

TIMEOUT = 20
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

# Matches the JS calls that carry each course's opaque model token:
#     Iwe_ClassSearch_SearchResults.AddToCourseData("COMSCI0111",{...})
COURSE_DATA_RE = re.compile(r'AddToCourseData\("[^"]+",(\{[^}]+\})\)')


# --- Helpers -----------------------------------------------------------------


def open_session() -> requests.Session:
    """Return a Session primed with SOC's cookies.

    The landing page request exists only to collect session state; SOC
    rejects the Results endpoints without it.
    """
    session = requests.Session()
    session.headers.update(HEADERS)
    session.get(SOC_URL, timeout=TIMEOUT).raise_for_status()
    return session


def save(filename: str, html: str) -> None:
    """Write one fixture and report its size."""
    path = FIXTURES_DIR / filename
    path.write_text(html, encoding="utf-8")
    print(f"  {filename:<32} {len(html):>8,} bytes")


def fetch(session: requests.Session, url: str, params: dict) -> str:
    """GET and return response text, raising on any non-2xx status.

    Raising matters here: silently saving UCLA's 500 page as a fixture
    would give us tests that pass against garbage.
    """
    response = session.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    return response.text


def extract_tokens(html: str, *, root: bool) -> list[dict]:
    """Pull AddToCourseData JSON objects out of embedded <script> blocks.

    Root tokens identify a course; non-root tokens identify its
    discussion/lab sub-level. Both are opaque -- they are handed back to
    UCLA verbatim, never constructed by us.
    """
    tokens = [json.loads(blob) for blob in COURSE_DATA_RE.findall(html)]
    return [t for t in tokens if bool(t.get("IsRoot")) is root]


# --- Capture steps -----------------------------------------------------------


def capture_landing(session: requests.Session) -> None:
    """SOC landing page -- the source for available term codes."""
    save("soc_landing_sample.html", fetch(session, SOC_URL, {}))


def capture_titles(session: requests.Session, term: str, subject: str,
                   catalog_no: str) -> dict:
    """CourseTitlesView -- course title plus the root model token.

    Returns the root token, which GetCourseSummary requires.
    """
    model = {
        "term_cd": term,
        "subj_area_cd": subject,
        "ses_grp_cd": "%",      # wildcard: any session group
        "class_no": "%",        # wildcard: any class number
        "crs_catlg_no": catalog_no,
    }
    html = fetch(session, COURSE_TITLES_URL, {
        "search_by": "subject",
        "model": json.dumps(model),
        "pageNumber": "1",
        "filterFlags": "{}",
    })
    save("course_titles_sample.html", html)

    roots = extract_tokens(html, root=True)
    if not roots:
        sys.exit(f"No course found for {subject} {catalog_no} in {term}.")
    return roots[0]


def capture_summary(session: requests.Session, token: dict, filename: str) -> str:
    """GetCourseSummary for one token. Returns the HTML for further mining."""
    html = fetch(session, COURSE_SUMMARY_URL, {
        "model": json.dumps(token),
        "FilterFlags": "{}",
    })
    save(filename, html)
    return html


# --- Entry point -------------------------------------------------------------


def main() -> None:
    if len(sys.argv) != 4:
        sys.exit(f"usage: {sys.argv[0]} TERM SUBJECT CATALOG_NO\n"
                 f'example: {sys.argv[0]} 26F "COM SCI" 0111')
    term, subject, catalog_no = sys.argv[1:4]

    FIXTURES_DIR.mkdir(exist_ok=True)
    print(f"Capturing {subject} {catalog_no} for {term} into {FIXTURES_DIR}/")

    session = open_session()
    capture_landing(session)
    root_token = capture_titles(session, term, subject, catalog_no)

    # Lecture level, then the sub-level (labs/discussions) it points to.
    summary_html = capture_summary(session, root_token,
                                   "course_summary_sample.html")

    sub_tokens = extract_tokens(summary_html, root=False)
    if sub_tokens:
        capture_summary(session, sub_tokens[0],
                        "course_summary_sub_sample.html")
    else:
        print("  (no sub-level sections for this course)")


if __name__ == "__main__":
    main()
