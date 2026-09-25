"""Regressions from the independent review: realistic absence is not failure."""
import json
import httpx
import pytest
from jsonschema import validate, ValidationError
from mcp.shared.memory import create_connected_server_and_client_session
from tools.server import create_server
from tools.catalogue import TOOLS
from tools.session import ToolSession
from test_new_catalogue import call, ORIGIN, ROOT, TASK, TIMETABLE, CASES


@pytest.mark.parametrize('status', ['', 'Pending', 'Not Submitted', 'Submitted', 'Not Assessed Yet'])
async def test_mixed_graded_and_ungraded_tasks(status):
    ungraded = '<div class="fusion-card-item"><a href="/student/classes/10/core_tasks/12">Practice</a>'
    if status: ungraded += f'<span class="task-status">{status}</span>'
    html = TASK.replace('Tasks (1)', 'Tasks (2)').replace('</main>', ungraded + '</div></main>')
    result = await call('get_grades', {'class_id':'10'}, {ROOT+'/core_tasks':html})
    assert [task['id'] for task in result['assessments']] == ['11']
    validate(result, TOOLS['get_grades'].DEFINITION.outputSchema)


@pytest.mark.parametrize('markup', ['<div data-grade="6">6</div>', '<div class="grade">A: 6</div>',
                                    '<div class="assessment-criteria"></div>'])
async def test_unreadable_assessment_still_errors(markup):
    html = '<main><h2>Tasks (1)</h2><div class="fusion-card-item"><a href="/student/classes/10/core_tasks/11">Lab</a>' + markup + '</div></main>'
    result = await call('get_grades', {'class_id':'10'}, {ROOT+'/core_tasks':html})
    assert 'error' in result and 'assessments' not in result


async def test_lunch_note_preserved_beside_classes():
    html = TIMETABLE.replace('</tbody>', '<tr><th>Break</th><td>Lunch break</td></tr></tbody>')
    result = await call('get_timetable', {}, {'/student/timetables':html})
    assert len(result['slots']) == 1
    assert result['notes'] == [{'day_display':'Sep 25, Fri', 'period':'Break', 'text':'Lunch break'}]
    validate(result, TOOLS['get_timetable'].DEFINITION.outputSchema)


async def test_lunch_colspan_keeps_source_day_alignment():
    html = '<table class="f-timetable"><thead><tr><th>Period</th><th>Mon</th><th>Tue</th></tr></thead><tbody><tr><th>Break</th><td colspan="2">Lunch</td></tr></tbody></table>'
    result = await call('get_timetable',{}, {'/student/timetables':html})
    assert result['slots'] == []
    assert [note['day_display'] for note in result['notes']] == ['Mon','Tue']


@pytest.mark.parametrize('name,args,path,html,key', CASES)
async def test_all_new_tools_return_visible_mcp_errors(name,args,path,html,key):
    async def fail(name, args):
        return {'error': {'code':'access_denied', 'message':'This page is not available to your account.'}}
    async with create_connected_server_and_client_session(create_server(fail)) as session:
        response = await session.call_tool(name,args)
        assert response.isError and response.structuredContent is None
        assert response.content[0].text == 'access_denied: This page is not available to your account.'


def test_model_orientation_and_specific_limits():
    server = create_server(lambda *args: None)
    for name in TOOLS: assert name in server.instructions
    assert 'node tree' not in server.instructions
    for name in ('get_unit', 'get_timetable'):
        assert '1 page,' in TOOLS[name].DEFINITION.description
        assert '50 pages' not in TOOLS[name].DEFINITION.description
    assert 'per class' in TOOLS['search_tasks'].DEFINITION.description


@pytest.mark.parametrize('name,args,path,html,key', CASES)
async def test_explicit_schemas_reject_extra_and_wrong_fields(name,args,path,html,key):
    result = await call(name,args,{path:html})
    target = result[key][0] if isinstance(result[key],list) else result[key]
    target['unplanned_debug_field'] = 'must not leak'
    with pytest.raises(ValidationError): validate(result, TOOLS[name].DEFINITION.outputSchema)
    del target['unplanned_debug_field']
    required = 'id' if 'id' in target else 'class_name'
    target[required] = 123
    with pytest.raises(ValidationError): validate(result, TOOLS[name].DEFINITION.outputSchema)


async def test_search_report_records_ids_not_search_text(tmp_path):
    def factory():
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(200,text=TASK,headers={'content-type':'text/html'})))
    session = ToolSession(ORIGIN,{},factory,True,tmp_path)
    await session.call('search_tasks',{'class_ids':['10'],'query':'private search phrase'})
    report = json.loads(next(tmp_path.glob('*/report.json')).read_text())
    assert report['target'] == {'class_ids':['10']}
    assert 'private search phrase' not in json.dumps(report)
