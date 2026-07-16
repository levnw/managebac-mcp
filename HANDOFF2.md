# ManageBac MCP — Handoff v2

An updated cold-start briefing for another AI/engineer. This file continues where
`HANDOFF.md` left off. Read that document first (sections 1–10 are still accurate).
This file covers everything added **after v1.8.0** through the current HEAD.

---

## What's new since v1.8.0

The sqlite fd-leak was fixed in v1.8.0 (502 root cause). Everything after that is
about the **ChatGPT native widget** (task card shown inline in chat), polishing it
to pixel-match ManageBac, plus a handful of scraper/delivery fixes.

---

## 1. ChatGPT native widget — overview

When a user calls `get_task_detail` or `find_task`, ChatGPT renders a **rich task
card widget** inline in the conversation. This uses the ChatGPT Apps SDK
(`openai/widgetAccessible`, `ui://` URIs, `toolOutput`).

### How the widget is delivered (current stable design)

```
get_task_detail / find_task
  → server builds task dict (grades, files, resources, description, theme …)
  → embeds it as toolOutput in the CallToolResult
  → returns _meta pointing to the SHARED static URI: ui://widget/task-detail-v7.html

ChatGPT:
  → calls list_resources() → gets the template URI registered
  → calls read_resource(uri) → gets the static template HTML (no task data baked in)
  → renders it; JS inside reads window.openai.toolOutput to get the task data
```

**Why static URI + toolOutput (not per-task baked HTML):**
Earlier versions baked task data into a per-hash URI. ChatGPT caches widget URIs
aggressively, so after a server restart (new hash → unknown URI) ChatGPT returned
"Error loading app / Failed to fetch template" permanently. The shared static URI
never changes; data travels via `toolOutput` which ChatGPT always delivers fresh.

The fallback `eff6a13` ensures any old per-task hash URI from before the migration
(cached in ChatGPT conversations) also returns the current template instead of 404.

### Widget files

| File | Purpose |
|---|---|
| `managebac_mcp/server.py` | Widget logic: `_make_task_widget()`, `list_resources()`, `read_resource()`, `_TASK_DETAIL_URI`, `_WIDGET_CSP`, `_THEME_COLORS` |
| `widget-preview/task-card.html` | Source of truth for widget HTML — the template served by `read_resource`. **Edit this file, not the inline string in server.py.** `server.py` reads it from disk at startup via `_TASK_CARD_PATH`. |
| `widget-preview/task-list.html` | **Reference-only HTML** for a `get_tasks` list view (ManageBac-matching layout). Not yet wired into the MCP server — built as a design reference for when that widget gets added. |
| `widget-preview/class-files.html` | **Reference-only HTML** for a `get_files` class-files view. Same status — design reference, not live. |
| `widget-preview/managebac-icons/` | Local mirrors of the exact ManageBac icon assets (see §3 below). |

### Content-Security-Policy

The widget CSP allows images/scripts from:
- `assets.managebac.com` (icons, teacher-embedded images)
- `es.managebac.com` (description images)
- `cdn.filestackcontent.com` (Dropbox/Filestack submission thumbnails)
- `www.dropbox.com` (submission links)

Both the `openai/widgetCSP` (object form) and the `<meta http-equiv>` header are
sent, because different ChatGPT builds read one or the other.

---

## 2. Widget feature set

The task card (`task-card.html` / `task-detail-v7.html`) shows:

- **Header** — task title, class name, coloured status badge (Pending / Submitted /
  Complete / Incomplete), due date.  Header background colour = student's ManageBac
  theme colour (see §4).
- **Description** — full HTML description including teacher-embedded images (those
  come from `es.managebac.com` and `assets.managebac.com` — both whitelisted in CSP).
- **Grades** — per-criterion scores (A/B/C/D), N/A rendered as ManageBac does.
  Empty Discussions box is hidden.
- **Resources** — teacher-posted files, matching ManageBac's exact layout:
  resource-card per post, teacher name + posted date, optional bold label, file
  cards with icon + size.  Icons are pulled from `assets.managebac.com` (same CDN
  as ManageBac itself).
- **Dropbox submissions** — "Your Dropbox Submissions" section with the student's
  submitted files and upload date.
- **Dark/light theme** — reads `window.openai.globals.theme`; flips on
  `openai:set_globals` event. Default is dark (matches ChatGPT).

### Known widget quirks

- **"Error loading app"** after server restart: fixed by `eff6a13` (stale per-task
  URIs now fall back to current template).
- **Layout flicker on load**: fixed by `543acd5` (deduplicated render calls —
  widget was rendering twice on init).
- **Text truncation**: raised caps in `6f9f52d` so long task descriptions no longer
  get cut off in the card.
- **outputSchema**: all tools had `outputSchema` added in `a5218f2` (to remove
  ChatGPT warning badges), then it was **removed** in `a9fc8a5` because ChatGPT
  kept logging "Output validation error". Do **not** re-add `outputSchema` to any
  tool.

---

## 3. ManageBac icon collection (`widget-preview/managebac-icons/`)

A small local mirror of ManageBac's CDN icons so they're available without a live
network hit during development.

| File | Used for |
|---|---|
| `resources.png` | Resources section header icon (orange/brown box) |
| `file-avatar.png` | Teacher post avatar (colored document icon next to teacher name) |
| `document_file.svg` | File row icon (blue-lined document) |
| `README.md` | Links to the original `assets.managebac.com` CDN URLs |

The **widget itself** loads icons directly from `assets.managebac.com` (not the
local copies) — the local copies are for offline reference/development only.

Avatar styling: **30px circle, 1px `#eaecf0` border, no fill** — matches
ManageBac's exact CSS. An earlier version used a gray square which was wrong.

---

## 4. Per-user theme colour

ManageBac lets students pick a theme (blue / orange / red / plum / teal) under
`/student/personalisation`. The widget header reflects this.

**How it works:**
1. `scraper.py :: fetch_task_detail()` reads the `<body class="theme-<name>">` on
   the ManageBac page it already fetched (free — no extra request).
2. `parse_theme(html)` extracts the theme name (regex `theme-(blue|orange|red|plum|teal)`).
3. `server.py :: get_task_detail` maps the name → hex colour via `_THEME_COLORS`
   dict and injects it into the `toolOutput` as `theme_color`.
4. The widget JS reads `TASK.theme_color` and applies it as the header background
   via CSS custom property `--accent`.

`_THEME_COLORS` in `server.py` (around line 526) holds all five mappings. Default
fallback is `#1D6DC2` (ManageBac blue).

---

## 5. Scraper additions since v1.8.0

| Function | What changed |
|---|---|
| `parse_theme(html)` | New. Extracts body class `theme-<name>`. |
| `fetch_task_detail()` | Calls `parse_theme` and adds `"theme"` key to result dict. Also calls `parse_resources()` for the Resources section. |
| `parse_resources(soup)` | New. Reads `div.resource-container` to extract teacher name, posted date, optional label, and file list (name, size, download URL) for the Resources section. |
| `fetch_grades()` | Now captures `B: N/A` pattern (and similar) — N/A criterion scores are included and rendered like ManageBac (hidden `/max` when score is N/A). |
| `submit_task_file()` | Added in an earlier version but referenced here — uploads a file to a Dropbox submission slot. |

The `submitted_files` in `get_task_detail` include the real signed CDN download
URL (not the preview-modal token that was 404ing before v1.7.0).

---

## 6. Fix history since v1.8.0

| Commits | What & why |
|---|---|
| `4644a3b` | Accept `task_url` / `link` as aliases for `url` in `get_task_detail`; return clean `{"error": …}` instead of raising `KeyError` when IDs can't be extracted. |
| `4a48be2` | Same fix, earlier pass: accept full URL and extract class_id/task_id automatically. |
| `79e7665` | Tell ChatGPT (via tool description) to extract IDs from the URL rather than passing the raw URL — improves model behaviour. |
| `0a14b30` + `a47ed1a` | N/A grade scraping: capture `B: N/A` pattern; display like ManageBac (score shown as N/A, `/max` hidden). |
| `36d2792` | Hide empty discussions box; skip N/A grades in grade summary. |
| `5fb8554` | Loading screen: clean spinner ("Loading task…") instead of geography example data. `fetch_task_detail` / `fetch_tasks` / `fetch_classes` now run concurrently via `asyncio.gather`. |
| `ad58959` | Fix card corner rendering in ChatGPT dark mode (leftover white background). |
| `959c14c` | Fix widget showing stale task when HTML is cached by ChatGPT (bump URI version). |
| `1aec5ec` | Fix JS syntax error (orphan closing brace) causing "Error loading app". |
| `a5218f2` | Add `outputSchema` to all 14 tools (removes ChatGPT warning badges). |
| `a9fc8a5` | **Remove `outputSchema` from all tools** (was causing "Output validation error"). Current state: no `outputSchema` anywhere. |
| `f8b662f` | Render teacher-embedded description images in the widget (CSP was blocking them). |
| `9579a31` | Fix widget CSP key so embedded images actually load in ChatGPT. |
| `10bb416` | Attach widget CSP to `resources/read` response so images load. |
| `9d93813` | Match widget header colour to student's ManageBac theme (per-user theme). |
| `844c079` | Default widget theme to blue (ManageBac's own default). |
| `c5f23c0` | Apply theme colour to all accent elements, not just header. |
| `bcc6e8b` | Fix widget showing wrong (last-loaded) task across tabs/users. |
| `f509e43` | Fix widget invisible: simplify outputSchema for `get_task_detail` + `find_task`. |
| `543acd5` | Dedupe widget renders (stop layout flicker). |
| `6f9f52d` | Raise widget text truncation caps so descriptions aren't cut off. |
| `be70dbd` | Show task Resources section; fix hidden Dropbox submissions. |
| `0c3ed70` | Resources section matches ManageBac (author, date, label, file cards). |
| `bcbe991` | Use exact ManageBac icons (`assets.managebac.com`) in Resources section. |
| `49872fe` | Fix resource avatar: 30px circle with 1px border (was gray square). |
| `cc1f0ae` | Dropbox matches ManageBac (PDF icon, header case, row layout). |
| `7eb9bb9` | Shrink Dropbox PDF icon to ManageBac proportion. |
| `34df4e1` | Wrap Dropbox file table in its own bordered box. |
| `fa2e4eb` | Add `task-list.html` + `class-files.html` reference widgets (not yet live in MCP). |
| `eff6a13` | Serve current task template for stale per-task widget URIs (fix permanent "Error loading app" in old conversations after server restart). |

---

## 7. Current state (verified 2026-06-13)

### Git / GitHub
```
v1.9.0-ui-checkpoint  — ChatGPT native UI with MCP metadata fix
HEAD (local + origin/multi-user)  — eff6a13  ~30 commits ahead of that tag
```
- Local `multi-user` and `origin/multi-user` are **in sync** — no unpushed or unpulled commits.
- **`main` branch on GitHub is far behind** — it's still at `cd18eb7 "Add HTTP transport
  for ChatGPT / remote clients"` (pre-multi-user work). All active development is on
  `multi-user`. Do not base PRs or deploys off `main`.

### Production server (100.77.121.118)
- **State:** running (`launchctl` state=running, pid active).
- **Version:** `eff6a13` — same as local HEAD. Server is fully up to date.
- **Traffic:** active — logs show steady 200 OK POST /mcp requests from Cloudflare IPs.
- **Enrolled users:** 5 (all `enabled=1, approved=1`): khatia.korshia, arina.abdolmalaki,
  nikoloz.chioreli, isabella.shanidze, levan.japaridze (all `@europeanschool.ge`).
- **Data dir:** `~/.managebac_mcp/` — `secret.key` present (44 bytes), `cache.db` 8.6MB,
  `users.db` 24KB, `admin.db` 28KB, `files/` dir for attachment cache.

There is no `v2.x` tag yet. Everything above is on the `multi-user` branch.

---

## 8. Open / candidate next tasks (updated)

Previously listed items still open; new ones from this work:

- **Wire `task-list.html` into MCP** — the HTML exists in `widget-preview/` and
  matches ManageBac's layout. Still needs a `get_tasks` path in `server.py` that
  returns a widget with a list of tasks (same toolOutput delivery pattern as the
  task card).
- **Wire `class-files.html` into MCP** — same situation as task-list above.
- **outputSchema saga** — adding it broke ChatGPT ("Output validation error");
  removing it brought back warning badges. Watch for future ChatGPT SDK changes
  that might make `outputSchema` work correctly again.
- **Widget CSP for non-ManageBac schools** — `es.managebac.com` is hardcoded in
  the CSP; multi-school support would need to parameterise this.
- **Per-user throttle**, **stale-while-revalidate**, **system LaunchDaemons**,
  **MYP grade-boundary table**, **chronological criterion series** — all still open
  from the original HANDOFF.md §12.

---

## 9. Quick reference additions

```bash
# Check widget is being served (should return HTML with <title>ManageBac)
curl -s "https://managebac.822538.xyz/resources/ui%3A%2F%2Fwidget%2Ftask-detail-v7.html" \
  | grep -o "<title>[^<]*"

# Deploy (same as before)
ssh server@100.77.121.118
cd /Users/server/managebac-mcp
git pull --ff-only origin multi-user
launchctl kickstart -k gui/502/com.managebac.mcp
curl -s localhost:8000/

# Tail logs
ssh server@100.77.121.118 'tail -50 /tmp/managebac-mcp.log'
```

---

*See `HANDOFF.md` for the base architecture, server setup, data storage, auth model,
deploy/rollback procedures, and older fix history (v1.1.0–v1.8.0).*
