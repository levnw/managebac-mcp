import json
import httpx
import pytest
from diagnostics import capture, event
from sources.managebac.classes import parse_page, page_url
from tools.classes import get_classes, ClassResult, DEFINITION
from onboarding.transport import FlowError

ORIGIN = 'https://es.managebac.com'
def html(ids, total, nxt=None, name='Science'):
    tiles = ''.join(f'<div class="f-class-tile"><p class="f-tile__title"><a href="/student/classes/{i}">{name}</a></p></div>' for i in ids)
    pagination = f'<div class="pagination"><a rel="next" href="{nxt}">Next</a></div>' if nxt else ''
    return f'<h2>My Classes ({total})</h2><nav><a href="/student/classes/999">Sidebar</a></nav>{tiles}{pagination}'

async def call(pages, arguments=None):
    requests=[]
    def respond(request):
        requests.append(str(request.url))
        value = pages[str(request.url)]
        return value if isinstance(value,httpx.Response) else httpx.Response(200,text=value,headers={'content-type':'text/html'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await get_classes(client,ORIGIN,arguments or {})
    if 'error' not in result:
        ClassResult.model_validate(result)
        assert set(result) == {'classes'}
    else:
        assert set(result) == {'error'}
    return result, requests

async def test_two_pages_complete_and_no_other_requests():
    root = ORIGIN+'/student/classes/my'
    result, requests = await call({root:html([1,2],3,'?page=2'),root+'?page=2':html([3],3)})
    assert requests == [root,root+'?page=2']
    assert [r['id'] for r in result['classes']] == ['1','2','3']

async def test_three_pages_in_one_call_and_deduplicated():
    root = ORIGIN+'/student/classes/my'
    pages = {root:html([1],3,'?page=2'),root+'?page=2':html([1,2],3,'?page=3'),root+'?page=3':html([3],3)}
    result,requests = await call(pages)
    assert [r['id'] for r in result['classes']] == ['1','2','3']
    assert requests == [root,root+'?page=2',root+'?page=3']
    denied,requests=await call({}, {'cursor':'old-cursor'})
    assert 'error' in denied and not requests

@pytest.mark.parametrize('link',['https://evil.test/student/classes/my','/student/classes/all','/student/classes/123','?page=0','?page=2&page=3','?page=2&token=secret'])
def test_unsafe_pagination(link):
    with pytest.raises(FlowError):
        page_url(ORIGIN,link)

async def test_second_page_failure_never_returns_partial():
    root=ORIGIN+'/student/classes/my'
    result,_=await call({root:html([1],2,'?page=2'),root+'?page=2':httpx.Response(503)})
    assert set(result) == {'error'}

async def test_expired_login_not_empty():
    result,requests=await call({ORIGIN+'/student/classes/my':httpx.Response(302,headers={'location':'/login'})})
    assert len(requests)==1
    assert result['error']['code']=='session_expired'

@pytest.mark.parametrize('content', ['<h1>Welcome</h1>','<input type="password">'])
def test_unrecognized_or_login_page(content):
    with pytest.raises(FlowError): parse_page(content,ORIGIN)

async def test_explicit_empty():
    result,_=await call({ORIGIN+'/student/classes/my':html([],0)})
    assert result == {'classes': []}

async def test_missing_classes_fail_count():
    result,_=await call({ORIGIN+'/student/classes/my':html([1],2)})
    assert result['error']['code']=='count_mismatch'

async def test_loop_not_complete():
    root=ORIGIN+'/student/classes/my'
    result,requests=await call({root:html([1],2,'?page=2'),root+'?page=2':html([2],2,'?page=1')})
    assert result['error']['code'] == 'pagination_loop'
    assert len(requests) == 2

def test_debug_off_and_secret_fields_rejected():
    with capture('test',False) as report:
        event('classes.parsed',count=15)
        assert report is None
    with capture('test',True) as report:
        event('classes.parsed',count=15)
        with pytest.raises(TypeError): event('test',password='secret')
        assert report.export()['events']==[{'stage':'classes.parsed','count':15}]

async def test_invalid_arguments_no_fetch():
    result,requests=await call({}, {'school':'https://evil.test'})
    assert 'error' in result and not requests

@pytest.mark.parametrize('second,total,code', [
    (html([2],3), 2, 'list_changed'),
    (html([1],1,name='Changed'), 1, 'list_changed'),
])
async def test_changed_list_returns_only_error(second,total,code):
    root=ORIGIN+'/student/classes/my'
    result,_=await call({root:html([1],total,'?page=2'),root+'?page=2':second})
    assert set(result)=={'error'} and result['error']['code']==code

@pytest.mark.parametrize('setting,value,code', [
    ('MAX_PAGES',1,'pagination_loop'),
    ('MAX_CLASSES',1,'result_too_large'),
    ('MAX_RESULT_BYTES',1,'result_too_large'),
])
async def test_limits_fail_without_truncation(monkeypatch,setting,value,code):
    monkeypatch.setattr('tools.classes.'+setting,value)
    root=ORIGIN+'/student/classes/my'
    result,_=await call({root:html([1],2,'?page=2'),root+'?page=2':html([2],2)})
    assert set(result)=={'error'} and result['error']['code']==code

async def test_total_timeout_returns_only_error(monkeypatch):
    import asyncio
    import tools.classes as module
    async def slow(*args, **kwargs):
        await asyncio.sleep(1)
    monkeypatch.setattr(module,'collect',slow)
    monkeypatch.setattr(module,'TOTAL_TIMEOUT_SECONDS',0.001)
    result,_=await call({})
    assert set(result)=={'error'} and result['error']['code']=='retrieval_timeout'

async def test_mcp_error_has_readable_text_and_no_success_payload():
    from tools.server import create_server
    from mcp.shared.memory import create_connected_server_and_client_session
    payload={'error':{'code':'session_expired','message':'Sign in again.'}}
    async def failed(name, arguments):
        return payload
    async with create_connected_server_and_client_session(create_server(failed)) as session:
        result=await session.call_tool('get_classes',{})
        assert result.isError
        assert result.content[0].text == 'session_expired: Sign in again.'
        assert result.structuredContent is None

def test_mcp_definition():
    assert DEFINITION.name=='get_classes'
    assert DEFINITION.annotations.readOnlyHint
    assert DEFINITION.inputSchema['additionalProperties'] is False
    assert DEFINITION.outputSchema['additionalProperties'] is False

async def test_real_mcp_list_and_call_in_memory():
    from tools.server import create_server
    from mcp.shared.memory import create_connected_server_and_client_session
    async def scoped_call(name, arguments):
        result,_ = await call({ORIGIN+'/student/classes/my':html([1],1)},arguments)
        return result
    async with create_connected_server_and_client_session(create_server(scoped_call)) as session:
        listing=await session.list_tools()
        assert [t.name for t in listing.tools][0]=='get_classes' and len(listing.tools)==12
        result=await session.call_tool('get_classes',{})
        assert not result.isError
        assert result.content == []
        assert result.structuredContent['classes'][0]['id']=='1'

@pytest.mark.parametrize('developer_mode',[False,True])
def test_web_inspector_login_separation_and_reports(tmp_path,developer_mode):
    from onboarding.app import create_app
    from onboarding.auth import Authenticator
    from starlette.testclient import TestClient
    requests=[]
    def respond(request):
        requests.append(request.url.path)
        assert request.url.path == '/student/classes/my'
        return httpx.Response(200,text=html([1],1),headers={'content-type':'text/html'})
    class FakeAuth(Authenticator):
        async def authenticate(self,client,origin,email,password):
            client.cookies.set('test_session','secret-test-cookie',domain='es.managebac.com')
            return {'authenticated':True,'verification':'test_only'}
    class FakeDiscovery:
        async def discover(self,email):
            return {'origin':ORIGIN,'name':'Test','logo':None}
    app=create_app(authenticator=FakeAuth(httpx.MockTransport(respond)),school_discovery=FakeDiscovery(),
        directory=tmp_path,developer_mode=developer_mode)
    with TestClient(app,base_url='http://127.0.0.1:8765') as client:
        csrf=client.get('/api/bootstrap').json()['csrf']
        headers={'Origin':'http://127.0.0.1:8765','X-CSRF-Token':csrf}
        assert client.post('/api/tools/get_classes',headers=headers,json={}).status_code==400
        client.post('/api/discover',headers=headers,json={'email':'test@example.test'})
        client.post('/api/signin',headers=headers,json={'email':'test@example.test','password':'test-secret','mode':'signup','understood':True})
        for _ in range(100):
            if not client.get('/api/state').json()['busy']: break
        assert not requests  # Login never invokes the tool.
        payload=client.post('/api/tools/get_classes',headers=headers,json={}).json()
        assert set(payload) == {'classes'} and len(payload['classes']) == 1
        reports=client.get('/api/reports').json()
        assert bool(reports['reports']) is developer_mode
        if developer_mode:
            assert reports['reports'][-1]['tool_result']==payload
            from pathlib import Path
            saved = reports['reports'][-1]['export']
            assert saved['saved']
            response_file = Path(saved['response_file'])
            assert json.loads(response_file.read_text()) == payload
            assert response_file.stat().st_mode & 0o777 == 0o600
            assert response_file.parent.stat().st_mode & 0o777 == 0o700
            login_files = list((tmp_path / 'Test Reports').glob('*-login-*/response.json'))
            assert len(login_files) == 1
            assert json.loads(login_files[0].read_text()) == {
                'authenticated': True, 'verification': 'test_only'}
            for file in (tmp_path / 'Test Reports').glob('*/*.json'):
                assert 'secret-test-cookie' not in file.read_text()
                assert 'test-secret' not in file.read_text()
        else:
            assert not (tmp_path / 'Test Reports').exists()
        assert 'secret-test-cookie' not in json.dumps(reports)
        assert 'test-secret' not in json.dumps(reports)
        assert client.get('/api/bootstrap').json()['csrf']==csrf
        # A different browser session cannot access results/cookies/reports.
        client.cookies.clear()
        client.get('/api/bootstrap')
        assert client.post('/api/tools/get_classes',json={},headers={'Origin':'http://127.0.0.1:8765','X-CSRF-Token':client.get('/api/bootstrap').json()['csrf']}).status_code==400
        assert client.get('/api/reports').json()['reports']==[]
