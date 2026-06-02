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
    tag_search,
    submit_task_file,
    find_task,
)
from . import cache

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
    "- submit_task_file uploads work to a task. Never submit without showing a dry-run "
    "preview first and getting the student's explicit confirmation.\n"
    "- Data is cached for speed (tasks ~10 min, classes/units longer). If the student asks "
    "to 'update', 'refresh', 'check again', or is waiting on a new grade/task, call refresh "
    "first and then re-fetch — that pulls live data from ManageBac."
)

server = Server("managebac", instructions=SERVER_INSTRUCTIONS)


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
                "Returns all tasks for one or more classes. "
                "BATCH SUPPORTED: class_id can be a single ID or a list — all fetched concurrently. "
                "Batch result is a dict keyed by class_id. "
                "Each task has: id, title, url, date, due_day_time, type (Summative/Formative), "
                "tags, status (Pending/Submitted/Complete/Incomplete/N/A), has_submission_box, "
                "grades (e.g. {A: {score: 7, max: 8}}), teacher_comment. "
                "Call get_task_detail for the full description, links, and attached files."
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
                "submitted_files (student uploads, with teacher_feedback_token if annotated), "
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
            name="submit_task_file",
            description=(
                "⚠️ WRITE OPERATION — uploads a file to a task's submission dropbox. "
                "Always call with dry_run=true first to show the student what will be submitted; "
                "only set dry_run=false when the student explicitly confirms. "
                "Provide the file in ONE of two ways: "
                "(a) file_path — an absolute local path (e.g. '/tmp/essay.pdf'); use this when running "
                "locally (Claude Desktop). Save generated files to /tmp/ first. "
                "(b) file_base64 + filename — the file's bytes base64-encoded plus its name; use this "
                "when running remotely (ChatGPT) where there is no shared filesystem. "
                "Returns success=true and the task url on success."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "class_id": {"type": "string", "description": "Class ID from get_classes"},
                    "task_id": {"type": "string", "description": "Task ID from get_tasks"},
                    "file_path": {
                        "type": "string",
                        "description": "Absolute local path to the file (local clients). Save to /tmp/ first.",
                    },
                    "file_base64": {
                        "type": "string",
                        "description": "The file's raw bytes, base64-encoded (remote clients). Requires filename.",
                    },
                    "filename": {
                        "type": "string",
                        "description": "File name to upload as (e.g. 'essay.pdf'). Required with file_base64.",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "true = preview only, do not submit (default). false = actually upload.",
                        "default": True,
                    },
                },
                "required": ["class_id", "task_id"],
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
    ]


def _is_batch(val) -> bool:
    return isinstance(val, list)


async def _batch(fn, ids: list[str]) -> dict:
    """Run fn(id) for each id concurrently and return {id: result}."""
    results = await asyncio.gather(*[fn(i) for i in ids])
    return dict(zip(ids, results))


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    t0 = time.monotonic()
    result: object

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

    elif name == "get_task_detail":
        tasks_arg = arguments.get("tasks")
        if tasks_arg:
            # Batch: [{class_id, task_id}, ...]
            results = await asyncio.gather(*[
                fetch_task_detail(t["class_id"], t["task_id"]) for t in tasks_arg
            ])
            result = list(results)
        else:
            result = await fetch_task_detail(arguments["class_id"], arguments["task_id"])

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

    elif name == "submit_task_file":
        result = await submit_task_file(
            arguments["class_id"],
            arguments["task_id"],
            file_path=arguments.get("file_path"),
            file_base64=arguments.get("file_base64"),
            filename=arguments.get("filename"),
            dry_run=arguments.get("dry_run", True),
        )

    elif name == "get_file_content":
        f = await fetch_file_readable(arguments["url"])
        if f["kind"] == "image":
            return [types.ImageContent(type="image", data=f["data_b64"], mimeType=f["content_type"])]
        elif f["kind"] == "text":
            return [types.TextContent(type="text", text=f["text"])]
        else:
            result = {"error": f["error"]}

    elif name == "tag_search":
        result = await tag_search(arguments["tag"], arguments.get("class_id", ""))

    elif name == "find_task":
        result = await find_task(arguments["query"])
        if result is None:
            result = {"error": "Task not found"}

    else:
        result = {"error": f"Unknown tool: {name}"}

    duration_ms = int((time.monotonic() - t0) * 1000)
    cache.log_request(name, arguments, result, source="mcp", duration_ms=duration_ms)

    return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]


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
