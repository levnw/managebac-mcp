# ManageBac MCP — Handoff

A complete cold-start briefing for another AI/engineer picking up this project.
Everything you need: what it is, where it lives, how it's deployed, what's been
fixed, what to watch out for, and what's left.

---

## 1. What this is

A **multi-user MCP (Model Context Protocol) server** that connects a student's
**ManageBac** account (their school's learning platform) to an AI assistant
(ChatGPT custom connector / Claude). Students enroll with their ManageBac login
and get a private connector URL; the AI can then answer questions about their
classes, tasks, grades, deadlines, units, files, and journal.

There is **no ManageBac API** — everything is done by **scraping ManageBac's
HTML** with `httpx` + `BeautifulSoup`. Each student's credentials are stored
encrypted and replayed to log in as them.

**Primary user goal:** predicting IB MYP grades from criterion scores (the
`get_grades` tool is the backbone of that).

School in use: European School (Georgia), `https://es.managebac.com`, IB MYP
(criterion A–D, scores out of 8). Grade 8.

---

## 2. Where everything lives

| Thing | Location |
|---|---|
| **Local repo (dev)** | `/Users/levanjaparidze/Documents/aplactions/student portal` |
| **GitHub** | `https://github.com/levnw/managebac-mcp` (branch: **`multi-user`**) |
| **Production server** | `ssh server@100.77.121.118` (Tailscale SSH) |
| **Server repo** | `/Users/server/managebac-mcp` (branch `multi-user`) |
| **Public URL** | `https://managebac.822538.xyz` (Cloudflare Tunnel → localhost:8000) |
| **Data dir (server)** | `/Users/server/.managebac_mcp/` |
| **Admin app (SwiftUI)** | `Server manage/` (macOS + iOS, talks to `/admin/*` API) |

⚠️ **`deploy/DEPLOY.md` is WRONG about the OS.** It describes Debian/systemd.
The real production server is **macOS (Darwin arm64)** running services via
**launchd**, not Linux/systemd. Trust this file over DEPLOY.md.

---

## 3. Architecture

```
ChatGPT / Claude  ──HTTPS──>  Cloudflare  ──tunnel "genesis"──>  cloudflared (server Mac)
   (MCP connector,                                                     │
    ?key=<token>)                                                      └─> 127.0.0.1:8000
                                                                            managebac-mcp (uvicorn/Starlette)
                                                                            │
                                                                            └─> es.managebac.com (scrape, per-user session)

Server Manage app  ──HTTPS──>  same /admin/* endpoints (Bearer admin token)
```

- The MCP server listens only on `127.0.0.1:8000`; Cloudflare reaches it via the
  tunnel. No inbound ports open.
- **Per-request user isolation:** the `?key=<token>` in the connector URL → the
  server looks up the user → pins them into a `contextvar` → every fetch/cache
  read is scoped to that user. No token = fail closed.

---

## 4. Production server reality (macOS / launchd)

- **OS:** macOS (Darwin), host `server.local`, user `server` (uid **502**).
- **SSH:** Tailscale SSH. **First connection each session prompts for browser
  re-auth** (`https://login.tailscale.com/a/...`) — only the human can click it.
  If SSH hangs or times out, that's usually the re-auth, or the Mac is asleep.
- **`uv`** is at `/Users/server/.local/bin/uv` (NOT on PATH).
- **Services run as launchd user agents in `gui/502`** (NOT system daemons):
  - `com.managebac.mcp` → `.venv/bin/managebac-mcp serve --host 127.0.0.1 --port 8000 --public-url https://managebac.822538.xyz`
  - `com.managebac.cloudflared` → cloudflared tunnel run genesis
  - Both have `KeepAlive=true` → auto-restart on crash / when machine wakes.
  - Logs: `/tmp/managebac-mcp.log`, `/tmp/cloudflared.log`
- **Sleep is disabled** (`sudo pmset -a sleep 0 disablesleep 1 autorestart 1 womp 1`)
  so the Mac doesn't drop the tunnel. If 502s return, first check the Mac is
  awake/online.

### Deploy
```bash
ssh server@100.77.121.118
cd /Users/server/managebac-mcp
git pull --ff-only origin multi-user
~/.local/bin/uv sync               # only needed if deps changed
launchctl kickstart -k gui/502/com.managebac.mcp   # restart (KeepAlive)
# verify:
curl -s localhost:8000/            # -> "ManageBac MCP server is running..."
git log --oneline -1
```
Back up data first when in doubt:
```bash
tar czf ~/managebac_mcp_data_backup_$(date +%Y%m%d-%H%M%S).tgz -C ~ .managebac_mcp
```

### Rollback
```bash
cd /Users/server/managebac-mcp
git reset --hard <tag>             # e.g. backup-pre-grades-fix, or any vX.Y.Z
launchctl kickstart -k gui/502/com.managebac.mcp
```
Data (`~/.managebac_mcp/*.db`, `secret.key`) is never touched by a code deploy.

### Health checks
```bash
curl https://managebac.822538.xyz/                 # 200 = up
curl -o/dev/null -w '%{http_code}' .../admin/users # 401 = healthy (auth required), 500/502 = broken
```

---

## 5. Python package map (`managebac_mcp/`)

| File | Responsibility |
|---|---|
| `server.py` | MCP server: tool definitions (`list_tools`), dispatch (`call_tool`) with the **error buffer**, `SERVER_INSTRUCTIONS`, and the `_slim_tasks` context-saver. Also stdio entrypoint. |
| `http_server.py` | Multi-user HTTP transport (Starlette ASGI). `/mcp` endpoint (token→user→dispatch), `/enroll` page, all `/admin/*` endpoints. |
| `scraper.py` | All HTML parsing + fetch functions (`fetch_classes`, `fetch_tasks`, `fetch_grades`, `fetch_upcoming`, `fetch_task_detail`, `fetch_units`, `fetch_files`, `fetch_journal`, `fetch_file_readable`, `tag_search`, `find_task`, `submit_task_file`, `prewarm`). Pure `parse_*` funcs are unit-tested against fixtures. |
| `auth.py` | Per-user login/session. `login()`, `authed_get()` (transparent re-login + raises `ManageBacError` on persistent login redirect), request throttle semaphore (4), per-user login lock. |
| `users.py` | User store (`users.db`): encrypted credentials (Fernet), tokens, per-user session cookies. CRUD incl. `update_email`/`update_password`, `set_enabled`, `regenerate_token`. |
| `admin.py` | Admin store (`admin.db`): admin login (PBKDF2), session tokens, one-time invite codes. |
| `cache.py` | Per-user response cache (`cache.db`) with TTLs + the request log (used by admin activity views). |
| `context.py` | `contextvar` user isolation (`set_current_user`/`require_user`) + `ManageBacError` (human-readable failure reason). |
| `config.py` | Env/paths + **`config.connect()`** = self-closing sqlite connection (WAL + busy_timeout). **All `_connect()`s use this.** |
| `cli.py` | Local CLI (peek/submit/cache-view) using a fixed `local` user from `.env`. |

### MCP tools (what the AI can call)
`get_classes`, `get_timetable`, `get_upcoming`, `get_tasks`, `get_task_detail`,
`get_files`, `get_journal`, `get_units`, `get_grades`, `tag_search`,
`find_task`, `get_file_content`, `refresh`.

Notes:
- Cross-class questions should use `get_upcoming` / `get_grades` / `tag_search`,
  NOT batched `get_tasks` (context cost). The descriptions + `SERVER_INSTRUCTIONS`
  steer the model this way.
- `get_grades` (all classes) = per-criterion summary only; pass a `class_id` for
  full graded-task detail incl. teacher comments.
- `get_file_content` downloads via the student's session and returns extracted
  **text** (PDF/DOCX) or the **image**. For submitted work, use the `url` field
  on `submitted_files` from `get_task_detail`.

### Admin API (`/admin/*`, Bearer token from `/admin/login`)
`login`, `codes` (GET/POST), `codes/{code}` (DELETE), `users` (GET),
`users/{id}` (DELETE), `.../pause`, `.../regenerate`, `.../approve`,
`.../credentials` (change ManageBac email/password + test login), `.../note`,
`.../activity`, `/admin/activity`.

---

## 6. SwiftUI admin app (`Server manage/`)

macOS/iOS app for the operator. Talks to the `/admin/*` API.
- `APIClient.swift` — `Session` (keychain-stored admin token) + `API` (all calls,
  incl. `updateCredentials`).
- `Models.swift` — `AdminUser`, `InviteCode`, `ActivityItem`, etc.
- `UsersView.swift` — user list + `UserDetailView` (pause/resume, regenerate
  link, note, **edit ManageBac email/password with "Save & test login"**, remove,
  activity).
- `CodesView.swift`, `ActivityView.swift`, `OverviewView.swift`, `LoginView.swift`,
  `RootView.swift`, `Theme.swift`, `Keychain.swift`.
- Default server URL baked in: `https://managebac.822538.xyz`.
- ⚠️ Xcode project tracks a `UserInterfaceState.xcuserstate` (UI junk) — do NOT
  commit it.

---

## 7. Data storage (`/Users/server/.managebac_mcp/`)

| File | Contents |
|---|---|
| `users.db` | users: id, token, label, mb_url, mb_email, **mb_password_enc** (Fernet), session_cookies, enabled, approved, note |
| `admin.db` | admins (PBKDF2), admin_sessions, invite_codes |
| `cache.db` | per-user response cache + request_log (last 500 calls, includes responses) |
| `secret.key` | Fernet key for password encryption — **back up separately, keep private** |
| `files/` | disk cache of downloaded attachments (1h) |

Cache TTLs (`cache.py`): classes 24h, timetable 6h, tasks 10m, task_detail 30m,
files 1h, journal 30m, units 24h, file_content 1h.

---

## 8. Multi-user / auth model

- Enroll at `/enroll` (needs a valid one-time **invite code**; create codes in the
  admin app). Verifies the login against ManageBac before saving.
- **No approval gate** (removed v1.2.0): a user works the instant they enroll.
  Admin can still **pause** (`enabled=0`) to cut access.
- Each user has a secret token = the `?key=` in their connector URL. Regenerate
  it to revoke/rotate.
- Passwords are reversibly encrypted (must be replayed to ManageBac). A server
  compromise + `secret.key` = all credentials — known trade-off.

---

## 9. Fix history (this is current as of v1.8.0)

| Tag | What & why |
|---|---|
| `backup-pre-grades-fix` | rollback point (commit before the grades work) |
| v1.1.0 | **Empty get_classes/get_grades fixed.** `fetch_classes` was caching an empty parse for 24h, poisoning everything downstream. Now never caches empty; journal checks concurrent. Slimmed `get_grades`. Compact JSON. Added `ManageBacError` + tool **error buffer** (failures return `{"error": reason}` and are logged, instead of silent empties). |
| v1.2.0 | **Removed admin approval gate** — enrolled users work immediately. |
| v1.3.0 | **Admin edit of a user's ManageBac email/password** (backend `/admin/users/{id}/credentials` + Swift UI "Save & test login"). |
| v1.4.0 | **get_tasks slimmed** — drop teacher_comment, omit empty fields, cap 12 most-recent tasks/class. (Context: was up to ~58K tokens in one call.) |
| v1.5.0 | More context cuts — `tag_search` capped at 40, descriptions/instructions steer the model to consolidated tools & away from re-fetching. |
| v1.6.0 | **Task status fix** — read the status `span.badge-label` instead of scanning whole-row text (titles/teacher comments containing "submitted"/"complete" mislabeled tasks; "Submitted" matched inside "Not Submitted"). |
| v1.7.0 | **Read submitted files** — `submitted_files` now include the real signed CDN download `url` (was only the preview-modal token → `get_file_content` 404'd). |
| v1.8.0 | **sqlite fd-leak fix (502 root cause).** `with sqlite3.connect()` commits but never closes → fds leaked to the 256 limit → "unable to open database file" → 502 on ChatGPT + admin. `config.connect()` now self-closes + WAL + busy_timeout. |

---

## 10. Known gotchas / operational notes

1. **Tailscale SSH re-auth:** first SSH per session may need a browser approval
   link the human must click. SSH hangs/timeouts are usually this (or the Mac
   asleep). Filter the `# Tailscale...` / `# Authentication...` comment lines out
   of script output.
2. **ManageBac rate-limits logins.** Many rapid logins (heavy testing, many cold
   fetches/restarts) cause ManageBac to **block logins from the server IP** for a
   while → tools return the `ManageBacError` login-redirect message even with
   correct credentials. It clears on its own; back off and wait.
3. **Cold-fetch latency:** `get_grades`/`tag_search`/cross-class calls fan out to
   all ~18 classes; on a cold cache that's ~45s (throttled to 4 concurrent). Warm
   cache is instant. If a connector times out, this is why.
4. **502 vs 530:** 530/“origin unreachable” = the Mac is down/asleep (check ping
   `100.77.121.118`). 502 = tunnel up but the MCP process errored/crashed (check
   `/tmp/managebac-mcp.log`; the v1.8.0 fd leak was one cause — restart clears it).
5. **fd limit is 256** (launchd default). The leak is fixed, but if you ever see
   "unable to open database file", check `lsof -p <pid> | wc -l` and restart;
   consider raising `SoftResourceLimits NumberOfFiles` in the plist.
6. Empty caches **self-heal** on the next call now; or call `refresh` per user.

---

## 11. Testing

- **Unit tests:** `.venv/bin/python -m pytest tests/test_parsers.py -q` — 18 tests
  against real HTML in `tests/fixtures/` (classes, tasks_*, task_detail_*, files,
  journal, timetable). Use these to verify parser changes WITHOUT hitting
  ManageBac. Refresh fixtures via `tests/save_fixtures.py` (needs live login).
- **Measuring payload sizes:** `cache.db.request_log` stores every response;
  `SELECT tool, length(response) FROM request_log ...` shows real token costs.
  You can also POST a JSON-RPC `tools/call` to `localhost:8000/mcp?key=<token>`
  and measure the SSE `data:` text length.
- **Live in ChatGPT:** connector under `+` menu → managebac. Good test prompts:
  "list my Digital Design tasks with submission status", "predict my MYP grades
  from my criterion scores", "read the PDF I submitted for <task>".

---

## 12. Open / candidate next tasks

The admin email/password editor (a recurring ask) is **DONE** (v1.3.0). Remaining
ideas discussed but not built:

- **Generalize the empty-cache guard** beyond classes/timetable (tasks/upcoming/
  files can still cache an unlucky empty parse for their TTL).
- **Canary self-test:** a scheduled login + `get_classes`/`get_grades` for one
  account that alerts (push/email) if it returns empty/errors — proactive
  detection of ManageBac HTML changes.
- **MYP grade-boundary table** baked into `SERVER_INSTRUCTIONS` (or a tool) so
  predicted grades use a consistent rubric instead of the model guessing.
- **Chronological per-criterion series** in single-class `get_grades` for better
  trend-based prediction.
- **Per-user throttle** instead of one global semaphore (fairness as users grow).
- **Convert services to system LaunchDaemons** (`deploy/install-macos-daemons.sh`,
  needs `sudo` on the server) so they survive reboot/logout, not just sleep.
- **Stale-while-revalidate:** serve last-known-good cache past TTL when a live
  fetch fails, instead of erroring.
- **Move `secret.key` out of the data dir** (env/secret store) to reduce blast
  radius of a DB leak.

---

## 13. Quick reference — useful one-liners

```bash
# server state
ssh server@100.77.121.118 'cd /Users/server/managebac-mcp; git log --oneline -1; \
  launchctl print gui/502/com.managebac.mcp | grep -E "state|pid"; curl -s localhost:8000/'

# user states (no secrets)
ssh server@100.77.121.118 'sqlite3 ~/.managebac_mcp/users.db \
  "SELECT mb_email, enabled, approved FROM users;"'

# payload sizes per tool
ssh server@100.77.121.118 'sqlite3 ~/.managebac_mcp/cache.db \
  "SELECT tool, COUNT(*), MAX(length(response)) FROM request_log GROUP BY tool;"'

# tail server log
ssh server@100.77.121.118 'tail -30 /tmp/managebac-mcp.log'
```
