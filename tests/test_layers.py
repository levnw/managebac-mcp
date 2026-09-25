"""Layered tools: get_tasks list/detail and get_files class/task."""
from pathlib import Path
import httpx
from jsonschema import validate
from tools.catalogue import TOOLS, invoke

ORIGIN = 'https://es.managebac.com'
DETAIL = (Path(__file__).parent / 'fixtures/tasks/detail.html').read_text()
TASK_PATH = '/student/classes/10/core_tasks/101'


async def call(name, args, pages):
    def handle(request):
        response = pages[request.url.raw_path.decode()]
        return response if isinstance(response, httpx.Response) else httpx.Response(
            200, text=response, headers={'content-type': 'text/html'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        return await invoke(name, client, ORIGIN, args)


async def test_detail_layer_opens_several_tasks_and_reports_each_failure():
    pages = {TASK_PATH: DETAIL, '/student/classes/10/core_tasks/102': '<main>Unrecognised</main>'}
    result = await call('get_tasks', {'open': [{'class_id': '10', 'task_id': '101'},
                                               {'class_id': '10', 'task_id': '102'}]}, pages)
    ok, failed = result['tasks']
    assert ok['id'] == '101' and isinstance(ok['description'], str)
    assert failed == {'class_id': '10', 'task_id': '102',
                      'error': {'code': failed['error']['code'], 'message': failed['error']['message']}}
    validate(result, TOOLS['get_tasks'].DEFINITION.outputSchema)


async def test_signed_out_session_fails_the_whole_detail_call():
    pages = {TASK_PATH: DETAIL, '/student/classes/10/core_tasks/102': httpx.Response(302, headers={'location': '/login'})}
    result = await call('get_tasks', {'open': [{'class_id': '10', 'task_id': '101'},
                                               {'class_id': '10', 'task_id': '102'}]}, pages)
    assert result == {'error': result['error']} and result['error']['code'] == 'session_expired'


async def test_one_layer_per_call():
    for args in ({}, {'class_ids': ['10'], 'open': [{'class_id': '10', 'task_id': '1'}]},
                 {'open': [{'class_id': '10', 'task_id': '1'}], 'status': 'Pending'},
                 {'open': [{'class_id': '10', 'task_id': '1'}] * 2},
                 {'open': [{'class_id': '10', 'task_id': str(n)} for n in range(11)]}):
        assert (await call('get_tasks', args, {}))['error']['code'] == 'invalid_arguments'


async def test_task_layer_lists_attachments_by_source():
    result = await call('get_files', {'class_id': '10', 'task_id': '101'}, {TASK_PATH: DETAIL})
    validate(result, TOOLS['get_files'].DEFINITION.outputSchema)
    assert result['url'] == ORIGIN + TASK_PATH and result['task_id'] == '101'
    by_source = {}
    for item in result['files']:
        by_source.setdefault(item['source'], []).append(item)
        assert item['kind'] in ('file', 'image', 'preview')
    assert [f['name'] for f in by_source['description']] == ['Lab instructions.pdf']
    assert by_source['teacher_resource'][0]['resource_title'] == 'Worksheet'
    assert by_source['submission'][0]['name'] == 'My answer.pdf'
    assert all(f['file_id'].startswith('f_') for f in result['files'])


async def test_same_file_has_the_same_file_id_in_task_detail_and_task_files():
    detail = (await call('get_tasks', {'open': [{'class_id': '10', 'task_id': '101'}]}, {TASK_PATH: DETAIL}))['tasks'][0]
    files = (await call('get_files', {'class_id': '10', 'task_id': '101'}, {TASK_PATH: DETAIL}))['files']
    assert {m['file_id'] for m in detail['media'] if m['kind'] == 'file'} <= {f['file_id'] for f in files}


async def test_folder_options_do_not_apply_to_a_task():
    for args in ({'class_id': '10', 'task_id': '101', 'folder_id': '7'}, {'class_id': '10', 'task_id': '101', 'recursive': True}):
        assert (await call('get_files', args, {}))['error']['code'] == 'invalid_arguments'
