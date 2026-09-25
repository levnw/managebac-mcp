"""Regressions from the second review: shared helpers, nested cards, merged timetable cells."""
import httpx
from jsonschema import validate
from sources.managebac.classes import parse_page
from tools.catalogue import TOOLS
from tools.classes import get_classes
from test_new_catalogue import call, ORIGIN, ROOT

ITEM = ('<a class="f-timetable-item" data-bs-content-url="/x?ib_class_id={id}">'
        '<div class="f-box-item__body"><p class="fw-semibold">{name}</p></div></a>')


def timetable(rows):
    return ('<table class="f-timetable"><thead><tr><th>Period</th><th>Mon</th><th>Tue</th></tr></thead>'
            '<tbody>' + ''.join(rows) + '</tbody></table>')


async def classes_response(response):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
        return await get_classes(client, ORIGIN, {})


async def test_class_redirect_to_login_is_session_expired():
    result = await classes_response(httpx.Response(302, headers={'location': '/login'}))
    assert result['error']['code'] == 'session_expired'


async def test_class_redirect_elsewhere_is_not_called_login_loss():
    result = await classes_response(httpx.Response(302, headers={'location': '/student/dashboard'}))
    assert result['error']['code'] == 'unexpected_redirect'


def test_class_numbered_pages_without_next_are_not_silently_complete():
    html = ('<h2>My Classes (2)</h2><div class="f-class-tile"><p class="f-tile__title">'
            '<a href="/student/classes/1">Maths</a></p></div><div class="pagination"><a href="?page=2">2</a></div>')
    try:
        parse_page(html, ORIGIN)
    except Exception as exc:
        assert exc.code == 'invalid_pagination'
    else:
        raise AssertionError('A second page without a Next link was ignored.')


NESTED = ('<main><h2>Tasks (1)</h2><div class="fusion-card-item"><div data-task-id="11">'
          '<a href="/student/classes/10/core_tasks/11">Lab</a>{extra}</div></div></main>')


async def test_card_with_inner_task_id_is_one_task():
    result = await call('get_tasks', {'class_id': '10'}, {ROOT + '/core_tasks': NESTED.format(extra='')})
    assert [task['id'] for task in result['tasks']] == ['11']


async def test_inner_task_id_must_match_the_link():
    html = NESTED.replace('data-task-id="11"', 'data-task-id="99"').format(extra='')
    result = await call('get_tasks', {'class_id': '10'}, {ROOT + '/core_tasks': html})
    assert result['error']['code'] == 'identity_mismatch'


async def test_grade_in_nested_card_is_reported_once():
    grade = '<div class="assessment-criteria"><table><tr><td>A</td><td>6 / 8</td></tr></table></div>'
    result = await call('get_grades', {'class_id': '10'}, {ROOT + '/core_tasks': NESTED.format(extra=grade)})
    assert [task['id'] for task in result['assessments']] == ['11']


async def test_double_period_class_is_one_slot_with_end_period():
    html = timetable([f'<tr><th>1</th><td rowspan="2">{ITEM.format(id=5, name="Maths")}</td><td></td></tr>',
                      f'<tr><th>2</th><td>{ITEM.format(id=6, name="Art")}</td></tr>',
                      '<tr><th>3</th><td></td><td></td></tr>'])
    result = await call('get_timetable', {}, {'/student/timetables': html})
    assert result['slots'] == [
        {'day_display': 'Mon', 'period': '1', 'period_end': '2', 'class_name': 'Maths', 'class_id': '5'},
        {'day_display': 'Tue', 'period': '2', 'class_name': 'Art', 'class_id': '6'}]
    validate(result, TOOLS['get_timetable'].DEFINITION.outputSchema)


async def test_three_period_note_spanning_both_days():
    html = timetable(['<tr><th>1</th><td colspan="2" rowspan="3">Exams</td></tr>',
                      '<tr><th>2</th></tr>', '<tr><th>3</th></tr>'])
    result = await call('get_timetable', {}, {'/student/timetables': html})
    assert result['notes'] == [{'day_display': day, 'period': '1', 'period_end': '3', 'text': 'Exams'}
                               for day in ('Mon', 'Tue')]


async def test_merged_cell_past_last_period_errors():
    html = timetable([f'<tr><th>1</th><td rowspan="3">{ITEM.format(id=5, name="Maths")}</td><td></td></tr>',
                      '<tr><th>2</th><td></td></tr>'])
    result = await call('get_timetable', {}, {'/student/timetables': html})
    assert result['error']['code'] == 'layout_changed'


async def test_row_with_extra_cell_errors():
    html = timetable(['<tr><th>1</th><td></td><td></td><td>Extra</td></tr>'])
    result = await call('get_timetable', {}, {'/student/timetables': html})
    assert result['error']['code'] == 'layout_changed'


async def test_timetable_item_without_class_name_becomes_a_note():
    """Live (25 Sep 08:22 UTC): an unnamed item made the whole timetable fail."""
    unnamed = '<a class="f-timetable-item"><div class="f-box-item__body"><small>8:00 AM</small><p>Homeroom</p></div></a>'
    html = timetable([f'<tr><th>1</th><td>{unnamed}</td><td>{ITEM.format(id=6, name="Art")}</td></tr>'])
    result = await call('get_timetable', {}, {'/student/timetables': html})
    assert result['slots'] == [{'day_display': 'Tue', 'period': '1', 'class_name': 'Art', 'class_id': '6'}]
    assert result['notes'] == [{'day_display': 'Mon', 'period': '1', 'text': '8:00 AM Homeroom'}]
    validate(result, TOOLS['get_timetable'].DEFINITION.outputSchema)


async def test_empty_unnamed_timetable_item_is_ignored():
    html = timetable(['<tr><th>1</th><td><a class="f-timetable-item"></a></td><td></td></tr>'])
    result = await call('get_timetable', {}, {'/student/timetables': html})
    assert result['slots'] == [] and 'notes' not in result
