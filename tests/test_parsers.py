"""
Unit tests for all parsers using saved HTML fixtures.
Run: pytest tests/test_parsers.py
"""
import json
import re
import pytest
from pathlib import Path
from managebac_mcp.scraper import parse_classes, parse_tasks, parse_task_detail, parse_files, parse_journal, parse_timetable

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    path = FIXTURES / name
    if not path.exists():
        pytest.skip(f"Fixture {name} not saved yet — run: python tests/save_fixtures.py")
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------

def test_parse_classes_returns_list():
    html = load("classes_my.html")
    classes = parse_classes(html)
    assert isinstance(classes, list)
    assert len(classes) > 0


def test_parse_classes_has_required_fields():
    html = load("classes_my.html")
    classes = parse_classes(html)
    for cls in classes:
        assert "id" in cls
        assert "name" in cls
        assert cls["id"].isdigit()
        assert len(cls["name"]) > 0


def test_parse_classes_known_class():
    html = load("classes_my.html")
    classes = parse_classes(html)
    ids = [c["id"] for c in classes]
    assert "12905566" in ids  # History (Grade 8) B


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

def test_parse_tasks_returns_list():
    html = load("tasks_history.html")
    tasks = parse_tasks(html)
    assert isinstance(tasks, list)
    assert len(tasks) > 0


def test_parse_tasks_fields():
    html = load("tasks_history.html")
    tasks = parse_tasks(html)
    task = tasks[0]
    assert "id" in task
    assert "title" in task
    assert "status" in task
    assert "grades" in task
    assert task["id"].isdigit()


def test_parse_tasks_grade_format():
    html = load("tasks_history.html")
    tasks = parse_tasks(html)
    graded = [t for t in tasks if t["grades"]]
    if graded:
        g = list(graded[0]["grades"].values())[0]
        assert "score" in g
        assert "max" in g


def test_parse_tasks_valid_statuses():
    html = load("tasks_history.html")
    tasks = parse_tasks(html)
    valid = {"Pending", "Submitted", "Complete", "Not Submitted", "Not Assessed Yet", "Incomplete", "N/A", ""}
    for t in tasks:
        assert t["status"] in valid, f"Unknown status: {t['status']}"


def test_parse_tasks_teacher_comment():
    html = load("tasks_physics.html")
    tasks = parse_tasks(html)
    tasks_with_comment = [t for t in tasks if t["teacher_comment"]]
    # Physics class should have some teacher comments
    assert len(tasks_with_comment) > 0


# ---------------------------------------------------------------------------
# Task detail
# ---------------------------------------------------------------------------

def test_parse_task_detail_structure():
    html = load("task_detail_history.html")
    detail = parse_task_detail(html, "12905566", "47408140")
    assert "description" in detail
    assert "text" in detail["description"]
    assert "links" in detail["description"]
    assert "embedded_files" in detail["description"]
    assert "submitted_files" in detail
    assert "task_history" in detail


def test_parse_task_detail_with_gdocs_link():
    html = load("task_detail_digital_design.html")
    detail = parse_task_detail(html, "12734244", "47590596")
    links = detail["description"]["links"]
    google_links = [l for l in links if "google.com" in l["url"]]
    assert len(google_links) > 0, "Should find Google Docs/Slides link in description"


def test_parse_task_detail_with_embedded_file():
    html = load("task_detail_english.html")
    detail = parse_task_detail(html, "12905672", "46880178")
    # English task has a PDF embedded in description
    assert len(detail["description"]["embedded_files"]) > 0 or len(detail["description"]["text"]) > 0


def test_parse_task_detail_feedback_token():
    html = load("task_detail_history.html")
    detail = parse_task_detail(html, "12905566", "47408140")
    submitted = detail["submitted_files"]
    if submitted:
        # At least one submitted file should have a feedback token
        tokens = [f["teacher_feedback_token"] for f in submitted if f["teacher_feedback_token"]]
        assert len(tokens) > 0


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def test_parse_files_returns_list():
    html = load("files_theatre.html")
    files = parse_files(html)
    assert isinstance(files, list)


def test_parse_files_fields():
    html = load("files_theatre.html")
    files = parse_files(html)
    assert files, "fixture should contain class files"
    f = files[0]
    assert "name" in f
    assert "size" in f
    # Uploader must be extracted from the "by NAME" label (regression: was always "")
    assert f["uploaded_by"] == "Gurami Ghonghadze"
    # uploaded_at must be a friendly local string, not the raw UTC ISO
    assert re.match(r"^[A-Z][a-z]{2} \d", f["uploaded_at"])
    assert "T" not in f["uploaded_at"] and "Z" not in f["uploaded_at"]


def test_parse_files_handles_escaped_page():
    # Chemistry's files page double-escapes its content: data-ec3-info is wrapped
    # in \'...\' with doubled backslashes, and the "by NAME" label leaks escape
    # artifacts. Regression for get_files silently returning [] on such pages.
    html = load("files_chemistry.html")
    files = parse_files(html)
    assert len(files) == 10
    f = files[0]
    assert f["name"] == "Chemistry_MYP.pdf"
    assert f["uploaded_by"] == "Nino Kavtaradze"      # not corrupted/escaped
    assert "<" not in f["uploaded_by"] and "\\" not in f["uploaded_by"]
    assert re.match(r"^[A-Z][a-z]{2} \d", f["uploaded_at"])
    # download URL must be usable, not double-escaped (& instead of &)
    assert f["url"].startswith("http") and "\\u" not in f["url"]


# ---------------------------------------------------------------------------
# Journal
# ---------------------------------------------------------------------------

def test_parse_journal_returns_list():
    html = load("journal_theatre.html")
    entries = parse_journal(html)
    assert isinstance(entries, list)


def test_parse_journal_fields():
    html = load("journal_theatre.html")
    entries = parse_journal(html)
    if entries:
        e = entries[0]
        assert "date" in e
        assert "is_read_only" in e
        assert "files" in e


# ---------------------------------------------------------------------------
# Timetable
# ---------------------------------------------------------------------------

def test_parse_timetable_returns_list():
    html = load("timetable.html")
    slots = parse_timetable(html)
    assert isinstance(slots, list)


def test_parse_timetable_fields():
    html = load("timetable.html")
    slots = parse_timetable(html)
    if slots:
        s = slots[0]
        assert "period" in s
        assert "day" in s
        assert "class_name" in s
