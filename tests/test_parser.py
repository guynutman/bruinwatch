"""Tests for the HTML parsers, run against saved fixtures.

Fixtures make these tests deterministic and offline: enrollment counts on
the live site change by the minute, and UCLA will not serve us a cancelled
section on demand. Cases the live capture cannot show are built as small
hand-written HTML snippets instead.
"""

from pathlib import Path

import pytest

from bruinwatch.models import SectionKind
from bruinwatch.parser import (
    _infer_kind,
    _parse_status_block,
    _parse_waitlist_block,
    _text_fields,
    parse_available_terms,
    parse_course_title,
    parse_model_tokens,
    parse_sections,
    parse_sub_tokens,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# Loaded once at module import -- these are read-only inputs, so there is no
# isolation benefit to re-reading them per test.
LANDING_HTML = load("soc_landing_sample.html")
TITLES_HTML = load("course_titles_sample.html")
SUMMARY_HTML = load("course_summary_sample.html")
SUMMARY_SUB_HTML = load("course_summary_sub_sample.html")


# --- parse_available_terms ---------------------------------------------------


def test_parses_terms_from_fixture():
    terms = parse_available_terms(LANDING_HTML)
    assert ("26F", "Fall 2026") in terms
    assert ("26S", "Spring 2026") in terms


def test_terms_preserve_document_order():
    codes = [code for code, _ in parse_available_terms(LANDING_HTML)]
    assert codes[:3] == ["27S", "27W", "26F"]


def test_terms_are_deduplicated():
    codes = [code for code, _ in parse_available_terms(LANDING_HTML)]
    assert len(codes) == len(set(codes))


def test_summer_sessions_are_distinct_terms():
    # UCLA splits summer into 261/262 with different names; the parser must
    # not collapse them just because both are "Summer 2026"-ish.
    terms = dict(parse_available_terms(LANDING_HTML))
    assert terms["261"] != terms["262"]


def test_selected_attribute_does_not_break_matching():
    # The current term carries selected="selected" between value and ">".
    html = '<option value="26F" data-x="y" selected="selected">Fall 2026</option>'
    assert parse_available_terms(html) == [("26F", "Fall 2026")]


def test_terms_ignores_non_term_options():
    html = '<option value="COM SCI">Computer Science</option>'
    assert parse_available_terms(html) == []


def test_terms_on_empty_html():
    assert parse_available_terms("") == []


# --- parse_course_title ------------------------------------------------------


def test_parses_course_title_from_fixture():
    assert parse_course_title(TITLES_HTML) == "111 - Operating Systems Principles"


def test_title_returns_none_when_absent():
    assert parse_course_title("<html><body>no title here</body></html>") is None


def test_title_returns_none_when_blank():
    # Empty is reported as absent, never as "" -- callers check `is None`.
    assert parse_course_title('<button id="X-title">   </button>') is None


# --- parse_model_tokens / parse_sub_tokens -----------------------------------


def test_parses_root_token_from_titles_fixture():
    tokens = parse_model_tokens(TITLES_HTML)
    assert len(tokens) == 1
    assert tokens[0]["IsRoot"] is True
    assert tokens[0]["SubjectAreaCode"] == "COM SCI"
    assert tokens[0]["Term"] == "26F"


def test_titles_fixture_has_no_sub_tokens():
    assert parse_sub_tokens(TITLES_HTML) == []


def test_parses_sub_token_from_summary_fixture():
    tokens = parse_sub_tokens(SUMMARY_HTML)
    assert len(tokens) == 1
    assert tokens[0]["IsRoot"] is False
    assert tokens[0]["Path"] == "187336200_COMSCI0111"


def test_summary_fixture_root_token_is_not_returned_as_sub():
    roots = parse_model_tokens(SUMMARY_HTML)
    subs = parse_sub_tokens(SUMMARY_HTML)
    assert all(t["IsRoot"] for t in roots)
    assert not any(t["IsRoot"] for t in subs)


def test_malformed_token_json_is_skipped_not_raised():
    # One bad entry must not cost us the others.
    html = (
        'AddToCourseData("bad",{not valid json})'
        'AddToCourseData("good",{"IsRoot":true,"Term":"26F"})'
    )
    tokens = parse_model_tokens(html)
    assert len(tokens) == 1
    assert tokens[0]["Term"] == "26F"


def test_token_missing_isroot_key_counts_as_non_root():
    html = 'AddToCourseData("x",{"Term":"26F"})'
    assert parse_model_tokens(html) == []
    assert len(parse_sub_tokens(html)) == 1


def test_tokens_on_empty_html():
    assert parse_model_tokens("") == []
    assert parse_sub_tokens("") == []


# --- parse_sections: real fixtures -------------------------------------------


def test_parses_lecture_from_summary_fixture():
    sections = parse_sections(SUMMARY_HTML)
    assert len(sections) == 1

    lecture = sections[0]
    assert lecture.section_id == "187336200"
    assert lecture.label == "Lec 1"
    assert lecture.kind is SectionKind.LECTURE
    assert (lecture.enrolled, lecture.capacity) == (91, 120)
    assert (lecture.waitlisted, lecture.waitlist_capacity) == (0, 30)
    assert lecture.status_text == "Open"


def test_parses_both_labs_from_sub_fixture():
    sections = parse_sections(SUMMARY_SUB_HTML)
    assert [s.label for s in sections] == ["Lab 1A", "Lab 1B"]
    assert all(s.kind is SectionKind.LAB for s in sections)


def test_sub_level_ids_use_the_sections_own_id():
    # Sub-level ids nest as {section}_{parent}_{course}; the leading digits
    # are the section's own id, not its parent's.
    ids = [s.section_id for s in parse_sections(SUMMARY_SUB_HTML)]
    assert ids == ["187336201", "187336202"]


def test_derived_seat_counts_match_uclas_own_arithmetic():
    # UCLA also prints "29 Spots Left"; we discard it and derive instead.
    # This asserts the two agree, which is why discarding is safe.
    lecture = parse_sections(SUMMARY_HTML)[0]
    assert lecture.seats_available == 29
    assert lecture.is_open


def test_sections_on_empty_html():
    assert parse_sections("") == []
    assert parse_sections("<html><body>nothing</body></html>") == []


# --- parse_sections: hand-built edge cases -----------------------------------


def section_html(
    sid: str = "1",
    label: str | None = "Lec 1",
    status: str = "Open<br />10 of 100 Enrolled",
    waitlist: str | None = "0 of 15 Taken",
) -> str:
    """Build a minimal section block; None omits that div entirely."""
    parts = []
    if label is not None:
        parts.append(
            f'<div id="{sid}_COMSCI0111-section"><p><a href="x">{label}</a></p></div>'
        )
    parts.append(f'<div id="{sid}_COMSCI0111-status_data"><p>{status}</p></div>')
    if waitlist is not None:
        parts.append(
            f'<div id="{sid}_COMSCI0111-waitlist_data"><p>{waitlist}</p></div>'
        )
    return "\n".join(parts)


def test_missing_label_falls_back_to_section_id():
    section = parse_sections(section_html(sid="999", label=None))[0]
    assert section.label == "Section 999"


def test_missing_waitlist_div_yields_none_not_zero():
    # None means "no waitlist exists"; 0 would mean "empty waitlist".
    section = parse_sections(section_html(waitlist=None))[0]
    assert section.waitlist_capacity is None
    assert section.waitlisted == 0


def test_empty_waitlist_is_distinct_from_absent_waitlist():
    section = parse_sections(section_html(waitlist="0 of 15 Taken"))[0]
    assert section.waitlist_capacity == 15
    assert section.waitlisted == 0


def test_no_waitlist_text_yields_none():
    section = parse_sections(section_html(waitlist="No Waitlist"))[0]
    assert section.waitlist_capacity is None


def test_closed_section_with_free_seats_is_not_open():
    # The case that justifies checking status text as well as arithmetic.
    section = parse_sections(section_html(status="Closed<br />10 of 100 Enrolled"))[0]
    assert section.seats_available == 90
    assert not section.is_open


def test_class_full_sets_enrolled_equal_to_capacity():
    section = parse_sections(section_html(status="Class Full<br />Class Full (120)"))[0]
    assert section.enrolled == section.capacity == 120
    assert section.seats_available == 0


def test_cancelled_section_without_counts_defaults_to_zero():
    section = parse_sections(section_html(status="Cancelled"))[0]
    assert (section.enrolled, section.capacity) == (0, 0)
    assert section.status_text == "Cancelled"
    assert not section.is_open


def test_status_text_is_preserved_verbatim():
    # The parser reports; models.is_open interprets. One definition of "open".
    section = parse_sections(
        section_html(status="Closed by Petition<br />5 of 50 Enrolled")
    )[0]
    assert section.status_text == "Closed by Petition"


def test_multiple_sections_preserve_document_order():
    html = "\n".join(
        section_html(sid=sid, label=label)
        for sid, label in [("1", "Lec 1"), ("2", "Dis 1A"), ("3", "Lab 1B")]
    )
    sections = parse_sections(html)
    assert [s.section_id for s in sections] == ["1", "2", "3"]
    assert [s.kind for s in sections] == [
        SectionKind.LECTURE,
        SectionKind.DISCUSSION,
        SectionKind.LAB,
    ]


def test_section_without_status_block_is_skipped():
    # Status drives the loop: a label alone is not a usable section.
    html = '<div id="7_X-section"><p><a href="x">Lec 1</a></p></div>'
    assert parse_sections(html) == []


# --- helpers -----------------------------------------------------------------


def test_text_fields_splits_on_br_and_strips_tags():
    raw = '<i class="icon-unlock"></i>Open<br />52 of 60 Enrolled<br />8 Spots Left'
    assert _text_fields(raw) == ["Open", "52 of 60 Enrolled", "8 Spots Left"]


def test_text_fields_drops_empty_fields():
    assert _text_fields("A<br /><br />B") == ["A", "B"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Open<br />52 of 60 Enrolled", ("Open", 52, 60)),
        ("Closed<br />120 of 120 Enrolled", ("Closed", 120, 120)),
        ("Waitlist<br />120 of 120 Enrolled", ("Waitlist", 120, 120)),
        ("Class Full<br />Class Full (120)", ("Class Full", 120, 120)),
        ("Cancelled", ("Cancelled", 0, 0)),
        ("", ("", 0, 0)),
    ],
)
def test_parse_status_block(raw, expected):
    assert _parse_status_block(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0 of 15 Taken", (0, 15)),
        ("12 of 30 Taken", (12, 30)),
        ("No Waitlist", (0, None)),
        ("", (0, None)),
        (None, (0, None)),
    ],
)
def test_parse_waitlist_block(raw, expected):
    assert _parse_waitlist_block(raw) == expected


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Lec 1", SectionKind.LECTURE),
        ("LEC 2", SectionKind.LECTURE),  # case-insensitive
        ("Dis 1A", SectionKind.DISCUSSION),
        ("Lab 1B", SectionKind.LAB),
        ("  lab 2  ", SectionKind.LAB),  # stripped
        ("Sem 1", SectionKind.LECTURE),  # unmodelled kind -> default
        ("Tut 3", SectionKind.LECTURE),
        ("", SectionKind.LECTURE),
    ],
)
def test_infer_kind(label, expected):
    assert _infer_kind(label) is expected
