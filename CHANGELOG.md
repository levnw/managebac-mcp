# Changelog

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
