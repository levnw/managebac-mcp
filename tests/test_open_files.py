"""get_files open layer: authorised downloads, widget-only bytes, and the files card."""
import base64
import json
from pathlib import Path
import httpx
import pytest
from jsonschema import validate
from sources.managebac.pages import fetch_file, MAX_FILE_BYTES
from tools.catalogue import TOOLS, invoke
from tools.files import WIDGET_URI

ORIGIN = 'https://es.managebac.com'
TASK = '/student/classes/10/core_tasks/101'
DETAIL = (Path(__file__).parent / 'fixtures/tasks/detail.html').read_text()
PDF = b'%PDF-1.7 lab instructions'


def school(extra=None, seen=None):
    pages = {TASK: DETAIL, '/uploads/asset/file/501/lab.pdf': httpx.Response(200, content=PDF, headers={'content-type': 'application/pdf'})}
    pages.update(extra or {})
    def handle(request):
        if seen is not None: seen.append((request.url.host, request.headers.get('cookie')))
        value = pages[request.url.raw_path.decode()]
        return value if isinstance(value, httpx.Response) else httpx.Response(200, text=value, headers={'content-type': 'text/html'})
    return httpx.MockTransport(handle)


async def run(args, transport):
    async with httpx.AsyncClient(transport=transport) as client:
        return await invoke('get_files', client, ORIGIN, args)


async def ids_for(transport):
    listing = await run({'class_id': '10', 'task_id': '101'}, transport)
    return {f['name']: f['file_id'] for f in listing['files'] if 'file_id' in f}


async def test_open_downloads_a_listed_file_into_widget_only_meta():
    ids = await ids_for(school())
    result = await run({'class_id': '10', 'task_id': '101', 'open': [ids['Lab instructions.pdf']]}, school())
    [opened] = result['files']
    assert opened == {'file_id': ids['Lab instructions.pdf'], 'name': 'Lab instructions.pdf',
                      'mime_type': 'application/pdf', 'size_bytes': len(PDF), 'status': 'ready'}
    [payload] = result['_meta']['managebac/files']
    assert base64.b64decode(payload['data']) == PDF and payload['name'] == 'Lab instructions.pdf'
    validate({k: v for k, v in result.items() if k != '_meta'}, TOOLS['get_files'].DEFINITION.outputSchema)


async def test_unknown_file_and_preview_are_reported_not_fetched():
    ids = await ids_for(school())
    listing = await run({'class_id': '10', 'task_id': '101'}, school())
    preview = next(f['file_id'] for f in listing['files'] if f['kind'] == 'preview')
    result = await run({'class_id': '10', 'task_id': '101', 'open': ['f_0000000000000000', preview]}, school())
    assert [f['error']['code'] for f in result['files']] == ['file_not_found', 'not_a_file']
    assert result['_meta'] == {'managebac/files': []}


async def test_signed_out_download_fails_the_call():
    ids = await ids_for(school())
    transport = school({'/uploads/asset/file/501/lab.pdf': httpx.Response(302, headers={'location': '/login'})})
    result = await run({'class_id': '10', 'task_id': '101', 'open': [ids['Lab instructions.pdf']]}, transport)
    assert result['error']['code'] == 'session_expired'


@pytest.mark.parametrize('args', [
    {'class_id': '10', 'open': ['not-an-id']}, {'class_id': '10', 'open': ['f_0000000000000000'] * 2},
    {'class_id': '10', 'open': ['f_0000000000000000'], 'recursive': True},
    {'class_id': '10', 'open': ['f_0000000000000000'], 'date_from': '2026-09-01'},
    {'class_id': '10', 'open': [f'f_{n:016x}' for n in range(6)]}])
async def test_open_arguments_are_strict(args):
    assert (await run(args, school()))['error']['code'] == 'invalid_arguments'


async def test_redirect_to_storage_never_carries_school_cookies():
    seen = []
    def handle(request):
        seen.append((request.url.host, request.headers.get('cookie')))
        if request.url.host == 'es.managebac.com':
            return httpx.Response(302, headers={'location': 'https://files.s3.amazonaws.com/lab.pdf?X-Amz-Signature=1'})
        return httpx.Response(200, content=PDF, headers={'content-type': 'application/pdf'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), cookies={'_managebac_session': 'secret'}) as client:
        client.cookies.set('_managebac_session', 'secret', domain='es.managebac.com')
        data, kind = await fetch_file(client, ORIGIN, ORIGIN + '/attachments/abc')
    assert data == PDF and kind == 'application/pdf'
    assert seen[0][0] == 'es.managebac.com' and 'secret' in (seen[0][1] or '')
    assert seen[1] == ('files.s3.amazonaws.com', None)


@pytest.mark.parametrize('response,code', [
    (httpx.Response(302, headers={'location': 'https://evil.example/x.pdf'}), 'unsupported_file_host'),
    (httpx.Response(403), 'file_link_expired'),
    (httpx.Response(200, content=b'x' * (MAX_FILE_BYTES + 1)), 'file_too_large'),
    (httpx.Response(200, text='<form><input type="password"></form>', headers={'content-type': 'text/html'}), 'session_expired'),
])
async def test_download_guards(response, code):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
        with pytest.raises(Exception) as error:
            await fetch_file(client, ORIGIN, ORIGIN + '/uploads/asset/file/1/a.pdf')
    assert error.value.code == code


async def test_mcp_keeps_bytes_out_of_structured_content_and_serves_the_card():
    from mcp.shared.memory import create_connected_server_and_client_session
    from tools.server import create_server
    ids = await ids_for(school())
    async def scoped(name, arguments):
        return await run(arguments, school())
    async with create_connected_server_and_client_session(create_server(scoped)) as session:
        tools = {t.name: t for t in (await session.list_tools()).tools}
        assert tools['get_files'].meta['ui']['resourceUri'] == WIDGET_URI
        response = await session.call_tool('get_files', {'class_id': '10', 'task_id': '101', 'open': [ids['Lab instructions.pdf']]})
        assert '_meta' not in response.structuredContent and 'data' not in json.dumps(response.structuredContent)
        assert response.meta['managebac/files'][0]['file_id'] == ids['Lab instructions.pdf']
        [resource] = (await session.list_resources()).resources
        assert str(resource.uri) == WIDGET_URI and resource.mimeType == 'text/html;profile=mcp-app'
        [content] = (await session.read_resource(WIDGET_URI)).contents
        assert 'window.openai.uploadFile' in content.text and content.mimeType == 'text/html;profile=mcp-app'


async def test_reports_never_store_file_bytes(tmp_path):
    from tools.session import ToolSession
    ids = await ids_for(school())
    session = ToolSession(ORIGIN, {}, lambda: httpx.AsyncClient(transport=school()), developer_mode=True, report_directory=tmp_path)
    result = await session.call('get_files', {'class_id': '10', 'task_id': '101', 'open': [ids['Lab instructions.pdf']]})
    assert result['_meta']['managebac/files']
    saved = json.loads(next(tmp_path.glob('*/response.json')).read_text())
    assert '_meta' not in saved and saved['_meta_omitted'] == {'files': 1}
    assert base64.b64encode(PDF).decode() not in json.dumps(saved)
    await session.aclose()
