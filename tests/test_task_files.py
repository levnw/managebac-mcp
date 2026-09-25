"""Narrow requests, preservation, bounded traversal and honest failure semantics."""
import json
from pathlib import Path
import pytest
import httpx
from jsonschema import validate

from tools.tasks import get_tasks, DEFINITION as TASKS
from tools.files import get_files as get_class_files, DEFINITION as FILES


async def get_task(client, origin, args):
    """Open one task through get_tasks' detail layer (the retired get_task's shape, for these tests)."""
    result = await get_tasks(client, origin, {'open': [args]})
    if 'error' in result: return result
    item = result['tasks'][0]
    return {'error': item['error']} if 'error' in item else {'task': item}
from tools.session import ToolSession
from tools.catalogue import definitions
from sources.managebac.task_detail import parse_detail
from tools.task_output import compact_task
from sources.managebac.files import file_info
from sources.managebac.rich_text import RichText
from onboarding.transport import FlowError
from bs4 import BeautifulSoup

FIXTURES = Path(__file__).parent / 'fixtures'
ORIGIN = 'https://es.managebac.com'


def test_editor_css_emphasis_and_srcset_only_image():
    rich = RichText(ORIGIN, ORIGIN + '/student/classes/10/core_tasks/101')
    result = rich.parse(BeautifulSoup('<div><span style="font-weight:700;font-style:italic">Important</span>'
        '<img srcset="/small.png 1x, /large.png 2x" alt="Diagram"></div>', 'html.parser').div)
    assert result[0]['marks'] == ['bold', 'italic']
    assert len(result[1]['variants']) == 2
    assert 'unavailable' not in result[1]


@pytest.mark.asyncio
async def test_named_mcp_registration_uses_exact_payload_and_errors():
    from tools.server import create_server
    from tools.catalogue import invoke
    from mcp.shared.memory import create_connected_server_and_client_session
    seen = []
    async with client_for({'/student/classes/10/core_tasks/101': fixture('tasks/detail.html')}, seen) as client:
        async def scoped(name, arguments):
            return await invoke(name, client, ORIGIN, arguments)
        server = create_server(scoped)
        async with create_connected_server_and_client_session(server) as session:
            listing = await session.list_tools()
            from tools.catalogue import TOOLS
            assert {t.name for t in listing.tools} == set(TOOLS)
            response = await session.call_tool('get_tasks', {'open': [{'class_id': '10', 'task_id': '101'}]})
            assert response.content == [] and not response.isError
            assert response.structuredContent == {'tasks': [compact_task(parse_detail(fixture('tasks/detail.html'), ORIGIN, '10', '101'))]}
            invalid = await session.call_tool('get_tasks', {'open': [{'class_id': '../other', 'task_id': '101'}]})
            assert invalid.isError
            assert len(seen) == 1


def fixture(name):
    return (FIXTURES / name).read_text()


def client_for(pages, requests):
    def handle(request):
        requests.append(str(request.url))
        assert request.method == 'GET'
        path = request.url.raw_path.decode()
        assert path in pages, f'Unexpected request: {path}'
        value = pages[path]
        return value if isinstance(value, httpx.Response) else httpx.Response(200, text=value, headers={'content-type': 'text/html'})
    return httpx.AsyncClient(transport=httpx.MockTransport(handle), follow_redirects=True)


def nodes(value):
    if isinstance(value, dict):
        yield value
        for v in value.values(): yield from nodes(v)
    elif isinstance(value, list):
        for v in value: yield from nodes(v)


@pytest.mark.asyncio
async def test_task_list_is_compact_and_follows_only_its_pages():
    seen = []
    async with client_for({'/student/classes/10/core_tasks': fixture('tasks/page1.html'),
                           '/student/classes/10/core_tasks?page=2': fixture('tasks/page2.html')}, seen) as c:
        result = await get_tasks(c, ORIGIN, {'class_ids': ['10']})
    assert len(seen) == 2
    assert result['classes'] == [{'class_id': '10', 'url': ORIGIN + '/student/classes/10/core_tasks'}]
    assert seen[0] == result['classes'][0]['url'] != result['tasks'][0]['url']
    assert all(task['class_id'] == '10' for task in result['tasks'])
    assert [r['id'] for r in result['tasks']] == ['101', '102']
    assert result['tasks'][0]['status'] == 'Not Submitted'
    assert result['tasks'][0]['tags'] == ['Criterion A', 'Complete analysis']
    assert 'assessment-comments' not in json.dumps(result)
    assert 'This comment' not in json.dumps(result)
    assert 'warnings' not in result
    validate(result, TASKS.outputSchema)


@pytest.mark.asyncio
async def test_empty_task_list_still_has_list_url():
    seen = []
    async with client_for({'/student/classes/10/core_tasks': '<main><h2>Tasks (0)</h2></main>'}, seen) as client:
        result = await get_tasks(client, ORIGIN, {'class_ids': ['10']})
    assert result == {'classes': [{'class_id': '10', 'url': seen[0]}], 'tasks': []}
    validate(result, TASKS.outputSchema)


@pytest.mark.asyncio
@pytest.mark.parametrize('developer_mode', [False, True])
async def test_missing_task_total_is_diagnostics_only(developer_mode):
    from diagnostics import capture
    seen = []
    pages = {'/student/classes/10/core_tasks': fixture('tasks/page1.html').replace('Tasks (2)', 'Tasks'),
             '/student/classes/10/core_tasks?page=2': fixture('tasks/page2.html').replace('Tasks (2)', 'Tasks')}
    with capture('get_tasks', developer_mode) as report:
        async with client_for(pages, seen) as client:
            result = await get_tasks(client, ORIGIN, {'class_ids': ['10']})
    assert set(result) == {'classes', 'tasks'}
    assert len(result['tasks']) == 2
    assert 'source_total_unavailable' not in json.dumps(result)
    assert 'warnings' not in TASKS.outputSchema['properties']
    assert 'Source total' not in TASKS.description
    validate(result, TASKS.outputSchema)
    if developer_mode:
        assert any(e['stage'] == 'list.source_total_unavailable_pagination_followed' for e in report.events)
    else:
        assert report is None


@pytest.mark.asyncio
async def test_task_detail_preserves_meaning_and_performs_one_request():
    seen = []
    async with client_for({'/student/classes/10/core_tasks/101': fixture('tasks/detail.html')}, seen) as c:
        result = await get_task(c, ORIGIN, {'class_id': '10', 'task_id': '101'})
    assert len(seen) == 1
    assert isinstance(result['task']['description'], str)
    assert 'history' not in result['task'] and 'discussions' not in result['task']
    assert result['task']['submission']['box'] == 'present'
    assert 'teacher_resources' in result['task'] and 'files' in result['task']['submission']
    task = parse_detail(fixture('tasks/detail.html'), ORIGIN, '10', '101')
    tree = list(nodes(task['description']))
    assert {'heading', 'paragraph', 'list', 'list_item', 'quote', 'image', 'caption', 'table',
            'table_row', 'table_cell', 'code_block', 'line_break', 'file', 'link', 'embed', 'math'} <= {n.get('type') for n in tree}
    assert any(n.get('start') == 2 for n in tree)
    assert any(n.get('rowspan') == 2 for n in tree)
    assert any(n.get('marks') == ['bold'] for n in tree)
    assert any(n.get('marks') == ['subscript'] for n in tree)
    assert any(n.get('alt') == 'A beaker warming over a flame' for n in tree)
    assets = {a['ref']: a for a in task['assets']}
    for node in nodes(task):
        if 'ref' in node: assert node['ref'] in assets
    assert len(assets) == len(task['assets'])
    assert task['submissions']['state'] == 'present'
    assert task['resources']['state'] == 'present'
    assert 'discussions' not in task and 'history' not in task
    assert 'My answer.pdf' not in json.dumps(task['resources'])
    assert 'Worksheet.docx' not in json.dumps(task['submissions'])
    assert 'stealSecrets' not in json.dumps(result) and 'javascript:' not in json.dumps(result)
    assert not any('/school-logo' in a['url'] for a in assets.values())
    assert 'warnings' not in task
    validate({'tasks': [result['task']]}, TASKS.outputSchema)


@pytest.mark.asyncio
async def test_files_nonrecursive_reads_root_pages_not_children():
    seen = []
    async with client_for({'/student/classes/10/files': fixture('files/root.html'),
                           '/student/classes/10/files/page/2': fixture('files/root2.html')}, seen) as c:
        result = await get_class_files(c, ORIGIN, {'class_id': '10'})
    assert len(seen) == 2
    assert [f['id'] for f in result['files']] == ['601', '602']
    assert result['files'][0]['size_bytes'] == 0
    assert result['files'][0]['uploaded_by'] == 'Example Teacher'
    assert result['folders'][0]['id'] == '701'
    assert result['recursive'] is False
    validate(result, FILES.outputSchema)


@pytest.mark.asyncio
async def test_recursive_files_preserves_parent_relations():
    seen = []
    async with client_for({'/student/classes/10/files': fixture('files/root.html'),
                           '/student/classes/10/files/page/2': fixture('files/root2.html'),
                           '/student/classes/10/files/folder/701': fixture('files/folder.html'),
                           '/student/classes/10/files/folder/702': fixture('files/empty.html')}, seen) as c:
        result = await get_class_files(c, ORIGIN, {'class_id': '10', 'recursive': True})
    assert len(seen) == 4
    assert len(result['files']) == 3
    assert result['files'][-1]['folder_id'] == '701'
    assert result['folders'][-1]['parent_id'] == '701'


@pytest.mark.asyncio
@pytest.mark.parametrize('status,code', [(401,'session_expired'),(403,'access_denied'),(404,'not_found'),(429,'rate_limited'),(500,'upstream_unavailable')])
async def test_http_errors_are_not_empty_success(status, code):
    seen = []
    async with client_for({'/student/classes/10/core_tasks/101': httpx.Response(status)}, seen) as c:
        result = await get_task(c, ORIGIN, {'class_id': '10', 'task_id': '101'})
    assert result['error']['code'] == code and 'task' not in result


@pytest.mark.asyncio
@pytest.mark.parametrize('location,code', [('/login','session_expired'),('https://attacker.example/','unexpected_redirect')])
async def test_redirects_never_follow_even_with_redirecting_client(location, code):
    seen = []
    async with client_for({'/student/classes/10/files': httpx.Response(302,headers={'location': location})}, seen) as c:
        result = await get_class_files(c, ORIGIN, {'class_id': '10'})
    assert result['error']['code'] == code and len(seen) == 1


@pytest.mark.asyncio
async def test_missing_section_is_not_empty_and_wrong_identity_fails():
    html = '<main><h2 class="page-title">Test</h2><div class="task-description"></div></main>'
    data = parse_detail(html, ORIGIN, '10', '101')
    assert data['description'] == [] and data['resources'] == {'state': 'not_on_page'}
    with pytest.raises(FlowError, match='description'):
        parse_detail(html.replace('class="task-description"', 'class="unknown"'), ORIGIN, '10', '101')
    with pytest.raises(FlowError):
        parse_detail(fixture('tasks/detail.html'), ORIGIN, '10', '102')


@pytest.mark.asyncio
async def test_pagination_count_mismatch_and_foreign_destination_fail():
    for changed, expected in [
        (fixture('tasks/page1.html').replace('Tasks (2)','Tasks (3)'), 'count_mismatch'),
        (fixture('tasks/page1.html').replace('/core_tasks?page=2','/files?page=2'), 'invalid_pagination'),
    ]:
        seen = []
        pages = {'/student/classes/10/core_tasks': changed,
                 '/student/classes/10/core_tasks?page=2': fixture('tasks/page2.html').replace('Tasks (2)', 'Tasks (3)')}
        async with client_for(pages, seen) as c:
            result = await get_tasks(c, ORIGIN, {'class_ids': ['10']})
        assert result['error']['code'] == expected and 'tasks' not in result


@pytest.mark.asyncio
async def test_partway_files_error_returns_no_partial_data():
    seen = []
    async with client_for({'/student/classes/10/files': fixture('files/root.html'),
                           '/student/classes/10/files/page/2': httpx.Response(403)}, seen) as c:
        result = await get_class_files(c, ORIGIN, {'class_id': '10'})
    assert set(result) == {'error'}


def test_encoded_metadata_roundtrips_without_corrupting_backslashes():
    value = {'name': 'Lab \\ New – წყალი.pdf', 'download_url': 'https://example.org/f?x=1&y=2'}
    for raw in (json.dumps(value), json.dumps(json.dumps(value)), "'"+json.dumps(value)+"'"):
        assert file_info(raw) == value
    with pytest.raises(FlowError): file_info('{broken}')


@pytest.mark.asyncio
async def test_invalid_arguments_do_not_request_anything():
    seen = []
    async with client_for({}, seen) as c:
        for args in ({'class_id': '../1'}, {'class_id': 10}, {'class_id': '10', 'extra': True}):
            assert (await get_tasks(c, ORIGIN, args))['error']['code'] == 'invalid_arguments'
        assert (await get_class_files(c, ORIGIN, {'class_id': '10', 'recursive': 'true'}))['error']['code'] == 'invalid_arguments'
    assert not seen


@pytest.mark.asyncio
async def test_page_and_result_limits_fail_without_truncation(monkeypatch):
    import tools.retrieval as bounds
    seen = []
    async with client_for({'/student/classes/10/core_tasks/101': 'x'*2_000_001}, seen) as c:
        assert (await get_task(c, ORIGIN, {'class_id':'10','task_id':'101'}))['error']['code'] == 'page_too_large'
    monkeypatch.setattr(bounds, 'MAX_RESULT_BYTES', 100)
    async with client_for({'/student/classes/10/core_tasks/101': fixture('tasks/detail.html')}, []) as c:
        assert (await get_task(c, ORIGIN, {'class_id':'10','task_id':'101'}))['error']['code'] == 'result_too_large'


def test_asset_dedup_and_unsafe_urls_and_size_bounds():
    rich = RichText(ORIGIN, ORIGIN+'/student/classes/10/core_tasks/101')
    doc = BeautifulSoup('<p><img src="/a.png"><img src="/a.png"><a href="file:///etc/passwd">bad</a></p>', 'html.parser')
    tree = rich.parse(doc)
    assert len(rich.assets) == 1
    assert 'file:' not in json.dumps(tree)
    assert 'unsafe_asset_url_omitted' in rich.noted  # reported to developer diagnostics only
    with pytest.raises(FlowError): rich.parse(BeautifulSoup('<p>'+'a'*120001+'</p>', 'html.parser'))


@pytest.mark.asyncio
async def test_session_isolation_and_developer_exact_output(tmp_path):
    def factory():
        def handle(request):
            assert request.headers['cookie'] == 'session=only-this-account'
            return httpx.Response(200,text=fixture('tasks/detail.html'))
        return httpx.AsyncClient(transport=httpx.MockTransport(handle))
    session = ToolSession(ORIGIN, {'session':'only-this-account'}, factory, True, tmp_path/'reports')
    result = await session.call('get_tasks', {'open': [{'class_id':'10','task_id':'101'}]})
    exports = list((tmp_path/'reports').glob('*/response.json'))
    assert len(exports) == 1 and json.loads(exports[0].read_text()) == result
    assert 'only-this-account' not in exports[0].read_text()
    assert {t.name for t in definitions()} == {'get_classes','get_tasks','get_files','get_timetable'}


def test_rich_text_notes_reach_developer_reports_not_output():
    from diagnostics import capture
    with capture('get_task', True) as report:
        rich = RichText(ORIGIN, ORIGIN + '/student/classes/10/core_tasks/101')
        rich.parse(BeautifulSoup('<p><math>x</math><video src="/v.mp4"></video></p>', 'html.parser'))
    stages = [e['stage'] for e in report.events]
    assert 'rich.visual_or_math_content_needs_review' in stages and 'rich.embedded_media_not_read' in stages
    assert 'warnings' not in rich.finish({})
