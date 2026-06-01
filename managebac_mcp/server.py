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
    fetch_file_bytes,
    submit_task_file,
    find_task,
)
from . import cache

server = Server("managebac")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_classes",
            description=(
                "ManageBac is the school's IB (International Baccalaureate) learning management system "
                "at es.managebac.com — it is where teachers post assignments, grades, resources, and "
                "feedback for every subject. "
                "This tool returns all classes the student is currently enrolled in. "
                "Each class has: id (numeric string, required by other tools), name (e.g. 'Mathematics HL'), "
                "url (direct clickable link to the class page on ManageBac), "
                "level_tags (e.g. HL or SL for IB subjects), and has_journal (true if the class "
                "has a learner portfolio / journal tab). "
                "ALWAYS call this first — you need the class id to call any other tool."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="get_timetable",
            description=(
                "Returns the student's full weekly school timetable from ManageBac. "
                "Each slot has: period (number), day (e.g. Monday), time_start, time_end, "
                "class_name, teacher, room, and task_count (number of pending tasks for that class). "
                "Use this to answer questions like 'what do I have tomorrow?', "
                "'when is my next Biology class?', or 'what room is Math in?'."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="get_tasks",
            description=(
                "Returns every task (assignment, test, project, homework) posted in a class on ManageBac. "
                "BATCH SUPPORTED: pass a list of class_ids to fetch multiple classes in one call "
                "(e.g. ['12734244', '12900718']) — all fetched concurrently. "
                "When batching, result is a dict keyed by class_id. "
                "Each task has: id, title, url (direct clickable link — always include when mentioning a task), "
                "date (when assigned, e.g. 'MAR 15'), due_day_time (e.g. 'Friday at 11:59 PM'), "
                "type (Summative or Formative), "
                "tags (criteria like 'Criterion A', or labels like 'Homework' / 'Test'), "
                "status (Pending / Submitted / Complete / Not Submitted / Incomplete / N/A), "
                "has_submission_box (true if the student needs to upload a file), "
                "grades (e.g. {A: {score: 7, max: 8}}), and teacher_comment (teacher's written feedback, "
                "already expanded — no clicking needed). "
                "To get the full task description, links, and files, call get_task_detail next."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "class_id": {
                        "description": "One class ID (e.g. '12734244') or a list of IDs for batch fetching",
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
                "Returns the full detail page for one or more tasks on ManageBac. "
                "BATCH SUPPORTED: pass a 'tasks' list of {class_id, task_id} objects to fetch "
                "multiple tasks in one call — all fetched concurrently. Result is a list. "
                "Single task: pass class_id and task_id directly. "
                "Returns per task: url (clickable link), "
                "description.text (full instructions in Markdown — bold/italic/lists preserved), "
                "description.links (external URLs the teacher embedded — Google Docs, Slides, YouTube, Canva…), "
                "description.embedded_files (PDFs or files attached in the description, each with a url), "
                "resources (teacher-posted files on the task), "
                "submitted_files (files the student uploaded, with teacher_feedback_token if annotated), "
                "task_history (created_at, reminder_sent_at, last_updated_at), "
                "discussions (posts with author, posted_at, text, links, replies). "
                "Always share the url and any description.links with the student — they are clickable."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "class_id": {
                        "type": "string",
                        "description": "Numeric class ID — for single task only",
                    },
                    "task_id": {
                        "type": "string",
                        "description": "Numeric task ID — for single task only",
                    },
                    "tasks": {
                        "type": "array",
                        "description": "List of tasks for batch fetching — use instead of class_id/task_id",
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
                "Returns all resource files uploaded to a class's Files section on ManageBac "
                "(not task-specific — these are class-wide materials posted by the teacher). "
                "BATCH SUPPORTED: pass a list of class_ids to fetch multiple classes at once. "
                "When batching, result is a dict keyed by class_id. "
                "Each file has: name, size, uploaded_by (teacher name), uploaded_at (date). "
                "Use this when the student asks 'what files are in my Biology class?' or "
                "'has the teacher uploaded any notes for this unit?'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "class_id": {
                        "description": "One class ID or a list for batch fetching",
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
                "Returns learner portfolio / reflective journal entries for a class on ManageBac. "
                "Only certain classes have journals (e.g. Theatre, CAS, ToK, Digital Design). "
                "Check has_journal from get_classes before calling. "
                "BATCH SUPPORTED: pass a list of class_ids to fetch multiple journals at once. "
                "When batching, result is a dict keyed by class_id. "
                "Each entry has: date, time, body (Markdown), learning_outcomes, is_starred, links, files. "
                "Use this when the student asks about their portfolio, reflections, or journal."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "class_id": {
                        "description": "One class ID or a list for batch fetching",
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
                "⚠️ WRITE OPERATION — uploads a file to a task's submission dropbox on ManageBac. "
                "ALWAYS call with dry_run=true first to confirm details with the student before submitting. "
                "Only submit when the student explicitly says 'yes, submit it'. "
                "Requires class_id and task_id (from get_tasks or get_classes). "
                "file_path must be the absolute local path to the file on the student's computer. "
                "dry_run=true (default): validates the file and task, shows exactly what would be submitted, "
                "but does NOT upload anything. "
                "dry_run=false: actually uploads the file. "
                "Returns success=true with the task URL on success, or an error message on failure. "
                "Note: ManageBac will mark uploads as late if the deadline has passed — "
                "this is shown in the server_response field."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "class_id": {
                        "type": "string",
                        "description": "Numeric class ID from get_classes",
                    },
                    "task_id": {
                        "type": "string",
                        "description": "Numeric task ID from get_tasks",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Absolute local path to the file to submit (e.g. '/Users/you/Documents/essay.pdf')",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "true = preview only, do NOT submit (default). false = actually upload.",
                        "default": True,
                    },
                },
                "required": ["class_id", "task_id", "file_path"],
            },
        ),
        types.Tool(
            name="get_file_content",
            description=(
                "Downloads a ManageBac attachment and returns it as a native file "
                "so you can read it directly — no text conversion. "
                "Use this when a task has a PDF, image, or other file in "
                "description.embedded_files or resources that you need to read. "
                "Pass the full URL exactly as it appears in embedded_files[].url. "
                "The file is fetched using the student's authenticated session. "
                "PDFs are returned as embedded PDF resources (you can read them natively). "
                "Images are returned as image content. "
                "Files are cached on disk for 1 hour — repeated calls for the same URL are instant."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": (
                            "Full ManageBac attachment URL from description.embedded_files[].url "
                            "or resources[].files[].url"
                        ),
                    }
                },
                "required": ["url"],
            },
        ),
        types.Tool(
            name="get_units",
            description=(
                "Returns all IB curriculum units for a class with the full MYP/DP framework: "
                "statement of inquiry, key concepts (with definitions), related concepts, global context, "
                "conceptual understanding, inquiry questions (Factual/Conceptual/Debatable), "
                "ATL skills, start date, duration, and status (current/completed/upcoming). "
                "BATCH SUPPORTED: pass a list of class_ids to fetch units for multiple classes at once. "
                "When batching, result is a dict keyed by class_id. "
                "IMPORTANT: multiple tasks belong to the same unit — call this ONCE per class and reuse. "
                "Match tasks to units via the task title prefix (e.g. 'Unit 4: task 2') or date range. "
                "Use this when the student asks about a unit's statement of inquiry, global context, "
                "key concepts, or the IB framework behind their tasks."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "class_id": {
                        "description": "One class ID or a list for batch fetching",
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
            name="find_task",
            description=(
                "Finds a specific task by either a ManageBac URL or a title search across all classes. "
                "Use this when the student pastes a ManageBac link or mentions a task by name "
                "without saying which class it is in. "
                "URL mode: pass the full ManageBac URL (e.g. "
                "'https://es.managebac.com/student/classes/12734244/core_tasks/47617250') — "
                "the class_id and task_id are extracted automatically and full task detail is returned. "
                "Title search mode: pass a task name (e.g. 'biology essay' or 'end of unit reflection') — "
                "it performs a fuzzy match across every class and returns the best matching task's full detail. "
                "Returns the same structure as get_task_detail, including the url field."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Either a full ManageBac task URL, or a task title / partial title to search for"
                        ),
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
            arguments["file_path"],
            dry_run=arguments.get("dry_run", True),
        )

    elif name == "get_file_content":
        import base64
        file = await fetch_file_bytes(arguments["url"])
        if file["error"]:
            result = {"error": file["error"]}
        else:
            ct = file["content_type"]
            b64 = base64.standard_b64encode(file["data"]).decode()
            if ct.startswith("image/"):
                return [types.ImageContent(type="image", data=b64, mimeType=ct)]
            else:
                return [types.EmbeddedResource(
                    type="resource",
                    resource=types.BlobResourceContents(
                        uri=arguments["url"],
                        mimeType=ct,
                        blob=b64,
                    ),
                )]

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
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="managebac",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
