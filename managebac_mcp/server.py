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

WIDGET_MIME = "text/html+skybridge"

_TEST_WIDGET_URI = "ui://widget/test.html"
_TEST_WIDGET_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>UI Test</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="m-0 p-6 bg-white font-sans">
  <div class="max-w-md mx-auto bg-green-50 border-2 border-green-500 rounded-xl p-8 text-center">
    <div class="text-5xl mb-4">&#9989;</div>
    <h1 class="text-2xl font-bold text-green-700 mb-2">UI is working!</h1>
    <p class="text-slate-600 mb-6">The ChatGPT iframe loaded and received tool data.</p>
    <div class="bg-white rounded-lg border border-slate-200 p-4 text-left">
      <p class="text-xs font-semibold text-slate-500 mb-1">toolOutput:</p>
      <pre id="out" class="text-xs text-slate-800 whitespace-pre-wrap">loading...</pre>
    </div>
  </div>
  <script>
    const out = window.openai?.toolOutput;
    document.getElementById('out').textContent = JSON.stringify(out, null, 2);
    window.addEventListener('openai:set_globals', e => {
      if (e.detail?.globals?.theme === 'dark') document.body.style.background = '#0f172a';
    }, { passive: true });
  </script>
</body>
</html>"""

_TASK_DETAIL_URI = "ui://widget/task-detail.html"
_TASK_DETAIL_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Task Detail</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="m-0 p-0 bg-white text-slate-900">
  <div id="root" class="p-6 max-w-3xl mx-auto overflow-auto h-full">
    <p class="text-slate-400">Loading...</p>
  </div>
  <script>
    function render(task) {
      if (!task) return;
      const e = s => String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
      let h = '';

      // Header
      h += '<h1 class="text-2xl font-bold mb-2">' + e(task.title) + '</h1>';
      if (task.status) {
        const ok = task.status.toLowerCase().includes('submitted');
        h += '<span class="inline-block px-3 py-1 rounded-full text-sm font-medium mb-4 ' +
          (ok ? 'bg-green-100 text-green-800' : 'bg-orange-100 text-orange-800') + '">' + e(task.status) + '</span>';
      }

      // Due date
      if (task.due_date) {
        h += '<div class="mb-4 p-3 bg-slate-50 rounded-lg text-sm text-slate-600">Due: <strong>' + e(task.due_date) + '</strong></div>';
      }

      // Description
      if (task.description) {
        h += '<h2 class="text-lg font-semibold mt-5 mb-2">Description</h2>';
        const txt = typeof task.description === 'string' ? task.description : task.description.text || '';
        h += '<div class="prose text-sm leading-relaxed">' + txt + '</div>';
        const links = task.description?.links || [];
        if (links.length) {
          h += '<ul class="mt-3 space-y-1">' + links.map(l =>
            '<li><a href="' + e(l) + '" target="_blank" class="text-blue-600 hover:underline text-sm break-all">' + e(l) + '</a></li>'
          ).join('') + '</ul>';
        }
      }

      // Submitted files
      if (task.submitted_files?.length) {
        h += '<h2 class="text-lg font-semibold mt-5 mb-2">Your Submissions</h2>';
        h += task.submitted_files.map(f =>
          '<div class="flex justify-between items-center p-3 mb-2 bg-green-50 border border-green-200 rounded-lg">' +
          '<div><p class="font-medium text-sm">' + e(f.name) + '</p>' +
          (f.size ? '<p class="text-xs text-slate-500">' + e(f.size) + '</p>' : '') + '</div>' +
          (f.url ? '<button class="text-blue-600 text-sm hover:underline view-file" data-url="' + e(f.url) + '">View</button>' : '') +
          '</div>'
        ).join('');
      }

      // Open link
      if (task.url) {
        h += '<div class="mt-8 pt-5 border-t border-slate-200">' +
          '<a href="' + e(task.url) + '" target="_blank" class="inline-block px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700">Open in ManageBac &#8599;</a>' +
          '</div>';
      }

      document.getElementById('root').innerHTML = h;

      document.querySelectorAll('.view-file').forEach(btn => {
        btn.addEventListener('click', () => {
          window.parent.postMessage({
            jsonrpc: '2.0', id: Math.random(),
            method: 'tools/call',
            params: { name: 'get_file_content', arguments: { url: btn.dataset.url } }
          }, '*');
        });
      });
    }

    render(window.openai?.toolOutput);

    window.addEventListener('message', e => {
      if (e.source !== window.parent) return;
      if (e.data?.method === 'ui/notifications/tool-result') render(e.data.params?.structuredContent);
    }, { passive: true });

    window.addEventListener('openai:set_globals', e => {
      if (e.detail?.globals?.theme === 'dark') {
        document.body.classList.add('dark');
        document.body.style.background = '#0f172a';
        document.body.style.color = '#f1f5f9';
      }
    }, { passive: true });
  </script>
</body>
</html>"""

_WIDGETS = {
    _TEST_WIDGET_URI: _TEST_WIDGET_HTML,
    _TASK_DETAIL_URI: _TASK_DETAIL_HTML,
}


@server.list_resources()
async def list_resources() -> list[types.Resource]:
    return [
        types.Resource(uri=uri, name=uri, mimeType=WIDGET_MIME)
        for uri in _WIDGETS
    ]


@server.read_resource()
async def read_resource(uri) -> list:
    from mcp.server.lowlevel.helper_types import ReadResourceContents
    uri_str = str(uri)
    html = _WIDGETS.get(uri_str)
    if html is None:
        raise ValueError(f"Unknown resource: {uri_str}")
    return [ReadResourceContents(content=html, mime_type=WIDGET_MIME)]


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
                "BATCH SUPPORTED: pass a 'tasks' list of {class_id, task_id} pairs — all fetched concurrently, result is a list. "
                "Single task: pass class_id and task_id directly. "
                "Returns per task: url, "
                "description.text (full instructions as Markdown — bold/italic/lists preserved), "
                "description.links (external URLs embedded by the teacher), "
                "description.embedded_files (attached files, each with name, size, url), "
                "resources (teacher-posted files), "
                "submitted_files (the student's own uploads — each has a `url` you can pass to "
                "get_file_content to read the PDF/doc they turned in; plus teacher_feedback_token if annotated), "
                "task_history, discussions (posts with author, timestamp, text, links, replies)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "class_id": {
                        "type": "string",
                        "description": "Class ID — single task mode only",
                    },
                    "task_id": {
                        "type": "string",
                        "description": "Task ID — single task mode only",
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
            _meta={
                "openai/outputTemplate": _TASK_DETAIL_URI,
                "openai/toolInvocation/invoking": "Loading task...",
                "openai/toolInvocation/invoked": "Task loaded",
            },
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
            _meta={
                "openai/outputTemplate": _TEST_WIDGET_URI,
                "openai/toolInvocation/invoking": "Loading test widget...",
                "openai/toolInvocation/invoked": "Test widget loaded",
            },
        ),
    ]


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
            tasks_arg = arguments.get("tasks")
            if tasks_arg:
                results = await asyncio.gather(*[
                    fetch_task_detail(t["class_id"], t["task_id"]) for t in tasks_arg
                ])
                result = list(results)
            else:
                task = await fetch_task_detail(arguments["class_id"], arguments["task_id"])
                duration_ms = int((time.monotonic() - t0) * 1000)
                cache.log_request(name, arguments, task, source="mcp", duration_ms=duration_ms)
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=json.dumps(task, ensure_ascii=False, separators=(",", ":")))],
                    structuredContent=task,
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
            result = await find_task(arguments["query"])
            if result is None:
                result = {"error": "Task not found", "tool": name}

        elif name == "test_ui":
            sc = {"message": "UI infrastructure test", "status": "ok", "timestamp": time.time()}
            duration_ms = int((time.monotonic() - t0) * 1000)
            cache.log_request(name, arguments, sc, source="mcp", duration_ms=duration_ms)
            return types.CallToolResult(
                content=[types.TextContent(type="text", text="Test widget rendered.")],
                structuredContent=sc,
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
