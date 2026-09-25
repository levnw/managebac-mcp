"""Class Files listing with explicit folder scope and opt-in recursive traversal."""
from collections import deque
from urllib.parse import urlsplit
from pydantic import Field
from onboarding.transport import FlowError
from diagnostics import event
from sources.managebac.pages import fetch_html, MAX_PAGES
from sources.managebac.files import parse_page
from .retrieval import execute
from sources.managebac.collections import MAX_RECORDS
from .file_output import compact_files
from .contracts import NoArguments, definition
from .output_schemas import array, ID, URL, FILE, FOLDER


class Arguments(NoArguments):
    class_id: str = Field(pattern=r'^\d{1,20}$', description='Class ID from get_classes.')
    folder_id: str | None = Field(default=None, pattern=r'^\d{1,20}$', description='Folder ID from this tool; omit for class root.')
    recursive: bool = Field(default=False, description='False lists only this directory; true also traverses its returned descendant folders.')


DEFINITION = definition('get_class_files', Arguments,
    'List the Files section of one class, at its root or a returned folder ID. Default reads only '
    'the selected folder with all its list pages; recursive=true also visits descendant folders. '
    'Returns compact files (name, stable file_id, url when it does not expire, available native id, size, '
    'modified time, uploader, tags and Markdown description) and folders (id, name, url, optional parent_id). '
    'Root entries omit folder_id/parent_id. The top-level url opens the selected Files directory; recursive states '
    'whether descendants were read. A folder listed with recursive=false has not been opened. These are class '
    'resources, not task attachments or student submissions. File contents and external links are not fetched. '
    'Expiring signed download links are omitted; open those files from the directory url. file_id and id are '
    'ManageBac-derived, not ChatGPT file IDs. Empty/unrecognized/error states are distinct. '
    'No login, tasks or other class requests. Use a selected folder if the listing is too large.',
    {'class_id': ID, 'folder_id': ID, 'url': URL, 'recursive': {'type': 'boolean'},
     'files': array(FILE), 'folders': array(FOLDER)},
    required=['class_id', 'url', 'recursive', 'files', 'folders'], title='Get class files',
    invoking='Reading class files…', invoked='Read class files',
    limits='50 pages, 1000 entries across the whole call')


async def get_class_files(client, origin: str, arguments: dict):
    async def collect(args):
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
                  'folders': [{key: value for key, value in item.items() if value is not None}
                              for item in folders.values()]}
        if args.folder_id: result['folder_id'] = args.folder_id
        # Operational qualification belongs in opt-in diagnostics, not model JSON.
        event('files.source_total_unverified_pagination_followed', count=len(files))
        return result
    return await execute(Arguments, arguments, collect)
