# Changelog

## 2.3.0 — 2026-09-25

### Changed (breaking for callers of get_tasks)
- `get_tasks` now takes `class_ids` (1–10 classes) instead of one `class_id`,
  with optional filters that apply together: `title` (substring), `tag`
  (exact tag or assessment type) and `status` (exact, e.g. "Pending").
  Output: `classes` (each class's task-list URL) and `tasks`, each carrying its
  `class_id`. Every selected class is read completely or the call fails.
- There is no upcoming/past date filter: task lists usually show a weekday and
  time without a date, so the server cannot tell them apart reliably.

### Retired
- `search_tasks` (merged into `get_tasks`), `get_upcoming` (redundant with
  `get_tasks` and its filters), `get_units` and `get_unit` (not needed; never
  verified live). Code remains at tag `v2.2.0`. The deadlines page is no longer
  an allowed destination. The connector now exposes five tools:
  `get_classes`, `get_tasks`, `get_task`, `get_class_files`, `get_timetable`.

### Verified
- 214 automated tests; both replay scripts run.

## 2.2.0 — 2026-09-25

### Retired
- `get_grades`, with its page reader (`sources/managebac/grades.py`), schema and
  tests. It listed bare assessment blocks from a class task list, which is not
  enough detail to show grades meaningfully or support predictions, and it only
  recognised exact MYP-era class names, so unrecognised grade markup could be
  reported as "no published grades". The code remains at tag `v2.1.0`. A task's
  own assessment and teacher feedback are still returned by `get_task`. A
  redesigned grades capability is on the backlog. The connector now exposes nine
  tools.

### Verified
- 243 automated tests.

## 2.1.0 — 2026-09-25

### Retired
- `get_journal` and `get_discussions` are removed from the catalogue, with
  their page reader (`sources/managebac/conversations.py`), schemas, fixtures
  and tests. They were ported from v1 selectors for an older portal layout,
  never verified live, and are not planned for use. The code remains available
  at tag `v2.0.0`. The connector now exposes ten tools.

### Changed
- The shared list engine counts records only; the discussion-reply weighting
  it carried is gone with the tool.
- Server instructions no longer mention the retired tools.

### Verified
- 262 automated tests.

## 2.0.0 — 2026-09-25

First release of the v2 rebuild. v1 (`multi-user`, up to v1.9.0) is unchanged.

### Tools
- Twelve read-only tools: `get_classes`, `get_tasks`, `get_task`,
  `get_class_files`, `get_units`, `get_unit`, `get_journal`, `get_discussions`,
  `get_timetable`, `get_upcoming`, `search_tasks`, `get_grades`.
- Every tool has a title, ChatGPT status text, strict input schema and closed
  output schema, built from one definition helper (`tools/contracts.py`).
- Errors reach the model as readable text (`code: message`) with `isError`.

### Files
- School-stored files, images and previews carry an opaque `file_id` that is
  stable across page reads. Expiring signed download links are omitted.

### Reliability
- One shared list engine checks pages, records, duplicates and source totals.
- One pooled HTTP client per account; up to four concurrent calls.
- One jittered retry for connection errors, 502/503/504 and short 429s.
- Page reads keep the signed-in client's User-Agent and send no `Origin` header.
  (Live fix: a mismatched identity made ManageBac end the session.)
- A `session_expired` result is confirmed against the account profile; an
  inconclusive check keeps the session and says so.
- Live-observed layouts supported: class task pages with no tasks ("All Tasks"
  with no task links), timetable Homeroom items, merged timetable cells, nested
  task cards.

### Developer evidence
- Reports include target IDs, tool definition, serialized size, rich-text notes
  (e.g. media not read) and, for unrecognised task lists, page structure only.
- Confirmed session expiry records the session age, to measure real lifetime.
- The workbench warns when the 1,000-run report folder is nearly full.

### Removed
- Classes-only server mode (`create_server` now takes one `call_tool`) and
  `ToolSession.classes()`.
- Rich-text warnings in tool output (now developer-report events), parsed task
  history and the "discussions not requested" placeholder.
- Test-only re-export of `parse_detail`, a duplicate record limit, a duplicate
  signed-parameter list, an unused evaluation file and a legacy database column.
- Superseded design notes moved to `docs/history/`.

### Verified
- 283 automated tests.
- Live on the test connector: sign-in, `get_classes`, `get_tasks` (13 classes),
  `get_timetable`. The other tools are covered by tests and synthetic pages only.
