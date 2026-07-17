import asyncio
import hashlib
import json
import os
import sys
from collections import OrderedDict
from html.parser import HTMLParser
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
    fetch_upcoming,
    fetch_grades,
    tag_search,
    find_task,
)
from . import cache
from .context import ManageBacError, require_user


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
    "- get_task_detail and get_files expose attachment/file URLs. If the student wants ChatGPT "
    "to inspect attachments, use the widget attachment-selection flow rather than an MCP file-reading tool.\n"
    "- Use `get_*` tools when you need data for reasoning or text answers; they do not render widgets. "
    "Use `show_*` tools only when the student asks to see a visual card/list/table/widget.\n"
    "- After calling a `show_*` tool, do not repeat the widget's rows/details in prose. Give at most "
    "a one-sentence orientation or summary, because the widget is already the visual answer.\n"
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

_TASK_DETAIL_URI = "ui://widget/task-detail-v9.html"
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
          window.open(btn.dataset.url, '_blank', 'noopener');
        });
      });
    }

    // ── Data loading ────────────────────────────────────────────────────────────
    // _D is embedded by the server at widget-creation time — no toolOutput needed.
    // Fallbacks catch the page-refresh case and any postMessage delivery.
    const _D = /*D*/null;

    function tryRender(data) {
      if (!data) return;
      const task = extractTask(data);
      if (task) render(data);
    }

    // Embedded data — always available, renders immediately
    tryRender(_D);

    // Fallbacks for page-refresh / postMessage delivery
    if (window.openai?.toolOutput) tryRender(window.openai.toolOutput);
    window.addEventListener('message', ev => {
      const m = ev.data;
      if (!m || typeof m !== 'object') return;
      const candidates = [m, m.params, m.result, m.params?.structuredContent, m.result?.structuredContent];
      for (const c of candidates) { if (c && extractTask(c)) { tryRender(c); break; } }
    });
    window.addEventListener('openai:set_globals', ev => applyTheme(ev.detail?.globals?.theme));
  </script>
</body>
</html>"""

# New polished task card — loaded from disk so it's easy to iterate on.
_TASK_CARD_PATH = Path(__file__).parent.parent / "widget-preview" / "task-card.html"
_TASK_CARD_HTML: str = _TASK_CARD_PATH.read_text(encoding="utf-8")

# Class files widget — loaded from disk.
_CLASS_FILES_URI = "ui://widget/class-files-v4.html"
_CLASS_FILES_PATH = Path(__file__).parent.parent / "widget-preview" / "class-files.html"
_CLASS_FILES_HTML: str = _CLASS_FILES_PATH.read_text(encoding="utf-8")

# Grades widget — per-class criterion bars + estimated MYP level.
_GRADES_URI = "ui://widget/grades-v4.html"
_GRADES_PATH = Path(__file__).parent.parent / "widget-preview" / "grades-card.html"
_GRADES_HTML: str = _GRADES_PATH.read_text(encoding="utf-8")

# Timetable widget — weekly grid of classes.
_TIMETABLE_URI = "ui://widget/timetable-v4.html"
_TIMETABLE_PATH = Path(__file__).parent.parent / "widget-preview" / "timetable-card.html"
_TIMETABLE_HTML: str = _TIMETABLE_PATH.read_text(encoding="utf-8")

# Task list widget (get_upcoming) — grouped Upcoming/Completed rows
_TASK_LIST_URI = "ui://widget/task-list-v2.html"
_TASK_LIST_PATH = Path(__file__).parent.parent / "widget-preview" / "task-list.html"
_TASK_LIST_HTML: str = _TASK_LIST_PATH.read_text(encoding="utf-8")

# Class list widget (get_classes) — selectable class rows
_CLASS_LIST_URI = "ui://widget/class-list-v2.html"
_CLASS_LIST_PATH = Path(__file__).parent.parent / "widget-preview" / "class-list.html"
_CLASS_LIST_HTML: str = _CLASS_LIST_PATH.read_text(encoding="utf-8")

# Static widgets (test widget + task card stub registered so ChatGPT
# sees a widget for get_task_detail in list_resources).
_STATIC_WIDGETS = {
    _TEST_WIDGET_URI: {"html": _TEST_WIDGET_HTML, "title": "Test Widget"},
    _TASK_DETAIL_URI: {"html": _TASK_CARD_HTML, "title": "Task Detail"},
    _CLASS_FILES_URI: {"html": _CLASS_FILES_HTML, "title": "Class Files"},
    _GRADES_URI: {"html": _GRADES_HTML, "title": "Grades"},
    _TIMETABLE_URI: {"html": _TIMETABLE_HTML, "title": "Timetable"},
    _TASK_LIST_URI: {"html": _TASK_LIST_HTML, "title": "Tasks"},
    _CLASS_LIST_URI: {"html": _CLASS_LIST_HTML, "title": "Classes"},
}

# Per-task dynamic widgets: hash → {html, title}  (LRU capped at 60)
# Keyed by the short SHA1 hash; served at /ui/task/{hash} over HTTPS.
_TASK_WIDGETS: OrderedDict = OrderedDict()

# Public base URL — set by http_server.py at startup so we can build widget URLs.
# Default to the deployed HTTPS origin so import-time tool metadata never points
# ChatGPT at localhost.
_SERVER_PUBLIC_URL: str = "https://managebac.822538.xyz"


def set_server_public_url(url: str) -> None:
    """Called by http_server.build_app() once the public URL is known."""
    global _SERVER_PUBLIC_URL
    _SERVER_PUBLIC_URL = url.rstrip("/")

def _md_to_html(md: str) -> str:
    """Convert the simple Markdown produced by scraper._html_to_markdown → HTML for the card."""
    import re as _re
    if not md:
        return ""
    lines = md.split("\n")
    html_parts = []
    in_ul = False
    in_ol = False
    buffer = []

    def flush_para():
        nonlocal buffer
        text = " ".join(buffer).strip()
        buffer = []
        if text:
            html_parts.append(f"<p>{text}</p>")

    def flush_list():
        nonlocal in_ul, in_ol
        if in_ul:
            html_parts.append("</ul>")
            in_ul = False
        if in_ol:
            html_parts.append("</ol>")
            in_ol = False

    def inline(text: str) -> str:
        # Links [text](url)
        text = _re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank">\1</a>', text)
        # Bold **text** or __text__ (underline treated as bold-underline)
        text = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        text = _re.sub(r'__(.+?)__', r'<u>\1</u>', text)
        # Italic *text*
        text = _re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
        return text

    for line in lines:
        # Heading
        hm = _re.match(r'^(#{1,6})\s+(.*)', line)
        if hm:
            flush_para(); flush_list()
            level = min(len(hm.group(1)) + 2, 6)  # h1→h3, h6→h6 (keep readable size)
            html_parts.append(f"<h{level}>{inline(hm.group(2).strip())}</h{level}>")
            continue

        # Unordered list
        if _re.match(r'^[-*]\s+', line):
            flush_para()
            if not in_ul:
                flush_list()
                html_parts.append("<ul>")
                in_ul = True
            item = _re.sub(r'^[-*]\s+', '', line)
            html_parts.append(f"<li>{inline(item)}</li>")
            continue

        # Ordered list
        olm = _re.match(r'^(\d+)\.\s+(.*)', line)
        if olm:
            flush_para()
            if not in_ol:
                flush_list()
                html_parts.append("<ol>")
                in_ol = True
            html_parts.append(f"<li>{inline(olm.group(2))}</li>")
            continue

        # Blank line — flush paragraph + close lists
        if not line.strip():
            flush_para()
            flush_list()
            continue

        flush_list()
        buffer.append(inline(line))

    flush_para()
    flush_list()
    return "\n".join(html_parts)


class _HtmlTruncator(HTMLParser):
    """Streams HTML and stops after `limit` visible characters, closing any tags still
    open at the cutoff — so truncating never produces broken/unbalanced markup (the
    naive `text[:limit]` approach can slice mid-tag or mid-entity, which corrupts the
    innerHTML the widget injects it into). Limited to the small tag vocabulary
    `_md_to_html` actually produces; not a general HTML sanitizer."""

    _VOID = {"br", "img", "hr"}

    def __init__(self, limit: int):
        super().__init__(convert_charrefs=False)
        self.limit = limit
        self.out: list[str] = []
        self.count = 0
        self.stack: list[str] = []
        self.done = False

    def _attrs_str(self, attrs) -> str:
        return "".join(f' {k}="{v}"' for k, v in attrs if v is not None)

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        self.out.append(f"<{tag}{self._attrs_str(attrs)}>")
        if tag not in self._VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        if self.done:
            return
        self.out.append(f"<{tag}{self._attrs_str(attrs)}/>")

    def handle_endtag(self, tag):
        if self.done:
            return
        self.out.append(f"</{tag}>")
        if tag in self.stack:
            self.stack.remove(tag)

    def handle_data(self, data):
        if self.done:
            return
        remaining = self.limit - self.count
        if len(data) <= remaining:
            self.out.append(data)
            self.count += len(data)
        else:
            self.out.append(data[:remaining] + "…")
            self.count = self.limit
            self.done = True

    def handle_entityref(self, name):
        if self.done:
            return
        self.out.append(f"&{name};")
        self.count += 1

    def handle_charref(self, name):
        if self.done:
            return
        self.out.append(f"&#{name};")
        self.count += 1

    def result(self) -> str:
        for tag in reversed(self.stack):
            self.out.append(f"</{tag}>")
        return "".join(self.out)


def _truncate_html(html_str: str | None, limit: int) -> tuple[str | None, bool]:
    """Truncate HTML to ~limit visible characters, tag-safe. Returns (html, was_truncated)."""
    if not html_str or len(html_str) <= limit:
        return html_str, False
    truncator = _HtmlTruncator(limit)
    truncator.feed(html_str)
    return truncator.result(), True


def _truncate_text(text: str | None, limit: int) -> str | None:
    if not text or len(text) <= limit:
        return text
    return text[:limit] + "…"


def _cap_task_widget_sc(sc: dict) -> dict:
    """Cap every variable-length field on a task-detail-shaped structuredContent dict so
    it stays well under ChatGPT's undocumented ~4-5KB widget ceiling (measured: an
    uncapped task with a normal description + a couple of resources was already 7KB+ —
    over the ceiling on a single task, before batching. See WIDGETS.md §19). Shared by
    get_task_detail and find_task, which build the same widget shape.

    The widget shows a preview and reveals the rest via "Show More" using this same
    payload, so these are true content limits, not a display clamp — generous enough to
    read naturally, capped enough that the whole widget doesn't silently fail to render.
    """
    sc = dict(sc)
    sc["description"], sc["description_truncated"] = _truncate_html(sc.get("description"), 1200)
    sc["teacher_comment"] = _truncate_text(sc.get("teacher_comment"), 800)
    if sc.get("images"):
        sc["images"] = sc["images"][:3]
    if sc.get("resources"):
        sc["resources"] = sc["resources"][:6]
    if sc.get("desc_files"):
        sc["desc_files"] = sc["desc_files"][:10]
    if sc.get("submitted_files"):  # preserves None (no dropbox) vs [] (empty dropbox)
        sc["submitted_files"] = sc["submitted_files"][:10]
    if sc.get("discussions"):  # preserves None (hidden) vs [] (empty state)
        sc["discussions"] = [
            {**d, "body": _truncate_text(d.get("body") or "", 400)}
            for d in sc["discussions"][:5]
        ]
    return sc


def _build_task_obj(detail: dict, meta: dict | None, class_name: str = "") -> dict:
    """Combine fetch_task_detail + fetch_tasks metadata into the TASK object the card expects."""
    import re as _re
    from datetime import date as _date

    meta = meta or {}

    # ── Date ──────────────────────────────────────────────────────────────────
    # parse_tasks gives date as e.g. "MAY 22" or "JAN 3"
    date_str = meta.get("date", "")
    due_month = ""
    due_day = ""
    due_past = True  # default: assume past (gray badge)
    if date_str:
        dm = _re.match(r'([A-Za-z]+)\s+(\d+)', date_str.strip())
        if dm:
            month_abbr = dm.group(1).capitalize()  # "MAY" → "May"
            day_num = dm.group(2)
            due_month = month_abbr
            due_day = day_num
            # Determine if past: compare with today
            month_map = {
                "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
                "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
            }
            m_num = month_map.get(month_abbr, 0)
            today = _date.today()
            if m_num:
                # Guess year: if month/day is in the future relative to June, it's current year
                due_year = today.year
                try:
                    due_d = _date(due_year, m_num, int(day_num))
                    # If it's way in the past (e.g. Jan in a June-start year), try next year
                    if (today - due_d).days > 180:
                        due_d = _date(due_year + 1, m_num, int(day_num))
                    elif (due_d - today).days > 180:
                        due_d = _date(due_year - 1, m_num, int(day_num))
                    due_past = due_d < today
                except ValueError:
                    due_past = True

    # ── Labels ────────────────────────────────────────────────────────────────
    _LABEL_STYLES = {
        "summative": "label-summative",
        "formative": "label-formative",
        "homework": "label-homework",
        "classwork": "label-classwork",
    }
    labels = []
    task_type = meta.get("type", "")
    if task_type:
        style = _LABEL_STYLES.get(task_type.lower(), "label-formative")
        labels.append({"text": task_type, "style": style})
    for tag in (meta.get("tags") or []):
        style = _LABEL_STYLES.get(tag.lower(), "label-classwork")
        labels.append({"text": tag, "style": style})

    # ── Grades ────────────────────────────────────────────────────────────────
    grades_raw = meta.get("grades") or {}
    grades = None
    if grades_raw:
        grades = [
            {"label": k, "score": v["score"], "max": v["max"]}
            for k, v in sorted(grades_raw.items())
        ]

    # ── Submitted files ───────────────────────────────────────────────────────
    # Prefer what the task page actually shows: if the detail parse found
    # submitted files, there's definitely a dropbox with submissions — show them
    # even when the task-list meta is missing (e.g. an older task not in the
    # recent list, where has_submission_box isn't known).
    has_sub_box = meta.get("has_submission_box", False)
    raw_files = detail.get("submitted_files") or []
    submitted_files: list | None
    if raw_files:
        submitted_files = [
            {
                "name": f.get("name", ""),
                "uploaded": f.get("uploaded_at", ""),
                "url": f.get("url", "#"),
            }
            for f in raw_files
        ]
    elif has_sub_box:
        submitted_files = []    # dropbox exists but empty
    else:
        submitted_files = None   # no dropbox at all

    # ── Description ───────────────────────────────────────────────────────────
    desc_raw = detail.get("description") or {}
    desc_md = desc_raw.get("text", "") if isinstance(desc_raw, dict) else str(desc_raw)
    # Images are rendered as separate <img> elements in the card (see `images`
    # below), so strip the inline ![](…) markdown from the text to avoid artifacts.
    desc_md = _re.sub(r'!\[[^\]]*\]\([^)]*\)', '', desc_md)
    # Strip embedded-file placeholder lines (📎 …) — files render as cards via desc_files.
    # Handles cached data that was scraped before the scraper change.
    desc_md = _re.sub(r'📎[^\n]*\n?', '', desc_md)
    description = _md_to_html(desc_md) if desc_md.strip() else None
    desc_images = desc_raw.get("images") if isinstance(desc_raw, dict) else None
    embedded_files = desc_raw.get("embedded_files", []) if isinstance(desc_raw, dict) else []
    desc_files = [
        {"name": f.get("name", ""), "size": f.get("size", ""), "url": f.get("url", "#")}
        for f in embedded_files
        if isinstance(f, dict) and f.get("name")
    ]

    # ── Discussions ───────────────────────────────────────────────────────────
    discussions_raw = detail.get("discussions")
    discussions: list | None
    if discussions_raw is None:
        discussions = None
    else:
        discussions = [
            {
                "author": d.get("author", ""),
                "body": d.get("body", "") or d.get("text", ""),
                "posted": d.get("posted_at", "") or d.get("date", ""),
            }
            for d in (discussions_raw or [])
            if isinstance(d, dict)
        ]

    # ── Teacher comment ───────────────────────────────────────────────────────
    teacher_comment = meta.get("teacher_comment") or None

    # ── Resources (teacher-posted files, grouped by post) ─────────────────────
    resources = []
    for r in (detail.get("resources") or []):
        if not isinstance(r, dict):
            continue
        files = [
            {"name": f.get("name", ""), "url": f.get("url", "#"), "size": f.get("size", "")}
            for f in (r.get("files") or [])
            if isinstance(f, dict) and f.get("name")
        ]
        if files:
            resources.append({
                "author": r.get("author", ""),
                "posted": r.get("posted", ""),
                "label": r.get("label", ""),
                "files": files,
            })

    # ── Assemble ──────────────────────────────────────────────────────────────
    task_obj: dict = {
        "title": detail.get("title") or meta.get("title") or "Task",
        "class_name": class_name,
        "url": detail.get("url") or meta.get("url") or "",
        "due_month": due_month,
        "due_day": due_day,
        "due_past": due_past,
        "labels": labels,
        "status": meta.get("status") or "",
        "due_time": meta.get("due_day_time") or None,
        "grades": grades,
        "teacher_comment": teacher_comment,
        "unit": None,   # not available from task list; could be added later
        "description": description,
        "desc_files": desc_files,
        "submitted_files": submitted_files,
        "resources": resources,
        "discussions": discussions,
        "due_passed_late": due_past,
        "images": desc_images or [],
    }
    return task_obj


def _make_task_widget(task_obj: dict) -> str:
    """Return the stable task-detail widget URI.

    We deliberately do NOT bake task data into the served HTML anymore.
    The widget HTML at _TASK_DETAIL_URI stays a clean template (_INJECTED_TASK
    is null) and the per-call task data reaches the widget via
    window.openai.toolOutput (the CallToolResult.structuredContent).

    Why: the widget URI is shared across every task and every user. Baking
    one task's data into that single shared HTML meant the LAST call's task
    leaked into earlier widgets (and across users) whenever a widget fell back
    to the baked _INJECTED_TASK instead of toolOutput. Relying solely on
    toolOutput keeps every widget showing its own task.
    """
    return _TASK_DETAIL_URI


# Content-Security-Policy for the widget iframe. Keep the two domains separate:
# - ManageBac domains: remote LMS assets/images/files the widget may display.
# - Widget domain: the origin hosting this MCP server's widget resources.
# CRITICAL: the CSP must be on the resource returned by resources/read, not just
# resources/list (that's why it kept showing "CSP not set").
_MANAGEBAC_RESOURCE_DOMAINS = [
    "https://*.managebac.com",
    "https://es.managebac.com",
    "https://assets.managebac.com",
    "https://cdn.ca.managebac.com",
    "https://cdn.uk.managebac.com",
    "https://cdn.managebac.com",
]
_DEFAULT_WIDGET_DOMAIN = "https://managebac.822538.xyz"


def _widget_domain() -> str:
    return (os.environ.get("MANAGEBAC_WIDGET_DOMAIN") or _SERVER_PUBLIC_URL or _DEFAULT_WIDGET_DOMAIN).rstrip("/")


# Apps SDK documented format (ui.csp, camelCase)
def _widget_csp() -> dict:
    return {
        "connectDomains": [_widget_domain()],
        "resourceDomains": _MANAGEBAC_RESOURCE_DOMAINS,
    }


# Alternate format some ChatGPT builds read (openai/widgetCSP, snake_case).
# Including both maximises the chance the sandbox honours one of them.
def _widget_csp_alt() -> dict:
    return {
        "connect_domains": [_widget_domain()],
        "resource_domains": _MANAGEBAC_RESOURCE_DOMAINS,
        "redirect_domains": [_widget_domain()],
    }


def _widget_description(uri: str) -> str:
    if uri == _CLASS_LIST_URI:
        return "Interactive class list. Do not repeat the class names in prose unless the user asks for a written copy."
    if uri == _TASK_LIST_URI:
        return "Interactive task list. Do not restate the full task list in prose; summarize only if useful."
    if uri == _TASK_DETAIL_URI:
        return "Interactive task-detail card. Do not repeat the full task description, files, or feedback in prose."
    if uri == _GRADES_URI:
        return "Interactive grades widget. Do not duplicate every criterion score in prose unless asked."
    if uri == _TIMETABLE_URI:
        return "Interactive timetable widget. Do not repeat every class period in prose unless asked."
    if uri == _CLASS_FILES_URI:
        return "Interactive class-files widget. Do not repeat every file name in prose unless asked."
    return "Interactive ManageBac widget. Avoid duplicating the widget contents in prose."


def _widget_content_text(uri: str, sc: dict | None = None) -> str:
    sc = sc or {}
    if uri == _CLASS_LIST_URI:
        count = len(sc.get("classes") or [])
        return f"Rendered an interactive class list widget with {count} classes. Do not repeat the list in prose."
    if uri == _TASK_LIST_URI:
        count = len(sc.get("tasks") or [])
        return f"Rendered an interactive task list widget with {count} tasks. Do not repeat the task rows in prose."
    if uri == _TASK_DETAIL_URI:
        return "Rendered an interactive task-detail widget. Do not repeat the task description, files, or feedback in prose."
    if uri == _GRADES_URI:
        count = len(sc.get("classes") or [])
        return f"Rendered an interactive grades widget for {count} classes. Do not repeat the scores in prose."
    if uri == _TIMETABLE_URI:
        count = len(sc.get("days") or sc.get("timetable") or [])
        return f"Rendered an interactive timetable widget with {count} days. Do not repeat the schedule in prose."
    if uri == _CLASS_FILES_URI:
        count = len(sc.get("files") or [])
        return f"Rendered an interactive class-files widget with {count} files. Do not repeat the file names in prose."
    return "Rendered an interactive ManageBac widget. Do not repeat the widget contents in prose."


def _widget_meta(uri: str, invoking: str, invoked: str) -> dict:
    return {
        "openai/outputTemplate": uri,
        "ui": {"resourceUri": uri, "domain": _widget_domain(), "csp": _widget_csp()},
        "openai/widgetDomain": _widget_domain(),
        "openai/widgetCSP": _widget_csp_alt(),
        "openai/widgetDescription": _widget_description(uri),
        "openai/toolInvocation/invoking": invoking,
        "openai/toolInvocation/invoked": invoked,
        "openai/widgetAccessible": True,
    }

_TEST_META = _widget_meta(_TEST_WIDGET_URI, "Loading test widget...", "Test widget loaded")
# Static task meta used only in the tool *definition* so ChatGPT knows the tool has a widget.
# Actual CallToolResult uses a per-task URI from _make_task_widget().
_TASK_META_STATIC = _widget_meta(_TASK_DETAIL_URI, "Loading task...", "Task loaded")
_FILES_META_STATIC = _widget_meta(_CLASS_FILES_URI, "Loading files...", "Files loaded")
_GRADES_META_STATIC = _widget_meta(_GRADES_URI, "Loading grades...", "Grades loaded")
_TIMETABLE_META_STATIC = _widget_meta(_TIMETABLE_URI, "Loading timetable...", "Timetable loaded")
_TASK_LIST_META_STATIC = _widget_meta(_TASK_LIST_URI, "Loading tasks...", "Tasks loaded")
_CLASS_LIST_META_STATIC = _widget_meta(_CLASS_LIST_URI, "Loading classes...", "Classes loaded")


def _resource_meta(uri: str) -> dict:
    """Full _meta for a widget resource (list + read), including the image CSP."""
    if uri == _TEST_WIDGET_URI:
        invoking, invoked = "Loading test widget...", "Test widget loaded"
    elif uri == _CLASS_FILES_URI:
        invoking, invoked = "Loading files...", "Files loaded"
    elif uri == _GRADES_URI:
        invoking, invoked = "Loading grades...", "Grades loaded"
    elif uri == _TIMETABLE_URI:
        invoking, invoked = "Loading timetable...", "Timetable loaded"
    elif uri == _TASK_LIST_URI:
        invoking, invoked = "Loading tasks...", "Tasks loaded"
    elif uri == _CLASS_LIST_URI:
        invoking, invoked = "Loading classes...", "Classes loaded"
    else:
        invoking, invoked = "Loading task...", "Task loaded"
    return {
        "openai/outputTemplate": uri,
        "openai/widgetAccessible": True,
        "openai/toolInvocation/invoking": invoking,
        "openai/toolInvocation/invoked": invoked,
        "openai/widgetDescription": _widget_description(uri),
        "ui": {"domain": _widget_domain(), "csp": _widget_csp()},
        "openai/widgetDomain": _widget_domain(),
        "openai/widgetCSP": _widget_csp_alt(),
    }


@server.list_resources()
async def list_resources() -> list[types.Resource]:
    # Static widgets use their URI as key; task widgets use hash as key (served via HTTPS)
    resources = [
        types.Resource(uri=uri, name=info["title"], title=info["title"],
                       mimeType=WIDGET_MIME, _meta=_resource_meta(uri))
        for uri, info in _STATIC_WIDGETS.items()
    ]
    for h, info in _TASK_WIDGETS.items():
        url = f"{_SERVER_PUBLIC_URL}/ui/task/{h}"
        resources.append(types.Resource(uri=url, name=info["title"], title=info["title"], mimeType=WIDGET_MIME))
    return resources


@server.list_resource_templates()
async def list_resource_templates() -> list[types.ResourceTemplate]:
    return [
        types.ResourceTemplate(uri_template=uri, name=info["title"], title=info["title"],
                               mimeType=WIDGET_MIME, _meta=_resource_meta(uri))
        for uri, info in _STATIC_WIDGETS.items()
    ]


# Raw resources/read handler (not the @server.read_resource() decorator) so we can
# attach _meta — including the widget CSP — to the returned TextResourceContents.
# The decorator's ReadResourceContents helper cannot carry _meta, which is why the
# CSP never reached ChatGPT and images stayed blocked.
async def _handle_read_resource(req: types.ReadResourceRequest) -> types.ServerResult:
    uri = req.params.uri
    uri_str = str(uri)
    info = _STATIC_WIDGETS.get(uri_str) or _TASK_WIDGETS.get(uri_str)
    canonical_uri = uri_str if uri_str in _STATIC_WIDGETS else None
    if info is None and uri_str.startswith("ui://widget/task-list"):
        info = _STATIC_WIDGETS.get(_TASK_LIST_URI)
        canonical_uri = _TASK_LIST_URI
    if info is None and uri_str.startswith("ui://widget/task"):
        info = _STATIC_WIDGETS.get(_TASK_DETAIL_URI)
        canonical_uri = _TASK_DETAIL_URI
    if info is None and uri_str.startswith("ui://widget/class-files"):
        info = _STATIC_WIDGETS.get(_CLASS_FILES_URI)
        canonical_uri = _CLASS_FILES_URI
    if info is None and uri_str.startswith("ui://widget/grades"):
        info = _STATIC_WIDGETS.get(_GRADES_URI)
        canonical_uri = _GRADES_URI
    if info is None and uri_str.startswith("ui://widget/timetable"):
        info = _STATIC_WIDGETS.get(_TIMETABLE_URI)
        canonical_uri = _TIMETABLE_URI
    if info is None and uri_str.startswith("ui://widget/class-list"):
        info = _STATIC_WIDGETS.get(_CLASS_LIST_URI)
        canonical_uri = _CLASS_LIST_URI
    if info is None:
        return types.ServerResult(
            types.ReadResourceResult(contents=[], _meta={"error": f"Unknown resource: {uri_str}"})
        )
    canonical_uri = canonical_uri or _TASK_DETAIL_URI
    meta = _resource_meta(canonical_uri)
    contents = [
        types.TextResourceContents(uri=uri, mimeType=WIDGET_MIME, text=info["html"], _meta=meta),
        types.TextResourceContents(uri=uri, mimeType=WIDGET_MIME_ALT, text=info["html"], _meta=meta),
    ]
    return types.ServerResult(types.ReadResourceResult(contents=contents))


server.request_handlers[types.ReadResourceRequest] = _handle_read_resource


# Every current tool either just reads ManageBac data (never creates/updates/deletes anything,
# never reaches outside the student's own account) or, for `refresh`, only clears our own local
# cache (regenerable, not user data loss). None are destructive or open-world; all are safe to
# retry. See WIDGETS.md §14/§19 — OpenAI's review explicitly checks these against actual behavior.
_RO_ANNOTATIONS = types.ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, openWorldHint=False, idempotentHint=True,
)
_LOCAL_MUTATION_ANNOTATIONS = types.ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, openWorldHint=False, idempotentHint=True,
)


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    _tools = [
        types.Tool(
            name="get_classes",
            description=(
                "Returns all classes the student is enrolled in. "
                "Each class has: id (required by every other tool), name, url, level_tags, "
                "and has_journal (true if the class has a journal/portfolio tab). "
                "Call this first to get class IDs."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
            annotations=_RO_ANNOTATIONS,
        ),
        types.Tool(
            name="show_classes",
            description=(
                "Render a visual class-list widget showing all enrolled classes. "
                "Use this only when the student asks to see, choose, select, or interact with their classes. "
                "For reasoning or text-only answers, call get_classes instead."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
            annotations=_RO_ANNOTATIONS,
            _meta=_CLASS_LIST_META_STATIC,
        ),
        types.Tool(
            name="get_timetable",
            description=(
                "Returns the student's full weekly timetable plus the current date/time. "
                "The result has two keys: 'current' (the live weekday, date, time, and timezone — "
                "use this to know what day 'today'/'tomorrow' is, never assume) and 'timetable' "
                "(the weekly slots). Each slot has: period, day, time_start, time_end, class_name, "
                "class_id, teacher, room, and task_count. task_count is ManageBac's per-day task "
                "badge for that class — it counts tasks scheduled on that day and may include "
                "already-graded or past tasks, so it is NOT a to-do/unfinished count. Never tell "
                "the student they have work due based on task_count; use get_upcoming for what is "
                "actually due or still to submit. "
                "DAY FILTERING: by default returns the whole week. To show only specific days, "
                "pass 'days' (a single value or list of: 'today', 'tomorrow', a weekday like "
                "'Monday', or a date as shown in the timetable like 'Jun 9'). For a span of days, "
                "pass 'from' and 'to' instead (same accepted values) — e.g. from 'Monday' to "
                "'Wednesday'. Relative words ('today'/'tomorrow') are resolved in the school's "
                "timezone, so just pass the student's words through."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {
                        "description": "Optional. Which day(s) to show. Omit for the whole week. "
                                       "A single value or a list of: 'today', 'tomorrow', a weekday "
                                       "('Monday'), or a date ('Jun 9').",
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ],
                    },
                    "from": {
                        "type": "string",
                        "description": "Optional start of a day range (weekday, 'today'/'tomorrow', "
                                       "or a date like 'Jun 9'). Use together with 'to'.",
                    },
                    "to": {
                        "type": "string",
                        "description": "Optional end of a day range. Use together with 'from'.",
                    },
                },
                "required": [],
            },
            annotations=_RO_ANNOTATIONS,
        ),
        types.Tool(
            name="show_timetable",
            description=(
                "Render a visual timetable widget. Use this when the student asks to see today's "
                "timetable, the week timetable, or a selectable schedule. For reasoning or text-only "
                "answers, call get_timetable instead."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {
                        "description": "Optional. Which day(s) to show. Omit for the whole week. "
                                       "A single value or a list of: 'today', 'tomorrow', a weekday "
                                       "('Monday'), or a date ('Jun 9').",
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ],
                    },
                    "from": {
                        "type": "string",
                        "description": "Optional start of a day range (weekday, 'today'/'tomorrow', "
                                       "or a date like 'Jun 9'). Use together with 'to'.",
                    },
                    "to": {
                        "type": "string",
                        "description": "Optional end of a day range. Use together with 'from'.",
                    },
                },
                "required": [],
            },
            _meta=_TIMETABLE_META_STATIC,
            annotations=_RO_ANNOTATIONS,
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
            annotations=_LOCAL_MUTATION_ANNOTATIONS,
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
            annotations=_RO_ANNOTATIONS,
        ),
        types.Tool(
            name="show_upcoming",
            description=(
                "Render a visual task-list widget for upcoming, overdue, or past tasks. "
                "Use this when the student asks to see a task list. For planning/reasoning "
                "without a widget, call get_upcoming instead."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "view": {
                        "type": "string",
                        "enum": ["upcoming", "overdue", "past"],
                        "description": "Which list to render (default 'upcoming')",
                    }
                },
                "required": [],
            },
            annotations=_RO_ANNOTATIONS,
            _meta=_TASK_LIST_META_STATIC,
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
            annotations=_RO_ANNOTATIONS,
        ),
        types.Tool(
            name="show_tasks",
            description=(
                "Render a visual task-list widget for recent tasks in one class, or a small batch of classes. "
                "Use this when the student asks to show/list/display tasks for a specific class using a widget "
                "(for example, 'show my Digital Design tasks using a widget'). For text-only reasoning, call get_tasks instead. "
                "After this tool renders, do not repeat the full task list in prose."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "class_id": {
                        "description": "A single class ID or a small list of class IDs for batch rendering",
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ],
                    }
                },
                "required": ["class_id"],
            },
            _meta=_TASK_LIST_META_STATIC,
            annotations=_RO_ANNOTATIONS,
        ),
        types.Tool(
            name="get_task_detail",
            description=(
                "Returns the full detail for one or more tasks. "
                "Single task: pass class_id + task_id (preferred), or pass the ManageBac task URL and the IDs will be parsed from it. "
                "ManageBac URLs follow the pattern …/classes/{class_id}/core_tasks/{task_id} — you can read the IDs directly from the URL. "
                "BATCH SUPPORTED: pass a 'tasks' list of {class_id, task_id} pairs — all fetched concurrently. "
                "Returns per task: title, url, "
                "description.text (full instructions as Markdown), "
                "description.links (external URLs embedded by the teacher), "
                "resources (teacher-posted files), "
                "submitted_files (the student's own uploads, with file URLs for the widget attachment-selection flow), "
                "task_history, discussions."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "class_id": {
                        "type": "string",
                        "description": "Class ID — from get_upcoming, get_tasks, or the number after /classes/ in the task URL.",
                    },
                    "task_id": {
                        "type": "string",
                        "description": "Task ID — from get_upcoming, get_tasks, or the number after /core_tasks/ in the task URL.",
                    },
                    "url": {
                        "type": "string",
                        "description": "Full ManageBac task URL — class_id and task_id are parsed from the path automatically. Use when you have the URL but prefer not to extract the IDs manually.",
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
            annotations=_RO_ANNOTATIONS,
        ),
        types.Tool(
            name="show_task_detail",
            description=(
                "Render a visual task-detail card for one or more tasks. Use this only when the "
                "student asks to show/open/display a task card or wants the task visually. "
                "For text-only reasoning about a task, call get_task_detail instead."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "class_id": {
                        "type": "string",
                        "description": "Class ID — from get_upcoming, get_tasks, or the number after /classes/ in the task URL.",
                    },
                    "task_id": {
                        "type": "string",
                        "description": "Task ID — from get_upcoming, get_tasks, or the number after /core_tasks/ in the task URL.",
                    },
                    "url": {
                        "type": "string",
                        "description": "Full ManageBac task URL — class_id and task_id are parsed from the path automatically.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Optional task URL or partial title. If IDs are not provided, this searches like find_task and renders the best match.",
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
            _meta=_TASK_META_STATIC,
            annotations=_RO_ANNOTATIONS,
        ),
        types.Tool(
            name="get_files",
            description=(
                "Fetches files from the student's ManageBac school platform — specifically the Files "
                "section of a class (class-wide materials uploaded by the teacher, NOT the student's "
                "own uploaded files). Use this whenever the student asks about class files, teacher "
                "resources, or worksheets on ManageBac. "
                "BATCH SUPPORTED: class_id can be a single ID or a list. "
                "Each file has: name, size, url (pre-signed download link), uploaded_by, uploaded_at. "
                "For ChatGPT file analysis, use the widget file-selection flow instead of an MCP file-content command."
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
            annotations=_RO_ANNOTATIONS,
        ),
        types.Tool(
            name="show_files",
            description=(
                "Render a visual class-files widget for one class or a small set of classes. "
                "Use this when the student asks to see/select class files. For text-only reasoning "
                "or attachment lookup, call get_files instead."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "class_id": {
                        "description": "A single class ID or a list for batch rendering",
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ],
                    },
                },
                "required": ["class_id"],
            },
            _meta=_FILES_META_STATIC,
            annotations=_RO_ANNOTATIONS,
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
            annotations=_RO_ANNOTATIONS,
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
            annotations=_RO_ANNOTATIONS,
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
            annotations=_RO_ANNOTATIONS,
        ),
        types.Tool(
            name="show_grades",
            description=(
                "Render a visual grades widget with criterion bars and predictor controls. "
                "Use this when the student asks to see grades visually or interact with grade prediction. "
                "For advice/reasoning about grades without a widget, call get_grades instead."
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
            _meta=_GRADES_META_STATIC,
            annotations=_RO_ANNOTATIONS,
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
            annotations=_RO_ANNOTATIONS,
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
            annotations=_RO_ANNOTATIONS,
        ),
        types.Tool(
            name="test_ui",
            description=(
                "TEST TOOL: Simple UI test to verify the iframe infrastructure is working. "
                "Call this to see if ChatGPT can render embedded UI components."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
            _meta=_TEST_META,
            annotations=_RO_ANNOTATIONS,
        ),
    ]

    # Advertise an outputSchema on every tool so ChatGPT stops warning that results
    # are unvalidated. Validation itself is intentionally loose: each tool returns a
    # CallToolResult (see call_tool), which the MCP SDK passes through WITHOUT running
    # jsonschema validation — so these schemas describe the shape without risking a
    # hard failure on a field mismatch.
    # - Data tools return their JSON mirrored under {"result": …} (see the common
    #   return in call_tool), so their schema requires a "result" property.
    # - Widget/content tools return their own structuredContent shape, so they get a
    #   permissive object schema.
    _result_schema = {
        "type": "object",
        "properties": {"result": {"description": "The tool's JSON result (same as the text content)."}},
        "required": ["result"],
    }
    _passthrough_schema = {"type": "object", "additionalProperties": True}
    _own_sc_tools = {
        "show_classes", "show_timetable", "show_upcoming", "show_task_detail",
        "show_tasks", "show_files", "show_grades", "test_ui",
    }
    for _t in _tools:
        _t.outputSchema = _passthrough_schema if _t.name in _own_sc_tools else _result_schema

    return _tools


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


# ── Timetable day filtering ─────────────────────────────────────────────────
# Lets the student ask for a subset of the week ("tomorrow", "Monday",
# "Jun 9", or a range) instead of always getting all five days.
_TT_WEEKDAYS = {
    "monday": "mon", "mon": "mon", "tuesday": "tue", "tue": "tue", "tues": "tue",
    "wednesday": "wed", "wed": "wed", "weds": "wed", "thursday": "thu", "thu": "thu",
    "thur": "thu", "thurs": "thu", "friday": "fri", "fri": "fri",
    "saturday": "sat", "sat": "sat", "sunday": "sun", "sun": "sun",
}


def _tt_month_day(s: str):
    import re
    s = (s or "").lower()
    mm = re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", s)
    dd = re.search(r"(\d{1,2})", s)
    return (mm.group(1) if mm else None, int(dd.group(1)) if dd else None)


def _tt_matcher(token: str):
    """Resolve a day token to a matcher: ('wd', 'mon') or ('date', (month, day))."""
    import datetime
    t = (token or "").strip().lower()
    if not t:
        return None
    now = datetime.datetime.now().astimezone()
    if t in ("today", "tonight"):
        return ("wd", now.strftime("%a").lower())
    if t == "tomorrow":
        return ("wd", (now + datetime.timedelta(days=1)).strftime("%a").lower())
    if t == "yesterday":
        return ("wd", (now - datetime.timedelta(days=1)).strftime("%a").lower())
    if t in _TT_WEEKDAYS:
        return ("wd", _TT_WEEKDAYS[t])
    mo, dy = _tt_month_day(t)
    if mo or dy:
        return ("date", (mo, dy))
    return None


def _tt_entry_matches(entry, matcher) -> bool:
    # entry = (day_str, weekday_abbr_lower, date_part_lower)
    kind, val = matcher
    if kind == "wd":
        return entry[1] == val
    mo, dy = val
    emo, edy = _tt_month_day(entry[2])
    if mo and dy:
        return emo == mo and edy == dy
    if dy:
        return edy == dy
    if mo:
        return emo == mo
    return False


def _filter_timetable(result: dict, days_arg, from_arg, to_arg) -> dict:
    slots = result.get("timetable") or []
    if not slots:
        return result
    # distinct days in week order
    order = []
    for s in slots:
        d = s.get("day") or ""
        if not any(o[0] == d for o in order):
            parts = [p.strip() for p in d.split(",")]
            order.append((d, parts[1].lower() if len(parts) > 1 else "",
                          parts[0].lower() if parts else ""))
    keep = None
    tokens = days_arg if isinstance(days_arg, list) else ([days_arg] if days_arg else [])
    if tokens:
        matchers = [m for m in (_tt_matcher(t) for t in tokens) if m]
        if matchers:
            keep = {o[0] for o in order if any(_tt_entry_matches(o, m) for m in matchers)}
    elif from_arg or to_arg:
        def idx_of(tok):
            m = _tt_matcher(tok)
            if not m:
                return None
            for i, o in enumerate(order):
                if _tt_entry_matches(o, m):
                    return i
            return None
        i_from = idx_of(from_arg) if from_arg else 0
        i_to = idx_of(to_arg) if to_arg else len(order) - 1
        if i_from is None:
            i_from = 0
        if i_to is None:
            i_to = len(order) - 1
        lo, hi = min(i_from, i_to), max(i_from, i_to)
        keep = {o[0] for o in order[lo:hi + 1]}
    if keep is None:
        return result
    filtered = dict(result)
    filtered["timetable"] = [s for s in slots if (s.get("day") or "") in keep]
    return filtered


def _classes_widget_sc(classes: list) -> dict:
    return {
        "scope": "All classes",
        "url": require_user().mb_url.rstrip("/") + "/student",
        "classes": [{"id": c.get("id"), "name": c.get("name")} for c in classes],
    }


def _timetable_widget_sc(result: dict) -> dict:
    cur = result.get("current") or {}
    slim_slots = []
    for s in result.get("timetable") or []:
        t = (s.get("time_start") or "")
        if s.get("time_end"):
            t = (t + "-" + s["time_end"]) if t else s["time_end"]
        slot = {
            "p": s.get("period"),
            "d": s.get("day"),
            "t": t,
            "c": " ".join((s.get("class_name") or "").split()),
        }
        if s.get("teacher"):
            slot["tr"] = s["teacher"]
        if s.get("room"):
            slot["r"] = s["room"]
        if s.get("task_count"):
            slot["n"] = s["task_count"]
        slim_slots.append(slot)
    return {
        "current": {k: cur.get(k) for k in ("weekday", "date", "time")},
        "timetable": slim_slots,
        "url": require_user().mb_url.rstrip("/") + "/student/timetables",
    }


def _upcoming_widget_sc(result: dict, view: str) -> dict:
    due_past = view in ("overdue", "past")

    def slim(t):
        due = (t.get("due") or "").strip()
        date_part, _, time_part = due.partition(",")
        out = {
            "title": t.get("title"),
            "class_name": t.get("class_name"),
            "url": t.get("url"),
            "due_past": due_past,
        }
        if date_part.strip():
            out["date"] = date_part.strip()
        if time_part.strip():
            out["due_time"] = time_part.strip()
        if t.get("type"):
            out["type"] = t["type"]
        status = t.get("status") or ""
        if not status and t.get("needs_submission"):
            status = "Not Submitted"
        if status:
            out["status"] = status
        return out

    return {
        "title": {"upcoming": "Upcoming tasks", "overdue": "Overdue tasks", "past": "Past tasks"}[view],
        "tasks": [slim(t) for t in (result.get("tasks") or [])[:25]],
        "url": require_user().mb_url.rstrip("/") + "/student",
    }


def _tasks_widget_sc(result, class_names: dict[str, str], title: str = "Tasks") -> dict:
    def is_completed(t: dict) -> bool:
        status = (t.get("status") or "").strip().lower()
        return status in {"submitted", "complete", "completed"} or bool(t.get("grades"))

    def slim(t: dict, class_id: str | None = None) -> dict:
        out = {
            "title": t.get("title"),
            "url": t.get("url"),
            "type": t.get("type"),
            "status": t.get("status"),
            "date": t.get("date"),
            "due_day_time": t.get("due_day_time"),
            "grades": t.get("grades"),
            "bucket": "Completed" if is_completed(t) else "Upcoming",
        }
        labels = []
        if t.get("type"):
            labels.append({"text": t.get("type")})
        labels.extend({"text": tag} for tag in (t.get("tags") or [])[:2])
        if labels:
            out["labels"] = labels
        cid = str(t.get("class_id") or class_id or "")
        class_name = t.get("class_name") or class_names.get(cid)
        if class_name:
            out["class_name"] = class_name
        if t.get("teacher_comment"):
            out["teacher_comment"] = True
        return {k: v for k, v in out.items() if v not in (None, "", [], {})}

    tasks = []
    class_name = ""
    if isinstance(result, dict):
        for cid, class_tasks in result.items():
            tasks.extend(slim(t, str(cid)) for t in (class_tasks or []) if isinstance(t, dict))
        if len(result) == 1:
            only_id = str(next(iter(result.keys())))
            class_name = class_names.get(only_id, "")
    else:
        tasks = [slim(t) for t in (result or []) if isinstance(t, dict)]

    sc = {
        "title": title,
        "tasks": tasks[:40],
        "url": require_user().mb_url.rstrip("/") + "/student",
    }
    if class_name:
        sc["class_name"] = class_name
    return sc


def _files_widget_sc(files_list, class_name, page_url):
    # File lists can blow ChatGPT's ~4-5KB structuredContent ceiling fast:
    # presigned download URLs alone run hundreds of bytes each. Keep URLs while
    # they fit, then shed URLs, then cap count.
    def slim(f, with_url):
        d = {"name": f.get("name")}
        for k in ("size", "uploaded_at", "uploaded_by", "folder"):
            if f.get(k):
                d[k] = f[k]
        if with_url and f.get("url"):
            d["url"] = f["url"]
        return d

    for with_url, cap in (
        (True, 80), (True, 40), (False, 80), (False, 40),
        (False, 25), (False, 15), (False, 8),
    ):
        sc = {
            "files": [slim(f, with_url) for f in files_list[:cap]],
            "class_name": class_name,
            "url": page_url,
        }
        if len(json.dumps(sc).encode("utf-8")) <= 4200:
            return sc
    return {"files": [], "class_name": class_name, "url": page_url}


def _grades_widget_sc(result: dict) -> dict:
    def sc_class(c):
        raw_criteria = c.get("criteria") or {}

        def crit(v):
            d = {"latest": v.get("latest")}
            if v.get("best") is not None:
                d["best"] = v.get("best")
            return d

        slim_criteria = {
            k: crit(v) for k, v in raw_criteria.items()
            if isinstance(v, dict) and v.get("latest") is not None
        }
        return {"class_name": c.get("class_name"), "criteria": slim_criteria}

    return {
        "scope": result.get("scope"),
        "url": require_user().mb_url.rstrip("/") + "/student",
        "classes": [sc_class(c) for c in result.get("classes") or []],
    }


async def _task_detail_widget_sc(d_cid, d_tid, detail):
    task_meta_obj: dict = {}
    class_name = ""
    try:
        task_list = await fetch_tasks(d_cid)
        classes = await fetch_classes()
        task_meta_obj = next((t for t in task_list if str(t.get("id")) == str(d_tid)), {})
        cls_match = next((c for c in classes if str(c.get("id")) == str(d_cid)), None)
        if cls_match:
            class_name = cls_match.get("name") or cls_match.get("title") or ""
    except Exception:
        pass
    return _cap_task_widget_sc(_build_task_obj(
        detail if isinstance(detail, dict) else {}, task_meta_obj, class_name,
    ))


_PAUSED_PROMPT = """\
📢 Notice from your administrator: Your ManageBac account has been suspended. \
None of the tools are available right now — tasks, grades, timetable, files, \
and everything else are offline for your account. \
To restore access, re-enroll at: {enroll_url}
"""

_MESSAGE_PROMPT = """\
📢 Message from your administrator:

{message}
"""


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    t0 = time.monotonic()
    result: object

    # ── Pre-flight checks (run before ANY tool logic) ──────────────────────
    from .context import get_current_user
    from . import users as _users, admin as _admin
    _u = get_current_user()
    if _u and _u.id != "local":
        # 1. Paused account — intercept every call
        if not _users.is_enabled(_u.id):
            from . import config as _cfg
            prompt = _PAUSED_PROMPT.format(enroll_url=(_cfg.BASE_URL or "managebac.822538.xyz") + "/enroll")
            cache.log_request(name, arguments, {"suspended": True}, source="mcp",
                              duration_ms=int((time.monotonic() - t0) * 1000))
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=prompt)],
                isError=True,
            )

        # 2. Pending admin message — deliver it and swallow the tool call
        _msg = _admin.pop_message(_u.id)
        if _msg:
            prompt = _MESSAGE_PROMPT.format(message=_msg)
            cache.log_request(name, arguments, {"admin_message": True}, source="mcp",
                              duration_ms=int((time.monotonic() - t0) * 1000))
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=prompt)],
                isError=True,
            )
    # ── End pre-flight ─────────────────────────────────────────────────────

    # Error buffer: any failure inside the dispatch is turned into a structured
    # {"error": ...} the AI can read aloud to the student, AND logged with its
    # reason so the admin can see WHY a call failed instead of a silent empty.
    try:
        if name in ("get_classes", "show_classes"):
            result = await fetch_classes()
            if name == "show_classes" and isinstance(result, list):
                sc = _classes_widget_sc(result)
                duration_ms = int((time.monotonic() - t0) * 1000)
                cache.log_request(name, arguments, result, source="mcp", duration_ms=duration_ms)
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=_widget_content_text(_CLASS_LIST_URI, sc))],
                    structuredContent=sc,
                    _meta=_CLASS_LIST_META_STATIC,
                )
            # else (empty/error) → common return below

        elif name in ("get_timetable", "show_timetable"):
            result = await fetch_timetable()
            # Optional day filtering: days=["tomorrow"]/"Monday"/"Jun 9", or from/to range.
            if isinstance(result, dict) and result.get("timetable") and (
                arguments.get("days") or arguments.get("from") or arguments.get("to")
            ):
                result = _filter_timetable(
                    result, arguments.get("days"), arguments.get("from"), arguments.get("to")
                )
            if name == "show_timetable" and isinstance(result, dict) and isinstance(result.get("timetable"), list):
                sc = _timetable_widget_sc(result)
                duration_ms = int((time.monotonic() - t0) * 1000)
                cache.log_request(name, arguments, result, source="mcp", duration_ms=duration_ms)
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=_widget_content_text(_TIMETABLE_URI, sc))],
                    structuredContent=sc,
                    _meta=_TIMETABLE_META_STATIC,
                )
            # else (empty/error) → common return below

        elif name == "refresh":
            cache.clear_user()
            result = {"status": "refreshed",
                      "message": "Cleared cached data. Re-call the data tool now to get live results from ManageBac."}

        elif name in ("get_upcoming", "show_upcoming"):
            view = arguments.get("view", "upcoming")
            view = view if view in ("upcoming", "overdue", "past") else "upcoming"
            result = await fetch_upcoming(view)
            if name == "show_upcoming" and isinstance(result, dict) and isinstance(result.get("tasks"), list):
                sc = _upcoming_widget_sc(result, view)
                duration_ms = int((time.monotonic() - t0) * 1000)
                cache.log_request(name, arguments, result, source="mcp", duration_ms=duration_ms)
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=_widget_content_text(_TASK_LIST_URI, sc))],
                    structuredContent=sc,
                    _meta=_TASK_LIST_META_STATIC,
                )
            # else (empty/error) → common return below

        elif name in ("get_tasks", "show_tasks"):
            cid = arguments["class_id"]
            if _is_batch(cid):
                result = await _batch(fetch_tasks, cid)
            else:
                result = await fetch_tasks(cid)
            if name == "show_tasks":
                classes = await fetch_classes()
                class_names = {str(c.get("id")): c.get("name", "") for c in classes}
                title = "Class tasks" if _is_batch(cid) else "Tasks"
                sc = _tasks_widget_sc(result, class_names, title)
                duration_ms = int((time.monotonic() - t0) * 1000)
                cache.log_request(name, arguments, result, source="mcp", duration_ms=duration_ms)
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=_widget_content_text(_TASK_LIST_URI, sc))],
                    structuredContent=sc,
                    _meta=_TASK_LIST_META_STATIC,
                )
            result = _slim_tasks(result)   # drop teacher_comment to protect context

        elif name in ("get_task_detail", "show_task_detail"):
            import re as _re
            print(f"[{name}] args={list(arguments.keys())} cid={arguments.get('class_id')} tid={arguments.get('task_id')} url={arguments.get('url','')[:60]}", flush=True)

            # ── Resolve class_id + task_id ───────────────────────────────────
            tasks_arg = arguments.get("tasks")
            if tasks_arg:
                pairs = [(t["class_id"], t["task_id"]) for t in tasks_arg]
                fetched = await asyncio.gather(*[fetch_task_detail(c, t) for c, t in pairs])
                full = {"tasks": list(fetched)}
                if name == "show_task_detail":
                    scs = await asyncio.gather(
                        *[_task_detail_widget_sc(c, t, d) for (c, t), d in zip(pairs, fetched)]
                    )
                    sc = scs[0] if len(scs) == 1 else {"tasks": list(scs)}
            else:
                cid = arguments.get("class_id")
                tid = arguments.get("task_id")
                # Fallback: extract IDs from any URL argument ChatGPT might pass
                if not cid or not tid:
                    url_arg = (arguments.get("url") or arguments.get("task_url")
                               or arguments.get("link") or "")
                    m = _re.search(r"/classes/(\d+)/core_tasks/(\d+)", url_arg)
                    if m:
                        cid, tid = m.group(1), m.group(2)
                if (not cid or not tid) and name == "show_task_detail" and arguments.get("query"):
                    task = await find_task(arguments["query"])
                    if task is None:
                        result = {"error": "Task not found", "tool": name}
                        return types.CallToolResult(
                            content=[types.TextContent(type="text", text=json.dumps(result))],
                            isError=True,
                        )
                    cid = task.get("class_id")
                    tid = task.get("task_id")
                    detail = task
                    full = task
                    sc = await _task_detail_widget_sc(cid, tid, detail)
                    duration_ms = int((time.monotonic() - t0) * 1000)
                    cache.log_request(name, arguments, full, source="mcp", duration_ms=duration_ms)
                    return types.CallToolResult(
                        content=[types.TextContent(type="text", text=_widget_content_text(_TASK_DETAIL_URI, sc))],
                        structuredContent=sc,
                        _meta=_TASK_META_STATIC,
                    )
                if not cid or not tid:
                    result = {"error": "Please provide the task URL (pass it as the 'url' argument)", "tool": name}
                    return types.CallToolResult(
                        content=[types.TextContent(type="text", text=json.dumps(result))],
                        isError=True,
                    )
                detail = await fetch_task_detail(cid, tid)
                full = detail              # single → flat object (back-compat)
                if name == "show_task_detail":
                    sc = await _task_detail_widget_sc(cid, tid, detail)

            if name == "show_task_detail":
                duration_ms = int((time.monotonic() - t0) * 1000)
                cache.log_request(name, arguments, full, source="mcp", duration_ms=duration_ms)
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=_widget_content_text(_TASK_DETAIL_URI, sc))],
                    structuredContent=sc,
                    _meta=_TASK_META_STATIC,
                )
            result = full

        elif name == "get_units":
            cid = arguments["class_id"]
            if _is_batch(cid):
                result = await _batch(fetch_units, cid)
            else:
                result = await fetch_units(cid)

        elif name in ("get_files", "show_files"):
            cid = arguments["class_id"]
            mb_url = require_user().mb_url.rstrip("/")
            if _is_batch(cid):
                result = await _batch(fetch_files, cid)
                if name == "show_files":
                    classes = await fetch_classes()
                    name_of = {str(c.get("id")): c.get("name", "") for c in classes}
                    merged = []
                    for one_id, one_files in result.items():
                        if not isinstance(one_files, list):
                            continue
                        label = name_of.get(str(one_id)) or f"Class {one_id}"
                        for f in one_files:
                            merged.append({**f, "folder": label})
                    n_classes = len([v for v in result.values() if isinstance(v, list)])
                    sc = _files_widget_sc(merged, f"{n_classes} classes", f"{mb_url}/student")
                    duration_ms = int((time.monotonic() - t0) * 1000)
                    cache.log_request(name, arguments, result, source="mcp", duration_ms=duration_ms)
                    return types.CallToolResult(
                        content=[types.TextContent(type="text", text=_widget_content_text(_CLASS_FILES_URI, sc))],
                        structuredContent=sc,
                        _meta=_FILES_META_STATIC,
                    )
            else:
                files = await fetch_files(cid)
                result = {"files": files}
                if name == "show_files":
                    classes = await fetch_classes()
                    cls = next((c for c in classes if str(c.get("id")) == str(cid)), {})
                    class_name = cls.get("name", "")
                    sc = _files_widget_sc(files, class_name, f"{mb_url}/student/classes/{cid}/files")
                    duration_ms = int((time.monotonic() - t0) * 1000)
                    cache.log_request(name, arguments, result, source="mcp", duration_ms=duration_ms)
                    return types.CallToolResult(
                        content=[types.TextContent(type="text", text=_widget_content_text(_CLASS_FILES_URI, sc))],
                        structuredContent=sc,
                        _meta=_FILES_META_STATIC,
                    )

        elif name == "get_journal":
            cid = arguments["class_id"]
            if _is_batch(cid):
                result = await _batch(fetch_journal, cid)
            else:
                result = await fetch_journal(cid)

        elif name in ("get_grades", "show_grades"):
            result = await fetch_grades(arguments.get("class_id", ""))
            if name == "show_grades" and isinstance(result, dict) and isinstance(result.get("classes"), list):
                sc = _grades_widget_sc(result)
                duration_ms = int((time.monotonic() - t0) * 1000)
                cache.log_request(name, arguments, result, source="mcp", duration_ms=duration_ms)
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=_widget_content_text(_GRADES_URI, sc))],
                    structuredContent=sc,
                    _meta=_GRADES_META_STATIC,
                )
            # else (error / no classes) → common return below

        elif name == "tag_search":
            result = await tag_search(arguments["tag"], arguments.get("class_id", ""))

        elif name == "find_task":
            task = await find_task(arguments["query"])
            if task is None:
                result = {"error": "Task not found", "tool": name}
            else:
                result = task

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
    # The model reads the JSON from the text content; structuredContent={"result": …}
    # mirrors it so these tools satisfy their declared outputSchema (returning a
    # CallToolResult also skips the SDK's strict output validation).
    return types.CallToolResult(
        content=[types.TextContent(
            type="text",
            text=json.dumps(result, ensure_ascii=False, separators=(",", ":")),
        )],
        structuredContent={"result": result},
    )


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
