# ManageBac MCP — v2

A read-only connector that lets ChatGPT (and other MCP clients such as Claude)
read a student's own ManageBac portal: classes, tasks, task details, class
files, units, timetable, deadlines and published grades.

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

| Tool | Reads |
|---|---|
| `get_classes` | Enrolled classes (all list pages, total verified) |
| `get_tasks` | One class's task list |
| `get_task` | One task: Markdown instructions, media, tables, teacher resources, submission evidence, feedback |
| `get_class_files` | A class Files folder, optionally recursive |
| `get_units` / `get_unit` | Unit list / one unit's sections |
| `get_timetable` | The displayed week (classes, merged periods, Homeroom-style notes) |
| `get_upcoming` | Upcoming, overdue or past deadlines across classes |
| `search_tasks` | Title/tag search across up to 10 chosen classes |
| `get_grades` | Published assessment blocks on a class task list |

### Retired tools

`get_journal` (class journal reflections) and `get_discussions` (task discussion
posts and replies) existed in **v2.0.0** and were retired in **v2.1.0**. Their
page readers were ported from v1 selectors written for an earlier portal layout,
were never verified against the current portal, and are not planned for use.
The code is preserved at tag [`v2.0.0`](https://github.com/levnw/managebac-mcp/tree/v2.0.0): `tools/journal.py`,
`tools/discussions.py` and `sources/managebac/conversations.py`. Rebuilding
either tool should start from fresh evidence of the current pages, not from
that code.

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
- `docs/history/` — superseded design notes kept for their reasoning
