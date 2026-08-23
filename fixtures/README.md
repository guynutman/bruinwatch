# Fixtures

Raw HTML captured from UCLA's Schedule of Classes on 2026-08-23 for
COM SCI 111, term 26F (Fall 2026). Used by `tests/test_parser.py` so the
parser can be tested without network access.

| File | Endpoint | Contains |
|---|---|---|
| `soc_landing_sample.html` | `/Public/SOC` | Term `<select>` only — full page is ~517KB of chrome |
| `course_titles_sample.html` | `CourseTitlesView` | Course title + one root `AddToCourseData` model token |
| `course_summary_sample.html` | `GetCourseSummary` | Lecture-level section (`Lec 1`) + one sub token |
| `course_summary_sub_sample.html` | `GetCourseSummary` | Lab-level sections (`Lab 1A`, `Lab 1B`) |

Do not reformat these files. They are a frozen record of what UCLA served;
editing them to "clean up" the HTML would defeat the point.

To add a case the live site does not currently show (a cancelled section, a
missing waitlist block, "Class Full"), copy a fixture and hand-edit the copy.
Name it for the case, e.g. `course_summary_class_full.html`.

Regenerate with `scripts/capture_fixtures.py TERM SUBJECT CATALOG_NO`.
