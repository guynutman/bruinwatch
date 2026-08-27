# BruinWatch

[![CI](https://github.com/guynutman/bruinwatch/actions/workflows/ci.yml/badge.svg)](https://github.com/guynutman/bruinwatch/actions/workflows/ci.yml)

Monitors UCLA's [Schedule of Classes](https://sa.ucla.edu/ro/Public/SOC) for
open seats and alerts you when one appears.

```
[08:55:28] Polling 1 course(s)...
  >>> COM SCI 111 - Lec 1: 27 seat(s) open
```

This is a rebuild. The original was a single 400-line script that worked but
could not be tested, changed, or explained. The code below is the same
feature set with the responsibilities separated — which is the actual point
of the project.

## Install

```bash
git clone https://github.com/guynutman/bruinwatch.git
cd bruinwatch
python -m venv .venv && source .venv/bin/activate
pip install -e ".[notify,dev]"
```

## Run

```bash
bruinwatch                       # interactive: prompts for term and courses
```

It asks for a term, then one or more courses, then polls every three
minutes until you press Ctrl+C. Desktop notifications need `plyer`; without
it, alerts still print and still make a sound.

Every prompt has a flag, so it is equally usable from a script or a cron
entry:

```bash
bruinwatch -t 26F -c "COM SCI M51A"              # skip the prompts
bruinwatch -t 26F -c "MATH 61" -c "COM SCI 111"  # several courses
bruinwatch -t 26F -c "COM SCI 111" --once        # one poll, then exit
bruinwatch -t 26F -c "COM SCI 111" -q -i 300     # alerts only, every 5 min
bruinwatch --help
```

## Tests

```bash
pytest        # 153 tests, ~0.2s, no network
ruff check .
```

Every test runs offline against saved HTML in [`fixtures/`](fixtures/).
That is a design consequence, not a testing trick — see below.

---

## Architecture

Five modules, each owning one concern and hiding it from the others.

```
bruinwatch.py    CLI: prompts, wiring, platform-specific alerts
    │
    ├── watcher.py     poll loop, state diffing, notification dispatch
    │       │
    │       ├── client.py    HTTP session, endpoints, retries  →  raw HTML
    │       └── parser.py    raw HTML  →  model objects
    │
    └── models.py    frozen dataclasses; imported by everything, imports nothing
```

Dependencies point one way. `models.py` is standard-library only.
`parser.py` never imports `requests`. `watcher.py` never imports `plyer`,
`platform`, or `winsound`.

### `models.py` — the shared vocabulary

Frozen dataclasses: `SectionKind`, `SectionStatus`, `Course`,
`CourseSnapshot`. No I/O, no parsing, no formatting.

The original passed dicts everywhere, so `sec["spots_lef"]` was a runtime
crash rather than a caught error, and the rules about the data were
scattered across the file. Here, derived values are properties
(`seats_available`, `is_open`, `display_name`) rather than stored fields, so
they cannot drift out of sync with the data they come from.

Snapshots are frozen because `watcher.py` holds the previous one to diff
against. A mutable snapshot could be edited after capture, and the diff
would compare an object against itself.

### `parser.py` — HTML in, objects out

Pure functions. No network, no state, no side effects.

This is the trust boundary: untrusted HTML enters, validated
`SectionStatus` objects leave. It is also why the test suite needs no
mocking library — a pure function has no way to reach the network, so
testing it means passing a string and checking the result.

It hides the fact that UCLA's data arrives as HTML at all. If they shipped a
JSON API tomorrow, only this file would change.

### `client.py` — HTTP and nothing else

Returns **raw HTML** and never parses it. That separation is what keeps
`parser.py` independently testable.

It is a class while `parser.py` is plain functions, because it has state: one
`requests.Session` holding the cookies SOC sets on its landing page and
requires on every subsequent call. Match the abstraction to whether state
exists, not to a preference for objects.

Catalog-number zero-padding lives here (`"111"` → `"0111"`). The user types
`111`, `Course` stores `111`, and only the API wants `0111` — so the
translation belongs with transport.

Exhausted retries raise `SOCError`, not `requests.RequestException`, so
callers can handle transport failure without importing `requests`.

### `watcher.py` — poll, diff, react

Composes the other three. Knows nothing about HTTP, HTML, or what a
notification is.

**State diffing** is the interesting part. A section is *newly* open if it is
open now and was not open — or did not exist — on the previous poll:

| Poll | Section | Alert |
|------|---------|-------|
| 1    | Open    | ✓ |
| 2    | Open    | — |
| 3    | Closed  | — |
| 4    | Open    | ✓ |

The original re-alerted every three minutes for as long as a seat stayed
open. Missing section ids read as falsy, which handles "was closed" and "did
not exist yet" without special cases.

A failed fetch skips that course entirely rather than recording it as
closed — otherwise recovery would fire a spurious alert.

### `bruinwatch.py` — the thin end

The only module that imports `plyer`, `platform`, or `winsound`, calls
`input()`, or has a `__main__` guard. Confining those is what lets the other
four be tested with no terminal, no display, and no sound device.

---

## Two decisions worth explaining

### Notification is injected, not imported

`Watcher` takes a callback:

```python
NotifyCallback = Callable[[str, int, str], None]
```

It decides *when* to alert — business logic. The caller decides *what an
alert is* — policy. Desktop popup, sound, webhook, or `list.append`.

In the original these were fused: platform-specific `winsound`/`say`/`paplay`
branches sat inside the poll loop, so polling could not be tested without a
sound card. Now the tests pass `notify=lambda *a: alerts.append(a)` and
assert on a list.

### Fixtures, not live requests

Tests parse saved HTML from [`fixtures/`](fixtures/) rather than calling
UCLA. Enrollment counts change by the minute, so live assertions would fail
for reasons unrelated to the code. More importantly, UCLA will not serve a
cancelled section on demand — those cases are hand-built as small HTML
snippets.

When UCLA redesigns their markup, the tests keep passing against the old
fixture. Capture a new one, watch it fail, and the diff tells you exactly
what changed.

Regenerate with `python scripts/capture_fixtures.py 26F "COM SCI" 0111`.

---

## Trade-offs and known limitations

**Regex instead of BeautifulSoup.** HTML is not a regular language, and for
arbitrary documents `bs4` is the right tool. It is defensible here because
the markup is machine-generated with stable ids and flat content, and
because the model tokens are JSON embedded in JavaScript — which needs
regex regardless. For a system meant to be maintained for years, `bs4` would
be the better call; the module boundary means swapping it would touch one
file and no test signatures.

**`watcher.py` prints.** Presentation logic in a business-logic module. A
stricter design would emit events or take a logger.

**Naive timestamps.** Every `datetime` here is local wall-clock text for the
user's own terminal — never stored, compared across zones, or serialised.

**Polling, not push.** UCLA offers no webhook. Three minutes is a deliberate
compromise between latency and load on a public endpoint.

**No persistence.** State lives in memory; restarting re-alerts for anything
currently open.

---

## Scope

Reads public, unauthenticated course data — the same pages any browser
loads, at a slower rate than a person clicking refresh. No credentials, no
enrollment actions, no personal data. Built for personal use during
enrollment.
