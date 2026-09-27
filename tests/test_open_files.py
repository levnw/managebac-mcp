"""Account-scoped downloads whose text is returned to the model."""
import base64
import json
from pathlib import Path
import httpx
import pytest
from jsonschema import validate
from sources.managebac.pages import fetch_file, MAX_FILE_BYTES
from tools.catalogue import TOOLS, invoke

ORIGIN = 'https://es.managebac.com'
TASK = '/student/classes/10/core_tasks/101'
DETAIL = (Path(__file__).parent / 'fixtures/tasks/detail.html').read_text()


def pdf(text: str) -> bytes:
    """A minimal one-page PDF with a text layer."""
    stream = f'BT /F1 18 Tf 72 720 Td ({text}) Tj ET'.encode()
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
               b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'\nendstream',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    out, offsets = bytearray(b'%PDF-1.4\n'), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out)); out += b'%d 0 obj\n' % number + body + b'\nendobj\n'
    xref = len(out)
    out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objects) + 1) + b''.join(b'%010d 00000 n \n' % o for o in offsets)
    out += b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objects) + 1, xref)
    return bytes(out)


PDF = pdf('Lab 3: measure the boiling point of water')


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


async def test_open_returns_the_file_text():
    ids = await ids_for(school())
    result = await run({'class_id': '10', 'task_id': '101', 'open': [ids['Lab instructions.pdf']]}, school())
    [opened] = result['files']
    assert opened == {'file_id': ids['Lab instructions.pdf'], 'name': 'Lab instructions.pdf', 'mime_type': 'application/pdf',
                      'size_bytes': len(PDF), 'status': 'read', 'text': 'Lab 3: measure the boiling point of water'}
    assert base64.b64encode(PDF).decode() not in json.dumps(result)
    validate(result, TOOLS['get_files'].DEFINITION.outputSchema)


async def test_unknown_file_and_preview_are_reported_not_fetched():
    ids = await ids_for(school())
    listing = await run({'class_id': '10', 'task_id': '101'}, school())
    preview = next(f['file_id'] for f in listing['files'] if f['kind'] == 'preview')
    result = await run({'class_id': '10', 'task_id': '101', 'open': ['f_0000000000000000', preview]}, school())
    assert [f['error']['code'] for f in result['files']] == ['file_not_found', 'not_a_file']


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


async def test_mcp_returns_the_text_as_structured_content():
    from mcp.shared.memory import create_connected_server_and_client_session
    from tools.server import create_server
    ids = await ids_for(school())
    async def scoped(name, arguments):
        return await run(arguments, school())
    async with create_connected_server_and_client_session(create_server(scoped)) as session:
        tools = {t.name: t for t in (await session.list_tools()).tools}
        assert 'ui' not in (tools['get_files'].meta or {})
        response = await session.call_tool('get_files', {'class_id': '10', 'task_id': '101', 'open': [ids['Lab instructions.pdf']]})
        assert not response.isError and response.content == []
        assert response.structuredContent['files'][0]['text'] == 'Lab 3: measure the boiling point of water'


async def test_reports_never_store_file_bytes(tmp_path):
    from tools.session import ToolSession
    ids = await ids_for(school())
    session = ToolSession(ORIGIN, {}, lambda: httpx.AsyncClient(transport=school()), developer_mode=True, report_directory=tmp_path)
    result = await session.call('get_files', {'class_id': '10', 'task_id': '101', 'open': [ids['Lab instructions.pdf']]})
    saved = json.loads(next(tmp_path.glob('*/response.json')).read_text())
    assert saved == result
    assert base64.b64encode(PDF).decode() not in json.dumps(saved)
    await session.aclose()


async def test_an_image_says_it_has_no_text_instead_of_guessing():
    png = b'\x89PNG\r\n\x1a\noriginal-image-bytes'
    transport = school({'/attachments/diagram.png': httpx.Response(200, content=png, headers={'content-type': 'image/png'})})
    ids = await ids_for(transport)
    result = await run({'class_id': '10', 'task_id': '101', 'open': [ids['A beaker warming over a flame']]}, transport)
    [opened] = result['files']
    assert opened['status'] == 'error' and opened['error']['code'] == 'no_text_layer'
    assert opened['mime_type'] == 'image/png' and 'text' not in opened


async def test_known_reference_does_not_bypass_another_accounts_source_page():
    ids = await ids_for(school())
    # Same task is visible, but the other account cannot see this attachment.
    other = school({TASK: DETAIL.replace('/uploads/asset/file/501/lab.pdf', '/uploads/asset/file/999/other.pdf')})
    result = await run({'class_id': '10', 'task_id': '101', 'open': [ids['Lab instructions.pdf']]}, other)
    assert result['files'][0]['error']['code'] == 'file_not_found'


def test_workbench_reads_file_text(tmp_path):
    from onboarding.app import create_app
    from onboarding.auth import Authenticator
    from starlette.testclient import TestClient

    class FakePortal(Authenticator):
        async def discover(self, email):
            return {'origin': ORIGIN, 'name': 'Test School', 'logo': None}

        async def authenticate(self, client, origin, email, password):
            return {'authenticated': True, 'verification': 'profile_account_controls'}

    portal = FakePortal(school())
    app = create_app(authenticator=portal, school_discovery=portal, directory=tmp_path, developer_mode=True)
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        csrf = client.get('/api/bootstrap').json()['csrf']
        headers = {'Origin': 'http://127.0.0.1:8765', 'X-CSRF-Token': csrf}
        denied = client.post('/api/tools/get_files', json={'class_id': '10'}, headers=headers)
        assert denied.json()['error']['code'] == 'login_required'
        assert client.post('/api/discover', json={'email': 'test@example.test'}, headers=headers).status_code == 200
        assert client.post('/api/signin', json={'email': 'test@example.test', 'password': 'fake',
            'mode': 'signup', 'understood': True}, headers=headers).status_code == 202
        for _ in range(100):
            state = client.get('/api/state').json()
            if not state['busy']: break
        assert state['authenticated']
        args = {'class_id': '10', 'task_id': '101'}
        listing = client.post('/api/tools/get_files', json=args, headers=headers).json()
        file_id = next(f['file_id'] for f in listing['files'] if f.get('name') == 'Lab instructions.pdf')
        opened = client.post('/api/tools/get_files', json={**args, 'open': [file_id]}, headers=headers).json()
        assert opened['files'][0]['text'] == 'Lab 3: measure the boiling point of water'
        reports = '\n'.join(p.read_text() for p in (tmp_path / 'Test Reports').glob('*/*.json'))
        assert reports and base64.b64encode(PDF).decode() not in reports


async def test_empty_files_page_as_seen_live_is_an_empty_listing():
    """Live (25 Sep, six classes): 'No files' / 'No files have been uploaded yet.'"""
    page = ('<main><section class="f-hero"><h1>IB DP Physics 2</h1></section><section class="f-layout-main__content f-surface">'
            '<h2>Files</h2><div class="h4">No files</div><p>No files have been uploaded yet.</p></section></main>')
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text=page, headers={'content-type': 'text/html'}))
    result = await run({'class_id': '10'}, transport)
    assert result['files'] == [] and result['folders'] == []
    validate(result, TOOLS['get_files'].DEFINITION.outputSchema)


async def test_rejected_arguments_name_the_field_not_the_value():
    result = await run({'class_id': '10', 'task_id': '101', 'open': ['Brain.pptx']}, school())
    assert result['error']['code'] == 'invalid_arguments' and 'open takes distinct file_ids' in result['error']['message']
    assert 'Brain.pptx' not in result['error']['message']


async def test_a_file_over_the_limit_asks_the_student_to_attach_it():
    ids = await ids_for(school())
    big = httpx.Response(200, content=b'x', headers={'content-type': 'application/pdf', 'content-length': '23400000'})
    result = await run({'class_id': '10', 'task_id': '101', 'open': [ids['Lab instructions.pdf']]},
                       school({'/uploads/asset/file/501/lab.pdf': big}))
    [opened] = result['files']
    assert opened['error']['code'] == 'file_too_large' and opened['attach_instead'] is True
    assert opened['download_from'] == ORIGIN + TASK
    assert '23.4 MB' in opened['error']['message'] and 'attach it to this chat' in opened['error']['message']
    validate(result, TOOLS['get_files'].DEFINITION.outputSchema)


async def test_errors_the_student_cannot_fix_by_attaching_do_not_ask_for_it():
    result = await run({'class_id': '10', 'task_id': '101', 'open': ['f_0000000000000000']}, school())
    assert 'attach_instead' not in result['files'][0]
