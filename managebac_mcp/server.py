import sys
from pathlib import Path

import asyncio
import json
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
    fetch_file_content,
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
                "Returns every task (assignment, test, project, homework) posted in a specific class on ManageBac. "
                "Requires class_id from get_classes. "
                "Each task has: id, title, url (direct clickable link to the task — always include this "
                "when telling the student about a task), date (when it was assigned, e.g. 'MAR 15'), "
                "due_day_time (e.g. 'Friday at 11:59 PM'), type (Summative or Formative), "
                "tags (criteria like 'Criterion A', or labels like 'Homework' / 'Test'), "
                "status (Pending / Submitted / Complete / Not Submitted / Incomplete / N/A), "
                "has_submission_box (true if the student needs to upload a file), "
                "grades (e.g. {A: {score: 7, max: 8}}), and teacher_comment (teacher's written feedback, "
                "already expanded — no clicking needed). "
                "To get the full task description, links, and attached files, call get_task_detail next."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "class_id": {
                        "type": "string",
                        "description": "Numeric class ID from get_classes (e.g. '12734244')",
                    }
                },
                "required": ["class_id"],
            },
        ),
        types.Tool(
            name="get_task_detail",
            description=(
                "Returns the full detail page for a specific task on ManageBac. "
                "Requires class_id and task_id (both available from get_tasks). "
                "Returns: url (direct clickable link to this task), "
                "description.text (full assignment instructions — CSS 'Show More' is already expanded), "
                "description.links (external URLs embedded in the instructions, e.g. Google Docs, "
                "Google Slides, YouTube, Canva — these are the links the teacher wants the student to open), "
                "description.embedded_files (PDFs or files attached inside the description), "
                "resources (files and posts added by the teacher to this task), "
                "submitted_files (files the student already uploaded, with teacher_feedback_token "
                "if the teacher annotated the submission), "
                "task_history (created_at, reminder_sent_at, last_updated_at), "
                "discussions (list of posts — each has author, posted_at, text, links, and replies; "
                "empty list means no one has posted yet). "
                "Always share the url and any description.links with the student — they are clickable."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "class_id": {
                        "type": "string",
                        "description": "Numeric class ID (e.g. '12734244')",
                    },
                    "task_id": {
                        "type": "string",
                        "description": "Numeric task ID from get_tasks (e.g. '47617250')",
                    },
                },
                "required": ["class_id", "task_id"],
            },
        ),
        types.Tool(
            name="get_files",
            description=(
                "Returns all resource files uploaded to a class's Files section on ManageBac "
                "(not task-specific — these are class-wide materials posted by the teacher). "
                "Requires class_id from get_classes. "
                "Each file has: name, size, uploaded_by (teacher name), uploaded_at (date). "
                "Use this when the student asks 'what files are in my Biology class?' or "
                "'has the teacher uploaded any notes for this unit?'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "class_id": {
                        "type": "string",
                        "description": "Numeric class ID from get_classes",
                    },
                },
                "required": ["class_id"],
            },
        ),
        types.Tool(
            name="get_journal",
            description=(
                "Returns learner portfolio / reflective journal entries for a class on ManageBac. "
                "Only certain classes have journals (e.g. Theatre, CAS, ToK). "
                "If the class has no journal, returns an empty list. "
                "Check has_journal from get_classes before calling this. "
                "Each entry has: date, is_read_only, is_starred, files (attachments in the entry). "
                "Use this when the student asks about their portfolio, reflections, or journal."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "class_id": {
                        "type": "string",
                        "description": "Numeric class ID from get_classes",
                    },
                },
                "required": ["class_id"],
            },
        ),
        types.Tool(
            name="get_file_content",
            description=(
                "Downloads a ManageBac attachment and returns its text content. "
                "Use this when you have a file URL from a task's description.embedded_files, "
                "resources, or submitted_files and the student needs to know what is inside the file. "
                "Supports PDF (including multi-page documents with tables), DOCX, and plain text. "
                "Pass the full URL exactly as it appears in the embedded_files or resources list. "
                "The file is downloaded using the authenticated ManageBac session — "
                "no separate login is needed. "
                "Returns: content_type, size_bytes, page_count (for PDFs), text (extracted content), "
                "truncated (true if the file was too long to return in full — typically novels or "
                "very long PDFs), and error (null on success). "
                "Images and unsupported file types return an error message, not a crash. "
                "Results are cached for 1 hour so the same file is never downloaded twice."
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
                "Returns all IB curriculum units for a class, each with the full MYP/DP "
                "framework: statement of inquiry, key concepts, related concepts, global context, "
                "conceptual understanding, inquiry questions, ATL skills, start date, and duration. "
                "Requires class_id from get_classes. "
                "IMPORTANT: Multiple tasks usually belong to the same unit — call this ONCE per "
                "class and reuse the data rather than fetching it per-task. "
                "To match a task to its unit: most task titles are prefixed with the unit name "
                "(e.g. 'Unit 4: task 2 — Research'), or compare the task due date with the unit's "
                "start date and duration. The 'status' field tells you if a unit is 'current', "
                "'completed', or 'upcoming'. "
                "Use this when the student asks about a unit's statement of inquiry, global context, "
                "key concepts, or needs to understand the bigger IB framework behind their tasks."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "class_id": {
                        "type": "string",
                        "description": "Numeric class ID from get_classes",
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


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    t0 = time.monotonic()
    result: object

    if name == "get_classes":
        result = await fetch_classes()
    elif name == "get_timetable":
        result = await fetch_timetable()
    elif name == "get_tasks":
        result = await fetch_tasks(arguments["class_id"])
    elif name == "get_task_detail":
        result = await fetch_task_detail(arguments["class_id"], arguments["task_id"])
    elif name == "get_file_content":
        result = await fetch_file_content(arguments["url"])
    elif name == "get_units":
        result = await fetch_units(arguments["class_id"])
    elif name == "get_files":
        result = await fetch_files(arguments["class_id"])
    elif name == "get_journal":
        result = await fetch_journal(arguments["class_id"])
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
