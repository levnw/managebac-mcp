# ManageBac MCP

An MCP (Model Context Protocol) server that gives AI assistants access to your ManageBac student account — tasks, timetable, grades, teacher comments, units, files, journal entries, discussions, and attachment contents. It can also submit work to a task's dropbox.

Works with **Claude Desktop** out of the box. The first release is focused on a local Claude setup, but the project is intended to grow toward broader AI/client support over time.

> ⚠️ **Almost entirely read-only.** Every tool reads data except one: `submit_task_file`, which uploads a file to a task's dropbox. It defaults to a preview-only dry run and only ever uploads when explicitly confirmed. The server never comments, deletes, or modifies anything else.

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
| `get_file_content(url)` | Downloads any attachment using your session and returns the raw file (PDF, image, …) for the AI to read natively — no text conversion |
| `submit_task_file(class_id, task_id, file_path)` | ⚠️ Uploads a local file to a task's dropbox. Always previews first; only submits on explicit confirmation |
| `find_task(query)` | Find a task by pasting a ManageBac URL, or fuzzy-search by title across all classes |

### Batch fetching
`get_tasks`, `get_units`, `get_files`, and `get_journal` accept either a single
`class_id` or a **list** of them — all fetched concurrently in one call.
`get_task_detail` accepts a `tasks` list of `{class_id, task_id}` pairs.
This lets the AI pull data for every subject at once instead of one call per class.

### How `find_task` works
- **URL mode**: paste any ManageBac task URL → extracts the class ID and task ID automatically
- **Fuzzy title mode**: type part of a task name → searches across all classes and returns the best match

### Reading attachments
`get_task_detail` and `get_files` expose a `url` on every file. Pass that URL to
`get_file_content` and the server downloads it through your authenticated session
and hands the raw file straight to the AI — so the AI can read a teacher's PDF
worksheet, rubric, or novel without you downloading anything yourself.

### Submitting work
`submit_task_file` uploads a local file to a task's submission dropbox. It is the
only **write** operation in the server and is deliberately cautious: it defaults to
`dry_run=true` (preview only) and only uploads when explicitly told to. Save the
file to an absolute path (e.g. `/tmp/essay.pdf`) before calling it.

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

- **`httpx`** — async HTTP client for all requests
- **`BeautifulSoup4` + `lxml`** — HTML parsing
- **`mcp` SDK** — stdio JSON-RPC server that Claude Desktop connects to

No browser automation, no Playwright, no JavaScript execution needed.

Auth flow: `GET /login` → extract CSRF token → `POST /sessions` → store session cookie. Re-authenticates automatically on session expiry.

---

## Project structure

```
managebac_mcp/
├── config.py      # Credentials loading (~/.managebac_mcp/.env)
├── auth.py        # Login, CSRF, session cookie management
├── scraper.py     # All HTTP fetching + HTML parsing
├── cache.py       # SQLite cache + TTL management
├── server.py      # MCP stdio server + tool definitions
└── cli.py         # managebac-mcp CLI (setup, install, peek, submit, cache-view)

tests/
├── test_parsers.py   # Unit tests using saved HTML fixtures
├── test_live.py      # Integration tests (hit real ManageBac, marked slow)
└── smoke_test.py     # Quick sanity check for all tools
```

---

## Changelog

### v1.0.0 — First technical release

The full toolset is in place and working end-to-end against a live account.

**New tools since v0.1.0:**
- `get_units` — every curriculum unit with the full IB framework (statement of inquiry, key concepts + definitions, related concepts, global context, conceptual understanding, inquiry questions typed Factual/Conceptual/Debatable, ATL skills, status). Fetches all unit detail popups concurrently in one session.
- `get_file_content` — downloads any attachment through the authenticated session and returns the **raw file** (PDF/image/…) so the AI reads it natively — no lossy text conversion.
- `submit_task_file` — uploads a local file to a task's dropbox (multipart POST with CSRF). The only write operation; defaults to `dry_run=true` and only uploads on explicit confirmation.

**Improvements:**
- **Batch fetching** — `get_tasks`, `get_task_detail`, `get_units`, `get_files`, and `get_journal` accept a list of IDs and fetch concurrently (≈3× faster for multi-subject queries).
- Tool descriptions rewritten to be school-agnostic — no hardcoded URL, no IB/MYP wording — so the server works for any ManageBac school.
- `get_files` now exposes a `url` (pre-signed download link) on every file, so class-wide files can be read with `get_file_content`.

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

### Done in v1.0.0
- ✅ Unit context (`get_units`)
- ✅ Reading protected task attachments and class files (`get_file_content`)
- ✅ Submitting work to a task (`submit_task_file`)

### Next: keeping data fresh

Help the AI notice when cached ManageBac data may be stale (a task gets graded, a due date changes, feedback appears) so it knows when to re-check instead of trusting old data.

### Later: broader AI and hosted access

Longer term, the project may move beyond a local-only setup. The goal is to explore support for more AI clients, such as ChatGPT, Claude, Gemini, and personal AI assistants, possibly through a hosted/server version instead of requiring every user to run it on their own machine.

### Product ideas

Bigger product ideas, such as multiple student accounts, hosted access, paid usage, and safe submission workflows, are tracked as separate GitHub Issues so they can be discussed and designed properly.

---

## Security

- Credentials are stored in `~/.managebac_mcp/.env`, never in the project directory
- `.env` is in `.gitignore` — will never be committed
- All tools are read-only except `submit_task_file`, which is the only tool that writes. It defaults to a preview-only dry run and uploads only on explicit confirmation. Nothing is ever commented, deleted, or otherwise modified.
