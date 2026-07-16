# Pre-Redesign Archive — 2026-07-16

**This is a deliberate checkpoint, not a living document.** Everything below is frozen at
commit `77daf66` on branch `design-refresh`. From here on the project is heading into a major
visual redesign and feature rework — this file exists purely so you can always answer "what did
things look like, and how did they work, right before that started."

**To restore to this exact point:**
```
git checkout pre-redesign-2026-07-16          # detached HEAD at the tagged commit
# or, to branch off it fresh:
git checkout -b restart-from-pre-redesign pre-redesign-2026-07-16
```
(Tag created immediately after this file is committed — see the end of this doc for confirmation
it exists.)

---

## 1. Product identity at this checkpoint

- **App name:** Cadence. **Studio name:** Bromus. Both confirmed/kept.
- **Visual identity: intentionally blank.** The previous direction (warm wood tones, deep amber
  accent, "conductor/instrument" metaphor, Fraunces + Inter typefaces) was scrapped same-session
  — the user didn't write it, didn't want it, and had every source file for it deleted
  (`bromus-site-copy.md`, `bromus-site-wireframe.md`, `widget-preview/bromus-hero.html`,
  `widget-preview/bromus-hero-center.html`, `widget-preview/cadence-phone.html`,
  `widget-preview/bromus-site-wireframe.html`). GitHub issues #29, #32, #33 (which referenced
  that direction) had the stale language stripped and replaced with "TBD, pending new visual
  direction." **No replacement direction has been chosen as of this checkpoint.**
- **What actually exists visually right now:** all four live ChatGPT widgets are styled to match
  **ManageBac's own blue theme** (`#1570ef`-ish blue header, matching the school's own branding)
  — not Bromus branding at all. See §4 for a screenshot reference.

## 2. What this project is, in one paragraph

A Python MCP (Model Context Protocol) server that scrapes a student's ManageBac account (a
school LMS — no official API exists, everything is done by parsing rendered HTML with `httpx` +
BeautifulSoup4) and exposes it as tools to ChatGPT (via Apps SDK widgets) and Claude Desktop. It
started as the developer's own tool for tracking their IB MYP grades at a Georgian international
school, and has grown into a small multi-tenant product: other students enroll their own
ManageBac login and get an isolated, encrypted connector URL. An admin panel (web + a native
SwiftUI macOS/iOS app) lets the operator manage users, invite codes, and messaging.

## 3. Architecture snapshot

```
managebac_mcp/
  admin.py          — Admin DB (admin.db): sessions, invite codes, messages, audit_log
  admin_panel/      — Admin SPA (index.html served at GET /admin)
  auth.py           — httpx client factory + ManageBac login (Chrome UA required — bot UAs get reduced pages)
  branding.py       — Scrapes school name + logo from ManageBac for enroll-page branding
  cache.py          — SQLite response cache (cache.db), tool-call activity log
  cli.py            — Local dev CLI (peek / submit / cache commands)
  config.py         — Reads .env, sets BASE_URL, DATA_DIR
  context.py        — User namedtuple + contextvars (set_current_user / require_user) — per-request isolation
  enroll_server.py  — MCP server for in-chat /connect enroll tool
  http_server.py    — Starlette app: enroll pages, set-password page, admin API, MCP handler
  scraper.py        — All ManageBac scraping (classes, tasks, grades, files, timetable…)
  server.py         — MCP tool definitions + call_tool dispatcher + message/pause intercepts
  users.py          — Users DB (users.db): credentials (encrypted), tokens, session cookies
```

Transport: Streamable HTTP for ChatGPT/remote, stdio for Claude Desktop — same tool definitions
shared by both. Multi-user isolation is request-scoped via `contextvars`: every `/mcp` request
extracts a `?key=` token, resolves the user, pins them into context, and every scrape/cache read
is namespaced to that user. Fail-closed — no token, no fallback account.

**Repo:** `github.com/levnw/managebac-mcp`. Branch `main` = old single-user local-only version.
Branch `multi-user` = the actual production branch. Branch `design-refresh` (this checkpoint) =
branched off `multi-user`, where the redesign work happens.

## 4. The 14 MCP tools, as they stand at this checkpoint

All 14 now carry accurate `readOnlyHint`/`destructiveHint`/`openWorldHint`/`idempotentHint`
annotations (added this session, verified by actually calling `list_tools()`).

| Tool | What it does | readOnlyHint |
|---|---|:---:|
| `get_classes` | All enrolled classes, IDs, URLs | true |
| `get_timetable` | Full weekly timetable, day-filterable | true |
| `refresh` | Drops the current user's cache | **false** (only mutation-flagged tool) |
| `get_upcoming` | Upcoming/overdue tasks across all classes | true |
| `get_tasks` | Recent tasks for one or more classes (batchable) | true |
| `get_task_detail` | Full task detail incl. description, resources, discussions | true |
| `get_files` | Class-wide teacher-uploaded files | true |
| `get_journal` | Journal/portfolio entries | true |
| `get_file_content` | Downloads/reads an attachment's content directly | true |
| `get_units` | Full IB curriculum unit framework per class | true |
| `get_grades` | Consolidated grades, all classes or one | true |
| `tag_search` | Find tasks by tag/type across classes | true |
| `find_task` | Find a task by URL or fuzzy title | true |
| `test_ui` | Trivial widget-infrastructure test tool | true |

**Known discrepancy, not yet fixed:** `submit_task_file` (upload a file to a task's dropbox) is
documented in the README and HANDOFF docs as one of the tools, and exists in the CLI
(`managebac-mcp submit`) — but it is **not actually registered** in `list_tools()`. ChatGPT/Claude
cannot call it right now. A background task to fix this was started by the user in a separate
worktree (`.claude/worktrees/awesome-lalande-19db56`) around the time of this checkpoint —
check whether that landed before assuming this is still broken.

## 5. Widgets — current visual state

Four ChatGPT Apps SDK widgets, all in `widget-preview/`: `task-card.html`, `grades-card.html`,
`timetable-card.html`, `class-files.html`. All match ManageBac's own blue theme (see the
screenshot taken this session, reproduced in spirit below — a blue header bar with the task
title/class name, a white card body with due-date badge, status pill, grade breakdown, teacher
comment with "Show More", a linked unit card, a description section, and a Dropbox/submission
section with file rows).

**Interactivity state: none.** Every widget only reads `window.openai.toolOutput` on load. There
is zero `callTool`, zero `setWidgetState`, zero `notifyIntrinsicHeight`, zero
`requestDisplayMode`. Buttons that appear (Show More, etc.) are pure client-side DOM
manipulation, not tool-connected. Full detail in `WIDGETS.md` §19.

**Local preview:** `.claude/launch.json` serves `widget-preview/` on `:8899` — fixed this session
(previously pointed at a path from a different machine; now `/Users/mac/Desktop/Projects/
Managebac MCP/widget-preview` with an absolute `node` path). Widgets don't self-render standalone
— open `http://localhost:8899/task-card.html` and run `renderCard(TASK)` in the console (`TASK`
is a baked sample object at the top of the file) to see it.

## 6. Production deployment snapshot

| | |
|---|---|
| Host | macOS Mac mini/similar, hostname `server.local`, launchd services under `gui/502`, user `server` |
| SSH | Tailscale, `ssh server@100.77.121.118` — repo at `/Users/server/managebac-mcp`, on `multi-user` |
| Public URL | `https://managebac.822538.xyz` via Cloudflare Tunnel → `127.0.0.1:8000` |
| Services | `com.managebac.mcp` (the app), `com.managebac.cloudflared` (the tunnel) — both confirmed running this session (PID 722 / PID 1007) |
| Data | `~/.managebac_mcp/`: `users.db` (24K), `admin.db` (48K), `cache.db` (9.1MB), `files/` (4.6MB), `secret.key` |
| Health at this checkpoint | Public endpoint confirmed 200 OK; repo confirmed clean and in sync with `origin/multi-user` at `a32054d` |

**Known ops issues, confirmed but not fixed as of this checkpoint:**
- **App logs are effectively unrecoverable.** `/tmp/managebac-mcp.log` (the launchd
  `StandardOutPath`/`StandardErrorPath`) gets deleted out from under the running process by
  macOS's periodic `/tmp` cleanup, while the process keeps writing into the now-unlinked file
  (confirmed via `lsof` — the fd is open, the directory entry is gone). Fix identified but not
  applied: move the log path to somewhere persistent (e.g. `~/.managebac_mcp/logs/`) and restart.
- **`psutil` is not installed** in the server's venv, and isn't declared in `pyproject.toml`
  either — the admin panel's Server Health memory metric shows `—`. A plain `uv sync` won't fix
  this; it needs to be added as a real dependency.
- **Disk space is tight**, ~7% free container-wide. Root cause identified: 24+ accumulated hourly
  local Time Machine snapshots (not a real backup — no second disk exists, this is macOS's
  automatic local-snapshot fallback), estimated ~145GB reclaimable. The exact command was handed
  to the user (`sudo tmutil thinlocalsnapshots / 100000000000 4`, run interactively since it needs
  their password) — **not confirmed executed as of this checkpoint.**

## 7. GitHub issues backlog snapshot (48 total, as of 2026-07-16)

**Closed (7):** #1 (unit context), #2 (submit work), #3 (multi-client support), #4 (hosted
server), #7 (multi-account), #8 (release planning), #9 (attachment access).

**Open (~41), by theme:**
- **Legal/launch blockers:** #51 (no privacy policy/terms), #52 (no under-13/COPPA handling)
- **Reliability/observability:** #54 (server can go down unnoticed), #48 (no alerting), #49
  (scraper breaks silently on ManageBac HTML changes)
- **Account lifecycle:** #45 (confusing expired-session error), #46 (password change silently
  breaks connector), #47 (no self-serve password change/delete), #50 (2FA users can't enroll)
- **ChatGPT Apps SDK compliance:** #24 (no outputSchema — **now stale, this was fixed**), #25
  (CSP domain errors)
- **Widget/product polish:** #20 (class list widget), #21 (grades redesign), #22 (files
  redesign), #23 (unify upcoming/per-class widgets), #26 (general widget cleanup)
- **Native app track (mostly unstarted):** #27 (real domain), #28 (native iOS app), #29 (home/
  lock-screen widgets — edited this session, wood/amber language stripped), #30 (Apple Watch),
  #31 (push notifications)
- **Strategic/open:** #55 (how is Cadence different from ManageBac's own app — unresolved), #56
  (rethink the architecture — vague, unscoped), #32 (widget style presets — edited this session),
  #33 (native-ChatGPT vs branded widget styling — edited this session, recommends native for v1)

**New finding this session, not yet an issue:** OpenAI's Apps SDK app guidelines explicitly
reject apps that are "primarily unofficial connectors to third-party services" that "scrape
external sites... without proper authorization." ManageBac MCP is structurally exactly that. This
doesn't block current usage (developer-mode/direct-connector usage isn't a public listing), but
it means an eventual App Store submission isn't a pure engineering checklist — it may need an
actual authorization conversation with ManageBac (the company) first. Full writeup in
`WIDGETS.md` §14. Worth turning into a tracked issue if it isn't already.

## 8. This session's work, chronologically

1. Diagnosed and fixed a chain of missing dev-machine tooling (this Mac had none of: Homebrew,
   Tailscale, `gh`, `uv`, Node.js — all installed fresh this session).
2. Restored Tailscale SSH access to production, confirmed it healthy (uptime 3d+, both services
   running, public endpoint 200 OK).
3. Diagnosed the "low disk space" concern down to accumulated local TM snapshots (not the app) —
   command handed off, not yet run.
4. Deleted six files carrying the scrapped wood/amber/conductor design direction (all untracked,
   never committed — zero git history lost).
5. Edited GitHub issues #29, #32, #33 to strip the same stale design language.
6. Rewrote `WIDGETS.md` from scratch as a comprehensive Apps SDK reference — all 27 official docs
   pages actually read (five parallel subagents fetching raw markdown directly, not single-pass
   WebFetch summaries), organized with a table of contents and a gap analysis against this
   codebase's actual code.
7. Added tool annotations to all 14 tools; found and fixed two real `structuredContent` size bugs
   (`get_task_detail`/`find_task` were exceeding ChatGPT's undocumented ~4-5KB widget-drop
   ceiling; `get_grades()` was right at the edge) via a live-account audit — not a code-reading
   guess, actual measured bytes against the developer's real 18-class ManageBac account.
8. Had Codex independently review that diff; it caught two real gaps (`find_task` had the same
   size bug un-fixed; naive text-slicing could corrupt the HTML `description` field) — both fixed
   in the same pass, plus a shared `_cap_task_widget_sc()` helper extracted so the two call sites
   can't drift apart again.
9. Fixed the broken local widget-preview server config (stale path from a different machine,
   missing Node.js).
10. Branched `design-refresh` off `multi-user` for all of the above and everything that follows.
11. This archive.

## 9. Known open issues at this exact checkpoint (recap)

- `submit_task_file` not registered as a callable MCP tool (fix possibly in flight in a parallel
  worktree — check before assuming still broken).
- Production log file unrecoverable due to `/tmp` cleanup racing the running process.
- `psutil` missing from the server venv and from `pyproject.toml`.
- ~145GB reclaimable from local TM snapshots on the production Mac — command ready, not run.
- `get_tasks` batched across all classes can hit 60KB+ in one call — flagged as a soft,
  description-level-only guardrail, deliberately not hard-capped (see `WIDGETS.md` §19 for the
  reasoning).
- Zero widget interactivity — no `callTool`/`setWidgetState`/`notifyIntrinsicHeight`/
  `requestDisplayMode` anywhere.
- No OAuth — custom `?key=` token auth only.
- No dark mode in any widget.
- App Store submission has a real, not-yet-addressed policy risk (§7 above / `WIDGETS.md` §14).

## 10. Reference locations

- **Repo:** `github.com/levnw/managebac-mcp` — issues are the roadmap, not a static checklist.
- **Production:** Tailscale SSH `server@100.77.121.118`, repo at `/Users/server/managebac-mcp`.
- **Public URL:** `https://managebac.822538.xyz`.
- **Cold-start technical briefing:** `HANDOFF4.md` (supersedes `HANDOFF.md`–`HANDOFF3.md` for
  anything conflicting).
- **Apps SDK reference:** `WIDGETS.md` — living document, keep it updated; this archive is not.
- **Session memory:** `/Users/mac/.claude/projects/-Users-mac-Desktop-Projects-Managebac-MCP/
  memory/` (`MEMORY.md` index) — carries forward user/project context across future sessions.

---

## Exact restore point

- **Commit:** `77daf66b4c1a2d566ffb73b925b5e4a56c6fe2fc` (branch `design-refresh`)
- **Tag:** `pre-redesign-2026-07-16` (annotated, points at the commit that adds *this file*)
- **Parent production state:** `multi-user` was at `a32054d` (Normalize school URL + add tooltip
  on enroll form) when `design-refresh` branched off it — that's the last commit actually
  deployed to production as of this checkpoint.
