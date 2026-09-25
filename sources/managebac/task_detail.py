"""One-page task detail adapter; independent of lists and network/session logic.

Historical markup is evidence for candidate layouts, not permission to guess
the first heading or to fetch related discussion/attachment pages.
"""
from copy import deepcopy
from urllib.parse import urlsplit, urljoin
from bs4 import Tag
from onboarding.transport import FlowError
from diagnostics import event
from .pages import document, text, verify_identity
from .rich_text import RichText

SECTIONS = {
    'description': ('.task-description, .core-task-description, .core-task-show .core-task-details .show-more', 'Description'),
    'resources': ('.core-task-resources, .task-resources', 'Resources'),
    'submissions': ('.task-dropbox, #dropbox, .core-task-dropbox', 'Dropbox'),
    'feedback': ('.assessment-comments, .task-feedback', 'Teacher Feedback'),
    'assessment': ('.task-assessment, .assessment-criteria', 'Assessment Criteria'),
    'history': ('.task-history', 'Task History'),
}
GENERIC_HEADINGS = {v[1].casefold() for v in SECTIONS.values()} | {'discussions', 'tasks', 'files'}


def inside(node, container):
    return node is container or any(parent is container for parent in node.parents)


def usable(node):
    return not any(p.name in ('nav', 'form', 'template', 'script', 'style') or
                   p.has_attr('hidden') or p.get('aria-hidden') == 'true'
                   for p in [node, *node.parents] if isinstance(p, Tag))


def section(scope, selectors, label):
    candidates = [n for n in scope.select(selectors) if usable(n)]
    # Nested wrappers for one section are not separate competing sections.
    candidates = [n for n in candidates if not any(n is not other and inside(n, other) for other in candidates)]
    if len(candidates) > 1:
        raise FlowError('ambiguous_task_layout', f'Multiple {label} sections require review.')
    if candidates: return candidates[0]
    heads = [h for h in scope.select('h1,h2,h3,h4,h5,h6,.h4') if usable(h) and text(h).casefold() == label.casefold()]
    if len(heads) > 1:
        raise FlowError('ambiguous_task_layout', f'Multiple {label} headings require review.')
    if not heads: return None
    heading = heads[0]
    if label == 'Task History' and heading.parent.name == 'section':
        return heading.parent
    anchor = heading
    sibling = anchor.find_next_sibling()
    # Observed Dropbox: h3 -> .f-title__body -> header.f-title -> content.
    # Climb only heading-only wrappers; never climb into the whole task/page.
    for _ in range(4):
        if sibling is not None: break
        parent = anchor.parent
        if parent is scope or not isinstance(parent, Tag) or text(parent) != text(heading): break
        anchor = parent
        sibling = anchor.find_next_sibling()
    if sibling is None or sibling.name in ('h1','h2','h3','h4','h5','h6'):
        raise FlowError('unsupported_task_layout', f'The {label} heading has no unambiguous content container.')
    if any(text(h).casefold() in GENERIC_HEADINGS for h in sibling.select('h1,h2,h3,h4,h5,h6')):
        raise FlowError('ambiguous_task_layout', f'The {label} container includes another task section.')
    return sibling


def title_from(scope, sections):
    blocked = [root for root in sections.values() if root is not None]
    def eligible(node):
        return usable(node) and text(node).casefold() not in GENERIC_HEADINGS and not any(inside(node, root) for root in blocked)
    task_titles = [n for n in scope.select('.core-task-show > .fusion-card-item .title') if eligible(n)]
    explicit = task_titles or [n for n in scope.select('.page-title, .task-title') if eligible(n)]
    candidates = explicit or [n for n in scope.select('h1,h2') if eligible(n)]
    titles = list(dict.fromkeys(text(n) for n in candidates if text(n)))
    if len(titles) != 1 or len(titles[0]) > 1000:
        event('task.title_unrecognized', count=len(titles))
        raise FlowError('ambiguous_task_title' if len(titles) > 1 else 'unsupported_task_layout',
                        'A unique task title could not be identified. The page layout needs review.')
    event('task.title_recognized')
    return titles[0]


def clean_resource_controls(content):
    """Remove observed resource chrome, never arbitrary instructional images.

    Only run on resource/submission rows, not task instructions. A second
    icon-only download control is redundant only when its exact URL already
    belongs to a named file link in this same row.
    """
    named_urls = {link['href'] for link in content.select('a.file-name[href], a.fr-file[href], a.text-break[href]')
                  if text(link)}
    for link in list(content.select('a.btn-icon[href]')):
        if link['href'] in named_urls and not text(link) and not link.has_attr('data-pdf-preview-url-value'):
            link.decompose()
    for icon in list(content.select('.resource-head-icon img, img.file-icon, svg[aria-hidden="true"]')):
        icon.decompose()


def parse_detail(html, origin, class_id, task_id):
    # Local import keeps list metadata separate without a module import cycle.
    from .tasks import metadata
    soup = document(html)
    path = f'/student/classes/{class_id}/core_tasks/{task_id}'
    verify_identity(soup, origin, path)
    scope = soup.select_one('main, [role=main]') or soup.body or soup
    # A detail wrapper's identity is meaningful; an arbitrary data-task-id on
    # a sidebar/card/action button is not an authoritative page container.
    for root in scope.select('.core-task[data-task-id], #core_task[data-task-id]'):
        if root['data-task-id'] != task_id:
            raise FlowError('identity_mismatch', 'The returned task ID does not match the request.')
    if scope.get('data-task-id') and scope['data-task-id'] != task_id:
        raise FlowError('identity_mismatch', 'The returned task ID does not match the request.')
    sections = {key: section(scope, *spec) for key, spec in SECTIONS.items()}
    # The observed page places task history outside main, in its details sidebar.
    if sections['history'] is None and scope.select_one('.core-task-show'):
        sidebar = soup.select_one('#sidebar_info')
        if sidebar is not None:
            sections['history'] = section(sidebar, *SECTIONS['history'])
    description = sections['description']
    if description is None:
        raise FlowError('unsupported_task_layout', 'The task description section was not recognized; an empty description was not assumed.')
    title = title_from(scope, sections)
    rich = RichText(origin, origin + path)
    details = scope.select_one('.task-metadata, .task-details')
    if details is not None and any(root is not None and inside(details, root) for root in sections.values()):
        details = None
    if details is None:
        # Never infer task status from an unrelated badge inside instructions,
        # resource posts, submissions or feedback.
        details = deepcopy(scope)
        for spec in SECTIONS.values():
            root = section(details, *spec)
            if root is not None: root.decompose()
    result = {'id': task_id, 'class_id': class_id, 'title': title, 'url': origin + path,
              **metadata(details), 'description': rich.parse(description)}
    # Observed (saved page, 25 Sep): the due date badge sits in the task header card
    # (.core-task-show > .fusion-card-item), outside the metadata block.
    if 'due_month_day' not in result:
        badge = next((b for b in scope.select('.date-badge')
                      if not any(root is not None and inside(b, root) for root in sections.values())), None)
        month, day = (text(badge.select_one('.month')), text(badge.select_one('.day'))) if badge else ('', '')
        if month and day: result['due_month_day'] = f'{month} {day}'
    dropbox = sections['submissions']
    # Only a recognized dropbox or a form posting within this task is evidence.
    # Generic help text mentioning upload/dropbox is deliberately ignored.
    forms = []
    for form in scope.select('form[action]'):
        target = urlsplit(urljoin(origin + path, form['action']))
        if target.scheme + '://' + target.netloc == origin and (target.path == path or target.path.startswith(path + '/')):
            if form.select_one('input[type=file]'):
                forms.append(form)
    roots = ([dropbox] if dropbox is not None else []) + forms
    result['submission_box'] = {'box': 'present' if roots else 'not_detected'}
    controls = [n for root in roots for n in root.select('input[type=file]')]
    # This layout opens an upload page rather than rendering a file input.
    for root in roots:
        for link in root.select('a[href]'):
            target = urlsplit(urljoin(origin + path, link['href']))
            if (target.scheme + '://' + target.netloc == origin and target.path == path + '/dropbox'
                    and text(link).casefold() == 'upload submission' and usable(link)
                    and 'd-none' not in link.get('class', [])):
                controls.append(link)
    if controls:
        enabled = [n for n in controls if not n.has_attr('disabled') and n.get('aria-disabled') != 'true'
                   and 'disabled' not in n.get('class', [])
                   and not n.find_parent('fieldset', disabled=True)]
        result['submission_box']['upload_control'] = 'enabled' if enabled else 'disabled'
    empty_submissions = dropbox is not None and any(text(n).casefold() == 'no dropbox submissions'
        for n in dropbox.select('.blank-slate-container .h4, .empty-state .h4'))
    if empty_submissions:
        if dropbox.select_one('tr.file, .submission-file'):
            raise FlowError('ambiguous_task_layout', 'The Dropbox shows both files and an empty-submission message.')
        result['submission_box']['files'] = []
    for key, root in sections.items():
        # History is located only so it is never mistaken for title/metadata.
        if key in ('description', 'history'): continue
        if root is None:
            result[key] = {'state': 'not_on_page'}
            continue
        rows = root.select('.resource-container') if key == 'resources' else root.select('tr.file, .submission-file') if key == 'submissions' else []
        if not rows:
            result[key] = {'state': 'present', 'content': [] if key == 'submissions' and empty_submissions else rich.parse(root)}
            continue
        groups = []
        for row in rows:
            item, content = {}, deepcopy(row)
            if key == 'submissions':
                for link in content.select('.details a.text-break[href], .details > a[href], a.text-break[href]'):
                    if not link.has_attr('data-pdf-preview-url-value'):
                        link['class'] = [*link.get('class', []), 'fr-file']
            for field, selector in {'author': '.author-name', 'posted_display': '.posted-date', 'title': '.resource-title'}.items():
                node = content.select_one(selector)
                if text(node): item[field] = text(node); node.decompose()
            # Legacy evidence: submission rows label their upload time "Uploaded <date>".
            uploaded = next((n for n in content.select('label') if text(n).startswith('Uploaded')), None)
            if key == 'submissions' and 'posted_display' not in item and uploaded is not None:
                item['posted_display'] = text(uploaded); uploaded.decompose()
            previews = []
            for node in content.select('[data-pdf-preview-url-value]'):
                raw = node['data-pdf-preview-url-value']
                if raw.startswith(('/', 'https://')):
                    ref = rich.asset(raw, 'preview', 'Document preview')
                    if ref: previews.append(ref)
                else: rich.warn('document_preview_requires_separate_retrieval')
                node.decompose()  # Preview controls are not downloadable files.
            clean_resource_controls(content)
            item['content'] = rich.parse(content)
            if previews: item['preview_refs'] = list(dict.fromkeys(previews))
            groups.append(item)
        result[key] = {'state': 'present', 'items': groups}
    event('task.sections_parsed', count=sum(root is not None for root in sections.values()))
    return rich.finish(result)
