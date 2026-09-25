"""Historical layout variants, not a claim of fresh live-page validation."""
import pytest
from pathlib import Path
from sources.managebac.task_detail import parse_detail
from onboarding.transport import FlowError

ORIGIN = 'https://es.managebac.com'


def test_observed_managebac_div_headings_and_image_table():
    html = (Path(__file__).parent / 'fixtures/tasks/observed_layout.html').read_text()
    result = parse_detail(html, ORIGIN, '10', '101')
    assert result['title'] == 'Example worksheet task'
    assert 'Complete the table below.' in str(result['description'])
    assert "'type': 'image'" in str(result['description'])
    assert "'type': 'table'" not in str(result['description'])
    assert 'Show Less' not in str(result['description'])
    assert 'history' not in result  # located to exclude it, never output
    assert len(result['assets']) == 1


def test_observed_history_sidebar_outside_main():
    html = '<main><div class="core-task-show"><div class="fusion-card-item"><div class="title">Task</div></div>'
    html += '<div class="core-task-details"><div class="show-more">Read.</div></div></div></main>'
    html += '<div id="sidebar_info"><section><h6>Task History</h6><div>Created yesterday</div></section></div>'
    result = parse_detail(html, ORIGIN, '10', '101')
    # The sidebar History is recognised, so it is neither the title nor content.
    assert result['title'] == 'Task' and 'Created yesterday' not in str(result)


def test_bare_url_and_file_size_preserved():
    result = parse('<h1>Task</h1><div class="task-description"><p>See https://example.org/guide.</p>'
        '<a class="fr-file" data-name="Worksheet.pdf" href="/attachments/example">Worksheet '
        '<span class="fr-file-size">24 KB</span></a></div>')
    assert any(a['kind'] == 'link' and a['url'] == 'https://example.org/guide' for a in result['assets'])
    assert any(a.get('size_display') == '24 KB' for a in result['assets'])


def parse(content):
    return parse_detail('<main>' + content + '</main>', ORIGIN, '10', '101')


@pytest.mark.parametrize('heading', ['<div class="page-title">Chemistry</div>',
    '<h1>Chemistry</h1>', '<h2>Chemistry</h2>', '<header><span class="task-title">Chemistry</span></header>'])
def test_historical_title_variants(heading):
    result = parse(heading + '<div data-task-id="101">Action</div><h4>Description</h4>'
                   '<div class="show-more"><div class="fix-body-margins"><h2>Instructions</h2><p>Read this.</p></div></div>')
    assert result['title'] == 'Chemistry'
    assert result['resources'] == {'state': 'not_on_page'}


def test_title_does_not_come_from_navigation_or_resources():
    result = parse('<nav><h1>Dashboard</h1></nav><h1>Actual title</h1>'
                   '<div class="task-description"><h1>Instructions</h1></div>'
                   '<div class="task-resources"><h1>Resource title</h1></div>')
    assert result['title'] == 'Actual title'


def test_ambiguous_titles_are_not_guessed():
    with pytest.raises(FlowError) as error:
        parse('<h1>Class name</h1><h2>Possible task</h2><div class="task-description"></div>')
    assert error.value.code == 'ambiguous_task_title'


def test_wrapped_description_heading_and_no_badge_inference():
    result = parse('<h1>Task</h1><header><h4>Description</h4></header>'
                   '<div><p>Instruction</p><span class="badge-label">Not a task status</span></div>')
    assert 'status' not in result
    assert result['description']


def test_duplicate_sections_fail():
    with pytest.raises(FlowError) as error:
        parse('<h1>Task</h1><div class="task-description">A</div><div class="task-description">B</div>')
    assert error.value.code == 'ambiguous_task_layout'


def test_description_siblings_are_not_dropped():
    result = parse('<h1>Task</h1><div class="task-description"><p>Before editor</p>'
        '<div class="fr-element">Editor body</div><p>After editor</p></div>')
    assert all(value in str(result['description']) for value in ('Before editor', 'Editor body', 'After editor'))


def test_resource_metadata_not_duplicated_and_preview_not_file():
    result = parse('<h1>Task</h1><div class="task-description"></div><div class="task-resources">'
        '<div class="resource-container"><span class="author-name">Teacher</span><h5 class="resource-title">Worksheet</h5>'
        '<a href="/uploads/asset/file/1/a.pdf">Download</a></div></div>'
        '<div id="dropbox"><table><tr class="file"><td><a href="#" data-pdf-preview-url-value="opaque-secret">Feedback</a></td></tr></table></div>')
    item = result['resources']['items'][0]
    assert item['author'] == 'Teacher' and item['title'] == 'Worksheet'
    assert 'Teacher' not in str(item['content'])
    assert 'opaque-secret' not in str(result)
    assert not any(asset['url'].endswith('#') for asset in result['assets'])
