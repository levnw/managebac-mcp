# ManageBac MCP

An MCP (Model Context Protocol) server that gives AI assistants access to your ManageBac student account — tasks, timetable, grades, teacher comments, units, files, journal entries, discussions, and attachment contents.

Works with **Claude Desktop** out of the box (local stdio), and with **ChatGPT** or any HTTP MCP client via the built-in HTTP server (`managebac-mcp serve`) behind a tunnel or reverse proxy. Students connect from ChatGPT with a one-tap **OAuth sign-in popup** (like Canva's app) — they add one shared URL and log in with their ManageBac account.

> ⚠️ **Read-only over MCP.** Every tool exposed to an AI assistant only reads data — the server never comments, deletes, or modifies anything in ManageBac. (File submission to a task dropbox exists only as an operator CLI command, `managebac-mcp submit`; it is not exposed as an AI tool.)

---

## What it does

ManageBac is the IB school learning management system where teachers post assignments, grades, and feedback. This server scrapes it over HTTP (no browser needed — all content is server-rendered).

Once set up, you can ask your AI things like:

- *"What tasks do I have due this week?"*
- *"What did my teacher say about my Process Journal?"*
- *"Show me the description and links for this task: [paste URL]"*
- *"What classes do I have tomorrow and which ones have pending tasks?"*
- *"What files has my English teacher uploaded?"*
- *"What's in my Digital Design journal?"*

---

## Tools

| Tool | What it returns |
|------|----------------|
| `get_classes` | All enrolled classes with IDs, URLs, and whether they have a journal |
| `get_timetable` | Full weekly timetable — period, day, time, class name, teacher, room, task count, class ID |
| `get_tasks(class_id)` | All tasks for a class — title, due date/time, type, tags, status, grades, teacher comment (Markdown) |
| `get_task_detail(class_id, task_id)` | Full task — description (Markdown with bold/italic/lists), embedded file links, external links, submitted files, discussions |
| `get_units(class_id)` | All curriculum units with the full IB framework — statement of inquiry, key concepts, related concepts, global context, inquiry questions, ATL skills, status |
| `get_files(class_id)` | Resource files the teacher uploaded to the class, each with a download URL |
| `get_journal(class_id)` | Learner portfolio / journal entries with body text (Markdown), links, and attached files |
| `find_task(query)` | Find a task by pasting a ManageBac URL, or fuzzy-search by title across all classes |
| `get_upcoming` | Upcoming tasks across **all** classes in one call, sorted by due date |
| `get_grades(class_id?)` | Grades across all classes, or the per-criterion breakdown + graded tasks for one class |
| `tag_search(tag)` | Find tasks carrying a given tag (e.g. "Summative", "Homework") across all classes |
| `show_*` tools | Visual ChatGPT widgets (`show_task_detail`, `show_tasks`, `show_grades`, `show_timetable`, `show_files`, `show_classes`, `show_upcoming`) |
| `refresh` | Drop the cache for the current user so the next fetch pulls live data from ManageBac |

> For cross-class questions the AI should prefer the consolidated tools
> (`get_upcoming`, `get_grades`, `tag_search`) over calling `get_tasks` per class.

### Batch fetching
`get_tasks`, `get_units`, `get_files`, and `get_journal` accept either a single
`class_id` or a **list** of them — all fetched concurrently in one call.
`get_task_detail` accepts a `tasks` list of `{class_id, task_id}` pairs.
This lets the AI pull data for every subject at once instead of one call per class.

### How `find_task` works
- **URL mode**: paste any ManageBac task URL → extracts the class ID and task ID automatically
- **Fuzzy title mode**: type part of a task name → searches across all classes and returns the best match

### Reading attachments
`get_task_detail` and `get_files` expose a `url` on every file. ChatGPT-facing
file analysis now goes through the widget attachment-selection flow rather than
a separate file-content command.

### Submitting work (operator CLI only)
`managebac-mcp submit` uploads a local file to a task's submission dropbox — the
one **write** path, available only from the terminal, never as an AI tool. It
defaults to `--dry-run` (preview only) and uploads only when explicitly told to.

---

## Setup

### Requirements
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- A ManageBac student account

### Install

```bash
git clone https://github.com/YOUR_USERNAME/managebac-mcp
cd managebac-mcp
uv sync
```

### Configure credentials

```bash
cp .env.example .env
# Edit .env with your ManageBac URL, email, and password
```

Or run the interactive setup (also installs to Claude Desktop):

```bash
managebac-mcp setup
```

Credentials are stored in `~/.managebac_mcp/.env` — separate from the project, so they're never accidentally committed.

### Install to Claude Desktop

```bash
managebac-mcp install
```

Then restart Claude Desktop. The tools appear automatically in the 🔨 menu.

---

## Multi-user / ChatGPT (remote HTTP)

> **This is the `multi-user` branch.** It runs the server as a small multi-user
> web service so you and a few friends can each connect your *own* ManageBac
> account from ChatGPT. (The `main` branch is the single-user, local Claude
> Desktop version.)

Claude Desktop runs the server locally and reads one account. ChatGPT can't do
that — it connects to a **public URL**. So here the server runs once (on your
own machine or server), everyone adds the **same** connector URL, and ChatGPT's
OAuth sign-in popup keeps each student scoped to their own account.

### How auth + isolation work (no user ever sees another's data)

- Auth is **OAuth 2.1** (the server is its own authorization server — see
  `oauth.py`). ChatGPT opens a sign-in popup on your domain; the student logs in
  with their ManageBac credentials; ChatGPT receives an **access token** it sends
  as `Authorization: Bearer …` on every request.
- Each request is pinned to that user via a request-scoped context. Every
  ManageBac fetch and every cache row is namespaced by user id.
- **Fail closed:** a request with no valid token gets a `401` + a
  `WWW-Authenticate` challenge (which is what makes ChatGPT show *Sign in*).
  There is no global fallback account.
- Passwords are **encrypted at rest** (`~/.managebac_mcp/secret.key`); access
  and refresh tokens are stored hashed (`oauth.db`). Each user has their own
  session cookies and can be at a different school.

> ⚠️ Storing other people's ManageBac passwords is a real responsibility. The
> encryption protects against a stolen database file, but not against a full
> compromise of the server (the key lives on the same box). Tell your friends
> honestly that their login sits on your server.

### 1. Run the server

```bash
managebac-mcp serve --host 0.0.0.0 --port 8000 \
  --public-url https://managebac.yourdomain.com
```

`--public-url` is **required** — the OAuth discovery metadata is built from it.

### 2. Expose it with your Cloudflare Tunnel

Point your tunnel at the local port so `https://managebac.yourdomain.com`
forwards to `http://localhost:8000`. HTTPS is required — the OAuth sign-in page
receives passwords.

### 3. Hand out a one-time invite code

A *new* student's first sign-in requires a valid, unused **invite code**
(generated by the operator in the admin panel). Each code works once and is only
consumed after the ManageBac login is confirmed valid, so a failed attempt never
wastes a code. (Returning students just log in — no code.)

### 4. The student connects

Everyone adds the **same** connector — no per-person URL:

```
https://managebac.yourdomain.com/mcp
```

In ChatGPT → **Settings → Connectors → Add custom connector** → paste that URL →
create → click **Sign in**. The popup is a school-branded login page (logo + name
pulled live from that school's ManageBac login, so a new school needs zero
setup): the student enters their ManageBac URL, email, password, and — first time
only — an invite code. That's it.

> ChatGPT custom connectors require a paid plan with developer mode enabled, and
> OpenAI changes the exact steps periodically. (A styled `/enroll` web page also
> still exists as an alternative way to pre-register an account.)

### Rich ChatGPT widgets

Most tools have a `show_*` counterpart that renders a native, **ChatGPT-styled**
card inline in the chat (Apps SDK): task card, task list, grades (with an
interactive **Edit & predict** mode — drag sliders to model target scores and
ask ChatGPT how to reach them), weekly timetable, class files, and class list.
They inherit ChatGPT's own look in light and dark mode rather than imposing a
brand. Data-only `get_*` tools return the same data without a widget, so the
model can reason over it first.

### Managing users (operator)

```bash
managebac-mcp users          # list enrolled users
managebac-mcp deluser <id>   # remove a user and wipe their cached data
```

---

## CLI commands

```bash
# Interactive setup + Claude Desktop registration
managebac-mcp setup

# Re-register with Claude Desktop
managebac-mcp install

# Inspect raw tool output in the terminal
managebac-mcp peek classes
managebac-mcp peek timetable
managebac-mcp peek tasks        --class 12734244
managebac-mcp peek task         --class 12734244 --task 47617250
managebac-mcp peek units        --class 12734244
managebac-mcp peek files        --class 12734244
managebac-mcp peek journal      --class 12734244
managebac-mcp peek find         --query "end of unit reflection"
managebac-mcp peek file-content --url "https://es.managebac.com/attachments/..."

# Force a fresh scrape (bypass cache)
managebac-mcp peek classes --no-cache

# Submit a file to a task's dropbox (previews first, asks before uploading)
managebac-mcp submit --class 12734244 --task 48220527 --file ~/Documents/essay.pdf

# Run the HTTP server for ChatGPT / remote clients
managebac-mcp serve --host 0.0.0.0 --port 8000 --public-url https://mb.yourdomain.com

# View what's currently in the cache
managebac-mcp cache-view
```

---

## Caching

All responses are cached in SQLite at `~/.managebac_mcp/cache.db` to avoid hammering ManageBac on every question.

| Data | Cache TTL |
|------|-----------|
| Classes | 24 hours |
| Timetable | 6 hours |
| Tasks list | 10 minutes |
| Task detail | 30 minutes |
| Units | 24 hours |
| Files | 1 hour |
| Journal | 30 minutes |
| File content | 1 hour (cached to disk at `~/.managebac_mcp/files/`) |

---

## How it works

ManageBac is a server-rendered Rails app — all content is in the raw HTML, including text that appears to be hidden behind "Show More" buttons (those are CSS-only). The server uses:

- **`httpx`** — async HTTP client for all requests (with a real Chrome User-Agent — bot UAs get reduced pages)
- **`BeautifulSoup4` + `lxml`** — HTML parsing
- **`mcp` SDK** — both stdio (Claude Desktop) and Streamable HTTP (ChatGPT) transports via the same tool definitions
- **`Starlette` + `uvicorn`** — ASGI layer for the HTTP transport, OAuth endpoints, and enroll page
- **`SQLite`** — user store, cache, admin/invite codes, and OAuth clients/codes/tokens (all separate databases)

No browser automation, no Playwright, no JavaScript execution needed.

Auth flow: `GET /login` → extract CSRF token → `POST /sessions` → store session cookie. Re-authenticates automatically on session expiry.

---

## Project structure

```
managebac_mcp/
├── config.py        # Credentials loading (~/.managebac_mcp/.env)
├── auth.py          # Login, CSRF, session cookie management
├── scraper.py       # All HTTP fetching + HTML parsing
├── cache.py         # SQLite cache + TTL management
├── server.py        # MCP server + tool definitions (shared by stdio and HTTP)
├── http_server.py   # HTTP/Streamable transport + OAuth endpoints + enroll web page
├── oauth.py         # OAuth 2.1 authorization server + token store (oauth.db)
├── branding.py      # Per-school logo + name, pulled live from the school's login page
├── users.py         # Multi-user store: encrypted credentials, session cookies
├── backoffice.py    # Operator data: invite codes, messaging, audit log (admin.db)
├── context.py       # Request-scoped per-user context (fail-closed isolation)
└── cli.py           # managebac-mcp CLI (setup, install, peek, submit, serve, cache-view)

tests/
├── test_parsers.py   # Unit tests using saved HTML fixtures
├── test_live.py      # Integration tests (hit real ManageBac, marked slow)
└── smoke_test.py     # Quick sanity check for all tools
```

---

## Changelog

### Unreleased

- **OAuth 2.1 sign-in (Canva-style popup)** — the connector authenticates via OAuth instead of a per-user `?key=` URL. The server is its own authorization server (`oauth.py` + `/authorize`, `/token`, discovery, DCR): everyone adds one shared `/mcp` URL, ChatGPT shows a *Sign in* button, and the school-branded popup does full enrollment (new users) or login (returning). PKCE, opaque hashed access/refresh tokens with rotation, and 401 + `WWW-Authenticate` challenges. **Breaking:** old `?key=` connectors no longer work — users re-add `/mcp` and sign in once.
- **ChatGPT-native widget redesign** — the inline cards were rebuilt to inherit ChatGPT's own look (system fonts/colours, light + dark) instead of ManageBac branding, and split into data-only `get_*` tools and render `show_*` tools. Includes an interactive **grade predictor** (drag sliders to model target scores, "ask how to improve"), a class list, and a task list.
- **Per-school auto-branding** — `branding.py` pulls each school's logo and name from their own ManageBac login page (Chrome UA) and caches it 24 h. Zero config for a new school; graceful fallback to neutral "ManageBac".
- **Invite code system** — a new student's first sign-in requires a valid, unused invite code (generated via the admin panel). Codes are consumed atomically *after* the ManageBac login is confirmed valid, so a failed attempt never wastes a code. Returning users just log in.
- **Admin panel** — a web UI (served at `/admin`) over an `/admin/*` API: invite codes, list/pause/delete users, view password, per-user + broadcast messaging, audit log.
- **Multi-user isolation** — request-scoped per-user context (`context.py`) with fail-closed enforcement; every cache row is namespaced by user id; passwords encrypted at rest.
- **ChatGPT / remote support** — `managebac-mcp serve` runs the same tools over Streamable HTTP through a Cloudflare Tunnel or reverse proxy. Stdio (Claude Desktop) and HTTP share the same tool definitions.
- **New consolidated tools** — `get_upcoming` (all due tasks across all classes, sorted by date), `get_grades` (all grades, or per-criterion breakdown for one class), `tag_search` (find tasks by tag across all classes), `refresh` (drop cache for the current user).

### v1.0.0 — First technical release

The full toolset is in place and working end-to-end against a live account.

**New tools since v0.1.0:**
- `get_units` — every curriculum unit with the full IB framework (statement of inquiry, key concepts + definitions, related concepts, global context, conceptual understanding, inquiry questions typed Factual/Conceptual/Debatable, ATL skills, status). Fetches all unit detail popups concurrently in one session.
- `submit_task_file` — uploads a local file to a task's dropbox (multipart POST with CSRF). The only write operation; defaults to `dry_run=true` and only uploads on explicit confirmation.

**Improvements:**
- **Batch fetching** — `get_tasks`, `get_task_detail`, `get_units`, `get_files`, and `get_journal` accept a list of IDs and fetch concurrently (≈3× faster for multi-subject queries).
- Tool descriptions rewritten to be school-agnostic — no hardcoded URL, no IB/MYP wording — so the server works for any ManageBac school.
- `get_files` now exposes a `url` (pre-signed download link) on every file.

**Bugs fixed:**
- `lxml` was silently stripping the `data-ec3-info` attribute that holds class file download URLs → `parse_files` now uses `html.parser`.
- `submit_task_file` failed on relative paths because the MCP server's working directory differs from where files are created → now resolves/validates paths and returns a clear error telling the caller to use an absolute `/tmp/` path.

### v0.1.0

**Tools built:**
- `get_classes`, `get_timetable`, `get_tasks`, `get_task_detail`, `get_files`, `get_journal`, `find_task`

**Bugs fixed during development:**
- Tags on tasks were pulling in dates, status words, and grade numbers → fixed with targeted junk filter
- Timetable `class_name` was the entire cell text concatenated (time + class + grade + teacher) → rewrote parser using `a.f-timetable-item` structure; also added `class_id` per slot
- Journal parser matched navigation menu items and cookie consent banners as entries → anchored on `div.journal-evidence` class
- Journal `learning_outcomes` showed `["Read-only"]` instead of actual MYP criteria → filtered meta-labels
- Embedded PDFs in task descriptions showed as mangled markdown links `[filename418 KB](url)` → `fr-file` links now render as `📎 filename (size)` in text and expose `url` in `embedded_files`
- Bare URLs typed as plain text by teachers weren't appearing in `description.links` → added regex scan of text nodes
- `description.text` was plain text stripping all teacher formatting → converted to Markdown (`**bold**`, `*italic*`, numbered lists, `[link](url)`) using inline style detection
- Session file and cache path used `Path(__file__).parent` which broke when package was installed to site-packages → moved all user data to `~/.managebac_mcp/`
- uv editable install wrote quoted paths in `.pth` files that Python's site module couldn't parse (space in project directory name) → copy package directly to site-packages
- Discussions were counted but not fetched → added `/discussions` sub-page fetch to every `get_task_detail` call; parses author, timestamp, message body (Markdown), links, and replies

---

## Roadmap

Future work is tracked in GitHub Issues instead of being maintained as a static checklist. This keeps planning, discussion, and implementation details in the right place.

### Done

- ✅ Unit context (`get_units`)
- ✅ Selecting protected task attachments and class files for ChatGPT handoff
- ✅ Submitting work to a task (`submit_task_file`)
- ✅ Multi-user hosted server with per-user isolation and encrypted credential storage
- ✅ ChatGPT support via Streamable HTTP + Cloudflare Tunnel
- ✅ OAuth 2.1 / Canva-style sign-in popup (`/authorize`, `/token`, PKCE, DCR)
- ✅ Per-school auto-branding with zero config
- ✅ ChatGPT-native widgets + interactive grade predictor
- ✅ Admin panel (invite codes, users, messaging, audit) — web + native app
- ✅ Consolidated cross-class tools (`get_upcoming`, `get_grades`, `tag_search`, `refresh`)

### Next

- **Stale-data awareness** — help the AI notice when cached ManageBac data may be outdated (a task gets graded, a due date changes) so it knows when to re-check instead of trusting old data.
- **Fullscreen widget views** — full-week timetable grid, file browser, and a grade-trend explorer, using ChatGPT's fullscreen display mode.

### Product ideas

Bigger product ideas — paid usage, school-wide deployments, submission workflows with AI feedback — are tracked as separate GitHub Issues.

---

## Security

- Credentials are stored in `~/.managebac_mcp/.env`, never in the project directory
- `.env` is in `.gitignore` — will never be committed
- **Every tool exposed to an AI assistant is read-only** — nothing is ever commented, deleted, submitted, or otherwise modified in ManageBac. The one write path (uploading a file to a task dropbox) exists only as an operator CLI command (`managebac-mcp submit`, dry-run by default), never as an AI tool.
- ChatGPT authenticates via OAuth 2.1; access/refresh tokens are stored hashed and are revoked when an admin deletes or regenerates a user.
