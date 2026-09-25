"""Consolidated deadline tiles, with filter-preserving pagination."""
import re
from urllib.parse import urljoin, urlsplit, parse_qs, urlencode
from onboarding.transport import FlowError, school_origin
from .pages import document, text, verify_identity
from .tasks import task_link, metadata


def parse_upcoming(html, origin, view, current):
    soup = document(html)
    verify_identity(soup, origin, '/student/tasks_and_deadlines')
    scope = soup.select_one('.js-tasks')
    if scope is None: raise FlowError('layout_changed', 'The consolidated deadline list was not recognized.')
    rows = []
    for tile in scope.select('.f-task-tile'):
        link = tile.select_one('a.f-tile__title-link[href]')
        match = re.fullmatch(r'/student/classes/([0-9]{1,20})/core_tasks/[0-9]{1,20}',
                             urlsplit(urljoin(origin, link['href'])).path) if link else None
        if not match or not text(link): raise FlowError('layout_changed', 'A deadline tile was not recognized.')
        class_id = match[1]
        task_id, url = task_link(link['href'], origin, class_id)
        row = {'id': task_id, 'class_id': class_id, 'title': text(link), 'url': url, **metadata(tile)}
        group = tile.find_previous('p', role='heading')
        if group and scope in group.parents: row['due_group'] = text(group)
        rows.append(row)
    if not rows and not any(re.fullmatch(r'No (?:tasks|deadlines)(?: available| found| due)?[.!]?', text(n), re.I)
                           for n in scope.select('.empty-state, .blank-slate, .no-results')):
        raise FlowError('layout_changed', 'No deadline tiles or explicit empty state were recognized.')
    candidates = set()
    page = int(parse_qs(urlsplit(current).query).get('page', ['1'])[0])
    for link in soup.select('.pagination a[href], a[rel~=next][href]'):
        label = text(link).casefold()
        is_next = 'next' in link.get('rel', []) or label in ('next', 'next ›', 'next »')
        if not is_next and not label.isdecimal(): continue
        p = urlsplit(urljoin(current, link['href']))
        query = parse_qs(p.query, keep_blank_values=True)
        if (school_origin(p.geturl()) != origin or p.path != '/student/tasks_and_deadlines'
                or p.fragment or set(query) - {'view', 'page'}
                or query.get('view', [view]) != [view] or len(query.get('page', [])) != 1
                or not re.fullmatch(r'[1-9][0-9]{0,3}', query['page'][0])):
            raise FlowError('invalid_pagination', 'Deadline pagination changes its scope.')
        number = int(query['page'][0])
        if is_next: candidates.add(origin + p.path + '?' + urlencode({'view': view, 'page': number}))
    if len(candidates) > 1: raise FlowError('invalid_pagination', 'Conflicting next deadline pages were found.')
    if not candidates and any(text(a).isdecimal() and int(text(a)) > page for a in soup.select('.pagination a')):
        raise FlowError('invalid_pagination', 'More deadline pages exist without a recognized next link.')
    return rows, next(iter(candidates), None)
