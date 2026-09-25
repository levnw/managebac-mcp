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

UNIT, TIMETABLE, UPCOMING, TASK = [fixture(name) for name in
    ('units', 'timetable', 'upcoming', 'grades')]

CASES = [
    ('get_units', {'class_id': '10'}, ROOT + '/units', UNIT, 'units'),
    ('get_unit', {'class_id': '10', 'unit_id': '7'}, ROOT + '/units/7/popup',
     fixture('unit'), 'unit'),
    ('get_timetable', {}, '/student/timetables', TIMETABLE, 'slots'),
    ('get_upcoming', {}, '/student/tasks_and_deadlines?view=upcoming', UPCOMING, 'tasks'),
    ('search_tasks', {'class_ids': ['10'], 'tag': 'Homework'}, ROOT + '/core_tasks', TASK, 'tasks'),
    ('get_grades', {'class_id': '10'}, ROOT + '/core_tasks', TASK, 'assessments'),
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


async def test_rich_unit_content():
    name, args, path, html, _ = CASES[1]
    result = (await call(name, args, {path: html}))['unit']['sections'][0]
    assert result['title'] == 'Inquiry'
    assert result['tables'][0]['rows'][0][0]['text'] == 'Cell'
    assert result['media'][0]['url'] == ORIGIN + '/diagram.png'


async def test_upcoming_retains_view_and_rejects_changed_filter():
    path = '/student/tasks_and_deadlines?view=overdue'
    result = await call('get_upcoming', {'view': 'overdue'}, {
        path: UPCOMING + '<a rel="next" href="?page=2">Next</a>',
        path + '&page=2': UPCOMING.replace('/11', '/12')})
    assert [r['id'] for r in result['tasks']] == ['11', '12']
    result = await call('get_upcoming', {'view': 'overdue'}, {
        path: UPCOMING + '<a rel="next" href="?view=past&page=2">Next</a>'})
    assert result['error']['code'] == 'invalid_pagination'


async def test_search_no_silent_partial_and_scope_validation():
    result = await call('search_tasks', {'class_ids': ['10', '20'], 'query': 'Lab'}, {
        ROOT + '/core_tasks': TASK, '/student/classes/20/core_tasks': httpx.Response(403)})
    assert set(result) == {'error'}
    for args in ({'class_ids': ['10']}, {'class_ids': ['10', '10'], 'query': 'Lab'},
                 {'class_ids': ['../x'], 'query': 'Lab'}, {'class_ids': [], 'tag': 'Test'}):
        result = await call('search_tasks', args, {})
        assert result['error']['code'] == 'invalid_arguments'


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
    assert set(TOOLS) == {'get_classes', 'get_tasks', 'get_task', 'get_class_files', 'get_units',
                          'get_unit', 'get_timetable',
                          'get_upcoming', 'search_tasks', 'get_grades'}


async def test_grade_absence_is_no_published_grade_on_this_page():
    html = '<main><h2>Tasks (1)</h2><div class="fusion-card-item"><a href="/student/classes/10/core_tasks/11">Lab</a></div></main>'
    result = await call('get_grades', {'class_id': '10'}, {ROOT + '/core_tasks': html})
    assert result['assessments'] == []


async def test_redirect_does_not_discard_verified_account_session():
    seen = []
    def handler(request):
        seen.append(request.url.path)
        if request.url.path == '/student/profile':
            return httpx.Response(200, text='<a class="profile-link" href="/student/profile" aria-label="Account"></a><a class="logout" href="/logout">Sign out</a>')
        return httpx.Response(302, headers={'location': '/login'})
    session = ToolSession(ORIGIN, {'session': 'test-only'},
                          lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    result = await session.call('get_units', {'class_id': '10'})
    assert result['error']['code'] == 'page_unavailable_authenticated'
    assert seen == [ROOT + '/units', '/student/profile']
    assert session.cookies.get('session') == 'test-only'


@pytest.mark.parametrize('name,args,path,message,key', [
    ('get_units', {'class_id': '10'}, ROOT + '/units', 'No units', 'units'),
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


async def test_second_units_page_is_not_fetched_as_details():
    path = ROOT + '/units'
    seen = []
    result = await call('get_units', {'class_id': '10'}, {
        path: UNIT + '<a rel="next" href="?page=2">Next</a>',
        path + '?page=2': UNIT.replace('_7"', '_8"')}, seen)
    assert [u['id'] for u in result['units']] == ['7', '8']
    assert seen == [path, path + '?page=2']


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
