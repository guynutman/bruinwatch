"""Tests for the HTTP client.

No real requests are made. SOCClient holds one requests.Session, so
substituting a fake Session is enough to exercise every path -- including
the retry loop, which would otherwise take 20 seconds of real sleeping.
"""

import json
from unittest.mock import patch

import pytest
import requests

from bruinwatch.client import (
    COURSE_SUMMARY_URL,
    COURSE_TITLES_URL,
    MAX_RETRIES,
    SOC_URL,
    SOCClient,
    SOCError,
    format_catalog_number,
)

# --- Test doubles ------------------------------------------------------------


class FakeResponse:
    """Stands in for requests.Response, raising like the real one does."""

    def __init__(self, text: str = "<html></html>", status: int = 200):
        self.text = text
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Error")


class FakeSession:
    """Records every GET so tests can assert on URLs and params.

    Takes a list of responses to hand out in order; a response that is an
    exception instance is raised instead, which is how failure sequences
    are expressed.
    """

    def __init__(self, responses=None):
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, dict]] = []
        self._responses = list(responses or [])

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params or {}))
        if not self._responses:
            return FakeResponse()
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def fake_session():
    """Patch requests.Session so SOCClient builds against the fake.

    Also patches time.sleep: the retry path would otherwise spend
    RETRY_DELAY seconds per attempt doing nothing.
    """
    session = FakeSession()
    with (
        patch("bruinwatch.client.requests.Session", return_value=session),
        patch("bruinwatch.client.time.sleep") as sleep,
    ):
        session.sleep = sleep
        yield session


# --- format_catalog_number ---------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("32", "0032"),
        ("111", "0111"),
        ("33A", "0033A"),
        ("1", "0001"),
        ("0111", "0111"),  # already padded -- idempotent
        # Leading letters (M = multiple-listed, C = concurrent) move to the
        # END in UCLA's internal format, after the zero-padded digits.
        ("M51A", "0051A M"),
        ("M16", "0016 M"),
        ("C121", "0121 C"),
        ("M151B", "0151B M"),
        ("m51a", "0051A M"),  # normalised to upper
        ("CM121", "CM121"),  # unrecognised shape -- passed through
        ("  32  ", "0032"),  # normalised whitespace
    ],
)
def test_format_catalog_number(raw, expected):
    assert format_catalog_number(raw) == expected


def test_leading_letter_becomes_a_trailing_suffix():
    """UCLA stores M51A as "0051A M" -- the M moves, it is not a prefix.

    Getting this wrong made every M- and C-prefixed course report as "not
    found", which is indistinguishable from a course that is not offered.
    """
    assert format_catalog_number("M51A") == "0051A M"


def test_format_catalog_number_is_idempotent():
    # Formatting an already-formatted number must not double-pad it.
    once = format_catalog_number("32")
    assert format_catalog_number(once) == once


# --- __init__ ----------------------------------------------------------------


def test_init_bootstraps_cookies_from_landing_page(fake_session):
    SOCClient()
    # Exactly one request, to the landing page, purely for its cookies.
    assert len(fake_session.calls) == 1
    assert fake_session.calls[0][0] == SOC_URL


def test_init_sets_browser_headers(fake_session):
    SOCClient()
    assert "Chrome" in fake_session.headers["User-Agent"]
    # The header that makes SOC return small HTML fragments instead of a
    # ~500KB page.
    assert fake_session.headers["X-Requested-With"] == "XMLHttpRequest"
    assert fake_session.headers["Referer"] == SOC_URL


def test_init_raises_when_landing_page_is_unreachable():
    session = FakeSession([requests.ConnectionError("down")])
    with (
        patch("bruinwatch.client.requests.Session", return_value=session),
        pytest.raises(requests.RequestException),
    ):
        SOCClient()


# --- fetch_terms_page --------------------------------------------------------


def test_fetch_terms_page_returns_raw_html(fake_session):
    client = SOCClient()
    fake_session._responses.append(FakeResponse("<option value='26F'>"))

    assert client.fetch_terms_page() == "<option value='26F'>"
    assert fake_session.calls[-1][0] == SOC_URL


# --- fetch_course_titles -----------------------------------------------------


def test_fetch_course_titles_builds_the_model_param(fake_session):
    client = SOCClient()
    client.fetch_course_titles("26F", "COM SCI", "111")

    url, params = fake_session.calls[-1]
    assert url == COURSE_TITLES_URL
    assert params["search_by"] == "subject"
    assert params["pageNumber"] == "1"
    assert params["filterFlags"] == "{}"

    # model is JSON nested inside a query parameter.
    model = json.loads(params["model"])
    assert model["term_cd"] == "26F"
    assert model["subj_area_cd"] == "COM SCI"
    assert model["ses_grp_cd"] == "%"  # wildcards, or the search over-constrains
    assert model["class_no"] == "%"


def test_fetch_course_titles_zero_pads_the_catalog_number(fake_session):
    client = SOCClient()
    client.fetch_course_titles("26F", "COM SCI", "111")

    model = json.loads(fake_session.calls[-1][1]["model"])
    assert model["crs_catlg_no"] == "0111"


def test_fetch_course_titles_normalises_the_subject_area(fake_session):
    # Callers pass what the user typed; the client speaks UCLA's format.
    client = SOCClient()
    client.fetch_course_titles("26F", "  com sci  ", "m51a")

    model = json.loads(fake_session.calls[-1][1]["model"])
    assert model["subj_area_cd"] == "COM SCI"
    assert model["crs_catlg_no"] == "0051A M"


# --- fetch_course_summary ----------------------------------------------------


def test_fetch_course_summary_passes_the_token_verbatim(fake_session):
    # The token is opaque -- we hand UCLA back exactly what it gave us.
    token = {"Term": "26F", "IsRoot": True, "Token": "MDExMQ=="}
    client = SOCClient()
    client.fetch_course_summary(token)

    url, params = fake_session.calls[-1]
    assert url == COURSE_SUMMARY_URL
    assert json.loads(params["model"]) == token


def test_fetch_course_summary_uses_capital_filter_flags(fake_session):
    # UCLA spells this differently than CourseTitlesView's filterFlags.
    client = SOCClient()
    client.fetch_course_summary({"IsRoot": True})

    params = fake_session.calls[-1][1]
    assert params["FilterFlags"] == "{}"
    assert "filterFlags" not in params


def test_fetch_course_summary_works_for_sub_tokens(fake_session):
    # One method serves both hierarchy levels; only the token differs.
    client = SOCClient()
    client.fetch_course_summary({"IsRoot": False, "Path": "187336200_COMSCI0111"})

    model = json.loads(fake_session.calls[-1][1]["model"])
    assert model["IsRoot"] is False


# --- retry behaviour ---------------------------------------------------------


def test_retries_then_succeeds(fake_session):
    client = SOCClient()
    fake_session._responses.extend(
        [requests.ConnectionError("flaky"), FakeResponse("<html>ok</html>")]
    )

    assert client.fetch_terms_page() == "<html>ok</html>"


def test_gives_up_after_max_retries(fake_session):
    client = SOCClient()
    fake_session._responses.extend([requests.ConnectionError("down")] * MAX_RETRIES)

    with pytest.raises(SOCError):
        client.fetch_terms_page()


def test_retry_count_matches_max_retries(fake_session):
    client = SOCClient()
    before = len(fake_session.calls)
    fake_session._responses.extend([requests.ConnectionError("down")] * MAX_RETRIES)

    with pytest.raises(SOCError):
        client.fetch_terms_page()

    assert len(fake_session.calls) - before == MAX_RETRIES


def test_sleeps_between_attempts_but_not_after_the_last(fake_session):
    client = SOCClient()
    fake_session._responses.extend([requests.ConnectionError("down")] * MAX_RETRIES)

    with pytest.raises(SOCError):
        client.fetch_terms_page()

    # Three attempts means two gaps, not three.
    assert fake_session.sleep.call_count == MAX_RETRIES - 1


def test_http_error_status_is_retried(fake_session):
    # raise_for_status turns 5xx into HTTPError, a RequestException subclass.
    client = SOCClient()
    fake_session._responses.extend([FakeResponse(status=503), FakeResponse("ok")])

    assert client.fetch_terms_page() == "ok"


def test_failure_raises_socerror_not_requests_error(fake_session):
    # watcher.py catches SOCError so it never has to import requests.
    client = SOCClient()
    fake_session._responses.extend([requests.ConnectionError("down")] * MAX_RETRIES)

    with pytest.raises(SOCError) as exc_info:
        client.fetch_terms_page()

    # The original error survives as __cause__ for diagnosis.
    assert isinstance(exc_info.value.__cause__, requests.RequestException)


def test_failure_never_returns_empty_html(fake_session):
    # Empty HTML would parse into zero sections, which downstream looks
    # like a full class rather than a failed request.
    client = SOCClient()
    fake_session._responses.extend([requests.ConnectionError("down")] * MAX_RETRIES)

    with pytest.raises(SOCError):
        client.fetch_terms_page()
