import asyncio
import json
import sys
from pathlib import Path
import time
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from .scraper import (
    fetch_classes,
    fetch_timetable,
    fetch_tasks,
    fetch_task_detail,
    fetch_files,
    fetch_journal,
    fetch_units,
    fetch_file_readable,
    fetch_upcoming,
    fetch_grades,
    tag_search,
    find_task,
)
from . import cache
from .context import ManageBacError


SERVER_INSTRUCTIONS = (
    "You are connected to the student's own ManageBac account (their school's "
    "learning platform) through this server. The person you are helping is the "
    "account owner — answer about their classes, tasks, grades, deadlines, units, "
    "files, and journal.\n"
    "\n"
    "Always follow these rules without being asked:\n"
    "- Whenever you mention a specific task, class, file, or unit, include its `url` "
    "as a clickable link so the student can open it directly. Never refer to a task "
    "by name without also giving its link.\n"
    "- If a task's description has links (description.links — e.g. Google Docs, "
    "Slides, forms the teacher wants opened), share those links too.\n"
    "- When the student asks about several subjects at once, pass a list of class_ids "
    "in a single call rather than calling one class at a time.\n"
    "- Dates and times are already in the student's school timezone — use them as given.\n"
    "- get_task_detail and get_files expose a file `url`; if the student wants to read "
    "an attachment, pass that url to get_file_content.\n"
    "- Data is cached for speed (tasks ~10 min, classes/units longer). If the student asks "
    "to 'update', 'refresh', 'check again', or is waiting on a new grade/task, call refresh "
    "first and then re-fetch — that pulls live data from ManageBac.\n"
    "- Be economical with tool calls to keep the conversation fast: for cross-class questions "
    "use the consolidated tools (get_upcoming, get_grades, tag_search) instead of calling "
    "get_tasks for every class. Reuse what you already fetched in this conversation rather than "
    "re-calling the same tool. Only fetch a class's full task list when the student is focused "
    "on that one class."
)

server = Server("managebac", instructions=SERVER_INSTRUCTIONS)


# ---------------------------------------------------------------------------
# Widget registry
# ---------------------------------------------------------------------------
# Maps widget name -> (uri, html_content)
# mimetype must be text/html+skybridge for ChatGPT to render the iframe

WIDGET_MIME = "text/html+skybridge"  # official Python examples
WIDGET_MIME_ALT = "text/html;profile=mcp-app"  # troubleshooting guide

_TEST_WIDGET_URI = "ui://widget/test.html"
_TEST_WIDGET_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>UI Debug</title>
  <style>
    body { background: transparent; color: #0f172a; font-family: monospace; font-size: 12px; margin: 0; padding: 12px; }
    .row { margin-bottom: 8px; }
    .label { font-weight: bold; color: #64748b; }
    pre { background: #f1f5f9; padding: 8px; border-radius: 6px; white-space: pre-wrap; word-break: break-all; margin: 4px 0 0; }
    .msg { background: #e0f2fe; border-left: 3px solid #0284c7; padding: 6px 8px; margin: 4px 0; border-radius: 0 6px 6px 0; }
  </style>
</head>
<body>
  <div class="row"><span class="label">window.openai exists:</span> <span id="exists">?</span></div>
  <div class="row"><span class="label">toolOutput:</span><pre id="output">checking...</pre></div>
  <div class="row"><span class="label">toolInput:</span><pre id="input">checking...</pre></div>
  <div class="row"><span class="label">globals:</span><pre id="globals">checking...</pre></div>
  <div class="row"><span class="label">postMessages received:</span></div>
  <div id="msgs"></div>
  <script>
    document.getElementById('exists').textContent = (typeof window.openai !== 'undefined') ? 'YES' : 'NO';
    document.getElementById('output').textContent = JSON.stringify(window.openai?.toolOutput, null, 2);
    document.getElementById('input').textContent = JSON.stringify(window.openai?.toolInput, null, 2);
    document.getElementById('globals').textContent = JSON.stringify(window.openai?.globals, null, 2);

    window.addEventListener('message', ev => {
      const d = document.createElement('div');
      d.className = 'msg';
      d.textContent = JSON.stringify(ev.data);
      document.getElementById('msgs').appendChild(d);
    });

    window.addEventListener('openai:set_globals', ev => {
      document.getElementById('globals').textContent = JSON.stringify(ev.detail?.globals, null, 2);
    });
  </script>
</body>
</html>"""

_TASK_DETAIL_URI = "ui://widget/task-detail-v7.html"
_TASK_DETAIL_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Task</title>
  <style>
    /* Dark by default — matches ChatGPT's dark theme.
       Apply class="light" on <html> if light mode is detected. */
    :root {
      --surface: #2f2f2f;
      --surface2: #3a3a3a;
      --fg: #ececec;
      --fg2: #8e8ea0;
      --border: #454545;
      --accent: #10a37f;
      --accent-dim: rgba(16,163,127,.15);
      --red-dim: rgba(239,68,68,.15);
      --red: #f87171;
      --green: #34d399;
      --green-dim: rgba(52,211,153,.15);
    }
    html.light {
      --surface: #f7f7f8;
      --surface2: #efefef;
      --fg: #111827;
      --fg2: #6b7280;
      --border: #e5e7eb;
      --accent: #059669;
      --accent-dim: rgba(5,150,105,.1);
      --red-dim: rgba(239,68,68,.1);
      --red: #dc2626;
      --green: #059669;
      --green-dim: rgba(5,150,105,.1);
    }
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: transparent;
      color: var(--fg);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      font-size: 14px;
      line-height: 1.5;
    }
    #root { padding: 16px 18px 20px; }

    /* Title */
    .title {
      font-size: 1.1rem;
      font-weight: 700;
      line-height: 1.35;
      margin-bottom: 10px;
      color: var(--fg);
    }

    /* Status badge */
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 3px 10px;
      border-radius: 99px;
      font-size: 0.72rem;
      font-weight: 600;
      margin-bottom: 12px;
    }
    .badge-pending  { background: var(--red-dim);   color: var(--red);   }
    .badge-done     { background: var(--green-dim);  color: var(--green); }

    /* Due date */
    .due {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 0.8rem;
      color: var(--fg2);
      margin-bottom: 14px;
    }
    .due strong { color: var(--fg); }

    /* Section label */
    .section-label {
      font-size: 0.68rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--fg2);
      margin: 16px 0 6px;
    }

    /* Instructions */
    .instructions {
      font-size: 0.875rem;
      line-height: 1.65;
      color: var(--fg);
      white-space: pre-wrap;
    }

    /* Links */
    .link-list { display: flex; flex-direction: column; gap: 5px; margin-top: 2px; }
    .link-item {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 7px 10px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      text-decoration: none;
      color: var(--accent);
      font-size: 0.82rem;
      overflow: hidden;
    }
    .link-item span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

    /* File rows */
    .file-list { display: flex; flex-direction: column; gap: 5px; }
    .file-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      padding: 9px 12px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
    }
    .file-row.submitted {
      border-color: var(--accent);
      background: var(--accent-dim);
    }
    .file-info { min-width: 0; }
    .file-name { font-size: 0.83rem; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .file-size { font-size: 0.71rem; color: var(--fg2); margin-top: 1px; }
    .file-action {
      flex-shrink: 0;
      font-size: 0.78rem;
      font-weight: 600;
      color: var(--accent);
      background: none;
      border: none;
      cursor: pointer;
      padding: 0;
      text-decoration: none;
    }

    /* Open button */
    .divider { border: none; border-top: 1px solid var(--border); margin: 16px 0 14px; }
    .open-btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 8px 16px;
      background: var(--accent);
      color: #fff;
      border-radius: 8px;
      font-size: 0.83rem;
      font-weight: 600;
      text-decoration: none;
    }
    .open-btn:hover { opacity: .88; }

    .loading { color: var(--fg2); padding: 28px 0; text-align: center; font-size: 0.88rem; }
  </style>
</head>
<body>
  <div id="root"><p class="loading">Loading task…</p></div>
  <script>
    const esc = s => String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');

    // Theme: dark by default, only switch to light when explicitly detected
    function applyTheme(theme) {
      if (theme === 'light') document.documentElement.classList.add('light');
      else document.documentElement.classList.remove('light');
    }
    (function initTheme() {
      const t = window.openai?.globals?.theme;
      if (t) { applyTheme(t); return; }
      if (window.matchMedia('(prefers-color-scheme: light)').matches) applyTheme('light');
      // else stay dark (default)
    })();

    function extractTask(data) {
      if (!data || typeof data !== 'object') return null;
      if (Array.isArray(data)) return data[0] || null;
      if (Array.isArray(data.tasks)) return data.tasks[0] || null;
      if (data.url || data.description || data.title || data.submitted_files || data.resources) return data;
      return null;
    }

    function render(data) {
      const task = extractTask(data);
      if (!task) return; // keep "Loading…" — data shape unknown, might retry

      let h = '';

      // Title
      const title = task.title || task.name;
      if (title) h += '<div class="title">' + esc(title) + '</div>';

      // Status badge
      const status = task.status || task.task_status;
      if (status) {
        const s = status.toLowerCase();
        const done = s.includes('submit') || s.includes('complet');
        h += '<span class="badge ' + (done ? 'badge-done' : 'badge-pending') + '">' +
          (done ? '✓' : '○') + ' ' + esc(status) + '</span>';
      }

      // Due date
      const due = task.due_date || task.due || task.due_day_time;
      if (due) h += '<div class="due">📅 Due <strong>' + esc(due) + '</strong></div>';

      // Instructions
      const desc = task.description;
      if (desc) {
        const txt = typeof desc === 'string' ? desc : (desc.text || '');
        const links = Array.isArray(desc.links) ? desc.links : [];
        if (txt) {
          h += '<div class="section-label">Instructions</div>';
          h += '<div class="instructions">' + esc(txt) + '</div>';
        }
        if (links.length) {
          h += '<div class="section-label">Links</div><div class="link-list">';
          h += links.map(l => {
            const url = typeof l === 'string' ? l : (l.url || '');
            const label = (typeof l === 'object' && l.text) ? l.text : url;
            return '<a class="link-item" href="' + esc(url) + '" target="_blank" rel="noopener">' +
              '🔗 <span>' + esc(label) + '</span></a>';
          }).join('');
          h += '</div>';
        }
      }

      // Attachments / resources
      const resources = [
        ...(task.resources || []).flatMap(r => Array.isArray(r.files) ? r.files : (r.name ? [r] : [])),
        ...(task.description?.embedded_files || []),
      ].filter(f => f && f.name);
      if (resources.length) {
        h += '<div class="section-label">Attachments</div><div class="file-list">';
        h += resources.map(f =>
          '<div class="file-row"><div class="file-info"><div class="file-name">' + esc(f.name) + '</div>' +
          (f.size ? '<div class="file-size">' + esc(f.size) + '</div>' : '') + '</div>' +
          (f.url ? '<a class="file-action" href="' + esc(f.url) + '" target="_blank">Download</a>' : '') +
          '</div>'
        ).join('');
        h += '</div>';
      }

      // Submitted files
      const submitted = task.submitted_files || [];
      if (submitted.length) {
        h += '<div class="section-label">Your Submissions</div><div class="file-list">';
        h += submitted.map(f =>
          '<div class="file-row submitted"><div class="file-info"><div class="file-name">' + esc(f.name) + '</div>' +
          (f.size ? '<div class="file-size">' + esc(f.size) + '</div>' : '') + '</div>' +
          (f.url ? '<button class="file-action view-file" data-url="' + esc(f.url) + '">View →</button>' : '') +
          '</div>'
        ).join('');
        h += '</div>';
      }

      // Open button
      if (task.url) {
        h += '<div class="divider"></div>';
        h += '<a class="open-btn" href="' + esc(task.url) + '" target="_blank" rel="noopener">Open in ManageBac ↗</a>';
      }

      document.getElementById('root').innerHTML = h;

      document.querySelectorAll('.view-file').forEach(btn => {
        btn.addEventListener('click', () => {
          window.parent.postMessage({
            jsonrpc: '2.0', id: Date.now(),
            method: 'tools/call',
            params: { name: 'get_file_content', arguments: { url: btn.dataset.url } }
          }, '*');
        });
      });
    }

    // ── Data loading ───────────────────────────────────────────────────────────
    // ChatGPT sets window.openai.toolOutput asynchronously after the iframe
    // loads. Poll until it appears rather than checking once at load time.

    let rendered = false;
    function tryRender(data) {
      if (rendered || !data) return;
      const task = extractTask(data);
      if (!task) return; // not our data shape, keep polling
      rendered = true;
      render(data);
    }

    // Immediate check (catches synchronous set on page refresh / history load)
    tryRender(window.openai?.toolOutput);

    // Poll every 80ms for up to 5s
    if (!rendered) {
      let n = 0;
      const t = setInterval(() => {
        n++;
        if (window.openai?.toolOutput) { clearInterval(t); tryRender(window.openai.toolOutput); }
        else if (n >= 63) { clearInterval(t); } // ~5s
      }, 80);
    }

    // postMessage delivery (backup channel)
    window.addEventListener('message', ev => {
      const m = ev.data;
      if (m?.method === 'ui/notifications/tool-result') tryRender(m.params?.structuredContent);
    });
    window.addEventListener('openai:tool-result', ev => {
      tryRender(ev.detail?.structuredContent ?? ev.detail);
    });
    window.addEventListener('openai:set_globals', ev => {
      applyTheme(ev.detail?.globals?.theme);
    });
  </script>
</body>
</html>"""

_WIDGETS = {
    _TEST_WIDGET_URI: {"html": _TEST_WIDGET_HTML, "title": "Test Widget"},
    _TASK_DETAIL_URI: {"html": _TASK_DETAIL_HTML, "title": "Task Detail"},
}

def _widget_meta(uri: str, invoking: str, invoked: str) -> dict:
    return {
        "openai/outputTemplate": uri,
        "ui": {"resourceUri": uri},  # alternate key some clients check
        "openai/toolInvocation/invoking": invoking,
        "openai/toolInvocation/invoked": invoked,
        "openai/widgetAccessible": True,
    }

_TEST_META  = _widget_meta(_TEST_WIDGET_URI,  "Loading test widget...", "Test widget loaded")
_TASK_META  = _widget_meta(_TASK_DETAIL_URI,  "Loading task...",        "Task loaded")


@server.list_resources()
async def list_resources() -> list[types.Resource]:
    return [
        types.Resource(uri=uri, name=info["title"], title=info["title"], mimeType=WIDGET_MIME)
        for uri, info in _WIDGETS.items()
    ]


@server.list_resource_templates()
async def list_resource_templates() -> list[types.ResourceTemplate]:
    return [
        types.ResourceTemplate(uri_template=uri, name=info["title"], title=info["title"], mimeType=WIDGET_MIME)
        for uri, info in _WIDGETS.items()
    ]


@server.read_resource()
async def read_resource(uri) -> list:
    from mcp.server.lowlevel.helper_types import ReadResourceContents
    uri_str = str(uri)
    info = _WIDGETS.get(uri_str)
    if info is None:
        raise ValueError(f"Unknown resource: {uri_str}")
    # Return both mimetypes as separate content items so client finds whichever it expects
    return [
        ReadResourceContents(content=info["html"], mime_type=WIDGET_MIME),
        ReadResourceContents(content=info["html"], mime_type=WIDGET_MIME_ALT),
    ]


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_classes",
            description=(
                "Returns all classes the student is enrolled in. "
                "Each class has: id (required by every other tool), name, url, level_tags, "
                "and has_journal (true if the class has a journal/portfolio tab). "
                "Call this first to get class IDs."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="get_timetable",
            description=(
                "Returns the student's full weekly timetable plus the current date/time. "
                "The result has two keys: 'current' (the live weekday, date, time, and timezone — "
                "use this to know what day 'today'/'tomorrow' is, never assume) and 'timetable' "
                "(the weekly slots). Each slot has: period, day, time_start, time_end, class_name, "
                "class_id, teacher, room, and task_count (pending tasks for that class)."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="refresh",
            description=(
                "Force-refresh the student's data. Clears their cached ManageBac data so the very "
                "next tool call fetches LIVE from ManageBac instead of the cache. "
                "Call this whenever the student asks to 'update', 'refresh', 'check again', 'is it "
                "updated', or otherwise implies the cached data might be stale (e.g. waiting on a "
                "grade or a just-posted task). After calling refresh, call the relevant data tool "
                "again (e.g. get_upcoming) to get the fresh result."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="get_upcoming",
            description=(
                "THE authoritative list of upcoming (or overdue) tasks across ALL classes at once, "
                "grouped by day — use this for any 'what's due today / this week / what do I still "
                "have to submit' question instead of crawling get_tasks per class. "
                "Returns {current, view, tasks}. 'current' is the live date/time. Each task has: "
                "title, url, class_name, class_id, due (e.g. 'Jun 2, 2:40 PM'), due_group "
                "(e.g. 'Today - Tuesday, Jun 2'), type, status, and needs_submission. "
                "CRITICAL: needs_submission=true means the student has NOT submitted it yet and there "
                "is a Submit Coursework box — treat those as still-to-do. A task only counts as done "
                "if its status is Submitted/Complete and needs_submission is false. Never tell the "
                "student they're free unless you've checked needs_submission here. "
                "view defaults to 'upcoming'; pass 'overdue' for past-due unfinished work."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "view": {
                        "type": "string",
                        "enum": ["upcoming", "overdue", "past"],
                        "description": "Which list to return (default 'upcoming')",
                    }
                },
                "required": [],
            },
        ),
        types.Tool(
            name="get_tasks",
            description=(
                "Returns the recent tasks for a class (≈12 newest; older ones are summarized "
                "with a note — reach them via tag_search/find_task/get_grades). "
                "Use this to drill into ONE class. For cross-class questions do NOT batch every "
                "class here — that floods the context. Instead use: get_upcoming (what's due / to "
                "submit), get_grades (grades across classes), tag_search (find tasks by type/tag). "
                "BATCH SUPPORTED but use sparingly: class_id can be a single ID or a small list — "
                "all fetched concurrently. Batch result is a dict keyed by class_id. "
                "Each task has: id, title, url, date, due_day_time, type (Summative/Formative), "
                "tags, status (Pending/Submitted/Complete/Incomplete/N/A), has_submission_box, "
                "grades (e.g. {A: {score: 7, max: 8}}). "
                "This is a lightweight index — for the teacher's written comment/feedback, the "
                "full description, links, and attached files, call get_task_detail on a specific task."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "class_id": {
                        "description": "A single class ID or a list of class IDs for batch fetching",
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ],
                    }
                },
                "required": ["class_id"],
            },
        ),
        types.Tool(
            name="get_task_detail",
            description=(
                "Returns the full detail for one or more tasks. "
                "Single task: pass class_id + task_id, OR pass the task url (class_id and task_id will be extracted automatically). "
                "BATCH SUPPORTED: pass a 'tasks' list of {class_id, task_id} pairs — all fetched concurrently. "
                "Returns per task: title, url, "
                "description.text (full instructions as Markdown), "
                "description.links (external URLs embedded by the teacher), "
                "resources (teacher-posted files), "
                "submitted_files (the student's own uploads — each has a `url` you can pass to "
                "get_file_content to read the PDF/doc they turned in), "
                "task_history, discussions."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "class_id": {
                        "type": "string",
                        "description": "Class ID — from get_upcoming, get_tasks, etc.",
                    },
                    "task_id": {
                        "type": "string",
                        "description": "Task ID — from get_upcoming, get_tasks, etc.",
                    },
                    "url": {
                        "type": "string",
                        "description": "Full ManageBac task URL — class_id and task_id are extracted automatically. Use this if you have the URL but not the IDs.",
                    },
                    "tasks": {
                        "type": "array",
                        "description": "Batch mode: list of {class_id, task_id} objects",
                        "items": {
                            "type": "object",
                            "properties": {
                                "class_id": {"type": "string"},
                                "task_id": {"type": "string"},
                            },
                            "required": ["class_id", "task_id"],
                        },
                    },
                },
            },
            _meta=_TASK_META,
        ),
        types.Tool(
            name="get_files",
            description=(
                "Returns all resource files in a class's Files section "
                "(class-wide materials uploaded by the teacher, not attached to a specific task). "
                "BATCH SUPPORTED: class_id can be a single ID or a list. "
                "Each file has: name, size, url (pre-signed download link), uploaded_by, uploaded_at. "
                "Pass url to get_file_content to read the actual file contents."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "class_id": {
                        "description": "A single class ID or a list for batch fetching",
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ],
                    },
                },
                "required": ["class_id"],
            },
        ),
        types.Tool(
            name="get_journal",
            description=(
                "Returns journal/portfolio entries for a class. "
                "Only classes where has_journal=true (from get_classes) have entries — returns empty list otherwise. "
                "BATCH SUPPORTED: class_id can be a single ID or a list. "
                "Each entry has: id, date, time, body (Markdown), learning_outcomes, is_starred, is_read_only, links, files."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "class_id": {
                        "description": "A single class ID or a list for batch fetching",
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ],
                    },
                },
                "required": ["class_id"],
            },
        ),
        types.Tool(
            name="get_file_content",
            description=(
                "Reads an attachment (PDF, Word .docx, text, or image) using the student's "
                "authenticated session and returns its CONTENT directly — extracted text for "
                "documents, or the image itself. Use the url from description.embedded_files[].url, "
                "resources[].files[].url, or a class file's url. "
                "Returns lightweight text (not a raw file blob), so it won't bloat the conversation. "
                "Long documents are truncated. Cached on disk for 1 hour."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Full attachment URL from embedded_files[].url or resources[].files[].url",
                    }
                },
                "required": ["url"],
            },
        ),
        types.Tool(
            name="get_units",
            description=(
                "Returns all curriculum units for a class. "
                "Each unit has: id, title, status (current/completed/upcoming), start, duration, url, "
                "and framework fields: statement_of_inquiry, key_concepts (with definitions), "
                "related_concepts, global_context, conceptual_understanding, "
                "inquiry_questions (each typed as Factual/Conceptual/Debatable), atl_skills. "
                "BATCH SUPPORTED: class_id can be a single ID or a list. "
                "Multiple tasks share the same unit — call once per class and reuse. "
                "Match tasks to units by title prefix or date range."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "class_id": {
                        "description": "A single class ID or a list for batch fetching",
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ],
                    }
                },
                "required": ["class_id"],
            },
        ),
        types.Tool(
            name="get_grades",
            description=(
                "Consolidated grades across ALL classes (or one). Use for 'how am I doing', "
                "'what are my grades', 'my grades in Biology', and for predicting grades. "
                "Returns {scope, classes}; each class has a 'criteria' summary (per criterion: "
                "latest score, best, average, out_of, count) — this is everything you need to "
                "assess or predict a grade. "
                "Omit class_id for ALL classes: returns the compact criteria summary per class "
                "(no per-task detail, to keep the response small and reliable). "
                "Pass a class_id to scope to ONE class: that also includes 'graded_tasks' (each "
                "with title, url, type, date, grades, teacher_comment). "
                "If any class failed to load, the result has a 'fetch_errors' list — those classes "
                "are missing, not ungraded; retry or call refresh. "
                "Note: scores are MYP criterion levels (e.g. 7 out of 8), not percentages."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "class_id": {
                        "type": "string",
                        "description": "Optional — one class. Omit for all classes.",
                    }
                },
                "required": [],
            },
        ),
        types.Tool(
            name="tag_search",
            description=(
                "Find tasks by tag or type across ALL classes at once, or within one class. "
                "Use for requests like 'show me all summative tasks', 'all Criterion A tasks', "
                "'all homework in Biology'. The 'tag' matches a task's type (Summative/Formative) "
                "or any of its tags (e.g. 'Criterion A', 'Homework', 'Test', 'Classwork'). "
                "Omit class_id to search every class; pass a class_id to scope to one. "
                "Returns {query, scope, count, tasks} where each task has title, url, class_name, "
                "type, tags, status, date, due_day_time, grades."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "tag": {
                        "type": "string",
                        "description": "Tag or type to match, e.g. 'Summative', 'Criterion A', 'Homework'",
                    },
                    "class_id": {
                        "type": "string",
                        "description": "Optional — limit to one class. Omit to search all classes.",
                    },
                },
                "required": ["tag"],
            },
        ),
        types.Tool(
            name="find_task",
            description=(
                "Finds a task by URL or by fuzzy title search across all classes. "
                "URL mode: pass a full task URL — class_id and task_id are extracted automatically. "
                "Title mode: pass a partial title — searches all classes and returns the best match. "
                "Returns the same structure as get_task_detail."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A task URL or a partial task title to search for",
                    }
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="test_ui",
            description=(
                "TEST TOOL: Simple UI test to verify the iframe infrastructure is working. "
                "Call this to see if ChatGPT can render embedded UI components."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
            _meta=_TEST_META,
        ),
    ]


def _widget_sc(task: dict) -> dict:
    """Build a small structuredContent dict for the task-detail widget.

    ChatGPT silently drops toolOutput when structuredContent is too large —
    keep this under ~1 KB so the iframe always receives data.
    Full task JSON is still in TextContent for ChatGPT's own reasoning.
    """
    desc = task.get("description") or {}
    if isinstance(desc, str):
        desc = {"text": desc, "links": []}

    def slim(f):
        return {k: f[k] for k in ("name", "size", "url") if f.get(k)}

    resources = []
    for r in (task.get("resources") or []):
        if not isinstance(r, dict):
            continue
        for f in (r.get("files") or []):
            resources.append(slim(f))
    for f in (desc.get("embedded_files") or []):
        resources.append(slim(f))

    submitted = [slim(f) for f in (task.get("submitted_files") or []) if isinstance(f, dict)]

    sc: dict = {}
    if task.get("url"):
        sc["url"] = task["url"]
    if task.get("title"):
        sc["title"] = task["title"]
    if task.get("status"):
        sc["status"] = task["status"]
    if task.get("due_date") or task.get("due") or task.get("due_day_time"):
        sc["due_date"] = task.get("due_date") or task.get("due") or task.get("due_day_time")
    desc_text = (desc.get("text") or "")[:800]
    desc_links = (desc.get("links") or [])[:6]
    if desc_text or desc_links:
        sc["description"] = {"text": desc_text, "links": desc_links}
    if resources:
        sc["resources"] = resources[:8]
    if submitted:
        sc["submitted_files"] = submitted[:8]
    return sc


def _is_batch(val) -> bool:
    return isinstance(val, list)


async def _batch(fn, ids: list[str]) -> dict:
    """Run fn(id) for each id concurrently and return {id: result}."""
    results = await asyncio.gather(*[fn(i) for i in ids])
    return dict(zip(ids, results))


_TASKS_PER_CLASS_CAP = 12


def _slim_tasks(result):
    """Shrink get_tasks output so it can't blow up the context window.

    get_tasks was the biggest consumer (~58K tokens in one batched call). Three
    things bloat it: the full teacher_comment essays, empty/default fields
    repeated on every task, and the entire YEAR of tasks per class (×18 classes).
    So we (1) drop teacher_comment, (2) omit empty fields, (3) keep only the
    most-recent N tasks per class (they're newest-first) with a note when older
    ones are hidden.

    This only trims the get_tasks TOOL output — the full, uncapped task lists
    stay in the cache, so find_task, tag_search and get_grades still see
    everything. For a hidden/older task, use those or get_task_detail.
    Handles both a single list and a batch dict {class_id: [tasks]}."""
    def strip(t: dict) -> dict:
        out = {}
        for k, v in t.items():
            if k == "teacher_comment":
                continue
            if v is None or v is False or v == "" or v == [] or v == {}:
                continue
            out[k] = v
        return out

    def cap(tasks: list) -> list:
        slim = [strip(t) for t in tasks[:_TASKS_PER_CLASS_CAP]]
        hidden = len(tasks) - _TASKS_PER_CLASS_CAP
        if hidden > 0:
            slim.append({"_note": f"{hidden} older task(s) hidden to save space — "
                                  f"use tag_search, find_task or get_grades to reach them."})
        return slim

    if isinstance(result, dict):
        return {cid: cap(tasks) for cid, tasks in result.items()}
    if isinstance(result, list):
        return cap(result)
    return result


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    t0 = time.monotonic()
    result: object

    # Error buffer: any failure inside the dispatch is turned into a structured
    # {"error": ...} the AI can read aloud to the student, AND logged with its
    # reason so the admin can see WHY a call failed instead of a silent empty.
    try:
        if name == "get_classes":
            result = await fetch_classes()

        elif name == "get_timetable":
            result = await fetch_timetable()

        elif name == "refresh":
            cache.clear_user()
            result = {"status": "refreshed",
                      "message": "Cleared cached data. Re-call the data tool now to get live results from ManageBac."}

        elif name == "get_upcoming":
            result = await fetch_upcoming(arguments.get("view", "upcoming"))

        elif name == "get_tasks":
            cid = arguments["class_id"]
            if _is_batch(cid):
                result = await _batch(fetch_tasks, cid)
            else:
                result = await fetch_tasks(cid)
            result = _slim_tasks(result)   # drop teacher_comment to protect context

        elif name == "get_task_detail":
            import re as _re
            tasks_arg = arguments.get("tasks")
            if tasks_arg:
                fetched = await asyncio.gather(*[
                    fetch_task_detail(t["class_id"], t["task_id"]) for t in tasks_arg
                ])
                task = list(fetched)[0] if len(fetched) == 1 else list(fetched)
            else:
                cid = arguments.get("class_id")
                tid = arguments.get("task_id")
                # Fallback: extract IDs from a task URL if class_id/task_id not provided directly
                if not cid or not tid:
                    url_arg = arguments.get("url", "")
                    m = _re.search(r"/classes/(\d+)/core_tasks/(\d+)", url_arg)
                    if m:
                        cid, tid = m.group(1), m.group(2)
                if not cid or not tid:
                    result = {"error": "class_id and task_id are required (or pass url)", "tool": name}
                    raise KeyError("class_id and task_id missing — provide them or pass url")
                task = await fetch_task_detail(cid, tid)
            full = task if isinstance(task, dict) else {"tasks": task}
            # slim structuredContent so ChatGPT populates window.openai.toolOutput
            sc = _widget_sc(task) if isinstance(task, dict) else _widget_sc((task or [{}])[0])
            duration_ms = int((time.monotonic() - t0) * 1000)
            cache.log_request(name, arguments, full, source="mcp", duration_ms=duration_ms)
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(full, ensure_ascii=False, separators=(",", ":")))],
                structuredContent=sc,
                _meta=_TASK_META,
            )

        elif name == "get_units":
            cid = arguments["class_id"]
            if _is_batch(cid):
                result = await _batch(fetch_units, cid)
            else:
                result = await fetch_units(cid)

        elif name == "get_files":
            cid = arguments["class_id"]
            if _is_batch(cid):
                result = await _batch(fetch_files, cid)
            else:
                result = await fetch_files(cid)

        elif name == "get_journal":
            cid = arguments["class_id"]
            if _is_batch(cid):
                result = await _batch(fetch_journal, cid)
            else:
                result = await fetch_journal(cid)

        elif name == "get_file_content":
            f = await fetch_file_readable(arguments["url"])
            duration_ms = int((time.monotonic() - t0) * 1000)
            if f["kind"] == "image":
                cache.log_request(name, arguments, {"kind": "image", "content_type": f.get("content_type")},
                                  source="mcp", duration_ms=duration_ms)
                return [types.ImageContent(type="image", data=f["data_b64"], mimeType=f["content_type"])]
            elif f["kind"] == "text":
                cache.log_request(name, arguments, {"kind": "text", "truncated": f.get("truncated")},
                                  source="mcp", duration_ms=duration_ms)
                return [types.TextContent(type="text", text=f["text"])]
            else:
                result = {"error": f["error"], "tool": name}

        elif name == "get_grades":
            result = await fetch_grades(arguments.get("class_id", ""))

        elif name == "tag_search":
            result = await tag_search(arguments["tag"], arguments.get("class_id", ""))

        elif name == "find_task":
            task = await find_task(arguments["query"])
            if task is None:
                result = {"error": "Task not found", "tool": name}
            else:
                sc = _widget_sc(task)
                duration_ms = int((time.monotonic() - t0) * 1000)
                cache.log_request(name, arguments, task, source="mcp", duration_ms=duration_ms)
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=json.dumps(task, ensure_ascii=False, separators=(",", ":")))],
                    structuredContent=sc,
                    _meta=_TASK_META,
                )

        elif name == "test_ui":
            sc = {"message": "UI infrastructure test", "status": "ok", "timestamp": time.time()}
            duration_ms = int((time.monotonic() - t0) * 1000)
            cache.log_request(name, arguments, sc, source="mcp", duration_ms=duration_ms)
            return types.CallToolResult(
                content=[types.TextContent(type="text", text="Test widget rendered.")],
                structuredContent=sc,
                _meta=_TEST_META,
            )

        else:
            result = {"error": f"Unknown tool: {name}", "tool": name}

    except ManageBacError as e:
        # Expected, explainable failures (login/session/redirect) — surface the reason.
        result = {"error": e.reason, "tool": name}
        print(f"[tool error] {name} {arguments}: {e.reason}", flush=True)
    except Exception as e:
        # Anything unexpected (parse crash, network, etc.) — surface type + message.
        result = {"error": f"{type(e).__name__}: {e}", "tool": name}
        import traceback
        print(f"[tool error] {name} {arguments}: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()

    duration_ms = int((time.monotonic() - t0) * 1000)
    cache.log_request(name, arguments, result, source="mcp", duration_ms=duration_ms)

    # Compact separators (no indent / no spaces) — pretty-printing wasted ~35%
    # of the payload, and oversized payloads get truncated by the connector.
    # Keep _meta in the JSON (ChatGPT reads it from the response body, not TextContent._meta)
    return [types.TextContent(
        type="text",
        text=json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    )]


async def main():
    from mcp.server.models import InitializationOptions
    from mcp.server import NotificationOptions
    # stdio is single-user — bind the local account from ~/.managebac_mcp/.env
    from . import config, users
    from .context import set_current_user
    if config.EMAIL and config.PASSWORD:
        set_current_user(users.ensure_local_user(config.BASE_URL, config.EMAIL, config.PASSWORD))
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="managebac",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
