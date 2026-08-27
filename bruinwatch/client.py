"""HTTP access to UCLA's Schedule of Classes.

Knows about endpoints, session cookies, and retries. Returns raw HTML and
never parses it -- that separation is what lets parser.py be tested against
saved fixtures with no network involved.
"""

import json
import re
import time

import requests

# --- Endpoints ---------------------------------------------------------------

BASE_URL = "https://sa.ucla.edu/ro"
SOC_URL = f"{BASE_URL}/Public/SOC"
COURSE_TITLES_URL = f"{SOC_URL}/Results/CourseTitlesView"
COURSE_SUMMARY_URL = f"{SOC_URL}/Results/GetCourseSummary"

DEFAULT_TIMEOUT = 20
MAX_RETRIES = 3
RETRY_DELAY = 10.0

# SOC serves bare HTML fragments to AJAX callers and a ~500KB page to
# everyone else, so X-Requested-With is what keeps responses parseable.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": SOC_URL,
}

# Leading digits of a catalog number, which UCLA zero-pads to four:
#     "32" -> "0032", "131" -> "0131", "M51A" -> "M51A" (no leading digits)
CATALOG_NUMBER_RE = re.compile(r"^(?P<digits>\d+)(?P<suffix>.*)$")


def format_catalog_number(catalog_number: str) -> str:
    """Zero-pad a catalog number the way UCLA's API expects.

        "32" -> "0032", "33A" -> "0033A", "M51A" -> "M51A"

    Lives here rather than in models because it is an API formatting
    concern: the user types "111" and that is what Course stores.
    """


class SOCClient:
    """HTTP client for UCLA's Schedule of Classes.

    Holds one requests.Session for its lifetime -- SOC rejects the Results
    endpoints without the cookies its landing page sets. That state is why
    this is a class while parser.py is plain functions.
    """

    def __init__(self, *, timeout: int = DEFAULT_TIMEOUT) -> None:
        """Create the session, set browser headers, and collect cookies.

        Raises requests.RequestException if the landing page is unreachable.
        """

    def fetch_terms_page(self) -> str:
        """GET the SOC landing page. Returns raw HTML.

        Raises requests.RequestException if all retries fail.
        """

    def fetch_course_titles(
        self, term_cd: str, subject_area: str, catalog_number: str
    ) -> str:
        """Call CourseTitlesView for one course. Returns raw HTML.

        Zero-pads the catalog number internally, so callers pass what the
        user typed. Raises requests.RequestException if all retries fail.
        """

    def fetch_course_summary(self, model_token: dict) -> str:
        """Call GetCourseSummary with a token from CourseTitlesView.

        The token is opaque -- handed back to UCLA verbatim. Works for both
        root tokens (lectures) and sub tokens (discussions/labs). Returns
        raw HTML. Raises requests.RequestException if all retries fail.
        """

    def _get_with_retry(self, url: str, params: dict) -> str:
        """GET with retries, returning response text.

        Retries on any RequestException, including 5xx, since SOC is
        flaky under enrollment-period load. Raises the last exception
        once MAX_RETRIES attempts are exhausted -- failing loudly beats
        returning empty HTML that would parse as "no sections".
        """
