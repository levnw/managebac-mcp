# ManageBac MCP

An MCP (Model Context Protocol) server that gives AI assistants full read access to your ManageBac student account — tasks, timetable, grades, teacher comments, files, journal entries, and discussions.

Works with **Claude Desktop** out of the box. The first release is focused on a local Claude setup, but the project is intended to grow toward broader AI/client support over time.

> ⚠️ **Read-only by design.** The current server never submits, comments, deletes, or modifies anything in ManageBac.

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
| `get_files(class_id)` | Resource files the teacher uploaded to the class |
| `get_journal(class_id)` | Learner portfolio / journal entries with body text (Markdown), links, and attached files |
| `find_task(query)` | Find a task by pasting a ManageBac URL, or fuzzy-search by title across all classes |

### How `find_task` works
- **URL mode**: paste any ManageBac task URL → extracts the class ID and task ID automatically
- **Fuzzy title mode**: type part of a task name → searches across all classes and returns the best match

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
managebac-mcp peek tasks   --class 12734244
managebac-mcp peek task    --class 12734244 --task 47617250
managebac-mcp peek files   --class 12734244
managebac-mcp peek journal --class 12734244
managebac-mcp peek find    --query "end of unit reflection"
managebac-mcp peek find    --query "https://es.managebac.com/student/classes/.../core_tasks/..."

# Force a fresh scrape (bypass cache)
managebac-mcp peek classes --no-cache

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
| Files | 1 hour |
| Journal | 30 minutes |

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
└── cli.py         # managebac-mcp CLI (setup, install, peek, cache-view)

tests/
├── test_parsers.py   # Unit tests using saved HTML fixtures
├── test_live.py      # Integration tests (hit real ManageBac, marked slow)
└── smoke_test.py     # Quick sanity check for all tools
```

---

## Changelog

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

### First release: local Claude setup

The first release is focused on making the MCP work well as a local tool, especially with Claude Desktop. The goal is to keep setup clear, clean up development-only files, and make the current read-only tools reliable.

### Next: better task context

After the first release, the project should improve how AI understands tasks. This includes better unit context, protected task attachments, linked files, and making sure the AI can notice when ManageBac data may have changed.

### Later: broader AI and hosted access

Longer term, the project may move beyond a local-only setup. The goal is to explore support for more AI clients, such as ChatGPT, Claude, Gemini, and personal AI assistants, possibly through a hosted/server version instead of requiring every user to run it on their own machine.

### Product ideas

Bigger product ideas, such as multiple student accounts, hosted access, paid usage, and safe submission workflows, are tracked as separate GitHub Issues so they can be discussed and designed properly.

---

## Security

- Credentials are stored in `~/.managebac_mcp/.env`, never in the project directory
- `.env` is in `.gitignore` — will never be committed
- The current server is **read-only** — it calls only `GET` endpoints and never submits forms, posts comments, or deletes anything
