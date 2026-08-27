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


# UCLA fronts SOC with an F5 WAF that answers suspicious sessions with a
# JavaScript challenge page instead of results. It carries no course data,
# so parsing it yields zero sections -- indistinguishable from a course that
# does not exist unless we detect it here.
BOT_CHALLENGE_MARKERS = ("f5_cspm", "bobcmn")


class SOCError(Exception):
    """A request to UCLA's SOC failed after exhausting retries.

    Exists so callers can handle transport failure without importing
    requests: watcher.py should not need to know that this module
    speaks HTTP. The underlying error is kept as __cause__.
    """


class BotChallengeError(SOCError):
    """UCLA served a bot-detection challenge instead of the page we asked for.

    A subclass of SOCError so existing handlers keep working, but distinct
    so callers can tell "slow down" apart from "the site is unreachable".
    """


def _is_bot_challenge(html: str) -> bool:
    """True if this response is the WAF's challenge page rather than content.

    The challenge is short and carries an F5 fingerprint, so both are
    checked: real SOC fragments are larger and never contain these markers.
    """
    return len(html) < 4000 and any(m in html for m in BOT_CHALLENGE_MARKERS)


def format_catalog_number(catalog_number: str) -> str:
    """Zero-pad a catalog number the way UCLA's API expects.

        "32" -> "0032", "33A" -> "0033A", "M51A" -> "M51A"

    Lives here rather than in models because it is an API formatting
    concern: the user types "111" and that is what Course stores.
    """
    normalized = catalog_number.strip().upper()

    match = CATALOG_NUMBER_RE.match(normalized)
    if match is None:
        return normalized

    return match.group("digits").zfill(4) + match.group("suffix")


class SOCClient:
    """HTTP client for UCLA's Schedule of Classes.

    Holds one requests.Session for its lifetime -- SOC rejects the Results
    endpoints without the cookies its landing page sets. That state is why
    this is a class while parser.py is plain functions.
    """

    def __init__(self, *, timeout: int = DEFAULT_TIMEOUT) -> None:
        """Create the session, set browser headers, and collect cookies.

        Raises SOCError if the landing page is unreachable.
        """
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(DEFAULT_HEADERS)

        # SOC sets session state here and rejects the Results endpoints
        # without it, so this request exists purely to collect cookies.
        self._session.get(SOC_URL, timeout=timeout).raise_for_status()

    def fetch_terms_page(self) -> str:
        """GET the SOC landing page. Returns raw HTML.

        Raises SOCError if all retries fail.
        """
        return self._get_with_retry(SOC_URL, {})

    def fetch_course_titles(
        self, term_cd: str, subject_area: str, catalog_number: str
    ) -> str:
        """Call CourseTitlesView for one course. Returns raw HTML.

        Zero-pads the catalog number internally, so callers pass what the
        user typed. Raises SOCError if all retries fail.
        """
        model = {
            "term_cd": term_cd,
            "subj_area_cd": subject_area.strip().upper(),
            "ses_grp_cd": "%",  # wildcard: any session group
            "class_no": "%",  # wildcard: any class number
            "crs_catlg_no": format_catalog_number(catalog_number),
        }
        return self._get_with_retry(
            COURSE_TITLES_URL,
            {
                "search_by": "subject",
                "model": json.dumps(model),
                "pageNumber": "1",
                "filterFlags": "{}",
            },
        )

    def fetch_course_summary(self, model_token: dict) -> str:
        """Call GetCourseSummary with a token from CourseTitlesView.

        The token is opaque -- handed back to UCLA verbatim. Works for both
        root tokens (lectures) and sub tokens (discussions/labs). Returns
        raw HTML. Raises SOCError if all retries fail.
        """
        return self._get_with_retry(
            COURSE_SUMMARY_URL, {"model": json.dumps(model_token), "FilterFlags": "{}"}
        )

    def _get_with_retry(self, url: str, params: dict) -> str:
        """GET with retries, returning response text.

        Retries on any RequestException, including 5xx, since SOC is
        flaky under enrollment-period load. Raises the last exception
        once MAX_RETRIES attempts are exhausted -- failing loudly beats
        returning empty HTML that would parse as "no sections".
        """
        last_error: requests.RequestException | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self._session.get(url, params=params, timeout=self._timeout)
                response.raise_for_status()

                # A challenge page arrives as a normal 200, so it has to be
                # caught here rather than by raise_for_status.
                if _is_bot_challenge(response.text):
                    raise BotChallengeError(
                        "UCLA served a bot-detection challenge. Wait a minute "
                        "and try again, or poll less frequently."
                    )

                return response.text
            except BotChallengeError:
                # Retrying immediately would only deepen the block; the
                # caller needs to back off, so report it straight away.
                raise
            except requests.RequestException as exc:
                last_error = exc
                # Sleep between attempts, never after the last one.
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)

        raise SOCError(f"GET {url} failed after {MAX_RETRIES} attempts") from last_error
