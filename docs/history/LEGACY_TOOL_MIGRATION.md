# Legacy tool migration — 25 September 2026

## Independent-review fixes (latest; supersedes the initial strictness notes below)

- Pending, submitted and unmarked tasks without assessment blocks no longer fail
  get_grades. They have no published grade **on this page**, not necessarily no
  grade elsewhere. Explicit unsupported assessment markup still returns an error.
- MCP failures now use readable TextContent plus isError=true, without
  structuredContent that conflicts with the success schema. Successful JSON is
  still returned once, as requested. Local response.json keeps the tool payload.
- Server instructions now explain all twelve tools and compact file/rich content.
- Timetable notes such as lunch are preserved, including colspan notes aligned to
  the source day headers. Unrecognized class-like cells and ambiguous spans still
  fail rather than silently inventing classes.
- Eight new tools now have explicit nested output schemas: required fields,
  field types, permitted properties, rich media and table cells. Single-page and
  multi-class tools have accurate individual limit descriptions.
- Developer reports include bounded numeric search class_ids, never search text.
- Classes now use the shared bounded HTML transport, including content-type,
  redirect, size and decoding checks. Enrolled-list parsing stays separate.

See tests/test_review_fixes.py for regression coverage. Live Grade 10 validation
is still pending a fresh sign-in; these changes are not promotion evidence.
Verification after the fixes: 227 Python tests and two Node tests passed; app.js
syntax check passed. The restarted local preview returned HTTP 200 and exposed
the corrected grade description, timetable notes schema and single-page limits.

## Status and evidence

Implementation is in **Working**, not Approved. The local workbench at
`http://127.0.0.1:8765/` exposes twelve tools through one catalogue. It uses the
same account-scoped calls and JSON serializers as the Working MCP adapter.
The public test connector has not been changed or promoted.

Legacy reference: `https://github.com/levnw/managebac-mcp`, branch `multi-user`,
commit `c41363d325a65e652740491a8083619f41546f03`. Local HEAD and the remote branch
were checked during this work and matched. The old `server.py` tool inventory
and relevant `scraper.py` readers were inspected as source evidence, not copied
into a second monolithic scraper.

The eight new tools have synthetic legacy-layout tests and saved exact response
examples. This is **not live verification of the current Grade 10 portal**.
Verification: 199 Python tests passed, including actual in-memory MCP calls for
every new tool; two Node file-browser tests passed; app.js syntax check passed.
One existing Starlette/httpx deprecation warning remains. Safari showed all
twelve tools and the selected unit-detail schema in the running workbench.
The previous local session had already been marked unauthenticated after a task
redirect; no fresh password was available. The workbench was restarted to load
the new catalogue. It now needs a user sign-in for live validation.

## Capability map

| Old capability | Working replacement | Boundary / intentional change |
|---|---|---|
| get_classes | get_classes | Existing enrolled list reader; no enrichment |
| get_tasks | get_tasks | Existing complete list for one class |
| get_task_detail | get_task | Existing compact rich task detail |
| get_files | get_class_files | Existing folder-aware file listings |
| get_units | get_units + get_unit | Listing no longer requests all unit popups |
| get_journal | get_journal | One selected class; auth/404 is never an empty journal |
| Discussions inside task detail | get_discussions | Explicit separate call; posts and replies retain rich content |
| get_timetable | get_timetable | Current displayed week only; no silently substituted requested week |
| get_upcoming | get_upcoming | Upcoming/overdue/past; pagination retains the selected view |
| find_task, tag_search | search_tasks | One search implementation; explicit 1–10 class IDs, title and/or exact tag filters |
| get_grades | get_grades | Source assessment blocks; no invented averages, predicted or official report grades |
| show_* duplicates | Not recreated as retrieval tools | A future widget should render the same result, not fetch it again |
| refresh | Not needed for these tools | New tools currently read fresh data; no academic cache to invalidate |
| runtime_info, check_session, debug_snapshot | Not public academic tools | Diagnostics and auth verification belong to the workbench/session layer |

No new school-write tools, arbitrary URL reader, automatic attachment downloads,
OCR, or native ChatGPT attachment delivery were added. These require separate
resource authorization and bounded binary handling. Existing file/media output
contains references, **not proof that the model has read the file**.

## Source structure

```text
Working/
  onboarding/                 login, school discovery, local HTTP workbench
  sources/managebac/
    pages.py                  same-school bounded HTML transport
    collections.py            complete-list traversal, duplicate/page/record limits
    units.py                  list and unit-popup interpretation
    conversations.py          journal/discussion HTML boundaries
    timetable.py              displayed day/period alignment
    upcoming.py               deadline tiles and filter-preserving pagination
    grades.py                 assessment blocks; not scores guessed from prose
    tasks.py, task_detail.py, files.py, classes.py, rich_text.py
  tools/
    catalogue.py              single registration/dispatch inventory
    contracts.py              shared strict argument models and tool definitions
    retrieval.py              timeout, JSON budget and safe errors
    content_output.py         shared compact rich-content rendering
    units.py, unit.py, journal.py, discussions.py
    timetable.py, upcoming.py, search_tasks.py, grades.py
    classes.py, tasks.py, task.py, class_files.py
    session.py, server.py      account isolation, diagnostic export, MCP adapter
  tests/fixtures/catalogue/   explicitly synthetic school-page fragments
  scripts/replay_catalogue.py
  Test Reports/Synthetic Catalogue Examples/
```

Authentication never retrieves academic data. Parsers do not make network
requests. Tools own scope and compact output. Shared transport does not follow
redirects automatically. Lists finish traversal before returning a result;
failures do not return partial successes. Search composes the existing task-list
reader instead of defining another scraper.

## Model context

New content uses short text plus media/table references when needed, not DOM
trees, blank text nodes or generic asset catalogues. Explicit source labels are
preserved rather than aggressively translated into guessed school concepts.
Dates remain source wording when no trustworthy absolute date is present.

Examples from **synthetic fixtures**, not the student's account:

```json
{"class_id":"10","url":"https://es.managebac.com/student/classes/10/units","units":[{"id":"7","title":"Energy","url":"https://es.managebac.com/student/classes/10/units/7/presentations","duration":"4 Weeks","status":"current"}]}
```

```json
{"class_id":"10","task_id":"11","url":"https://es.managebac.com/student/classes/10/core_tasks/11/discussions","discussions":[{"id":"9","author":"Teacher","replies":[{"author":"Student","text":"Answer"}],"text":"Question"}]}
```

The JSON files are the model payload. The MCP transport still has its required
protocol envelope; this does not claim access to ChatGPT's entire hidden context.

## Limits and error behavior

New tools share 60-second execution and 250 KB serialized result budgets.
Collections allow at most 50 pages and 1000 records. Single-page HTML is capped
at 2 MB. Exceeding a limit is an error, not silent clipping. Existing classes
retains its separately documented limits.

404, 403, 429 and login redirects stay distinct. Unknown layouts are not empty
lists. `get_grades` fails with `assessment_layout_unverified` when a task has
neither supported assessment markup nor an explicit unassessed status. It does
not average criteria or imply that task-list scores are the whole report card.

HTTP User-Agent is now consistent between login and page readers. On a tool's
`session_expired` response, the session layer verifies the existing account
profile once, without submitting credentials or retrying the tool. If the profile
still verifies, the error becomes `page_unavailable_authenticated`; the local app
keeps that session. This distinguishes a page/routing problem from confirmed
login loss, but does not diagnose the exact upstream cause.

Cookies remain in memory. Restart and the existing 30-minute local session TTL
still require a new sign-in; this change does not implement persistent cookies.
No password, OAuth token, database, tunnel secret or approved snapshot was altered.

## How to test and inspect

1. Open the local workbench on Atlas and sign in.
2. Get classes, then use **All tools workbench**. Required IDs are seeded from
   the selected class/task where available; inspect the input schema for details.
3. Run the selected tool. The inspector displays its exact payload and offers
   `Download response.json` on the browser's computer.
4. With developer mode enabled, each call also writes private `response.json`
   and safe `report.json` on Atlas under `Working/Test Reports/`.
5. To inspect without a login, open files in `Test Reports/Synthetic Catalogue
   Examples/`. Their names and folder deliberately identify them as synthetic.

Developer mode remains off by default in source. The existing local preview
launcher enables it. It is not an academic cache. No automatic newsletter use.

Commands from Working:

```sh
/Users/server/Desktop/managebac-mcp/.venv/bin/python -m pytest -q
/Users/server/Desktop/managebac-mcp/.venv/bin/python scripts/replay_catalogue.py
```

## Remaining verification and implementation work

- Live compare Grade 10 task, unit, timetable, journal and discussion pages with
  extracted results. Do not assume the old MYP selectors cover DP Foundation.
- Resolve the real task redirect using the new profile-vs-page distinction.
  The changed browser header is a consistency fix, not a proven root cause.
- Old task-audit extraction failures still need their source HTML and replay
  regression fixtures. This migration does not claim those are fixed.
- Grade markup is deliberately conservative and may need more observed variants.
- Historical/future timetable selection was intentionally not reintroduced until
  the returned week can be verified against a requested date.
- Native file contents, OCR, widgets, OAuth publication and promotion to Approved
  are not included in this Working catalogue rollout.
- New response schemas validate envelopes but some rich entity objects remain
  open-shaped; strengthen those as live contracts are verified.

Do not treat passing synthetic tests or the presence of a tool in the selector
as evidence of successful live extraction.
