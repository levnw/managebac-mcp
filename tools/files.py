"""Files in layers: a class's Files section (folders), or the files attached to one task."""
from collections import deque
from urllib.parse import urlsplit
from pydantic import Field, model_validator
from onboarding.transport import FlowError
from diagnostics import event
from sources.managebac.collections import MAX_RECORDS
from sources.managebac.files import parse_page
from sources.managebac.pages import fetch_html, MAX_PAGES
from .contracts import NoArguments, definition
from .file_output import compact_files
from .output_schemas import array, obj, ID, S, URL, FILE, FILE_ID, FOLDER
from .retrieval import execute
from .tasks import read_task
from .dates import ISO_DATE, shown_date, iso_day, valid_range, within
from .output_schemas import DATE

NUMERIC = r'^[0-9]{1,20}$'
ATTACHMENT_KINDS = {'file', 'image', 'preview'}   # links and embedded players are not files


class Arguments(NoArguments):
    class_id: str = Field(pattern=NUMERIC, description='Class ID from get_classes.')
    task_id: str | None = Field(default=None, pattern=NUMERIC,
                                description="Task layer: a task ID from get_tasks; returns that task's attached files.")
    folder_id: str | None = Field(default=None, pattern=NUMERIC,
                                  description='Class layer: a folder ID from this tool; omit for the Files root.')
    recursive: bool = Field(default=False, description='Class layer: also read every descendant folder.')
    date_from: str = Field(default='', pattern=f'{ISO_DATE}|^$',
                           description='Optional: file dated on or after YYYY-MM-DD (class files: last modified; task files: posted).')
    date_to: str = Field(default='', pattern=f'{ISO_DATE}|^$', description='Optional: file dated on or before YYYY-MM-DD.')

    @model_validator(mode='after')
    def one_layer(self):
        if self.task_id and (self.folder_id or self.recursive):
            raise ValueError('folder_id and recursive apply to class files, not to a task.')
        valid_range(self.date_from, self.date_to)
        return self


TASK_FILE = obj({'source': {'enum': ['description', 'teacher_resource', 'submission']},
                 'kind': {'enum': sorted(ATTACHMENT_KINDS)}, 'name': S, 'file_id': FILE_ID, 'url': URL,
                 'size_display': S, 'resource_title': S, 'author': S, 'posted_display': S, 'posted_date': DATE},
                ('source', 'kind'))

DEFINITION = definition('get_files', Arguments,
    'Files in layers. CLASS layer (class_id, optional folder_id and recursive): the class Files section, with '
    'files (name, stable file_id, url when it does not expire, native id, size, modified time, uploader, tags, '
    'description) and folders; a folder listed without recursive has not been opened. TASK layer (class_id + '
    'task_id): every file attached to that task, labelled by source: description (in the instructions), '
    'teacher_resource, or submission (files the student uploaded to that task; these are the student\'s own work). '
    'Optional date_from/date_to (YYYY-MM-DD) filter by date: last modified for class files, posted date for task '
    'files; files whose date could not be read are listed in undated, never silently dropped. Every school-stored '
    'file has a stable file_id across both layers. File contents are not read or downloaded; expiring download links are omitted, so '
    'send the student to the returned url. file_id is ManageBac-derived, not a ChatGPT file ID.',
    {'class_id': ID, 'task_id': ID, 'folder_id': ID, 'url': URL, 'recursive': {'type': 'boolean'},
     'files': array({'anyOf': [FILE, TASK_FILE]}), 'folders': array(FOLDER),
     'undated': array(obj({'name': S, 'file_id': FILE_ID, 'source': S}, ('name',)))},
    required=['class_id', 'url', 'files'], title='Get files', invoking='Reading files…', invoked='Read files',
    limits='class layer: 50 pages, 1000 entries; task layer: one 2 MB task page')


def task_files(task: dict) -> list[dict]:
    """Flatten a compact task's attachments, keeping where each file came from."""
    found = []
    def add(source, media, **context):
        for item in media or []:
            if item.get('kind') in ATTACHMENT_KINDS and (source != 'description' or item['kind'] == 'file'):
                entry = {'source': source, **{k: item[k] for k in ('kind', 'name', 'file_id', 'url', 'size_display') if k in item}}
                entry.update({k: v for k, v in context.items() if v})
                posted = shown_date(entry.get('posted_display', ''))
                if posted: entry['posted_date'] = posted
                found.append(entry)
    add('description', task.get('media'))
    for resource in task.get('teacher_resources', []):
        context = dict(resource_title=resource.get('title'), author=resource.get('author'),
                       posted_display=resource.get('posted_display'))
        add('teacher_resource', resource.get('media'), **context)
        add('teacher_resource', resource.get('previews'), **context)
    for upload in task.get('submission', {}).get('files', []):
        context = dict(author=upload.get('author'), posted_display=upload.get('posted_display'))
        add('submission', upload.get('media'), **context)
        add('submission', upload.get('previews'), **context)
    return found


async def class_files(client, origin, args) -> dict:
    queue = deque([args.folder_id])
    visited, queued, files, folders = set(), {args.folder_id}, {}, {}
    root_url = origin + f'/student/classes/{args.class_id}/files' + (f'/folder/{args.folder_id}' if args.folder_id else '')
    while queue:
        folder = queue.popleft()
        url = origin + f'/student/classes/{args.class_id}/files' + (f'/folder/{folder}' if folder else '')
        while url:
            if url in visited or len(visited) >= MAX_PAGES:
                raise FlowError('pagination_loop', 'File/folder traversal repeats or exceeds 50 pages.')
            visited.add(url)
            p = urlsplit(url)
            html = await fetch_html(client, origin, p.path + ('?' + p.query if p.query else ''))
            page, url = parse_page(html, origin, args.class_id, folder, url)
            for item in compact_files(page):
                key = (folder, item.get('id') or item.get('file_id') or item.get('url'))
                if key in files:
                    raise FlowError('list_changed', 'A file repeats across pages; no potentially incomplete listing was returned.')
                files[key] = item
            for item in page['folders']:
                fid = item['id']
                if fid in folders and folders[fid] != item:
                    raise FlowError('folder_conflict', 'A folder has conflicting names or parents.')
                folders[fid] = item
                if args.recursive and fid not in queued:
                    queue.append(fid); queued.add(fid)
                elif args.recursive and fid == args.folder_id:
                    raise FlowError('folder_cycle', 'A descendant links back to the starting folder.')
            event('files.page_parsed', count=len(page['files']) + len(page['folders']))
            if len(files) + len(folders) > MAX_RECORDS:
                raise FlowError('result_too_large', 'File traversal exceeds 1000 entries. Request a smaller folder.')
    result = {'class_id': args.class_id, 'url': root_url, 'recursive': args.recursive,
              'files': list(files.values()),
              'folders': [{key: value for key, value in item.items() if value is not None} for item in folders.values()]}
    if args.folder_id: result['folder_id'] = args.folder_id
    # Operational qualification belongs in opt-in diagnostics, not model JSON.
    event('files.source_total_unverified_pagination_followed', count=len(files))
    return result


def by_date(result: dict, args, date_of) -> dict:
    """Apply the date filter; files without a readable date go to undated, never vanish."""
    if not (args.date_from or args.date_to): return result
    kept, undated = [], []
    for item in result['files']:
        day = date_of(item)
        if day is None:
            undated.append({'name': item.get('name', '(unnamed)'), **{k: item[k] for k in ('file_id', 'source') if k in item}})
        elif within(day, args.date_from, args.date_to):
            kept.append(item)
    return {**result, 'files': kept, **({'undated': undated} if undated else {})}


async def get_files(client, origin: str, arguments: dict):
    async def run(args):
        if args.task_id:
            task = await read_task(client, origin, args.class_id, args.task_id)
            result = {'class_id': args.class_id, 'task_id': args.task_id, 'url': task['url'], 'files': task_files(task)}
            return by_date(result, args, lambda item: item.get('posted_date'))
        return by_date(await class_files(client, origin, args), args, lambda item: iso_day(item.get('updated_at')))
    return await execute(Arguments, arguments, run)
