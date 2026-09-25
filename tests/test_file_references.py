"""File references: stable identity, no expiring credentials in model output."""
import json
import httpx
from bs4 import BeautifulSoup
from jsonschema import validate
from sources.managebac.rich_text import RichText, file_id
from tools.task_output import TaskView
from tools.files import get_files as get_class_files, DEFINITION as FILES

ORIGIN = 'https://es.managebac.com'
PAGE = ORIGIN + '/student/classes/10/core_tasks/101'
SIGNED = ORIGIN + '/uploads/asset/file/19331/notes.pdf?Expires={e}&Signature={s}&Key-Pair-Id=K1'


def render(html):
    rich = RichText(ORIGIN, PAGE)
    nodes = rich.parse(BeautifulSoup(html, 'html.parser'))
    return TaskView(rich.assets).content(nodes)


def test_signed_link_is_replaced_by_stable_file_id():
    first = render(f'<a class="fr-file" href="{SIGNED.format(e=1, s="abc")}">notes.pdf</a>')
    second = render(f'<a class="fr-file" href="{SIGNED.format(e=2, s="xyz")}">notes.pdf</a>')
    [media] = first['media']
    assert 'url' not in media and media['file_id'] == second['media'][0]['file_id']
    assert media['file_id'] == file_id(ORIGIN + '/uploads/asset/file/19331/notes.pdf')
    assert 'Signature' not in json.dumps(first) and 'Expires' not in json.dumps(first)


def test_permanent_school_link_keeps_url_and_gains_file_id():
    [media] = render('<img src="/attachments/eyJhbGciOi.png" alt="Diagram">')['media']
    assert media['url'] == ORIGIN + '/attachments/eyJhbGciOi.png'
    assert media['file_id'].startswith('f_')


def test_external_links_and_images_have_no_file_id():
    result = render('<a href="https://docs.google.com/document/d/1">Doc</a><img src="https://example.org/a.png">')
    assert all('file_id' not in media and media['url'] for media in result['media'])


def test_signed_link_on_foreign_storage_still_hidden_but_identified():
    [media] = render('<a class="fr-file" href="https://bucket.s3.amazonaws.com/a.pdf?X-Amz-Signature=1&X-Amz-Expires=60">a.pdf</a>')['media']
    assert 'url' not in media and media['file_id'].startswith('f_')


async def test_class_file_with_signed_download_has_file_id_only():
    info = ('{"id":601,"name":"Revision.pdf","download_url":'
            '"/uploads/asset/file/601/revision.pdf?Expires=9&Signature=s&Key-Pair-Id=K"}')
    html = f"<main id=\"class-files\"><h2>Files (1)</h2><div class=\"row file\" data-ec3-info='{info}'></div></main>"
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=html, headers={'content-type': 'text/html'}))
    async with httpx.AsyncClient(transport=transport) as client:
        result = await get_class_files(client, ORIGIN, {'class_id': '10'})
    [item] = result['files']
    assert item['id'] == '601' and item['file_id'].startswith('f_') and 'url' not in item
    assert 'Signature' not in json.dumps(result)
    validate(result, FILES.outputSchema)
