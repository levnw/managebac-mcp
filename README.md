# ManageBac MCP — v2

A read-only connector that lets ChatGPT (and other MCP clients such as Claude)
read a student's own ManageBac portal: classes, tasks (with filters), task
details, class files and the timetable.

v2 is a rebuild of v1 (`multi-user` branch, up to v1.9.0). It keeps each tool
narrow, returns compact JSON, and reports an error instead of a guessed or
partial answer. Nothing is ever submitted or changed in ManageBac.

## How a request travels

```
ChatGPT / Claude
  → host (OAuth, account lookup)            not in this repository; see "Hosting"
  → tools/server.py      MCP adapter: lists tools, frames results and errors
  → tools/session.py     one pooled connection per student, ≤4 concurrent calls
  → tools/catalogue.py   tool lookup by name
  → tools/<tool>.py      input check, which page to read, compact output
  → sources/managebac/   bounded page fetch (pages.py) and pure HTML parsers
```

`sources/` reads ManageBac pages. `tools/` decides what the model gets back.

## Tools

Tools work in layers: list first, then open what you picked.

| Tool | Layer | Input | Returns |
|---|---|---|---|
| `get_classes` | | none | Enrolled classes (all list pages, total verified) |
| `get_tasks` | list | `class_ids` (1–10), optional `title`, `tag`, `status`, `date_from`, `date_to` | Task summaries with `due_date`, each with its class |
| | detail | `open`: up to 10 `{class_id, task_id}` | Markdown instructions, media, tables, teacher resources, submission, assessment, feedback; per-task errors |
| `get_files` | class | `class_id`, optional `folder_id`, `recursive`, `date_from`, `date_to` | The class Files section: files and folders |
| | task | `class_id`, `task_id`, optional `date_from`, `date_to` | Every file attached to one task, labelled `description`, `teacher_resource` or `submission` (your own uploads), with `posted_date` |
| | open | `class_id` + `task_id` or `folder_id`, `open`: up to 5 `file_id`s | Downloads those files for the **files card**, whose *Add to chat* button hands each one to ChatGPT's own file upload |
| `get_timetable` | | none | The displayed week (classes, merged periods, Homeroom-style notes) |

Dates: ManageBac shows a task's due month and day without a year, so `due_date`
uses the year closest to today. Files use their real dates (last modified for
class files, posted or uploaded for task files). With a date filter, anything
without a readable date is returned in `undated`, never silently dropped.

### Adding files to the chat

`get_files` shows a files card in ChatGPT (MCP Apps resource
`ui://managebac/files-v1.html`). *Add to chat* downloads the file through the
signed-in tool call (`open` layer) and passes it, unconverted, to
`window.openai.uploadFile`, so it becomes an ordinary ChatGPT file. The bytes
travel only in widget-only `_meta`; the model sees name, type, size and status.
Downloads are resolved against the task or folder page the student named, are
HTTPS-only to ManageBac or its storage (S3, CloudFront), strip school cookies
from any other host, and are capped at 10 MB per file and 15 MB per call.
Developer reports never store file bytes.

### Retired tools

| Tool | Existed in | Retired in | Why | Code preserved at |
|---|---|---|---|---|
| `get_journal`, `get_discussions` | v2.0.0 | v2.1.0 | Ported from v1 selectors for an older portal layout; never verified live; not planned for use | [`v2.0.0`](https://github.com/levnw/managebac-mcp/tree/v2.0.0): `tools/journal.py`, `tools/discussions.py`, `sources/managebac/conversations.py` |
| `get_task`, `get_class_files` | v2.0.0 | v2.4.0 | Merged into layers: `get_tasks` detail (`open`) and `get_files` class layer | [`v2.3.1`](https://github.com/levnw/managebac-mcp/tree/v2.3.1): `tools/task.py`, `tools/class_files.py` |
| `get_units`, `get_unit` | v2.0.0 | v2.3.0 | Not needed for the owner's use; never verified live | [`v2.2.0`](https://github.com/levnw/managebac-mcp/tree/v2.2.0): `tools/units.py`, `tools/unit.py`, `sources/managebac/units.py` |
| `get_upcoming` | v2.0.0 | v2.3.0 | Redundant with `get_tasks` plus filters; never verified live | [`v2.2.0`](https://github.com/levnw/managebac-mcp/tree/v2.2.0): `tools/upcoming.py`, `sources/managebac/upcoming.py` |
| `search_tasks` | v2.0.0 | v2.3.0 | Merged into `get_tasks` as optional filters (`title`, `tag`, `status`) | [`v2.2.0`](https://github.com/levnw/managebac-mcp/tree/v2.2.0): `tools/search_tasks.py` |
| `get_grades` | v2.0.0 | v2.2.0 | Returned bare task-list scores without the detail needed to show or predict grades, and only recognised exact MYP-era markup, so real grades could be missed | [`v2.1.0`](https://github.com/levnw/managebac-mcp/tree/v2.1.0): `tools/grades.py`, `sources/managebac/grades.py` |

A task's own assessment and teacher feedback are still returned by `get_task`.
A better grades design is on the backlog (`docs/BACKLOG.md`). Any rebuild should
start from fresh evidence of the current pages, not from the retired code.

Every tool is read-only, declares strict input and output schemas, and shares
the same limits (see each tool's description). School-stored files carry a
stable opaque `file_id`; expiring signed download links are never returned.

## Guarantees

- Only the student's own school origin and allow-listed student paths are read;
  redirects are never followed; pages are capped at 2 MB.
- A list is complete or it is an error: page, record, duplicate and source-total
  checks happen in one place (`sources/managebac/collections.py`).
- Unfamiliar layouts fail with `layout_changed` rather than returning empty data.
  In developer mode, the report records page *structure* (never content) so the
  layout can be supported from evidence.
- Page reads keep the signed-in client's identity; a changed User-Agent made
  ManageBac end sessions (fixed in 2.0.0).
- One retry, with jitter, for connection errors, 502/503/504 and short 429s.

## Development

```bash
uv sync
.venv/bin/python -m pytest -q
```

The local workbench (`onboarding/`) signs in and runs any tool on
`http://127.0.0.1:8765/`:

```bash
MBV2_DEVELOPER_MODE=1 .venv/bin/python -m uvicorn onboarding.app:app --host 127.0.0.1 --port 8765 --no-access-log
```

With developer mode on, every call writes a private `response.json` and
`report.json` under `Test Reports/` (ignored by git). Reports are evidence,
never a cache.

`scripts/replay_tools.py` and `scripts/replay_catalogue.py` export clearly
labelled synthetic examples through the real pipeline without network access.

## Hosting

The public test connector (OAuth, encrypted account state, Cloudflare tunnel)
lives outside this repository. It imports an approved copy of `diagnostics.py`,
`onboarding/{transport,auth}.py`, `sources/` and `tools/`, and calls
`create_server(call_tool)` with an account-scoped `call_tool(name, arguments)`.

## Documentation

- `CHANGELOG.md` — what changed in each version
- `docs/V2_DESIGN_PRINCIPLES.md`, `docs/MODEL_ORIENTATION.md` — design rules
- `docs/ARCHITECTURE_REVIEW_2026-09-25.md` — the latest architecture review
- `docs/BACKLOG.md` — ideas not yet built
- Superseded design notes were removed in 2.3.1; they remain at tag `v2.3.0` under `docs/history/`
