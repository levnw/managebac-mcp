"""Date filters: tasks by due date (year inferred), files by modified or posted date."""
from datetime import date
from pathlib import Path
import httpx
import pytest
from jsonschema import validate
from tools.catalogue import TOOLS, invoke
from tools.dates import month_day, shown_date

ORIGIN = 'https://es.managebac.com'
LIST = '/student/classes/10/core_tasks'
FIXTURES = Path(__file__).parent / 'fixtures'


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr('tools.dates.today', lambda: date(2026, 9, 25))


def card(task_id, title, badge=''):
    return (f'<div class="fusion-card-item"><a href="/student/classes/10/core_tasks/{task_id}">{title}</a>'
            + (f'<div class="date-badge"><div class="month">{badge.split()[0]}</div><div class="day">{badge.split()[1]}</div></div>' if badge else '')
            + '</div>')


LIST_PAGE = '<main><h2>Tasks (3)</h2>' + card(1, 'Lab', 'Sep 17') + card(2, 'Essay', 'Oct 2') + card(3, 'Reading') + '</main>'


async def call(name, args, pages):
    def handle(request):
        response = pages[request.url.raw_path.decode()]
        return response if isinstance(response, httpx.Response) else httpx.Response(
            200, text=response, headers={'content-type': 'text/html'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        return await invoke(name, client, ORIGIN, args)


def test_year_is_the_one_closest_to_today():
    ref = date(2026, 9, 25)
    assert month_day('Sep 17', ref) == '2026-09-17'
    assert month_day('Jan 5', ref) == '2027-01-05'       # early next year, not last January
    assert month_day('Dec 20', date(2027, 1, 3)) == '2026-12-20'
    assert month_day('Feb 30', ref) is None and month_day('Soon', ref) is None
    assert shown_date('Posted 1 file on Sep 16, 2026 at 9:48 PM') == '2026-09-16'


async def test_task_list_carries_due_date_and_filters_by_range():
    result = await call('get_tasks', {'class_ids': ['10']}, {LIST: LIST_PAGE})
    assert [(t['id'], t.get('due_date')) for t in result['tasks']] == [('1', '2026-09-17'), ('2', '2026-10-02'), ('3', None)]
    assert 'undated' not in result
    result = await call('get_tasks', {'class_ids': ['10'], 'date_from': '2026-09-20', 'date_to': '2026-10-31'}, {LIST: LIST_PAGE})
    assert [t['id'] for t in result['tasks']] == ['2']
    assert result['undated'] == [{'class_id': '10', 'id': '3', 'title': 'Reading'}]
    validate(result, TOOLS['get_tasks'].DEFINITION.outputSchema)


async def test_task_detail_has_due_date_from_the_badge():
    html = (FIXTURES / 'tasks/detail.html').read_text().replace(
        '</main>', '<div class="date-badge"><div class="month">Sep</div><div class="day">17</div></div></main>')
    result = await call('get_tasks', {'open': [{'class_id': '10', 'task_id': '101'}]}, {LIST + '/101': html})
    assert result['tasks'][0]['due_date'] == '2026-09-17'
    validate(result, TOOLS['get_tasks'].DEFINITION.outputSchema)


@pytest.mark.parametrize('args', [
    {'class_ids': ['10'], 'date_from': '2026-13-01'}, {'class_ids': ['10'], 'date_from': '25/09/2026'},
    {'class_ids': ['10'], 'date_from': '2026-10-01', 'date_to': '2026-09-01'},
    {'open': [{'class_id': '10', 'task_id': '1'}], 'date_from': '2026-09-01'},
    {'class_id': '10', 'date_to': 'tomorrow'}])
async def test_invalid_dates_are_rejected(args):
    name = 'get_files' if 'class_id' in args else 'get_tasks'
    assert (await call(name, args, {}))['error']['code'] == 'invalid_arguments'


async def test_class_files_filter_by_last_modified():
    pages = {'/student/classes/10/files': (FIXTURES / 'files/root.html').read_text(),
             '/student/classes/10/files/page/2': (FIXTURES / 'files/root2.html').read_text()}
    everything = await call('get_files', {'class_id': '10'}, pages)
    assert any(f.get('updated_at', '').startswith('2026-09-12') for f in everything['files'])
    kept = await call('get_files', {'class_id': '10', 'date_from': '2026-09-12', 'date_to': '2026-09-12'}, pages)
    assert kept['files'] and all(f['updated_at'].startswith('2026-09-12') for f in kept['files'])
    none = await call('get_files', {'class_id': '10', 'date_from': '2026-09-13'}, pages)
    assert none['files'] == []
    validate(kept, TOOLS['get_files'].DEFINITION.outputSchema)


async def test_task_files_have_posted_dates_including_submissions():
    html = (FIXTURES / 'tasks/detail.html').read_text()
    html = html.replace('<span class="posted-date">Sep 12</span>', '<span class="posted-date">Posted 1 file on Sep 12, 2026 at 9:00 AM</span>')
    html = html.replace('My answer.pdf</a>', 'My answer.pdf</a><label>Uploaded Sep 20, 2026 at 8:15 PM</label>')
    result = await call('get_files', {'class_id': '10', 'task_id': '101'}, {LIST + '/101': html})
    dated = {f['source']: f.get('posted_date') for f in result['files'] if f['source'] != 'description'}
    assert dated == {'teacher_resource': '2026-09-12', 'submission': '2026-09-20'}
    mine = await call('get_files', {'class_id': '10', 'task_id': '101', 'date_from': '2026-09-15'}, {LIST + '/101': html})
    # The upload and the teacher-feedback preview attached to it (kind preview).
    assert [(f['source'], f['kind']) for f in mine['files']] == [('submission', 'file'), ('submission', 'preview')]
    assert [u['name'] for u in mine['undated']] == ['Lab instructions.pdf']   # instructions file has no date
    validate(mine, TOOLS['get_files'].DEFINITION.outputSchema)


REAL_ROW = ('<main><h2>Tasks (1)</h2><div class="fusion-card-item">'
            '<a href="/student/classes/10/core_tasks/1">Lab work "Catalase"</a>'
            '<span class="badge"><span class="badge-label">HL</span></span>'
            '<div class="label-and-due"><div class="labels-set">'
            '<div class="label">Formative</div><div class="label">Classwork</div>'
            '<span class="badge color-box-gray" data-bs-title="Waiting"><span class="badge-label">Pending</span></span>'
            '<span class="due-date"><div class="due regular">Thursday at 12:30 PM</div></span></div></div>'
            '<div class="date-badge"><div class="month">Sep</div><div class="day">24</div></div></div></main>')


async def test_live_row_markup_gives_status_level_and_labels():
    """Live (25 Sep 19:07 UTC): status came out as "HL" and labels were never read."""
    result = await call('get_tasks', {'class_ids': ['10']}, {LIST: REAL_ROW})
    [task] = result['tasks']
    assert task['status'] == 'Pending' and task['level'] == 'HL'
    assert task['tags'] == ['Formative', 'Classwork'] and task['due_date'] == '2026-09-24'
    assert [t['id'] for t in (await call('get_tasks', {'class_ids': ['10'], 'status': 'pending'}, {LIST: REAL_ROW}))['tasks']] == ['1']
    assert [t['id'] for t in (await call('get_tasks', {'class_ids': ['10'], 'tag': 'formative'}, {LIST: REAL_ROW}))['tasks']] == ['1']
    validate(result, TOOLS['get_tasks'].DEFINITION.outputSchema)
