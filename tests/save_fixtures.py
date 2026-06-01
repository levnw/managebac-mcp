"""
Saves raw HTML pages from ManageBac to tests/fixtures/ for unit testing.
Run once: python tests/save_fixtures.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from managebac_mcp.auth import authed_get, get_client, login

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURES.mkdir(exist_ok=True)

PAGES = {
    "classes_my.html": "/student/classes/my",
    "timetable.html": "/student/timetables",
    "tasks_history.html": "/student/classes/12905566/core_tasks",
    "tasks_physics.html": "/student/classes/12863630/core_tasks",
    "tasks_biology.html": "/student/classes/12900718/core_tasks",
    "task_detail_history.html": "/student/classes/12905566/core_tasks/47408140",
    "task_detail_digital_design.html": "/student/classes/12734244/core_tasks/47590596",
    "task_detail_english.html": "/student/classes/12905672/core_tasks/46880178",
    "files_history.html": "/student/classes/12905566/files",
    "files_theatre.html": "/student/classes/12734216/files",
    "journal_theatre.html": "/student/classes/12734216/learner_portfolio/reflections",
}


async def main():
    print("Logging in...")
    async with await get_client() as client:
        await login(client)
        print("Logged in. Saving fixtures...")
        for filename, path in PAGES.items():
            r = await authed_get(client, path)
            out = FIXTURES / filename
            out.write_text(r.text, encoding="utf-8")
            print(f"  ✓ {filename} ({len(r.text):,} bytes)")

    print(f"\nAll fixtures saved to {FIXTURES}")


if __name__ == "__main__":
    asyncio.run(main())
