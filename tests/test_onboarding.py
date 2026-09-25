import asyncio
import httpx
import pytest
from bs4 import BeautifulSoup
from starlette.testclient import TestClient

from onboarding.app import create_app
from onboarding.transport import FlowError, school_origin
from onboarding.auth import Authenticator
from onboarding.school_discovery import SchoolDiscovery
from onboarding.store import Store


def soup(text):
    return BeautifulSoup(text, 'html.parser')


@pytest.mark.parametrize('url', ['http://es.managebac.com', 'https://evilmanagebac.com',
    'https://es.managebac.com.evil.test', 'https://user@es.managebac.com',
    'https://es.managebac.com:444', 'https://127.0.0.1', 'https://a.b.managebac.com'])
def test_reject_destinations(url):
    with pytest.raises(FlowError):
        school_origin(url)


def test_school_origin():
    assert school_origin('https://es.managebac.com/login') == 'https://es.managebac.com'
    assert school_origin('https://school.managebac.cn/login') == 'https://school.managebac.cn'




async def test_login_does_not_retry_or_follow_external():
    calls = []
    def respond(request):
        calls.append(str(request.url))
        if request.url.path == '/login':
            return httpx.Response(200, text='<meta name="csrf-token" content="test"><form action="/sessions"></form>')
        if request.method == 'POST':
            return httpx.Response(302, headers={'location': 'https://external.test/sso'})
        return httpx.Response(302, headers={'location': '/login'})
    portal = Authenticator(httpx.MockTransport(respond))
    async with portal.client() as c:
        with pytest.raises(FlowError) as e:
            await portal.authenticate(c,'https://es.managebac.com','test@example.test','fake')
    assert e.value.code == 'session_unverified'
    assert len(calls) == 3
    assert all('external' not in x for x in calls)


async def test_email_discovery():
    def respond(request):
        if request.url.host == 'es.managebac.com':
            return httpx.Response(200,text='<h3>School</h3><div class="school-logo"><img src="/logo.png"></div>')
        if request.method == 'GET':
            return httpx.Response(200,text='<meta name="csrf-token" content="test">')
        assert request.headers['accept'] == '*/*'
        assert b'find_school%5Bemail%5D' in request.content
        return httpx.Response(200,headers={'location':'https://es.managebac.com/'})
    school = await SchoolDiscovery(httpx.MockTransport(respond)).discover('test@example.test')
    assert school == {'origin':'https://es.managebac.com','name':'School','logo':'https://es.managebac.com/logo.png'}




def test_persistent_cooldown_and_separate_accounts(tmp_path):
    store = Store(tmp_path)
    assert store.reserve_attempt('test@example.test')
    assert not Store(tmp_path).reserve_attempt('TEST@example.test')
    store.account('test@example.test','https://es.managebac.com')
    assert store.exists('test@example.test','https://es.managebac.com')
    assert not store.exists('test@example.test','https://other.managebac.com')


def test_csrf_and_no_connection(tmp_path):
    with TestClient(create_app(directory=tmp_path),base_url='http://127.0.0.1:8765') as client:
        assert client.get('/').status_code == 200
        assert client.get('/').headers['cache-control'] == 'no-store'
        bootstrap_response = client.get('/api/bootstrap')
        data = bootstrap_response.json()
        response = client.post('/api/discover',json={'email':'test@example.test'})
        assert response.status_code == 400
        assert response.json()['error']['code'] == 'invalid_request'
        assert not client.get('/api/state').json()['connection_enabled']
        assert 'httponly' in bootstrap_response.headers['set-cookie'].lower()
        assert data['mode'] == 'local-development'


def test_discover_required_before_password(tmp_path):
    with TestClient(create_app(directory=tmp_path),base_url='http://127.0.0.1:8765') as client:
        csrf = client.get('/api/bootstrap').json()['csrf']
        result = client.post('/api/signin',json={'mode':'signup','email':'x@y.test','password':'fake','understood':True},
            headers={'Origin':'http://127.0.0.1:8765','X-CSRF-Token':csrf})
        assert result.json()['error']['code'] == 'discover_first'


def test_signup_creates_profile_but_does_not_fake_readiness(tmp_path):
    class FakePortal(Authenticator):
        async def discover(self, email):
            return {'origin':'https://es.managebac.com','name':'Test School','logo':None}

        async def authenticate(self, client, origin, email, password):
            assert password == 'fake-test-only'
            return {'authenticated':True, 'verification':'profile_account_controls'}

    with TestClient(create_app(authenticator=FakePortal(), school_discovery=FakePortal(), directory=tmp_path),base_url='http://127.0.0.1:8765') as client:
        csrf = client.get('/api/bootstrap').json()['csrf']
        headers = {'Origin':'http://127.0.0.1:8765','X-CSRF-Token':csrf}
        assert client.post('/api/discover',json={'email':'test@example.test'},headers=headers).status_code == 200
        response = client.post('/api/signin',headers=headers,json={'email':'test@example.test',
            'password':'fake-test-only','mode':'signup','understood':True})
        assert response.status_code == 202
        # Synchronize with the app event loop, without a wall-clock sleep.
        for _ in range(100):
            state = client.get('/api/state').json()
            if not state['busy']:
                break
        assert not state['busy']
        assert state['authenticated'] and not state['connection_enabled']
        assert state['capability_checks'] == 'not_implemented'
        assert 'results' not in state
        assert state['steps'][0]['state'] == 'passed'
        assert Store(tmp_path).exists('test@example.test','https://es.managebac.com')
        assert b'fake-test-only' not in (tmp_path / 'onboarding.db').read_bytes()





@pytest.mark.parametrize('markup,valid', [
    ('<a class="profile-link" href="/student/profile" aria-label="Test Student"></a><a class="logout" href="/logout">Logout</a>', True),
    ('<h1>Test Student</h1>', False),
    ('<a class="logout" href="/logout">Logout</a>', False),
    ('<input type="password">', False),
])
async def test_profile_controls_and_no_academic_requests(markup, valid):
    requests = []
    def respond(request):
        requests.append((request.method, request.url.path))
        if request.url.path == '/login':
            return httpx.Response(200,text='<form action="/sessions"></form><meta name="csrf-token" content="test">')
        if request.url.path == '/sessions':
            return httpx.Response(302,headers={'location':'/student/classes/my'})
        if request.url.path == '/student/profile':
            return httpx.Response(200,text=markup)
        raise AssertionError('Unexpected route')
    auth = Authenticator(httpx.MockTransport(respond))
    async with auth.client() as client:
        if valid:
            assert (await auth.authenticate(client,'https://es.managebac.com','test@example.test','fake'))['authenticated']
        else:
            with pytest.raises(FlowError):
                await auth.authenticate(client,'https://es.managebac.com','test@example.test','fake')
    assert requests == [('GET','/login'),('POST','/sessions'),('GET','/student/profile')]

@pytest.mark.parametrize('destination', ['/student/classes/my','https://external.test/profile','/login'])
async def test_profile_redirect_cannot_fetch_other_routes(destination):
    calls=[]
    def respond(request):
        calls.append(request.url.path)
        return httpx.Response(302,headers={'location':destination})
    auth=Authenticator(httpx.MockTransport(respond))
    async with auth.client() as client:
        with pytest.raises(FlowError):
            await auth.verify_session(client,'https://es.managebac.com')
    assert calls == ['/student/profile']
