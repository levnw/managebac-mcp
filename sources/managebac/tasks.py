"""Task list/detail interpretation; no requests, authentication or other entities."""
import re
from urllib.parse import urljoin, urlsplit
from onboarding.transport import FlowError, school_origin
from diagnostics import event, layout_evidence
from .pages import document, text, count_heading, next_page, verify_identity, outermost


def task_link(href, origin: str, class_id: str):
    p = urlsplit(urljoin(origin, href))
    match = re.fullmatch(r'/student/classes/' + re.escape(class_id) + r'/core_tasks/(\d{1,20})', p.path)
    if not match or school_origin(p.geturl()) != origin or p.query or p.fragment:
        raise FlowError('invalid_task', 'A task link does not belong to the requested class.')
    return match[1], origin + p.path


LEVELS = {'HL', 'SL', 'HL/SL', 'SL/HL'}


def metadata(scope) -> dict:
    """Read dedicated fields; never infer status/grades from title or prose."""
    output = {}
    fields = {'due_display': '.due-date, .task-due-date', 'assessment_type': '.task-type, .assessment-type'}
    for field, selector in fields.items():
        value = text(scope.select_one(selector))
        if value: output[field] = value
    when = scope.select_one('.due-date time[datetime], time.due-date[datetime], .task-due-date time[datetime]')
    if when: output['due_source'] = when['datetime']
    # Observed (saved task page, 25 Sep): <div class="date-badge"><div class="month">Sep</div>
    # <div class="day">17</div></div>. Month and day only; the year is not shown.
    badge = scope.select_one('.date-badge')
    if badge is not None:
        month, day = text(badge.select_one('.month')), text(badge.select_one('.day'))
        if month and day: output['due_month_day'] = f'{month} {day}'
    # Live evidence (25 Sep): a row can carry a level badge ("HL") and a status badge
    # (<span class="badge" data-bs-title="Waiting"><span class="badge-label">Pending</span>).
    badges = [text(n) for n in scope.select('.task-status, .badge[data-bs-title] .badge-label, .badge-label') if text(n)]
    levels = [b for b in dict.fromkeys(badges) if b.upper() in LEVELS]
    statuses = [b for b in dict.fromkeys(badges) if b.upper() not in LEVELS]
    if statuses: output['status'] = statuses[0]
    if levels: output['level'] = levels[0]
    # The task's own labels ("Formative", "Classwork") sit in .label-and-due; unit labels elsewhere do not count.
    tags = list(dict.fromkeys(text(n) for n in scope.select(
        '.task-tags .tag, .tags .tag, [data-task-tag], .label-and-due .labels-set .label') if text(n)))
    if tags: output['tags'] = tags
    # Preserve source labels/values without guessing a year, timezone or scale.
    labels = {}
    for dt in scope.select('dl dt'):
        dd = dt.find_next_sibling('dd')
        if text(dt) and dd is not None: labels[text(dt)] = text(dd)
    if labels: output['fields'] = labels
    return output


def parse_list(html: str, origin: str, class_id: str, current: str):
    soup = document(html)
    base = f'/student/classes/{class_id}/core_tasks'
    verify_identity(soup, origin, urlsplit(current).path)
    scope = soup.select_one('#core_tasks, .core-tasks, .task-list') or soup.select_one('main') or soup
    rows, ids = [], set()
    for card in outermost(scope.select('.fusion-card-item, [data-task-id]')):
        links = [a for a in card.select('a[href]') if re.search(r'/core_tasks/\d+(?:$|[?#])', a['href'])]
        titles = [a for a in links if text(a) and text(a) not in ('Submit Coursework', 'View Teacher Feedback')]
        if not titles:
            raise FlowError('layout_changed', 'A task row has no recognizable title link.')
        parsed = [task_link(a['href'], origin, class_id) for a in titles]
        if len({p[0] for p in parsed}) != 1:
            raise FlowError('invalid_task', 'A task row refers to multiple tasks.')
        task_id, url = parsed[0]
        title = text(titles[0])
        if len(title) > 1000: raise FlowError('invalid_task', 'A task title exceeds its limit.')
        if any(node['data-task-id'] != task_id for node in [card, *card.select('[data-task-id]')] if node.get('data-task-id')):
            raise FlowError('identity_mismatch', 'A task ID conflicts with its source link.')
        if task_id in ids: raise FlowError('list_changed', 'Duplicate task rows were found on a single page.')
        ids.add(task_id)
        rows.append({'id': task_id, 'title': title, 'url': url, **metadata(card)})
    total = count_heading(scope, 'Tasks')
    if total is None: total = count_heading(soup, 'Tasks')
    if not rows:
        empty = scope.select_one('.empty-state, .no-results, .blank-slate')
        # Observed live (25 Sep, owner-confirmed classes without tasks): the class's
        # own task page shows an 'All Tasks' heading and links to no task at all.
        no_tasks_page = (any(text(h).casefold() == 'all tasks' for h in scope.select('h1,h2,h3,h4'))
                         and not scope.select_one('a[href*="/core_tasks/"]'))
        if no_tasks_page:
            event('tasks.empty_all_tasks_without_task_links')
        elif total != 0 and not (empty and re.search(r'\bno tasks\b', text(empty), re.I)):
            # Structure only, so the unrecognised layout can be supported from evidence.
            layout_evidence(
                headings=[text(h) for h in scope.select('h1,h2,h3,h4') if text(h)],
                empty_like=[f"{'.'.join(n.get('class', []))}: {text(n)}" for n in
                            scope.select('[class*=empty], [class*=blank], [class*=placeholder], '
                                         '[class*=no-results], [class*=no-data], [class*=no-items]')
                            if 0 < len(text(n)) <= 80],
                main_children=['.'.join([c.name, *c.get('class', [])]) for c in scope.find_all(recursive=False)],
                candidate_rows=[f'{selector}={len(scope.select(selector))}' for selector in
                                ('.fusion-card-item', '[data-task-id]', 'a[href*="/core_tasks/"]', 'table tr', '.f-task-tile')],
                # Only when the page links to no task at all: its text is interface
                # chrome (filters, empty message), so record it to learn the wording.
                interface_text=[] if scope.select_one('a[href*="/core_tasks/"]') else
                    [text(scope.select_one('section.f-layout-main__content') or scope)[:300]],
                text_classes=list(dict.fromkeys('.'.join([n.name, *n.get('class', [])]) for n in scope.select('*')
                    if n.find(string=True, recursive=False) and n.find(string=True, recursive=False).strip()))[-12:])
            raise FlowError('layout_changed', 'No recognized task rows or explicit empty-task state were found.')
    if len(rows) > 200: raise FlowError('page_too_large', 'The task list page exceeds 200 records.')
    return rows, total, next_page(soup, origin, base, current)

