"""
Quick smoke test — calls every MCP tool and prints output.
Run: python tests/smoke_test.py
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from managebac_mcp.scraper import (
    fetch_classes, fetch_timetable, fetch_tasks,
    fetch_task_detail, fetch_files, fetch_journal, find_task,
)


def show(label: str, data: object) -> None:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print('='*60)
    print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])
    if len(json.dumps(data)) > 2000:
        print("  ... (truncated)")


async def main():
    print("Running ManageBac MCP smoke test...\n")

    print("1. get_classes()")
    classes = await fetch_classes()
    show("get_classes", classes)
    print(f"   → {len(classes)} classes found")

    print("\n2. get_timetable()")
    timetable = await fetch_timetable()
    show("get_timetable (first 3 slots)", timetable[:3])

    # Use History class for remaining tests
    history_id = "12905566"

    print(f"\n3. get_tasks(class_id={history_id})")
    tasks = await fetch_tasks(history_id)
    show("get_tasks — first 2 tasks", tasks[:2])
    print(f"   → {len(tasks)} tasks found")

    print(f"\n4. get_task_detail(class_id={history_id}, task_id=47408140)")
    detail = await fetch_task_detail(history_id, "47408140")
    show("get_task_detail", detail)

    print(f"\n5. get_files(class_id={history_id})")
    files = await fetch_files(history_id)
    show("get_files", files)

    print("\n6. get_journal(class_id=12734216)  [Theatre]")
    journal = await fetch_journal("12734216")
    show("get_journal", journal)

    print("\n7. find_task(url)")
    found = await find_task("https://es.managebac.com/student/classes/12905566/core_tasks/47408140")
    show("find_task by URL", found)

    print("\n8. find_task(title)")
    found2 = await find_task("Summative Task Unit 3")
    show("find_task by title", found2)

    print("\n\nSmoke test complete.")


if __name__ == "__main__":
    asyncio.run(main())
