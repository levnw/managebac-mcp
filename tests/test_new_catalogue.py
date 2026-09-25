"""Synthetic legacy-layout contracts, not evidence of current live compatibility."""
import json
from pathlib import Path
import httpx
import pytest
from jsonschema import validate
from tools.catalogue import TOOLS, invoke
from tools.session import ToolSession
from sources.managebac.pages import destination
from onboarding.transport import USER_AGENT
from onboarding.transport import FlowError, Transport

ORIGIN = 'https://es.managebac.com'
ROOT = '/student/classes/10'
def fixture(name):
    return (Path(__file__).parent / 'fixtures/catalogue' / (name + '.html')).read_text()

TIMETABLE, TASK = [fixture(name) for name in ('timetable', 'task_list')]

CASES = [
    ('get_timetable', {}, '/student/timetables', TIMETABLE, 'slots'),
    ('get_tasks', {'class_ids': ['10'], 'tag': 'Homework'}, ROOT + '/core_tasks', TASK, 'tasks'),
]


async def call(name, args, pages, seen=None):
    def handle(request):
        path = request.url.raw_path.decode()
        if seen is not None: seen.append(path)
        assert request.method == 'GET'
        assert request.url.host == 'es.managebac.com'
        response = pages[path]
        return response if isinstance(response, httpx.Response) else httpx.Response(200, text=response, headers={'content-type': 'text/html'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        return await invoke(name, client, ORIGIN, args)


@pytest.mark.parametrize('name,args,path,html,key', CASES)
async def test_success_exact_schema_no_unrelated_requests(name, args, path, html, key):
    seen = []
    result = await call(name, args, {path: html}, seen)
    assert 'error' not in result, result
    validate(result, TOOLS[name].DEFINITION.outputSchema)
    assert result[key]
    assert seen == [path]
    assert not {'warnings', 'assets', 'history', 'isError'} & result.keys()


@pytest.mark.parametrize('name,args,path,html,key', CASES)
@pytest.mark.parametrize('status,code', [(401, 'session_expired'), (403, 'access_denied'), (404, 'not_found'), (429, 'rate_limited')])
async def test_upstream_errors_never_empty(name, args, path, html, key, status, code):
    result = await call(name, args, {path: httpx.Response(status)})
    assert set(result) == {'error'}
    assert result['error']['code'] == code


@pytest.mark.parametrize('name,args,path,html,key', CASES)
async def test_unknown_layout_never_empty(name, args, path, html, key):
    result = await call(name, args, {path: '<main>Unrecognized page</main>'})
    assert result['error']['code'] == 'layout_changed'


async def test_task_filters_apply_together():
    both = TASK.replace('Tasks (1)', 'Tasks (2)').replace('</main>',
        '<div class="fusion-card-item"><a href="/student/classes/10/core_tasks/12">Essay draft</a>'
        '<span class="task-status">Pending</span></div></main>')
    pages = {ROOT + '/core_tasks': both}
    ids = lambda result: [t['id'] for t in result['tasks']]
    assert ids(await call('get_tasks', {'class_ids': ['10']}, pages)) == ['11', '12']
    assert ids(await call('get_tasks', {'class_ids': ['10'], 'tag': 'homework'}, pages)) == ['11']
    assert ids(await call('get_tasks', {'class_ids': ['10'], 'title': 'essay'}, pages)) == ['12']
    assert ids(await call('get_tasks', {'class_ids': ['10'], 'status': 'pending'}, pages)) == ['12']
    assert ids(await call('get_tasks', {'class_ids': ['10'], 'title': 'essay', 'tag': 'Homework'}, pages)) == []


async def test_several_classes_are_complete_or_the_call_fails():
    pages = {ROOT + '/core_tasks': TASK, '/student/classes/20/core_tasks': TASK.replace('/10/', '/20/')}
    result = await call('get_tasks', {'class_ids': ['10', '20']}, pages)
    assert [(t['class_id'], t['id']) for t in result['tasks']] == [('10', '11'), ('20', '11')]
    assert [c['class_id'] for c in result['classes']] == ['10', '20']
    pages['/student/classes/20/core_tasks'] = httpx.Response(403)
    assert set(await call('get_tasks', {'class_ids': ['10', '20']}, pages)) == {'error'}
    for args in ({'class_ids': []}, {'class_ids': ['10', '10']}, {'class_ids': ['../x']},
                 {'class_ids': [str(n) for n in range(11)]}, {'class_id': '10'}):
        assert (await call('get_tasks', args, {}))['error']['code'] == 'invalid_arguments'


@pytest.mark.parametrize('path', ['/logout', '//evil.test/a', '/student/classes/10/../logout',
                                  '/student/classes/10/core_tasks#x', '/student/classes/10/%2e%2e/logout'])
def test_transport_destination_rejects_unscoped_paths(path):
    with pytest.raises(FlowError): destination(ORIGIN, path)


async def test_user_agent_consistent_and_report_all_tools(tmp_path):
    async with Transport().client() as client:
        assert client.headers['user-agent'] == USER_AGENT
    for name, args, path, html, _ in CASES:
        def factory():
            return httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=html, headers={'content-type': 'text/html'})))
        session = ToolSession(ORIGIN, {}, factory, True, tmp_path / name)
        result = await session.call(name, args)
        exports = list((tmp_path / name).glob('*/response.json'))
        assert len(exports) == 1
        assert json.loads(exports[0].read_text()) == result


def test_catalogue_has_one_tool_per_capability():
    assert set(TOOLS) == {'get_classes', 'get_tasks', 'get_files', 'get_timetable'}


async def test_redirect_does_not_discard_verified_account_session():
    seen = []
    def handler(request):
        seen.append(request.url.path)
        if request.url.path == '/student/profile':
            return httpx.Response(200, text='<a class="profile-link" href="/student/profile" aria-label="Account"></a><a class="logout" href="/logout">Sign out</a>')
        return httpx.Response(302, headers={'location': '/login'})
    session = ToolSession(ORIGIN, {'session': 'test-only'},
                          lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    result = await session.call('get_tasks', {'class_ids': ['10']})
    assert result['error']['code'] == 'page_unavailable_authenticated'
    assert seen == [ROOT + '/core_tasks', '/student/profile']
    assert session.cookies.get('session') == 'test-only'


@pytest.mark.parametrize('name,args,path,message,key', [
    ('get_tasks', {'class_ids': ['10']}, ROOT + '/core_tasks', 'No tasks', 'tasks'),
])
async def test_explicit_empty_states(name, args, path, message, key):
    result = await call(name, args, {path: '<div class="empty-state">' + message + '</div>'})
    assert result[key] == []


async def test_timetable_does_not_drop_unknown_nonempty_cells():
    html = TIMETABLE.replace('class="f-timetable-item"', 'class="new-layout-item"')
    result = await call('get_timetable', {}, {'/student/timetables': html})
    assert result['error']['code'] == 'layout_changed'


@pytest.mark.parametrize('name,args,path,html,key', CASES)
async def test_canonical_mismatch_is_rejected(name, args, path, html, key):
    result = await call(name, args, {path: '<link rel="canonical" href="/student/classes/999/units">' + html})
    assert result['error']['code'] == 'identity_mismatch'


async def test_new_tools_through_actual_mcp_protocol():
    from tools.server import create_server
    from mcp.shared.memory import create_connected_server_and_client_session
    pages = {path: html for _, _, path, html, _ in CASES}
    async def scoped(name, arguments):
        return await call(name, arguments, pages)
    server = create_server(scoped)
    async with create_connected_server_and_client_session(server) as session:
        for name, args, _, _, _ in CASES:
            response = await session.call_tool(name, args)
            assert not response.isError, name
            assert response.content == []
            assert response.structuredContent == await scoped(name, args)
