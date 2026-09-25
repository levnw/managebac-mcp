# Changelog

## 2.6.1 — 2026-09-25

### Fixed (from the first live v2.6 session)
- Task `status` read the "HL" level badge instead of the status in Higher Level
  classes, so status filters missed them. Status now comes from the status badge
  (`.badge[data-bs-title] .badge-label`); HL/SL is a new `level` field.
- Task labels ("Formative", "Classwork") were never read, so `tags` was empty
  and the tag filter had nothing to match. They now come from the task's own
  `.label-and-due` strip (unit labels elsewhere on the page are excluded).

### Added
- Developer-mode structure evidence when a class Files page is not recognised
  (6 of 13 live classes; likely classes without files), to support it from
  evidence rather than a guess.

### Live-verified (25 Sep, 19:05–19:08 UTC)
- `due_date` on all 32 tasks across 10 classes; the three empty MYP classes
  return no tasks without errors.
- Class Files on 7 classes (1–16 files each).
- `open`: a 6.4 MB PowerPoint downloaded and delivered to the card in 2.9 s; a
  textbook over 10 MB was refused cleanly.

246 automated tests.

## 2.6.0 — 2026-09-25

### Added
- `get_files` **open layer**: `open` with up to 5 `file_id`s from a task or a
  class folder downloads those files with the student's session. The model sees
  each file's name, type, size and ready/error status; the bytes travel only in
  widget-only `_meta`.
- **Files card** (`ui://managebac/files-v1.html`, `text/html;profile=mcp-app`):
  shown with `get_files` results. *Add to chat* passes the file unconverted to
  ChatGPT's `window.openai.uploadFile` (also saved to the ChatGPT file library),
  records it in widget state for the model, and offers *Ask ChatGPT about it*.
  No network access of its own; outside ChatGPT it says adding is unavailable.
- Guarded downloader: redirects (≤3) only to ManageBac, S3 or CloudFront over
  HTTPS; cookies and referrer stripped for any host but the school's; 10 MB per
  file, 15 MB per call; expired links and sign-in pages are explicit errors.

### Not yet verified
- In ChatGPT itself: that the card renders, that `uploadFile` accepts the file,
  and whether the model reads an added PDF or document without the student
  attaching it again. Images are documented to reach the model via widget state.

### Verified
- 245 automated tests, including cookie stripping on storage redirects and that
  reports never contain file bytes.

## 2.5.0 — 2026-09-25

### Added
- Date filters `date_from` / `date_to` (YYYY-MM-DD) on `get_tasks` (list layer,
  by due date) and `get_files` (class files by last modified; task files by
  posted date). Items without a readable date are listed in `undated`.
- `due_date` on tasks, read from the task's date badge (month and day; the year
  is the one closest to today, since ManageBac does not show it). Verified on a
  saved real task page: badge "Sep 17" matches "Thursday at 11:00 PM".
- `posted_date` on task files, from "Posted … on Sep 16, 2026" for teacher
  resources and "Uploaded …" for the student's own submissions.
- `get_files`' task layer now states plainly that submissions are the student's
  own uploaded files.

### Verified
- 230 automated tests. Not yet verified live: that class task-list rows carry
  the same date badge as the task page (developer reports will show it).

## 2.4.0 — 2026-09-25

### Changed (breaking)
- Tools work in layers. `get_task` is merged into **`get_tasks`**: pass
  `class_ids` (+ optional `title`, `tag`, `status`) to list, or `open` with up to
  10 `{class_id, task_id}` pairs for full details in one call. A task that cannot
  be read is returned with its own error; signed-out or rate-limited sessions
  still fail the whole call.
- `get_class_files` becomes **`get_files`**: `class_id` (+ `folder_id`,
  `recursive`) for the class Files section, or `class_id` + `task_id` for the
  files attached to one task, each labelled `description`, `teacher_resource` or
  `submission`, with the same stable `file_id` used everywhere.
- The connector now exposes four tools: `get_classes`, `get_tasks`, `get_files`,
  `get_timetable`. Retired code remains at tag `v2.3.1`.

### Not included
- A file-contents layer. File contents are still not downloaded or read.

### Verified
- 220 automated tests; both replay scripts run.

## 2.3.1 — 2026-09-25

### Removed
- Code orphaned by the tool retirements: `tools/content_output.py`,
  `ClassArguments`, the unused `TASK` schema and `pages.identifier()`.
- `docs/history/` (14 superseded design notes). They remain at tag `v2.3.0`.

No behaviour change. 214 automated tests.

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
