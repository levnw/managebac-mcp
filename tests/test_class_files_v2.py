"""Contract and safety regressions for the compact Files browser."""
import json
import httpx
import pytest
from jsonschema import validate, ValidationError
from diagnostics import capture
from tools.files import get_files as get_class_files, DEFINITION
from test_task_files import client_for, fixture, ORIGIN


@pytest.mark.asyncio
async def test_compact_root_has_direct_urls_and_no_diagnostic_or_dom_dump():
    pages = {'/student/classes/10/files': fixture('files/root.html'),
             '/student/classes/10/files/page/2': fixture('files/root2.html')}
    with capture('get_class_files', True) as report:
        async with client_for(pages, []) as client:
            result = await get_class_files(client, ORIGIN, {'class_id': '10'})
    validate(result, DEFINITION.outputSchema)
    assert set(result) == {'class_id', 'url', 'recursive', 'files', 'folders'}
    file = result['files'][0]
    assert file['url'] == ORIGIN + '/uploads/asset/file/601/revision.pdf'
    assert file['description'].startswith('Read **chapter 2**')
    assert file['updated_at'] == '2026-09-12T10:00:00Z'
    assert file['size_bytes'] == 0
    assert not {'created_at', 'folder_id', 'ref'} & file.keys()
    assert not {'warnings', 'assets', 'children'} & set(json.dumps(result).split('"'))
    assert 'parent_id' not in result['folders'][0]
    assert any(e['stage'] == 'files.source_total_unverified_pagination_followed' for e in report.events)


@pytest.mark.asyncio
async def test_selected_empty_folder_is_explicit_and_does_not_walk_root():
    seen = []
    async with client_for({'/student/classes/10/files/folder/702': fixture('files/empty.html')}, seen) as client:
        result = await get_class_files(client, ORIGIN, {'class_id': '10', 'folder_id': '702'})
    assert result == {'class_id': '10', 'folder_id': '702', 'recursive': False,
                      'url': ORIGIN + '/student/classes/10/files/folder/702', 'files': [], 'folders': []}
    assert len(seen) == 1
    validate(result, DEFINITION.outputSchema)


@pytest.mark.asyncio
async def test_mixed_file_layouts_and_display_size():
    html = '''<main id="class-files">
    <div data-ec3-info='{"id":601,"name":"A.pdf","download_url":"/uploads/asset/file/601/a.pdf"}'></div>
    <table><tr class="file"><td class="details"><a class="text-break" href="/uploads/asset/file/602/b.pdf">B.pdf</a> 2.5 MB</td></tr></table>
    </main>'''
    async with client_for({'/student/classes/10/files': html}, []) as client:
        result = await get_class_files(client, ORIGIN, {'class_id': '10'})
    assert [f['id'] for f in result['files']] == ['601', '602']
    assert result['files'][1]['size_display'] == '2.5 MB'
    assert 'size_bytes' not in result['files'][1]


@pytest.mark.asyncio
@pytest.mark.parametrize('url,code', [
    ('javascript:alert(1)', 'invalid_file'), ('mailto:a@example.org', 'invalid_file'),
    ('http://example.org/a.pdf', 'invalid_file'),
    ('/uploads/asset/file/602/a.pdf', 'identity_mismatch'),
])
async def test_invalid_downloads_or_conflicting_ids_fail_closed(url, code):
    html = '<main><div data-ec3-info=\'' + json.dumps({'id':601, 'name':'A.pdf', 'download_url':url}) + '\'></div></main>'
    async with client_for({'/student/classes/10/files': html}, []) as client:
        result = await get_class_files(client, ORIGIN, {'class_id': '10'})
    assert result['error']['code'] == code
    assert 'files' not in result


@pytest.mark.asyncio
async def test_bad_json_row_cannot_be_hidden_by_table_fallback():
    html = '<main><div data-ec3-info="broken"></div><table><tr class="file"><td><a class="text-break" href="/a.pdf">A</a></td></tr></table></main>'
    async with client_for({'/student/classes/10/files': html}, []) as client:
        result = await get_class_files(client, ORIGIN, {'class_id':'10'})
    assert result['error']['code'] == 'unsupported_file_metadata'


@pytest.mark.asyncio
async def test_descendant_failure_never_returns_partial_files():
    pages = {'/student/classes/10/files': fixture('files/root.html'),
             '/student/classes/10/files/page/2': fixture('files/root2.html'),
             '/student/classes/10/files/folder/701': httpx.Response(500)}
    async with client_for(pages, []) as client:
        result = await get_class_files(client, ORIGIN, {'class_id': '10', 'recursive': True})
    assert set(result) == {'error'}


def test_schema_rejects_unplanned_file_fields():
    result = {'class_id':'10', 'url':ORIGIN+'/student/classes/10/files', 'recursive':False,
              'folders':[], 'files':[{'name':'A', 'url':ORIGIN+'/a.pdf', 'debug':'no'}]}
    with pytest.raises(ValidationError): validate(result, DEFINITION.outputSchema)


@pytest.mark.asyncio
async def test_failed_report_records_only_safe_target_ids(tmp_path):
    from tools.session import ToolSession
    session = ToolSession(ORIGIN, {}, lambda: client_for({'/student/classes/10/files': httpx.Response(500)}, []), True, tmp_path)
    await session.call('get_files', {'class_id':'10'})
    report = json.loads(next(tmp_path.glob('*/report.json')).read_text())
    assert report['target'] == {'class_id':'10', 'argument_names': ['class_id']}
    assert 'arguments' not in report


def test_file_browser_script_is_served_with_preview_security_headers(tmp_path):
    from onboarding.app import create_app
    from starlette.testclient import TestClient
    with TestClient(create_app(directory=tmp_path), base_url='http://127.0.0.1') as client:
        response = client.get('/file-browser.js')
        assert response.status_code == 200
        assert 'classFileBrowser' in response.text
        assert response.headers['cache-control'] == 'no-store'
        assert 'file-browser.js' in client.get('/').text


@pytest.mark.asyncio
async def test_browser_page_headers_and_422_remain_distinct():
    from onboarding.transport import Transport
    def respond(request):
        # Browser identity comes from the session client (the one that signed in).
        assert 'Chrome/' in request.headers['user-agent']
        assert 'origin' not in request.headers
        assert request.headers['referer'] == ORIGIN + '/student'
        assert request.headers['accept'].startswith('text/html')
        return httpx.Response(422)
    async with Transport(httpx.MockTransport(respond)).client() as client:
        result = await get_class_files(client, ORIGIN, {'class_id':'10'})
    assert result['error']['code'] == 'upstream_rejected'
    assert '422' in result['error']['message']


@pytest.mark.asyncio
async def test_files_through_mcp_match_plain_payload():
    from tools.server import create_server
    from tools.catalogue import invoke
    from mcp.shared.memory import create_connected_server_and_client_session
    pages = {'/student/classes/10/files': fixture('files/root.html'),
             '/student/classes/10/files/page/2': fixture('files/root2.html')}
    async with client_for(pages, []) as client:
        async def call(name, arguments):
            return await invoke(name, client, ORIGIN, arguments)
        expected = await call('get_files', {'class_id':'10'})
        async with create_connected_server_and_client_session(create_server(call)) as session:
            response = await session.call_tool('get_files', {'class_id':'10'})
            assert not response.isError and response.content == []
            assert response.structuredContent == expected


@pytest.mark.asyncio
async def test_folder_cycle_fails_without_partial_tree():
    pages = {'/student/classes/10/files/folder/7': '<main><a href="/student/classes/10/files/folder/8">Eight</a></main>',
             '/student/classes/10/files/folder/8': '<main><a href="/student/classes/10/files/folder/7">Seven</a></main>'}
    async with client_for(pages, []) as client:
        result = await get_class_files(client, ORIGIN, {'class_id':'10','folder_id':'7','recursive':True})
    assert result['error']['code'] == 'folder_cycle' and 'files' not in result
