"""Retry policy, connection reuse, concurrency and diagnostic ownership."""
import asyncio
import json
import httpx
import pytest
from diagnostics import capture, event
from sources.managebac.pages import fetch_html
from tools.session import ToolSession

ORIGIN = 'https://es.managebac.com'
PATH = '/student/classes/10/core_tasks'
OK = httpx.Response(200, text='<main>ok</main>', headers={'content-type': 'text/html'})


def scripted(*responses):
    calls = []
    def respond(request):
        calls.append(request)
        value = responses[min(len(calls), len(responses)) - 1]
        if isinstance(value, Exception): raise value
        return value
    return httpx.MockTransport(respond), calls


async def fetch(*responses):
    transport, calls = scripted(*responses)
    async with httpx.AsyncClient(transport=transport) as client:
        try:
            return await fetch_html(client, ORIGIN, PATH), len(calls)
        except Exception as exc:
            return getattr(exc, 'code', type(exc).__name__), len(calls)


@pytest.mark.parametrize('first', [httpx.Response(503), httpx.Response(502), httpx.Response(504),
                                   httpx.ConnectError('refused'),
                                   httpx.Response(429, headers={'retry-after': '0'})])
async def test_one_retry_recovers_transient_failures(first):
    assert await fetch(first, OK) == ('<main>ok</main>', 2)


async def test_second_transient_failure_is_reported_not_retried_again():
    assert await fetch(httpx.Response(503), httpx.Response(503), OK) == ('upstream_unavailable', 2)
    assert await fetch(httpx.ConnectError('x'), httpx.ConnectError('x'), OK) == ('ConnectError', 2)


@pytest.mark.parametrize('response,code', [
    (httpx.Response(429, headers={'retry-after': '30'}), 'rate_limited'),
    (httpx.Response(429), 'rate_limited'),
    (httpx.Response(404), 'not_found'),
    (httpx.Response(500), 'upstream_unavailable'),
    (httpx.Response(302, headers={'location': '/login'}), 'session_expired'),
])
async def test_non_transient_failures_are_not_retried(response, code):
    assert await fetch(response, OK) == (code, 1)


def tasks_page(n):
    return httpx.Response(200, text=f'<main><h2>Tasks (0)</h2><div class="empty-state">No tasks {n}</div></main>',
                          headers={'content-type': 'text/html'})


async def test_session_reuses_one_client_and_keeps_rotated_cookies():
    made = []
    def respond(request):
        return httpx.Response(200, text='<main><h2>Tasks (0)</h2><div class="empty-state">No tasks</div></main>',
                              headers={'content-type': 'text/html', 'set-cookie': f'rotated={len(made)}; Path=/'})
    def factory():
        made.append(httpx.AsyncClient(transport=httpx.MockTransport(respond)))
        return made[-1]
    session = ToolSession(ORIGIN, {'start': '1'}, factory)
    for _ in range(3):
        assert 'tasks' in await session.call('get_tasks', {'class_ids': ['10']})
    assert len(made) == 1
    assert session.cookies.get('rotated') == '1' and session.cookies.get('start') == '1'
    await session.aclose()
    assert made[0].is_closed and session.cookies.get('rotated') == '1'


async def test_calls_run_concurrently_up_to_the_cap():
    active, peak, release = 0, 0, asyncio.Event()
    async def handler(request):
        nonlocal active, peak
        active += 1; peak = max(peak, active)
        await release.wait()
        active -= 1
        return tasks_page(0)
    session = ToolSession(ORIGIN, {}, lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                          max_concurrent=2)
    calls = [asyncio.create_task(session.call('get_tasks', {'class_ids': [str(i)]})) for i in range(1, 4)]
    await asyncio.sleep(0.05)
    assert peak == 2          # parallel, but bounded
    release.set()
    results = await asyncio.gather(*calls)
    assert all('tasks' in result for result in results)
    await session.aclose()


async def test_host_diagnostics_are_not_replaced_without_a_report_writer():
    session = ToolSession(ORIGIN, {}, lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda r: tasks_page(0))))
    with capture('get_tasks', True) as report:
        await session.call('get_tasks', {'class_ids': ['10']})
    assert any(e['stage'] == 'page.request' for e in report.events)
    await session.aclose()


async def test_session_report_includes_definition_target_and_size(tmp_path):
    seen = []
    session = ToolSession(ORIGIN, {}, lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda r: tasks_page(0))),
                          developer_mode=True, report_directory=tmp_path)
    result = await session.call('get_tasks', {'class_ids': ['10']}, record=lambda report, result: seen.append(report))
    [report] = seen
    assert report['target'] == {'class_ids': ['10']} and report['export']['saved']
    assert report['tool_definition']['name'] == 'get_tasks' and report['serialized_bytes'] > 0
    assert (tmp_path / report['export']['response_file'].split('/')[-2] / 'response.json').exists()
    await session.aclose()


async def test_confirmed_expiry_records_session_age_only():
    def respond(request):
        return httpx.Response(302, headers={'location': '/login'})
    session = ToolSession(ORIGIN, {}, lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    with capture('get_tasks', True) as report:
        result = await session.call('get_tasks', {'class_ids': ['10']})
    assert result['error']['code'] == 'session_expired'
    [expired] = [e for e in report.events if e['stage'] == 'session.expired_confirmed']
    assert set(expired) == {'stage', 'seconds'} and expired['seconds'] >= 0
    await session.aclose()


async def test_page_reads_keep_the_signed_in_identity():
    """Live regression: a User-Agent differing from sign-in ended the ManageBac session."""
    seen = []
    def respond(request):
        seen.append(request.headers)
        return tasks_page(0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond),
                                 headers={'User-Agent': 'identity-used-at-sign-in'}) as client:
        await fetch_html(client, ORIGIN, PATH)
    assert seen[0]['user-agent'] == 'identity-used-at-sign-in'
    assert 'origin' not in seen[0]


def test_login_and_tool_clients_share_one_identity():
    from onboarding.auth import Authenticator
    from onboarding.transport import Transport
    assert Authenticator().client().headers['user-agent'] == Transport().client().headers['user-agent']


def test_unrecognised_task_list_records_structure_not_content():
    from sources.managebac.tasks import parse_list
    html = ('<main><h2>Tasks</h2><div class="placeholder-panel">Nothing assigned yet</div>'
            '<p class="secret">Private instructions</p></main>')
    with capture('get_tasks', True) as report:
        with pytest.raises(Exception):
            parse_list(html, ORIGIN, '10', ORIGIN + PATH)
    layout = report.export()['layout']
    assert layout['headings'] == ['Tasks']
    assert layout['empty_like'] == ['placeholder-panel: Nothing assigned yet']
    structural = {key: value for key, value in layout.items() if key != 'interface_text'}
    assert 'Private instructions' not in json.dumps(structural)
    assert 'candidate_rows' in layout


def test_layout_structure_ignores_layout_utility_classes_and_long_text():
    from sources.managebac.tasks import parse_list
    html = ('<main><h2>Tasks</h2><div class="no-margin">Private instructions for the essay</div>'
            '<div class="empty-state">' + 'x' * 200 + '</div></main>')
    with capture('get_tasks', True) as report:
        with pytest.raises(Exception):
            parse_list(html, ORIGIN, '10', ORIGIN + PATH)
    assert report.export()['layout']['empty_like'] == []


def test_page_without_task_links_records_interface_text_only():
    from sources.managebac.tasks import parse_list
    empty = ('<main><section class="f-hero"><h1>Biology</h1></section><section class="f-layout-main__content">'
             '<h2>Coursework</h2><div class="filters">Upcoming Past</div><p class="muted">Nothing here yet</p></section></main>')
    with capture('get_tasks', True) as report:
        with pytest.raises(Exception):
            parse_list(empty, ORIGIN, '10', ORIGIN + PATH)
    assert report.export()['layout']['interface_text'] == ['Coursework Upcoming Past Nothing here yet']
    with_task = empty.replace('Nothing here yet', '<a href="/core_tasks/5">x</a>')
    with capture('get_tasks', True) as report:
        with pytest.raises(Exception):
            parse_list(with_task.replace('/core_tasks/5', '/student/classes/10/core_tasks/5x'), ORIGIN, '10', ORIGIN + PATH)
    assert report.export()['layout'].get('interface_text', []) == []


LIVE_EMPTY = ('<main><section class="f-hero"><h1>IB MYP Biology (Grade 9) B</h1></section>'
              '<section class="f-layout-main__content f-surface"><h2>All Tasks</h2>'
              '<div class="filters">Upcoming Past</div></section></main>')


def test_live_observed_class_without_tasks_is_an_empty_list():
    from sources.managebac.tasks import parse_list
    with capture('get_tasks', True) as report:
        rows, total, following = parse_list(LIVE_EMPTY, ORIGIN, '10', ORIGIN + PATH)
    assert rows == [] and following is None
    assert any(e['stage'] == 'tasks.empty_all_tasks_without_task_links' for e in report.events)


def test_all_tasks_page_with_unrecognised_task_links_still_errors():
    from sources.managebac.tasks import parse_list
    html = LIVE_EMPTY.replace('Upcoming Past', '<a href="/student/classes/10/core_tasks/5">Essay</a>')
    with pytest.raises(Exception) as error:
        parse_list(html, ORIGIN, '10', ORIGIN + PATH)
    assert error.value.code == 'layout_changed'


def test_page_without_all_tasks_heading_still_errors():
    from sources.managebac.tasks import parse_list
    with pytest.raises(Exception) as error:
        parse_list(LIVE_EMPTY.replace('All Tasks', 'Overview'), ORIGIN, '10', ORIGIN + PATH)
    assert error.value.code == 'layout_changed'
