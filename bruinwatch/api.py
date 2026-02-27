"""
bruinwatch.api — UCLA Schedule of Classes API client.

Endpoints used (all public, no auth required):
  1. CourseTitlesView  — resolve subject + catalog number into course tokens
  2. GetCourseSummary  — fetch enrollment data for a course token
     Called twice: once for lectures, once per lecture for discussions/labs.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import requests

# ─── Constants ───────────────────────────────────────────────────────────────

BASE_URL = "https://sa.ucla.edu/ro"
SOC_URL = f"{BASE_URL}/Public/SOC"
COURSE_TITLES_URL = f"{SOC_URL}/Results/CourseTitlesView"
COURSE_SUMMARY_URL = f"{SOC_URL}/Results/GetCourseSummary"

RETRY_DELAY = 10  # seconds between retries
MAX_RETRIES = 3

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Term codes that have already passed — filtered out of the term picker.
PAST_TERMS = {"25W", "25S", "25F", "26W"}


# ─── Exceptions ──────────────────────────────────────────────────────────────

class APIError(Exception):
    """Raised when the UCLA API fails after all retries."""


class CourseNotFoundError(Exception):
    """Raised when a subject + course number cannot be resolved."""


# ─── Session ─────────────────────────────────────────────────────────────────

def create_session() -> requests.Session:
    """Return a ``requests.Session`` with realistic browser headers and
    initial cookies from the SOC landing page."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html, */*; q=0.01",
        "Accept-Language": "en-US,en;q=0.9",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": SOC_URL,
    })
    s.get(SOC_URL, timeout=15)
    return s


# ─── Low-level helpers ───────────────────────────────────────────────────────

def _get_with_retry(
    session: requests.Session, url: str, params: dict[str, str],
) -> requests.Response:
    """GET *url* with retry logic.  Raises ``APIError`` after exhaustion."""
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, params=params, timeout=20)
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
    raise APIError(
        f"Request to {url} failed after {MAX_RETRIES} attempts: {last_exc}"
    )


def _parse_sections_from_html(html: str) -> list[dict[str, Any]]:
    """Parse enrollment section rows from a *GetCourseSummary* HTML blob.

    Returns a list of dicts, each with keys:
        section_id, section_label, status, enrolled, capacity,
        spots_left, waitlist_taken, waitlist_capacity
    """
    sections: list[dict[str, Any]] = []

    # ── Section labels (Lec 1, Dis 1A …) ──
    section_labels: dict[str, str] = {}
    for m in re.finditer(
        r'id="(\d+)_[^"]*-section[_]?[^"]*"[^>]*>.*?'
        r'(?:>([^<]*(?:Lec|Dis|Lab|Sem|Tut|Fld|Res|Stu|Cli|Col|Act)\s*\S*)<)',
        html, re.DOTALL,
    ):
        section_labels[m.group(1)] = m.group(2).strip()

    # Fallback — link text
    for m in re.finditer(
        r'class_id=(\d+)[^>]*>([^<]*(?:Lec|Dis|Lab|Sem|Tut|Fld|Res|Stu|Cli|Col|Act)\s*\S*)</a>',
        html, re.IGNORECASE,
    ):
        section_labels.setdefault(m.group(1), m.group(2).strip())

    # ── Status data ──
    for m in re.finditer(
        r'id="(\d+)_[^"]*-status_data"[^>]*><p>\s*(.*?)\s*</p>',
        html, re.DOTALL,
    ):
        section_id = m.group(1)
        raw = m.group(2)
        clean = re.sub(r"<[^>]+>", "|", raw).strip()
        clean = re.sub(r"\s+", " ", clean)
        parts = [p.strip() for p in clean.split("|") if p.strip()]

        status = "Unknown"
        enrolled = capacity = spots_left = waitlist_taken = 0

        for part in parts:
            if part in ("Open", "Closed", "Cancelled", "Tentative"):
                status = part
            elif part.startswith("Closed"):
                status = "Closed"
            elif "Enrolled" in part:
                nums = re.findall(r"\d+", part)
                if len(nums) >= 2:
                    enrolled, capacity = int(nums[0]), int(nums[1])
            elif "Spots Left" in part:
                nums = re.findall(r"\d+", part)
                if nums:
                    spots_left = int(nums[0])
            elif "Class Full" in part:
                status = "Closed"
                nums = re.findall(r"\d+", part)
                if nums:
                    capacity = int(nums[0])
                    enrolled = capacity
            elif "capacity" in part and "enrolled" in part:
                nums = re.findall(r"\d+", part)
                if len(nums) >= 2:
                    capacity, enrolled = int(nums[0]), int(nums[1])
                if len(nums) >= 3:
                    waitlist_taken = int(nums[2])

        if spots_left == 0 and status == "Open":
            spots_left = max(0, capacity - enrolled)

        # ── Waitlist ──
        waitlist_capacity = 0
        wl_m = re.search(
            rf'id="{section_id}_[^"]*-waitlist_data"[^>]*>\s*<p>(.*?)</p>',
            html, re.DOTALL,
        )
        if wl_m:
            wl_text = re.sub(r"<[^>]+>", " ", wl_m.group(1)).strip()
            wl_nums = re.findall(r"\d+", wl_text)
            if "Taken" in wl_text and len(wl_nums) >= 2:
                waitlist_taken = int(wl_nums[0])
                waitlist_capacity = int(wl_nums[1])

        sections.append({
            "section_id": section_id,
            "section_label": section_labels.get(section_id, f"Section {section_id}"),
            "status": status,
            "enrolled": enrolled,
            "capacity": capacity,
            "spots_left": spots_left,
            "waitlist_taken": waitlist_taken,
            "waitlist_capacity": waitlist_capacity,
        })

    return sections


def _extract_sub_course_data(html: str) -> list[dict[str, Any]]:
    """Extract non-root ``AddToCourseData`` entries (point to discussions)."""
    subs: list[dict[str, Any]] = []
    for m in re.finditer(r'AddToCourseData\("([^"]+)",(\{[^}]+\})\)', html):
        data = json.loads(m.group(2))
        if not data.get("IsRoot"):
            subs.append(data)
    return subs


# ─── Public helpers ──────────────────────────────────────────────────────────

def format_catalog_number(crs_num: str) -> str:
    """Zero-pad the numeric prefix to 4 digits.

    >>> format_catalog_number("32")
    '0032'
    >>> format_catalog_number("33A")
    '0033A'
    >>> format_catalog_number("M51A")
    'M51A'
    """
    num_match = re.match(r"^(\d+)(.*)", crs_num)
    if num_match:
        return num_match.group(1).zfill(4) + num_match.group(2)
    return crs_num


def fetch_available_terms(session: requests.Session) -> list[dict[str, str]]:
    """Return ``[{"code": "26S", "name": "Spring 2026"}, …]`` for current/future terms."""
    r = session.get(SOC_URL, timeout=15)
    r.raise_for_status()
    pattern = re.compile(
        r'<option[^>]*value=["\'](\d{2}[A-Z0-9]+)["\'][^>]*>\s*([^<]+?)\s*</option>'
    )
    terms: list[dict[str, str]] = []
    seen: set[str] = set()
    for val, text in pattern.findall(r.text):
        if val not in seen and not val.startswith("%") and val not in PAST_TERMS:
            terms.append({"code": val, "name": text.strip()})
            seen.add(val)
    return terms


# ─── Core public functions ───────────────────────────────────────────────────

def get_course_titles(
    session: requests.Session,
    term_cd: str,
    subj_area_cd: str,
    crs_catlg_no: str,
) -> list[dict[str, Any]]:
    """Resolve a subject + catalog number into a list of root course dicts.

    Each dict has keys: ``id``, ``title``, ``data`` (raw API token dict).
    """
    model = {
        "term_cd": term_cd,
        "subj_area_cd": subj_area_cd,
        "ses_grp_cd": "%",
        "class_no": "%",
        "crs_catlg_no": crs_catlg_no,
    }
    params = {
        "search_by": "subject",
        "model": json.dumps(model),
        "pageNumber": "1",
        "filterFlags": json.dumps({}),
    }
    r = _get_with_retry(session, COURSE_TITLES_URL, params)

    title_match = re.search(
        r'aria-controls="[^"]*"[^>]*>([^<]+)</button>', r.text,
    )
    title = title_match.group(1).strip() if title_match else "Unknown Course"

    courses: list[dict[str, Any]] = []
    for cid, cjson in re.findall(
        r'AddToCourseData\("([^"]+)",(\{[^}]+\})\)', r.text,
    ):
        data = json.loads(cjson)
        if data.get("IsRoot"):
            courses.append({"id": cid, "title": title, "data": data})
    return courses


def get_course_summary(
    session: requests.Session, course_data: dict[str, Any],
) -> list[dict[str, Any]]:
    """Fetch full enrollment data (lectures + discussions/labs).

    Returns a list of lecture dicts. Each lecture dict has a ``"discussions"``
    key containing a list of discussion/lab section dicts.
    """
    params = {
        "model": json.dumps(course_data),
        "FilterFlags": json.dumps({}),
    }
    r = _get_with_retry(session, COURSE_SUMMARY_URL, params)
    lectures = _parse_sections_from_html(r.text)
    sub_data_list = _extract_sub_course_data(r.text)

    for i, lec in enumerate(lectures):
        lec["discussions"] = []
        if i < len(sub_data_list):
            try:
                sub_r = _get_with_retry(
                    session, COURSE_SUMMARY_URL,
                    {"model": json.dumps(sub_data_list[i]),
                     "FilterFlags": json.dumps({})},
                )
                lec["discussions"] = _parse_sections_from_html(sub_r.text)
            except APIError:
                pass  # non-critical — lecture data is still valid

    return lectures


def fetch_enrollment(
    session: requests.Session,
    term_cd: str,
    subject: str,
    course_number: str,
) -> dict[str, Any]:
    """High-level convenience: resolve + fetch a single course.

    Returns::

        {
            "subject": "COM SCI",
            "course_number": "33",
            "course_title": "33 - Introduction to Computer Organization",
            "course_data": {…},          # raw API token (for future polls)
            "sections": [ … ],           # lectures, each with .discussions
        }

    Raises ``CourseNotFoundError`` if the course cannot be resolved.
    """
    catlg = format_catalog_number(course_number)
    courses = get_course_titles(session, term_cd, subject, catlg)
    if not courses:
        # Retry with raw number (handles edge cases)
        courses = get_course_titles(session, term_cd, subject, course_number)
    if not courses:
        raise CourseNotFoundError(
            f"No course found for {subject} {course_number} in term {term_cd}."
        )
    course = courses[0]
    sections = get_course_summary(session, course["data"])
    return {
        "subject": subject,
        "course_number": course_number,
        "course_title": course["title"],
        "course_data": course["data"],
        "sections": sections,
    }
