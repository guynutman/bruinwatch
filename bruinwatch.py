# BruinWatch - UCLA Course Seat Availability Monitor
#
# Usage:
#   1. Install dependencies: pip install -r requirements.txt
#   2. Run: python bruinwatch.py
#   3. Follow the prompts to enter your course info
#   4. Press Ctrl+C to stop monitoring
#
# This script monitors the UCLA Schedule of Classes for open seats and alerts
# you with a visible ASCII banner and system sound when a seat opens up.

import requests
import json
import re
import time
import sys
import os
import platform
from datetime import datetime

try:
    from plyer import notification as desktop_notify
except ImportError:
    desktop_notify = None

# ─── Constants ───────────────────────────────────────────────────────────────

BASE_URL = "https://sa.ucla.edu/ro"
SOC_URL  = f"{BASE_URL}/Public/SOC"
COURSE_TITLES_URL = f"{SOC_URL}/Results/CourseTitlesView"
COURSE_SUMMARY_URL = f"{SOC_URL}/Results/GetCourseSummary"

POLL_INTERVAL = 180      # seconds between polls (3 minutes)
RETRY_DELAY   = 10       # seconds between retries on failure
MAX_RETRIES   = 3        # max retries per poll cycle

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# ─── ANSI Colors ─────────────────────────────────────────────────────────────

# Enable ANSI escape sequences on Windows 10+
if platform.system() == "Windows":
    os.system("")  # triggers VT100 mode in cmd / PowerShell

GREEN  = "\033[92m"
RED    = "\033[91m"
RESET  = "\033[0m"


# ─── Alert ───────────────────────────────────────────────────────────────────

def trigger_alert(course_name: str, seats_remaining: int, section_info: str):
    """Send a desktop notification and play a system sound."""

    # ── Desktop notification ──
    if desktop_notify:
        try:
            desktop_notify.notify(
                title="BruinWatch — Seat Available!",
                message=f"{course_name}\n{section_info}: {seats_remaining} spot(s) open",
                app_name="BruinWatch",
                timeout=10,
            )
        except Exception:
            pass

    # ── System sound ──
    system = platform.system()
    if system == "Darwin":
        os.system('say "Seat available in your course"')
    elif system == "Windows":
        try:
            import winsound
            winsound.Beep(1000, 1000)
        except Exception:
            print("\a")
    elif system == "Linux":
        os.system(
            'paplay /usr/share/sounds/freedesktop/stereo/bell.oga '
            '|| echo -e "\\a"'
        )
    else:
        print("\a")


# ─── API Helpers ─────────────────────────────────────────────────────────────

def create_session() -> requests.Session:
    """Create a requests session with realistic browser headers."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html, */*; q=0.01",
        "Accept-Language": "en-US,en;q=0.9",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": SOC_URL,
    })
    # Grab initial cookies / session state
    s.get(SOC_URL, timeout=15)
    return s


def fetch_available_terms(session: requests.Session) -> list[dict]:
    """Fetch available term codes from the SOC main page."""
    r = session.get(SOC_URL, timeout=15)
    r.raise_for_status()
    # Parse <option value="26S">Spring 2026</option> etc.
    # Only include actual academic terms (not session sub-options)
    term_pattern = re.compile(
        r'<option[^>]*value=["\'](\d{2}[A-Z0-9]+)["\'][^>]*>\s*([^<]+?)\s*</option>'
    )
    # Only include Spring 2026 and later (past terms are not useful)
    # Term codes: YYF=Fall, YYW=Winter, YYS=Spring, YY1=Summer
    # Academic ordering within a year: W < S < 1 < F
    PAST_TERMS = {"25W", "25S", "25F", "26W"}  # already occurred
    terms = []
    seen = set()
    for val, text in term_pattern.findall(r.text):
        if val not in seen and not val.startswith("%") and val not in PAST_TERMS:
            terms.append({"code": val, "name": text.strip()})
            seen.add(val)
    return terms


def fetch_with_retry(
    session: requests.Session, url: str, params: dict
) -> requests.Response | None:
    """GET with retry logic: up to MAX_RETRIES attempts with RETRY_DELAY."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, params=params, timeout=20)
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            print(f"  [!] Request failed (attempt {attempt}/{MAX_RETRIES}): {exc}")
            if attempt < MAX_RETRIES:
                print(f"      Retrying in {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)
    print("  [!] All retries exhausted. Skipping this poll cycle.")
    return None


def get_course_titles(
    session: requests.Session, term_cd: str, subj_area_cd: str,
    crs_catlg_no: str
) -> list[dict]:
    """
    Call CourseTitlesView to get the list of matching courses & their
    internal data tokens needed for GetCourseSummary.
    Returns a list of dicts with keys: id, title, data (the raw JSON object).
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
    r = fetch_with_retry(session, COURSE_TITLES_URL, params)
    if r is None:
        return []

    courses = []
    # Extract course title from the heading
    title_match = re.search(
        r'aria-controls="[^"]*"[^>]*>([^<]+)</button>', r.text
    )
    title = title_match.group(1).strip() if title_match else "Unknown Course"

    # Extract course data JSON
    data_matches = re.findall(
        r'AddToCourseData\("([^"]+)",(\{[^}]+\})\)', r.text
    )
    for course_id, course_json_str in data_matches:
        # Only root-level entries (not individual sections)
        data = json.loads(course_json_str)
        if data.get("IsRoot"):
            courses.append({
                "id": course_id,
                "title": title,
                "data": data,
            })
    return courses


def _parse_sections_from_html(html: str) -> list[dict]:
    """Parse enrollment section data from a GetCourseSummary HTML response."""
    sections = []

    # ── Extract section labels (Lec 1, Dis 1A, etc.) ──
    section_labels = {}
    for m in re.finditer(
        r'id="(\d+)_[^"]*-section[_]?[^"]*"[^>]*>.*?'
        r'(?:>([^<]*(?:Lec|Dis|Lab|Sem|Tut|Fld|Res|Stu|Cli|Col|Act)\s*\S*)<)',
        html, re.DOTALL
    ):
        section_labels[m.group(1)] = m.group(2).strip()

    # Fallback: extract from link text
    for m in re.finditer(
        r'class_id=(\d+)[^>]*>([^<]*(?:Lec|Dis|Lab|Sem|Tut|Fld|Res|Stu|Cli|Col|Act)\s*\S*)</a>',
        html, re.IGNORECASE
    ):
        sid = m.group(1)
        if sid not in section_labels:
            section_labels[sid] = m.group(2).strip()

    # ── Extract status data ──
    for m in re.finditer(
        r'id="(\d+)_[^"]*-status_data"[^>]*><p>\s*(.*?)\s*</p>',
        html, re.DOTALL
    ):
        section_id = m.group(1)
        raw_status = m.group(2)
        clean = re.sub(r'<[^>]+>', '|', raw_status).strip()
        clean = re.sub(r'\s+', ' ', clean)
        parts = [p.strip() for p in clean.split('|') if p.strip()]

        status = "Unknown"
        enrolled = 0
        capacity = 0
        spots_left = 0
        waitlist_taken = 0

        for part in parts:
            if part in ("Open", "Closed", "Cancelled", "Tentative"):
                status = part
            elif part.startswith("Closed"):
                status = "Closed"
            elif "Enrolled" in part:
                nums = re.findall(r'(\d+)', part)
                if len(nums) >= 2:
                    enrolled = int(nums[0])
                    capacity = int(nums[1])
            elif "Spots Left" in part:
                nums = re.findall(r'(\d+)', part)
                if nums:
                    spots_left = int(nums[0])
            elif "Class Full" in part:
                status = "Closed"
                nums = re.findall(r'(\d+)', part)
                if nums:
                    capacity = int(nums[0])
                    enrolled = capacity
            elif "capacity" in part and "enrolled" in part:
                nums = re.findall(r'(\d+)', part)
                if len(nums) >= 2:
                    capacity = int(nums[0])
                    enrolled = int(nums[1])
                if len(nums) >= 3:
                    waitlist_taken = int(nums[2])

        if spots_left == 0 and status == "Open":
            spots_left = max(0, capacity - enrolled)

        # ── Extract matching waitlist ──
        waitlist_capacity = 0
        wl_match = re.search(
            rf'id="{section_id}_[^"]*-waitlist_data"[^>]*>\s*<p>(.*?)</p>',
            html, re.DOTALL
        )
        if wl_match:
            wl_text = re.sub(r'<[^>]+>', ' ', wl_match.group(1)).strip()
            wl_nums = re.findall(r'(\d+)', wl_text)
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


def _extract_sub_course_data(html: str) -> list[dict]:
    """Extract non-root AddToCourseData entries from summary HTML."""
    subs = []
    for m in re.finditer(r'AddToCourseData\("([^"]+)",(\{[^}]+\})\)', html):
        data = json.loads(m.group(2))
        if not data.get("IsRoot"):
            subs.append(data)
    return subs


def get_course_summary(
    session: requests.Session, course_data: dict
) -> list[dict]:
    """
    Call GetCourseSummary to retrieve enrollment data for a course.
    Automatically fetches discussion/lab sub-levels for each lecture.
    Returns a list of section dicts.  Each lecture's discussions are
    stored in a 'discussions' key on the lecture dict.
    """
    params = {
        "model": json.dumps(course_data),
        "FilterFlags": json.dumps({}),
    }
    r = fetch_with_retry(session, COURSE_SUMMARY_URL, params)
    if r is None:
        return []

    html = r.text
    lectures = _parse_sections_from_html(html)

    # For each lecture, fetch discussion/lab sub-level
    sub_data_list = _extract_sub_course_data(html)

    for i, lec in enumerate(lectures):
        lec["discussions"] = []
        # Match sub-data to lecture by index (one sub-entry per lecture)
        if i < len(sub_data_list):
            sub_r = fetch_with_retry(
                session, COURSE_SUMMARY_URL,
                {"model": json.dumps(sub_data_list[i]), "FilterFlags": json.dumps({})},
            )
            if sub_r:
                lec["discussions"] = _parse_sections_from_html(sub_r.text)

    return lectures


# ─── Input / Validation ─────────────────────────────────────────────────────

def choose_term(session: requests.Session) -> tuple[str, str]:
    """Prompt the user to pick a term. Returns (term_cd, term_name)."""
    terms = fetch_available_terms(session)
    if not terms:
        print("Error: could not fetch available terms from UCLA SOC.")
        sys.exit(1)

    print("\nAvailable terms:")
    for i, t in enumerate(terms, 1):
        print(f"  [{i}] {t['name']}")

    while True:
        choice = input("\nSelect a term number [1]: ").strip()
        if choice == "":
            choice = "1"
        if choice.isdigit() and 1 <= int(choice) <= len(terms):
            idx = int(choice) - 1
            return terms[idx]["code"], terms[idx]["name"]
        print("Invalid selection. Try again.")


def format_catalog_number(crs_num: str) -> str:
    """Zero-pad the numeric prefix to 4 digits.
    e.g. '32' -> '0032', '33A' -> '0033A', 'M51A' -> 'M51A'
    """
    num_match = re.match(r'^(\d+)(.*)', crs_num)
    if num_match:
        return num_match.group(1).zfill(4) + num_match.group(2)
    return crs_num


def validate_course(
    session: requests.Session, term_cd: str, term_name: str,
    subj: str, crs_num: str,
) -> dict | None:
    """Try to find a course and return its config dict, or None."""
    crs_catlg_no = format_catalog_number(crs_num)
    courses = get_course_titles(session, term_cd, subj, crs_catlg_no)
    if not courses:
        courses = get_course_titles(session, term_cd, subj, crs_num)
    if not courses:
        return None
    course = courses[0]
    return {
        "term_cd": term_cd,
        "term_name": term_name,
        "subj_area_cd": subj,
        "crs_num_display": crs_num,
        "course_title": course["title"],
        "course_data": course["data"],
    }


def get_user_inputs(session: requests.Session) -> list[dict]:
    """Gather and validate user inputs. Returns a list of course configs."""
    term_cd, term_name = choose_term(session)
    print(f"\n→ Selected term: {term_name} ({term_cd})")

    watchlist: list[dict] = []

    while True:
        # Subject area
        while True:
            subj = input("\nEnter subject area (e.g. COM SCI, MATH, PHYSICS): ").strip().upper()
            if subj:
                break
            print("Subject area cannot be empty.")

        # Course number
        while True:
            crs_num = input("Enter course number (e.g. 32, 131, M51A): ").strip().upper()
            if crs_num:
                break
            print("Course number cannot be empty.")

        # ── Validate ──
        print(f"\nValidating {subj} {crs_num} for {term_name}...")
        config = validate_course(session, term_cd, term_name, subj, crs_num)
        if config is None:
            print(f"  ✗ No course found for {subj} {crs_num} in {term_name}.")
            print(f"    Check the subject area / number on: {SOC_URL}")
        else:
            print(f"  ✓ Added: {config['course_title']}")
            watchlist.append(config)

        # Ask to add more
        more = input("\nAdd another course? (y/n) [n]: ").strip().lower()
        if more != "y":
            break

    if not watchlist:
        print("\nNo courses added. Exiting.")
        sys.exit(1)

    return watchlist


# ─── Polling Loop ───────────────────────────────────────────────────────────

def poll_once(session: requests.Session, config: dict) -> list[dict]:
    """Poll one course and print results. Returns its sections."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    course_label = f"{config['subj_area_cd']} {config['crs_num_display']}"

    sections = get_course_summary(session, config["course_data"])

    if not sections:
        print(f"  [{now}] {course_label}: No section data returned (site may be down)")
        return []

    print(f"\n  {'─' * 72}")
    print(f"  {course_label} — {config['course_title']}")
    print(f"  {'─' * 72}")
    print(
        f"  {'Section':<16} {'Status':<10} {'Enrolled':<14} "
        f"{'Spots Left':<12} {'Waitlist':<12}"
    )
    print(f"  {'─' * 64}")

    def format_section(sec: dict, indent: str = "") -> str:
        label = indent + sec["section_label"]
        enrolled_str = f"{sec['enrolled']}/{sec['capacity']}"
        wl_str = (
            f"{sec['waitlist_taken']}/{sec['waitlist_capacity']}"
            if sec["waitlist_capacity"] > 0 else "N/A"
        )
        line = (
            f"  {label:<16} {sec['status']:<10} {enrolled_str:<14} "
            f"{str(sec['spots_left']):<12} {wl_str:<12}"
        )
        # Color-code: green if spots available, red if full/closed
        if sec["spots_left"] > 0:
            return f"{GREEN}{line}{RESET}"
        return f"{RED}{line}{RESET}"

    alerted = False  # only one sound per poll cycle

    for lec in sections:
        # Print lecture row
        print(format_section(lec))
        if lec["spots_left"] > 0 and not alerted:
            trigger_alert(
                course_name=f"{course_label} — {config['course_title']}",
                seats_remaining=lec["spots_left"],
                section_info=lec["section_label"],
            )
            alerted = True

        # Print discussions/labs indented under their lecture
        for dis in lec.get("discussions", []):
            print(format_section(dis, indent="  "))
            if dis["spots_left"] > 0 and not alerted:
                trigger_alert(
                    course_name=f"{course_label} — {config['course_title']}",
                    seats_remaining=dis["spots_left"],
                    section_info=f"{lec['section_label']} > {dis['section_label']}",
                )
                alerted = True

    return sections


def poll_all(session: requests.Session, watchlist: list[dict]):
    """Poll all courses in the watchlist."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'═' * 72}")
    print(f"  [{now}]  Polling {len(watchlist)} course(s)...")
    print(f"{'═' * 72}")
    for config in watchlist:
        poll_once(session, config)


def main():
    print("=" * 60)
    print("  BruinWatch — UCLA Course Seat Availability Monitor")
    print("=" * 60)

    if desktop_notify is None:
        print("  [info] Install 'plyer' for desktop notifications:")
        print("         pip install plyer")

    session = create_session()
    watchlist = get_user_inputs(session)

    print(f"\n{'─' * 60}")
    print(f"  Monitoring {len(watchlist)} course(s):")
    for cfg in watchlist:
        print(f"    • {cfg['subj_area_cd']} {cfg['crs_num_display']} — {cfg['course_title']}")
    print(f"  Watching all lectures and discussions.")
    print(f"  Polling every {POLL_INTERVAL // 60} minutes. Press Ctrl+C to stop.")
    print(f"{'─' * 60}")

    try:
        while True:
            poll_all(session, watchlist)
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print(f"\n\n{'─' * 60}")
        print("  BruinWatch stopped. Good luck with enrollment!")
        print(f"{'─' * 60}")
        sys.exit(0)


if __name__ == "__main__":
    main()
