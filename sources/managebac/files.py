"""One class Files directory page, including its immediate subfolder references."""
import json
import re
from urllib.parse import urlsplit, urljoin
from onboarding.transport import FlowError, school_origin
from .pages import document, text, next_page, verify_identity, count_heading, outermost
from .rich_text import RichText
from diagnostics import event, layout_evidence


def file_info(raw: str) -> dict:
    if len(raw) > 100_000:
        raise FlowError('invalid_file', 'File metadata exceeds its limit.')
    # Parse only explicit JSON encoding layers. Never globally replace slashes:
    # doing that corrupts filenames, Unicode, and signed download URLs.
    value = raw.strip()
    for _ in range(3):
        if isinstance(value, dict): return value
        if not isinstance(value, str): break
        if value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        try: value = json.loads(value)
        except (ValueError, TypeError): break
    if isinstance(value, dict): return value
    raise FlowError('unsupported_file_metadata', 'File metadata is malformed or uses an unsupported encoding. No files were silently skipped.')


def parse_page(html: str, origin: str, class_id: str, folder_id: str | None, current: str):
    soup = document(html)
    base = f'/student/classes/{class_id}/files' + (f'/folder/{folder_id}' if folder_id else '')
    verify_identity(soup, origin, urlsplit(current).path)
    scope = soup.select_one('#class-files, .class-files, .files-list') or soup.select_one('main') or soup
    rich = RichText(origin, origin + base)
    files, folders = [], []
    # Support mixed layouts without dropping table rows when JSON rows exist.
    # Nested metadata wrappers describe the same row, not a second file.
    rows = outermost(scope.select('[data-ec3-info], tr.file'))
    for row in rows:
        info = file_info(row['data-ec3-info']) if row.has_attr('data-ec3-info') else {}
        a = row.select_one('a.file-name[href], a.text-break[href], .details a[href], a[download][href]')
        name = info.get('name') or text(a)
        if not isinstance(name, str) or not name.strip() or len(name) > 1000:
            raise FlowError('invalid_file', 'A file has no valid filename.')
        href = info.get('download_url') or (a.get('href') if a else None)
        if not isinstance(href, str):
            raise FlowError('invalid_file', 'A file has no download address.')
        if urlsplit(urljoin(origin + base, href)).scheme != 'https':
            raise FlowError('invalid_file', 'A file download address must use HTTPS.')
        ref = rich.asset(href, 'file', name)
        if not ref: raise FlowError('invalid_file', 'A file download address could not be validated.')
        match = re.search(r'/uploads/asset/file/(\d{1,20})(?:/|$)', urlsplit(urljoin(origin, href)).path)
        native = info.get('id') if info.get('id') is not None else (match[1] if match else None)
        if native is not None and not re.fullmatch(r'\d{1,20}', str(native)):
            raise FlowError('invalid_file', 'The file ID has an unexpected format.')
        if native is not None and match and str(native) != match[1]:
            raise FlowError('identity_mismatch', 'File metadata and download address identify different files.')
        item = {'ref': ref, 'name': name, 'folder_id': folder_id}
        if native is not None: item['id'] = str(native)
        if 'file_size' in info:
            size = info['file_size']
            if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                raise FlowError('invalid_file', 'The file byte size is not a nonnegative integer.')
            item['size_bytes'] = size
        else:
            size = re.search(r'\b\d+(?:\.\d+)?\s*(?:KB|MB|GB|bytes)\b', text(row), re.I)
            if size: item['size_display'] = size[0]
        for field in ('created_at', 'updated_at', 'content_type'):
            if info.get(field):
                if not isinstance(info[field], str): raise FlowError('invalid_file', 'A file metadata field has an unexpected type.')
                item[field] = info[field]
        author = row.select_one('.author-name, .uploader, label')
        if text(author): item['uploaded_by'] = re.sub(r'^by\s+', '', text(author), flags=re.I)
        description = row.select_one('.file-description, .description')
        if description is not None: item['description'] = rich.parse(description)
        tags = list(dict.fromkeys(text(t) for t in row.select('.tags .tag, .file-tags .tag') if text(t)))
        if tags: item['tags'] = tags
        files.append(item)
    folder_pattern = re.compile(r'/student/classes/' + re.escape(class_id) + r'/files/folder/(\d{1,20})')
    seen = set()
    for a in scope.select('a[href]'):
        if a.find_parent(class_='breadcrumb') or a.find_parent('nav'): continue
        p = urlsplit(urljoin(origin + base, a['href']))
        m = folder_pattern.fullmatch(p.path)
        if not m or p.query or p.fragment or m[1] == folder_id: continue
        if school_origin(p.geturl()) != origin: raise FlowError('invalid_folder', 'A folder link leaves this school.')
        if not text(a): raise FlowError('invalid_folder', 'A folder has no displayed name.')
        if m[1] in seen:
            if any(f['id'] == m[1] and f['name'] != text(a) for f in folders):
                raise FlowError('folder_conflict', 'A folder has conflicting displayed names.')
            continue
        seen.add(m[1])
        folders.append({'id': m[1], 'name': text(a), 'parent_id': folder_id, 'url': origin + p.path})
    empty = scope.select_one('.empty-state, .no-results, .blank-slate')
    total = count_heading(scope, 'Files')
    file_like = scope.select_one('[data-ec3-info], tr.file, a[href*="/uploads/"], a[href*="/attachments/"]')
    # Live (25 Sep, six classes): an empty Files page shows <div class="h4">No files</div>
    # and "No files have been uploaded yet." with no file links at all.
    no_files_page = not file_like and any(text(n).casefold() == 'no files' for n in scope.select('.h4, h3, h4'))
    if no_files_page:
        event('files.empty_no_files_uploaded')
    elif not files and not folders and total != 0 and not (empty and re.search(r'\bno files\b', text(empty), re.I)):
        # Structure only (and interface text when nothing file-like is present), so an
        # unrecognised Files page can be supported from evidence rather than guessed.
        layout_evidence(
            headings=[text(h) for h in scope.select('h1,h2,h3,h4') if text(h)],
            main_children=['.'.join([c.name, *c.get('class', [])]) for c in scope.find_all(recursive=False)],
            candidate_rows=[f'{selector}={len(scope.select(selector))}' for selector in
                            ('[data-ec3-info]', 'tr.file', '.file', 'a[href*="/files/folder/"]', 'a[href*="/uploads/"]')],
            interface_text=[] if file_like else [text(scope.select_one('section.f-layout-main__content') or scope)[:300]],
            text_classes=list(dict.fromkeys('.'.join([n.name, *n.get('class', [])]) for n in scope.select('*')
                if n.find(string=True, recursive=False) and n.find(string=True, recursive=False).strip()))[-12:])
        raise FlowError('layout_changed', 'The file listing or an explicit empty state was not recognized.')
    if len(files) + len(folders) > 200:
        raise FlowError('page_too_large', 'The file page exceeds 200 entries.')
    return rich.finish({'files': files, 'folders': folders}), next_page(soup, origin, base, current)
