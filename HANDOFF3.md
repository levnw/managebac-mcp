# ManageBac MCP — Handoff 3

_Last updated: 2026-06-14. Branch: `multi-user` (the active branch, NOT `main`).
Supersedes HANDOFF.md / HANDOFF2.md for anything that conflicts._

## What this is
A multi-user MCP server that scrapes a student's ManageBac account and exposes it to
ChatGPT (Apps SDK) and Claude. Python + httpx + BeautifulSoup, served over HTTP with
Starlette/uvicorn. Users enroll at `https://managebac.822538.xyz/enroll` and get a private
connector URL; per-request user context via `contextvars` (`set_current_user` / `require_user`).

Tools (14): `get_classes, get_timetable, refresh, get_upcoming, get_tasks, get_task_detail,
get_files, get_journal, get_file_content, get_units, get_grades, tag_search, find_task, test_ui`.

## Production
- **Host:** macOS, launchd service `com.managebac.mcp` (domain `gui/502`).
- **Access:** Tailscale SSH `server@100.77.121.118`, repo at `/Users/server/managebac-mcp`.
- **Public:** Cloudflare tunnel → `https://managebac.822538.xyz` (listens on `127.0.0.1:8000`).
- **Logs:** `/tmp/managebac-mcp.log` on prod.

### Deploy
```
ssh server@100.77.121.118 "cd /Users/server/managebac-mcp && git pull --ff-only origin multi-user && launchctl kickstart -k gui/502/com.managebac.mcp"
```
**Tailscale SSH auth expires.** If deploy hangs / returns nothing, run `ssh server@100.77.121.118`
interactively once and complete the Tailscale login link, then retry.

## Local dev & testing (no SSH needed)
Credentials are in `~/.managebac_mcp/.env` (URL/EMAIL/PASSWORD) + `users.db`. Run scrapers locally
against live ManageBac — invaluable for debugging without deploying:
```python
from managebac_mcp import config, users, scraper, cache
from managebac_mcp.context import set_current_user
set_current_user(users.ensure_local_user(config.BASE_URL, config.EMAIL, config.PASSWORD))
cache.clear_user()                       # bypass stale cache
await scraper.fetch_files("12892869")    # Chemistry, has folders + 2 pages
```
Use `./.venv/bin/python`. Tests: `./.venv/bin/python -m pytest tests/test_parsers.py -q` (20 pass).
`tests/test_live.py` errors are pre-existing (`cache.clear_all` outdated). Fixtures in
`tests/fixtures/` are **gitignored** (local only).

## Widgets (ChatGPT Apps SDK) — READ THIS BEFORE TOUCHING WIDGETS
- HTML in `widget-preview/`: `task-card.html`, `class-files.html`, `grades-card.html`,
  `timetable-card.html`. Registered in `_STATIC_WIDGETS` (server.py) with `ui://widget/...-v2.html`
  URIs + `_widget_meta(...)`.
- A tool shows a widget when its `Tool(_meta=…)` and `CallToolResult(_meta=…)` both point at the
  widget URI and `structuredContent` carries the data. Widget reads `window.openai.toolOutput`;
  the model reads the **text content** (full JSON).
- **structuredContent SIZE LIMIT:** ChatGPT silently DROPS oversized `structuredContent` and falls
  back to text (no widget). Keep under ~4–5KB. Timetable full week was ~7.6KB → dropped; slimmed to
  ~3KB with short keys (`p/d/t/c/tr/r/n`). Grades single-class includes slimmed `graded_tasks`
  (~1.5KB).
- **Preview locally:** `.claude/launch.json` serves `widget-preview/` on :8899 (preview tool
  "task-card"). Navigate to `/<file>.html`, then call its `render*()` with sample data + screenshot.

### ⚠️ ChatGPT/Claude cache the connector manifest + widget HTML
Adding a widget or editing widget HTML does NOT show up until the user **refreshes the connector**
(ChatGPT → Settings → Connectors → ManageBac → refresh/sync, new chat). To force-bust cached widget
HTML, **bump the widget URI version** (current ones are all `-v2`). A Claude/ChatGPT connector will
500 on a tool whose `_meta` URI isn't in its cached manifest until refreshed.

### outputSchema
All 14 tools advertise `outputSchema`. Returning a `CallToolResult` makes the MCP SDK SKIP strict
output validation (`mcp/server/lowlevel/server.py` ~line 540) — schemas are advisory. Data tools
mirror JSON under `structuredContent={"result": …}`; widget/content tools keep their own shape.

## Scraper gotchas (don't regress these)
- **Real Chrome User-Agent is required.** ManageBac serves a REDUCED page to bot UAs (the Files page
  came back WITHOUT folders). `auth.get_client()` sends a Chrome UA. Do not revert.
- **`data-ec3-info` can be double-escaped** (wrapped `\'…\'`, doubled `\\u0026`). `parse_files`
  slices to outer `{…}` + collapses `\\`; uploader from `<label>by NAME</label>`; `uploaded_at` UTC
  → school-local via `_format_file_datetime`.
- **Files paginate AND nest in folders.** `fetch_files` BFS-crawls `/files/page/N` + recurses
  `/files/folder/{id}`, tagging each file with `folder`. Helpers: `parse_file_folders`,
  `_files_has_next_page`. Widget groups by `folder`.
- **`get_upcoming` empty is correct** at year-end. Timetable `task_count` = ManageBac's per-day
  badge, NOT a to-do count (its description says so to stop the model misreporting "work due").
- `get_timetable` accepts `days` / `from` / `to` ("tomorrow", "Monday", "Jun 9", ranges), resolved
  school-local server-side via `_filter_timetable`.

## Grades data shapes
- all: `{scope, classes:[{class_name, criteria:{A:{latest,best,average,out_of,count}…}}]}`
- one class: same + `graded_tasks:[{title,type,date,grades:{A:{score,max}…}}]}`.
- Widget: `classes.length===1 && graded_tasks` → ManageBac-style vertical-bar Progress Chart;
  else → simple table.

## Commits this session (newest first)
`25dd8db` redesign grades+timetable, bump URIs v2 · `70ed26b` get_files crawl pages+folders (Chrome
UA) · `6c82347` timetable variable day range · `e359d25` slim timetable sc · `c5828e0` add
grades+timetable widgets · `b34c2e2` files uploader/timestamp + batch task_detail + outputSchema ·
`3b0b928` files [] on escaped pages.

## Known / out of scope
- **Journal file attachments lack a download `url`** (markup doesn't expose one) — unsolved.
- `tests/test_live.py` stale.

## Memory
`~/.claude/projects/-Users-levanjaparidze-Documents-aplactions-student-portal/memory/` (`MEMORY.md`
index): deploy reality, multi-user bug fixes, files-parsing-bugs, outputSchema.
