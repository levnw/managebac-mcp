import json
from pathlib import Path
import pytest
from sources.managebac.task_detail import parse_detail
from tools.task_output import compact_task, TaskView

ORIGIN = 'https://es.managebac.com'


def output(extra='', description='Do the work.'):
    return compact_task(parse_detail('<main><h1>Task</h1><div class="task-description">' + description +
        '</div>' + extra + '</main>', ORIGIN, '10', '101'))


def test_compact_observed_description():
    html = (Path(__file__).parent/'fixtures/tasks/observed_layout.html').read_text()
    result = compact_task(parse_detail(html, ORIGIN, '10','101'))
    assert result['description'] == 'Dear students,\n\nThis is your written assignment:\n\nComplete the table below.\n\n[image_1]'
    assert result['submission'] == {'box':'not_detected'}
    assert not set(result) & {'history','created','discussions','warnings','assets','resources','submissions','feedback','assessment'}
    assert 'children' not in json.dumps(result)


@pytest.mark.parametrize('markup, expected', [
    ('<p>Read how to submit a file to the dropbox.</p>', {'box':'not_detected'}),
    ('<div id="dropbox"></div>', {'box':'present'}),
    ('<div id="dropbox"><input type="file"></div>', {'box':'present','upload_control':'enabled'}),
    ('<div id="dropbox"><input type="file" disabled></div>', {'box':'present','upload_control':'disabled'}),
    ('<div id="dropbox"><fieldset disabled><input type="file"></fieldset></div>', {'box':'present','upload_control':'disabled'}),
    ('<form action="/student/classes/10/core_tasks/101/submissions"><input type="file"></form>', {'box':'present','upload_control':'enabled'}),
    ('<form action="/student/classes/10/core_tasks/102/submissions"><input type="file"></form>', {'box':'not_detected'}),
])
def test_submission_box_evidence(markup, expected):
    assert output(markup)['submission'] == expected


def test_private_resources_and_submissions_kept_separate():
    result = output('<div class="task-resources"><div class="resource-container">'
        '<span class="author-name">Teacher</span><a class="fr-file" href="/attachments/private-teacher">Teacher.pdf</a>'
        '</div></div><div id="dropbox"><table><tr class="file"><td class="details">'
        '<a class="text-break" href="https://cdn.example.test/student.pdf">My.pdf</a>'
        '<label>Uploaded September 15 at 12:30</label></td></tr></table></div>')
    teacher = json.dumps(result['teacher_resources'])
    student = json.dumps(result['submission']['files'])
    assert '/attachments/private-teacher' in teacher and 'My.pdf' not in teacher
    assert 'My.pdf' in student and 'Teacher.pdf' not in student
    assert 'Uploaded September 15 at 12:30' in student
    assert result['submission']['files'][0]['media'][0]['kind'] == 'file'


def test_complex_table_and_code_not_flattened_or_trimmed():
    result = output(description='<table><caption>Scores</caption><tr><th>Criterion</th><th>Score</th></tr>'
        '<tr><td rowspan="2">B</td><td>6</td></tr><tr><td>7</td></tr></table>'
        '<pre>  a\n\n\n  b</pre>')
    assert result['tables'][0]['rows'][1][0] == {'text':'B','rowspan':2}
    assert result['tables'][0]['caption'] == 'Scores'
    assert '  a\n\n\n  b' in result['description']


def test_inline_spaces_and_emphasis_preserved():
    result = output(description='<p>Read <strong>both</strong> parts of H<sub>2</sub>O.</p>')
    assert result['description'] == 'Read **both** parts of H<sub>2</sub>O.'


def test_resource_icons_duplicate_downloads_and_neutral_previews():
    result = output('<div class="task-resources"><div class="resource-container">'
        '<div class="resource-head-icon"><img src="/generic.png"></div>'
        '<img class="file-icon" src="/pdf.svg">'
        '<p>Read slide 11. <img src="/meaningful-diagram.png" alt="Diagram"></p>'
        '<a class="file-name fr-file" href="/uploads/asset/file/12/work.pdf">Work.pdf</a>'
        '<a class="btn-icon" href="/uploads/asset/file/12/work.pdf"><svg aria-hidden="true"></svg></a>'
        '<a class="btn-icon" href="/preview" data-pdf-preview-url-value="/preview"><svg></svg></a>'
        '</div></div>')
    resource = result['teacher_resources'][0]
    serialized = json.dumps(resource)
    assert 'generic.png' not in serialized and 'pdf.svg' not in serialized
    assert 'Visual content requires' not in serialized
    assert 'Read slide 11.' in resource['text'] and 'meaningful-diagram.png' in serialized
    file = next(a for a in resource['media'] if a['kind'] == 'file')
    assert resource['text'].count('[' + file['id'] + ']') == 1
    assert resource['previews'][0]['name'] == 'Document preview'
    assert 'feedback_previews' not in resource


def test_instruction_images_are_not_cleaned_as_resource_icons():
    result = output(description='<img class="file-icon" src="/actual-instruction.png" alt="Study this">')
    assert result['media'][0]['url'].endswith('/actual-instruction.png')


def test_unique_icon_download_is_not_silently_removed():
    result = output('<div class="task-resources"><div class="resource-container">'
        '<a class="btn-icon" href="/uploads/asset/file/12/only.pdf"><svg aria-hidden="true"></svg></a>'
        '</div></div>')
    assert any(a['url'].endswith('/only.pdf') for a in result['teacher_resources'][0]['media'])
