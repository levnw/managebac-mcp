"""Real expiry evidence, inconclusive profile checks and URL identity boundaries."""
import httpx
import pytest
from diagnostics import capture
from tools.session import ToolSession
from sources.managebac.rich_text import file_id, resource_identity
from test_file_references import render

ORIGIN = 'https://es.managebac.com'


@pytest.mark.parametrize('profile', [
    httpx.Response(403), httpx.Response(429), httpx.Response(500),
    httpx.Response(200, text='<main>Changed profile layout</main>'),
    httpx.Response(302, headers={'location':'/student/dashboard'}),
    httpx.Response(302, headers={'location':'https://other.managebac.com/login'}),
    'timeout', 'connect_error',
])
async def test_inconclusive_check_does_not_confirm_expiry_or_discard_client(profile):
    def handle(request):
        if request.url.path == '/student/profile':
            if profile == 'timeout': raise httpx.ReadTimeout('sensitive upstream detail', request=request)
            if profile == 'connect_error': raise httpx.ConnectError('sensitive upstream detail', request=request)
            return profile
        return httpx.Response(302, headers={'location':'/login'})
    session = ToolSession(ORIGIN, {'session':'test-cookie'}, lambda:httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    try:
        with capture('get_tasks', True) as report:
            result = await session.call('get_tasks', {'class_ids': ['10']})
        assert result['error']['code'] == 'session_verification_unavailable'
        assert not any(e['stage'] == 'session.expired_confirmed' for e in report.events)
        assert any(e['stage'] == 'session.verification_unavailable' for e in report.events)
        assert session.cookies.get('session') == 'test-cookie'
        assert not session._client.is_closed
        assert 'sensitive upstream detail' not in str(result) + str(report.events)
    finally: await session.aclose()


@pytest.mark.parametrize('profile', [
    httpx.Response(401), httpx.Response(302,headers={'location':'/login'}),
    httpx.Response(200,text='<form action="/sessions"><input type="password"></form>'),
])
async def test_only_positive_login_evidence_confirms_expiry(profile):
    def handle(request):
        return profile if request.url.path == '/student/profile' else httpx.Response(302,headers={'location':'/login'})
    session = ToolSession(ORIGIN, {}, lambda:httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    try:
        with capture('get_tasks',True) as report:
            result = await session.call('get_tasks',{'class_ids': ['10']})
        assert result['error']['code'] == 'session_expired'
        assert len([e for e in report.events if e['stage']=='session.expired_confirmed']) == 1
    finally: await session.aclose()


def test_resource_query_preserved_and_signatures_rotate():
    first = ORIGIN + '/download?document=one&version=2&Signature=secret1&Expires=1'
    rotation = ORIGIN + '/download?document=one&version=2&Signature=secret2&Expires=9'
    different = ORIGIN + '/download?document=two&version=2&Signature=secret1&Expires=1'
    assert file_id(first) == file_id(rotation)
    assert file_id(first) != file_id(different)
    result = render(f'<a class="fr-file" href="{first}">One</a><a class="fr-file" href="{different}">Two</a>')
    assert len(result['media']) == 2
    assert all('url' not in entry for entry in result['media'])
    assert 'secret' not in str(result)


def test_query_encoding_duplicates_blanks_and_unknown_parameters_preserved():
    url = ORIGIN + '/download?id=a%2Fb&id=c&empty=&X-Amz-Version-Id=3&%53ignature=secret'
    assert resource_identity(url) == ORIGIN + '/download?id=a%2Fb&id=c&empty=&X-Amz-Version-Id=3'
    assert file_id(url) != file_id(url.replace('Version-Id=3','Version-Id=4'))
    assert file_id(url) != file_id(url.replace('id=c','id=d'))
    assert file_id(url) != file_id(url.replace('/download','/different'))
