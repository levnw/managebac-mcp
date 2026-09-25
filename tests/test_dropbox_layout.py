import pytest
from sources.managebac.task_detail import parse_detail
from tools.task_output import compact_task
from onboarding.transport import FlowError


def render(dropbox):
    page = '<main><div class="core-task-show"><div class="fusion-card-item"><div class="title">Task</div></div>'
    page += '<div class="core-task-details"><div class="show-more"><p>Instructions remain.</p></div></div>'
    page += '<header class="f-title"><div class="f-title__body"><h3>Dropbox</h3></div></header>'
    page += dropbox + '<div class="recent-discussions"><h3>Discussions</h3></div></div></main>'
    return compact_task(parse_detail(page,'https://es.managebac.com','10','101'))


@pytest.mark.parametrize('disabled,expected',[('', 'enabled'),(' disabled','disabled')])
def test_observed_nested_header_empty_dropbox(disabled,expected):
    result = render('<div class="mb-6"><div class="blank-slate-container"><div class="blank-slate-content">'
        '<div class="h4">No Dropbox Submissions</div><svg></svg><p>Click below.</p>'
        '<a href="javascript:void(0)">Google Drive account settings</a>'
        '<a class="btn'+disabled+'" href="/student/classes/10/core_tasks/101/dropbox">Upload Submission</a>'
        '</div></div></div>')
    assert result['submission'] == {'box':'present','upload_control':expected,'files':[]}
    assert result['description'] == 'Instructions remain.'
    assert 'Google Drive' not in str(result)
    assert 'warnings' not in result


def test_nested_header_with_uploaded_file():
    result = render('<div><table><tr class="file"><td class="details">'
        '<a class="text-break" href="/attachments/my-work">My work.pdf</a></td></tr></table></div>')
    assert result['submission']['box'] == 'present'
    assert result['submission']['files'][0]['media'][0]['name'] == 'My work.pdf'


def test_header_does_not_consume_next_section():
    with pytest.raises(FlowError):
        render('')


def test_wrong_task_upload_link_is_not_available_control():
    result = render('<div><a href="/student/classes/10/core_tasks/999/dropbox">Upload Submission</a></div>')
    assert 'upload_control' not in result['submission']
