"""One-off script: capture raw HTML from UCLA SOC endpoints as test fixtures.

Not part of the package -- this is scaffolding, run once to freeze real
responses into fixtures/ so parser.py can be built and tested offline.
"""
import json, sys, pathlib, requests

SOC = "https://sa.ucla.edu/ro/Public/SOC"
TITLES = f"{SOC}/Results/CourseTitlesView"
SUMMARY = f"{SOC}/Results/GetCourseSummary"
OUT = pathlib.Path("fixtures")

TERM, SUBJ, CATNO = sys.argv[1], sys.argv[2], sys.argv[3]

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": SOC,
})

landing = s.get(SOC, timeout=20); landing.raise_for_status()
(OUT / "soc_landing_sample.html").write_text(landing.text, encoding="utf-8")
print(f"soc_landing_sample.html      {len(landing.text):>8,} bytes")

model = {"term_cd": TERM, "subj_area_cd": SUBJ, "ses_grp_cd": "%",
         "class_no": "%", "crs_catlg_no": CATNO}
r = s.get(TITLES, params={"search_by": "subject", "model": json.dumps(model),
                          "pageNumber": "1", "filterFlags": "{}"}, timeout=20)
r.raise_for_status()
(OUT / "course_titles_sample.html").write_text(r.text, encoding="utf-8")
print(f"course_titles_sample.html    {len(r.text):>8,} bytes")

import re
roots, subs = [], []
for cid, blob in re.findall(r'AddToCourseData\("([^"]+)",(\{[^}]+\})\)', r.text):
    d = json.loads(blob)
    (roots if d.get("IsRoot") else subs).append(d)
print(f"  -> {len(roots)} root token(s), {len(subs)} sub token(s)")
if not roots:
    sys.exit("No root model token found -- check term/subject/catalog number.")

r2 = s.get(SUMMARY, params={"model": json.dumps(roots[0]), "FilterFlags": "{}"}, timeout=20)
r2.raise_for_status()
(OUT / "course_summary_sample.html").write_text(r2.text, encoding="utf-8")
print(f"course_summary_sample.html   {len(r2.text):>8,} bytes")

sub_tokens = [json.loads(b) for _, b in
              re.findall(r'AddToCourseData\("([^"]+)",(\{[^}]+\})\)', r2.text)
              if not json.loads(b).get("IsRoot")]
print(f"  -> {len(sub_tokens)} sub token(s) in summary")
if sub_tokens:
    r3 = s.get(SUMMARY, params={"model": json.dumps(sub_tokens[0]),
                                "FilterFlags": "{}"}, timeout=20)
    r3.raise_for_status()
    (OUT / "course_summary_sub_sample.html").write_text(r3.text, encoding="utf-8")
    print(f"course_summary_sub_sample.html {len(r3.text):>6,} bytes")
