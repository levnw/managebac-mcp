"""get_files everywhere layer: every class's Files and every task's attachments in one call."""
import asyncio
from pathlib import Path
import httpx
import pytest
from jsonschema import validate
from tools.catalogue import TOOLS, invoke
import tools.files

ORIGIN = 'https://es.managebac.com'
FIX = Path(__file__).parent / 'fixtures'
EMPTY_FILES = ('<main><section class="f-layout-main__content f-surface"><h2>Files</h2><div class="h4">No files</div>'
               '<p>No files have been uploaded yet.</p></section></main>')
PAGES = {
    '/student/classes/my': '<h2>My Classes (2)</h2>'
        '<div class="f-class-tile"><div class="f-tile__title"><a href="/student/classes/10">Biology</a></div></div>'
        '<div class="f-class-tile"><div class="f-tile__title"><a href="/student/classes/20">History</a></div></div>',
    '/student/classes/10/files': (FIX / 'files/root.html').read_text(),
    '/student/classes/10/files/page/2': (FIX / 'files/root2.html').read_text(),
    '/student/classes/10/files/folder/701': (FIX / 'files/folder.html').read_text(),
    '/student/classes/10/files/folder/702': (FIX / 'files/empty.html').read_text(),
    '/student/classes/10/core_tasks': '<main><h2>Tasks (2)</h2>'
        '<div class="fusion-card-item"><a href="/student/classes/10/core_tasks/101">Lab report</a></div>'
        '<div class="fusion-card-item"><a href="/student/classes/10/core_tasks/102">Quiz</a></div></main>',
    '/student/classes/10/core_tasks/101': (FIX / 'tasks/detail.html').read_text(),
    '/student/classes/10/core_tasks/102': (FIX / 'tasks/detail.html').read_text().replace('/core_tasks/101', '/core_tasks/102').replace('data-task-id="101"', 'data-task-id="102"'),
    '/student/classes/20/files': EMPTY_FILES,
    '/student/classes/20/core_tasks': '<main><h2>All Tasks</h2></main>',
}


async def call(args, pages=PAGES, delay=0.0, seen=None):
    active = [0, 0]
    async def handle(request):
        path = request.url.raw_path.decode()
        if seen is not None: seen.append(path)
        active[0] += 1; active[1] = max(active[1], active[0])
        try:
            if delay: await asyncio.sleep(delay)
            value = pages[path]
            return value if isinstance(value, httpx.Response) else httpx.Response(200, text=value, headers={'content-type': 'text/html'})
        finally:
            active[0] -= 1
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await invoke('get_files', client, ORIGIN, args)
    return result, active[1]


async def test_one_call_lists_class_files_and_task_attachments_grouped():
    result, _ = await call({})
    validate(result, TOOLS['get_files'].DEFINITION.outputSchema)
    assert 'incomplete' not in result
    biology, history = result['classes']
    assert (biology['class_id'], biology['name']) == ('10', 'Biology') and history['name'] == 'History'
    names = {f['name'] for f in biology['files']}
    assert {'Revision.pdf', 'Lab notes.txt'} <= names            # root, second page and a subfolder
    assert next(f for f in biology['files'] if f['name'] == 'Lab notes.txt')['folder_id'] == '701'
    assert biology['tasks_checked'] == 2 and [t['task_id'] for t in biology['tasks']] == ['101', '102']
    sources = {f['source'] for f in biology['tasks'][0]['files']}
    assert sources == {'description', 'teacher_resource', 'submission'}
    assert history == {'class_id': '20', 'name': 'History', 'url': ORIGIN + '/student/classes/20/files',
                       'files': [], 'tasks_checked': 0, 'tasks': []}
    assert result['file_count'] == len(biology['files']) + sum(len(t['files']) for t in biology['tasks'])


async def test_file_ids_match_the_single_class_layers_so_open_works():
    result, _ = await call({})
    task, _ = await call({'class_id': '10', 'task_id': '101'})
    assert {f['file_id'] for f in result['classes'][0]['tasks'][0]['files'] if 'file_id' in f} == \
           {f['file_id'] for f in task['files'] if 'file_id' in f}


async def test_pages_are_fetched_in_parallel_but_never_more_than_the_limit():
    seen = []
    result, most = await call({}, delay=0.05, seen=seen)
    assert 'incomplete' not in result
    assert 1 < most <= tools.files.PARALLEL_PAGES
    assert len(seen) == len(set(seen))                           # each page read once


async def test_an_unreadable_task_is_reported_and_the_rest_is_kept():
    pages = {**PAGES, '/student/classes/10/core_tasks/102': httpx.Response(404)}
    result, _ = await call({}, pages)
    [missing] = result['incomplete']
    assert missing['class_id'] == '10' and missing['task_id'] == '102' and missing['part'] == 'task'
    assert [t['task_id'] for t in result['classes'][0]['tasks']] == ['101']
    validate(result, TOOLS['get_files'].DEFINITION.outputSchema)


async def test_signing_out_midway_fails_the_whole_call():
    pages = {**PAGES, '/student/classes/10/core_tasks/102': httpx.Response(302, headers={'location': '/login'})}
    result, _ = await call({}, pages)
    assert result['error']['code'] == 'session_expired'


async def test_past_the_time_budget_parts_are_listed_not_silently_dropped(monkeypatch):
    monkeypatch.setattr(tools.files, 'EVERYWHERE_SECONDS', -1)
    result, _ = await call({})
    assert {p['error']['code'] for p in result['incomplete']} == {'time_budget'}
    assert {(p['class_id'], p['part']) for p in result['incomplete']} == {
        ('10', 'class_files'), ('10', 'task_list'), ('20', 'class_files'), ('20', 'task_list')}


async def test_class_ids_limit_the_scope_and_unknown_classes_are_refused():
    seen = []
    result, _ = await call({'class_ids': ['20']}, seen=seen)
    assert [c['class_id'] for c in result['classes']] == ['20']
    assert not any(path.startswith('/student/classes/10') for path in seen)
    result, _ = await call({'class_ids': ['99']})
    assert result['error']['code'] == 'class_not_found'


async def test_date_filter_applies_everywhere():
    result, _ = await call({'date_from': '2100-01-01'})
    assert result['file_count'] == 0
    assert all(u['class_id'] == '10' for u in result.get('undated', []))


@pytest.mark.parametrize('args', [{'open': ['f_0000000000000000']}, {'task_id': '101'}, {'recursive': True},
                                  {'class_id': '10', 'class_ids': ['10']}, {'class_ids': ['10', '10']}])
async def test_everywhere_arguments_are_strict(args):
    result, _ = await call(args)
    assert result['error']['code'] == 'invalid_arguments'
