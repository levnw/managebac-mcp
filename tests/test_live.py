"""
Integration tests — hit real ManageBac.
Skipped by default. Run with: pytest -m slow
"""
import pytest
from managebac_mcp.scraper import (
    fetch_classes, fetch_timetable, fetch_tasks,
    fetch_task_detail, fetch_files, fetch_journal, find_task,
)
from managebac_mcp import cache


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear_all()
    yield


@pytest.mark.slow
@pytest.mark.asyncio
async def test_fetch_classes():
    classes = await fetch_classes()
    assert len(classes) > 5
    ids = [c["id"] for c in classes]
    assert "12905566" in ids  # History


@pytest.mark.slow
@pytest.mark.asyncio
async def test_fetch_timetable():
    slots = await fetch_timetable()
    assert len(slots) > 0
    assert any(s["class_name"] for s in slots)


@pytest.mark.slow
@pytest.mark.asyncio
async def test_fetch_tasks_history():
    tasks = await fetch_tasks("12905566")
    assert len(tasks) > 0
    assert all("id" in t for t in tasks)
    assert all("title" in t for t in tasks)


@pytest.mark.slow
@pytest.mark.asyncio
async def test_fetch_tasks_uses_cache():
    await fetch_tasks("12905566")
    cached = cache.get("get_tasks:12905566")
    assert cached is not None


@pytest.mark.slow
@pytest.mark.asyncio
async def test_fetch_task_detail():
    detail = await fetch_task_detail("12905566", "47408140")
    assert detail["class_id"] == "12905566"
    assert detail["task_id"] == "47408140"
    assert len(detail["description"]["text"]) > 0


@pytest.mark.slow
@pytest.mark.asyncio
async def test_fetch_task_detail_has_feedback_token():
    detail = await fetch_task_detail("12905566", "47408140")
    tokens = [f["teacher_feedback_token"] for f in detail["submitted_files"] if f["teacher_feedback_token"]]
    assert len(tokens) > 0


@pytest.mark.slow
@pytest.mark.asyncio
async def test_fetch_task_detail_gdocs_link():
    detail = await fetch_task_detail("12734244", "47590596")
    google_links = [l for l in detail["description"]["links"] if "google.com" in l["url"]]
    assert len(google_links) > 0


@pytest.mark.slow
@pytest.mark.asyncio
async def test_find_task_by_url():
    result = await find_task("https://es.managebac.com/student/classes/12905566/core_tasks/47408140")
    assert result is not None
    assert result["task_id"] == "47408140"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_find_task_by_title():
    result = await find_task("Summative Task Unit 3")
    assert result is not None
    assert result["class_id"] == "12905566"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_find_task_not_found():
    result = await find_task("xyzzy task that does not exist anywhere 99999")
    assert result is None


@pytest.mark.slow
@pytest.mark.asyncio
async def test_fetch_files_theatre():
    files = await fetch_files("12734216")
    assert isinstance(files, list)
    assert any("pdf" in f["name"].lower() for f in files)


@pytest.mark.slow
@pytest.mark.asyncio
async def test_fetch_journal_theatre():
    entries = await fetch_journal("12734216")
    assert isinstance(entries, list)
    assert len(entries) > 0


@pytest.mark.slow
@pytest.mark.asyncio
async def test_fetch_journal_no_journal_class():
    # Georgian B has no journal tab
    entries = await fetch_journal("12734067")
    assert entries == []
