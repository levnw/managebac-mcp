"""Save clearly labelled synthetic examples using the actual account-scoped pipeline.

No login, external requests or real student data. Run from Working with the project Python.
"""
import asyncio
from pathlib import Path
import sys
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.session import ToolSession

CASES = [
    ('get_units', {'class_id': '10'}, '/student/classes/10/units', 'units'),
    ('get_unit', {'class_id': '10', 'unit_id': '7'}, '/student/classes/10/units/7/popup', 'unit'),
    ('get_journal', {'class_id': '10'}, '/student/classes/10/learner_portfolio/reflections', 'journal'),
    ('get_discussions', {'class_id': '10', 'task_id': '11'}, '/student/classes/10/core_tasks/11/discussions', 'discussions'),
    ('get_timetable', {}, '/student/timetables', 'timetable'),
    ('get_upcoming', {}, '/student/tasks_and_deadlines?view=upcoming', 'upcoming'),
    ('search_tasks', {'class_ids': ['10'], 'tag': 'Homework'}, '/student/classes/10/core_tasks', 'grades'),
    ('get_grades', {'class_id': '10'}, '/student/classes/10/core_tasks', 'grades'),
]


async def main():
    pages = {path: (ROOT / 'tests/fixtures/catalogue' / (fixture + '.html')).read_text()
             for _, _, path, fixture in CASES}
    def respond(request):
        assert request.method == 'GET' and request.url.host == 'es.managebac.com'
        return httpx.Response(200, text=pages[request.url.raw_path.decode()], headers={'content-type': 'text/html'})
    output = ROOT / 'Test Reports' / 'Synthetic Catalogue Examples'
    session = ToolSession('https://es.managebac.com', {},
                          lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)), True, output)
    for name, args, _, _ in CASES:
        result = await session.call(name, args)
        if 'error' in result: raise RuntimeError(f"Synthetic {name}: {result['error']['code']}")
        print(f'Synthetic {name}: exported')
    print(output)


if __name__ == '__main__': asyncio.run(main())
