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
#     <option class="select_term" value="26F"
#             data-yearText="Fall 2026">Fall 2026</option>
# [^>]* absorbs any extra attributes -- the current term carries selected="selected".
TERM_OPTION_RE = re.compile(
    r'<option[^>]*\bvalue="(?P<code>\d{2}[A-Z0-9])"[^>]*>(?P<name>[^<]+)</option>'
)

# Course data tokens, embedded as JavaScript calls inside <script> blocks:
#     Iwe_ClassSearch_SearchResults.AddToCourseData("COMSCI0111",{"Term":"26F",...})
# The captured group is the JSON object literal. [^}]+ stops at the first
# closing brace, which is safe here because these objects are never nested.
COURSE_DATA_RE = re.compile(r'AddToCourseData\("[^"]+",(\{[^}]+\})\)')

# Course title, rendered as a collapsible button on CourseTitlesView:
#     <button class="linkLikeButton" id="COMSCI0111-title" type="button"
#             aria-controls="COMSCI0111-container" ...>
#       111 - Operating Systems Principles</button>
# Anchored on the id suffix rather than the class, since -title names the
# element's role while class names are styling and change more freely.
COURSE_TITLE_RE = re.compile(
    r'<button[^>]*\bid="[^"]*-title"[^>]*>(?P<title>[^<]+)</button>'
)

# Section label, in the anchor text of the -section div:
#     <div class="cls-section click_info" id="187336201_187336200_COMSCI0111-section">
#       <p class="hide-small">
#         <a href="...class_id=187336201...">Lab 1A</a></p>
# Sub-level ids nest as {section}_{parent}_{course}, so anchoring the capture
# to the LEADING digits yields the section's own id at both levels.
SECTION_LABEL_RE = re.compile(
    r'id="(?P<sid>\d+)_[^"]*-section"[^>]*>.*?<a\b[^>]*>(?P<label>[^<]+)</a>',
    re.DOTALL,
)

# Enrollment status, one <p> holding <br />-delimited fields:
#     <div class="statusColumn" id="187336201_..._COMSCI0111-status_data">
#       <p><i class="icon-unlock" ...></i>Open<br />52 of 60 Enrolled
#          <br />8 Spots Left</p>
STATUS_BLOCK_RE = re.compile(
    r'id="(?P<sid>\d+)_[^"]*-status_data"[^>]*>\s*<p>(?P<body>.*?)</p>',
    re.DOTALL,
)

# Waitlist, same shape. The div is absent entirely for sections with no
# waitlist, which is why a missing entry means None rather than zero.
#     <div class="waitlistColumn" id="187336201_..._COMSCI0111-waitlist_data">
#       <p>0 of 15 Taken</p>
WAITLIST_BLOCK_RE = re.compile(
    r'id="(?P<sid>\d+)_[^"]*-waitlist_data"[^>]*>\s*<p>(?P<body>.*?)</p>',
    re.DOTALL,
)

# The "N of M" pairs that carry every count UCLA reports, in both
# "52 of 60 Enrolled" and "0 of 15 Taken".
X_OF_Y_RE = re.compile(r"(?P<x>\d+)\s+of\s+(?P<y>\d+)")

# <br /> in any of its spellings, used as a field delimiter before tags are
# stripped -- otherwise "Open" and "52 of 60 Enrolled" would run together.
BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)

# Any remaining HTML tag, e.g. the <i> icon that precedes the status text.
TAG_RE = re.compile(r"<[^>]+>")

# Label prefixes UCLA uses, mapped to the kinds we model. Checked
# case-insensitively against the start of the label ("Lab 1A" -> LAB).
_KIND_PREFIXES: tuple[tuple[str, SectionKind], ...] = (
    ("lec", SectionKind.LECTURE),
    ("dis", SectionKind.DISCUSSION),
    ("lab", SectionKind.LAB),
)


# --- Public functions --------------------------------------------------------


def parse_course_title(html: str) -> str | None:
    """Extract the course title from CourseTitlesView HTML.

    e.g. "111 - Operating Systems Principles". Returns None if absent.
    """
    match = COURSE_TITLE_RE.search(html)
    if match is None:
        return None

    title = match.group("title").strip()
    return title or None


def parse_model_tokens(html: str) -> list[dict]:
    """Root-level AddToCourseData objects from CourseTitlesView HTML.

    These opaque tokens are what GetCourseSummary requires. Only entries
    with IsRoot true.
    """
    return _parse_course_data(html, is_root=True)


def parse_sub_tokens(html: str) -> list[dict]:
    """Non-root AddToCourseData objects from GetCourseSummary HTML.

    Tokens for fetching the discussion/lab sub-level.
    """
    return _parse_course_data(html, is_root=False)


def parse_sections(html: str) -> list[SectionStatus]:
    """Parse enrollment data from GetCourseSummary HTML.

    The core parser. Returns [] if the HTML contains no sections.

    Status blocks drive the iteration: a section without enrollment data is
    unusable, whereas labels and waitlists are optional and get defaulted.
    """
    labels = {
        m.group("sid"): m.group("label").strip()
        for m in SECTION_LABEL_RE.finditer(html)
    }
    waitlists = {
        m.group("sid"): m.group("body") for m in WAITLIST_BLOCK_RE.finditer(html)
    }

    sections: list[SectionStatus] = []

    for match in STATUS_BLOCK_RE.finditer(html):
        section_id = match.group("sid")
        status_text, enrolled, capacity = _parse_status_block(match.group("body"))
        waitlisted, waitlist_capacity = _parse_waitlist_block(waitlists.get(section_id))
        label = labels.get(section_id) or f"Section {section_id}"

        sections.append(
            SectionStatus(
                section_id=section_id,
                label=label,
                kind=_infer_kind(label),
                enrolled=enrolled,
                capacity=capacity,
                waitlisted=waitlisted,
                waitlist_capacity=waitlist_capacity,
                status_text=status_text,
            )
        )

    return sections


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


# --- Internal helpers --------------------------------------------------------


def _parse_course_data(html: str, *, is_root: bool) -> list[dict]:
    """Shared helper: extract AddToCourseData tokens, filtered by IsRoot.

    Tokens are opaque -- they are handed back to UCLA verbatim, never
    constructed by us. A token whose JSON fails to parse is skipped rather
    than aborting the whole page: one malformed entry should not cost us
    the others.
    """
    tokens: list[dict] = []

    for match in COURSE_DATA_RE.finditer(html):
        try:
            token = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if bool(token.get("IsRoot")) is is_root:
            tokens.append(token)

    return tokens


def _text_fields(raw_html: str) -> list[str]:
    """Flatten an inner-HTML fragment into its <br />-delimited text fields.

        '<i class="icon"></i>Open<br />52 of 60 Enrolled<br />8 Spots Left'
        -> ['Open', '52 of 60 Enrolled', '8 Spots Left']

    <br /> is swapped for a sentinel before tags are stripped; otherwise the
    fields would run together into one unsplittable string.
    """
    text = BR_RE.sub("\x00", raw_html)
    text = TAG_RE.sub("", text)
    return [field.strip() for field in text.split("\x00") if field.strip()]


def _parse_status_block(raw_html: str) -> tuple[str, int, int]:
    """(status_text, enrolled, capacity) from a -status_data <p> body.

    UCLA puts its label first and the counts in a later field:
        'Open<br />52 of 60 Enrolled<br />8 Spots Left'

    "Class Full" carries a single count rather than a pair, so enrolled is
    set equal to capacity. Spots Left is deliberately ignored -- it is
    derivable, and SectionStatus.seats_available owns that arithmetic.
    """
    fields = _text_fields(raw_html)
    if not fields:
        return "", 0, 0

    status_text = fields[0]
    enrolled = capacity = 0

    for field in fields[1:]:
        lowered = field.casefold()
        pair = X_OF_Y_RE.search(field)

        if pair and "enrolled" in lowered:
            enrolled, capacity = int(pair.group("x")), int(pair.group("y"))
            break

        if "class full" in lowered:
            # Reported as "Class Full (120)" -- one number, meaning both.
            solo = re.search(r"\d+", field)
            if solo:
                capacity = enrolled = int(solo.group())
            break

    return status_text, enrolled, capacity


def _parse_waitlist_block(raw_html: str | None) -> tuple[int, int | None]:
    """(waitlisted, waitlist_capacity) from a -waitlist_data <p> body.

        '0 of 15 Taken' -> (0, 15)

    Returns (0, None) when the div is absent or says there is no waitlist:
    None means "no waitlist exists", which is not the same as an empty one.
    """
    if raw_html is None:
        return 0, None

    text = " ".join(_text_fields(raw_html))
    if not text or "no waitlist" in text.casefold():
        return 0, None

    pair = X_OF_Y_RE.search(text)
    if pair is None:
        return 0, None

    return int(pair.group("x")), int(pair.group("y"))


def _infer_kind(label: str) -> SectionKind:
    """Map a section label to its kind, e.g. 'Lab 1A' -> LAB.

    Defaults to LECTURE for unrecognised labels: UCLA has kinds we do not
    model (Sem, Tut, Fld, Stu), and treating them as the top-level kind is
    less wrong than inventing a category.
    """
    head = label.strip().casefold()
    for prefix, kind in _KIND_PREFIXES:
        if head.startswith(prefix):
            return kind
    return SectionKind.LECTURE
