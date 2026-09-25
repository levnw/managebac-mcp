"""Export synthetic examples through the real tool pipeline, without network/login.

Run from Working: python scripts/replay_tools.py
These reports are fixture demonstrations, never evidence of live extraction.
"""
import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
from tools.session import ToolSession


async def main():
    fixtures = ROOT / 'tests' / 'fixtures'
    pages = {
        '/student/classes/10/core_tasks': 'tasks/page1.html',
        '/student/classes/10/core_tasks?page=2': 'tasks/page2.html',
        '/student/classes/10/core_tasks/101': 'tasks/detail.html',
        '/student/classes/10/files': 'files/root.html',
        '/student/classes/10/files/page/2': 'files/root2.html',
        '/student/classes/10/files/folder/701': 'files/folder.html',
        '/student/classes/10/files/folder/702': 'files/empty.html',
    }

    def respond(request):
        if request.method != 'GET' or request.url.host != 'es.managebac.com':
            raise AssertionError('Unexpected fixture request')
        name = pages[request.url.raw_path.decode()]
        return httpx.Response(200, text=(fixtures / name).read_text(),
                              headers={'content-type': 'text/html'})

    output = ROOT / 'Test Reports' / 'Synthetic Examples'
    session = ToolSession('https://es.managebac.com', {},
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        developer_mode=True, report_directory=output)
    for name, arguments in [
        ('get_tasks', {'class_id': '10'}),
        ('get_task', {'class_id': '10', 'task_id': '101'}),
        ('get_class_files', {'class_id': '10'}),
        ('get_class_files', {'class_id': '10', 'recursive': True}),
    ]:
        response = await session.call(name, arguments)
        if 'error' in response:
            raise RuntimeError(f"Synthetic {name} failed: {response['error']['code']}")
        print(f'Synthetic {name}: exported')
    print(f'Open the response.json files under: {output}')


if __name__ == '__main__':
    asyncio.run(main())
