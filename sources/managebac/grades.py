"""Locate published assessment blocks without extracting scores from prose."""
import re
from urllib.parse import urlsplit
from onboarding.transport import FlowError
from .pages import document, outermost
from .tasks import parse_list, task_link


def parse_grades(html, origin, class_id, current):
    tasks, _, following = parse_list(html, origin, class_id, current)
    by_id = {row['id']: row for row in tasks}
    soup = document(html)
    rows = []
    for card in outermost(soup.select('.fusion-card-item, [data-task-id]')):
        grade = card.select_one('.assessment-criteria, .task-grades, .grades')
        if grade is None:
            # Missing grades are ordinary. Explicit assessment UI with an unknown
            # structure, however, cannot be silently labelled ungraded.
            if card.select_one('[data-grade], [data-score], [data-criterion], .assessment, .grade, .criterion-score'):
                raise FlowError('assessment_layout_unverified', 'Assessment markup was found but could not be interpreted. No partial grades were returned.')
            continue
        links = [a for a in card.select('a[href]') if re.search(r'/core_tasks/[0-9]+$', urlsplit(a['href']).path)]
        if not links: raise FlowError('layout_changed', 'An assessment has no associated task.')
        task_id, _ = task_link(links[0]['href'], origin, class_id)
        if task_id not in by_id: raise FlowError('identity_mismatch', 'An assessment refers to an unknown task.')
        rows.append({**by_id[task_id], '_assessment': grade, '_feedback': card.select_one('.assessment-comments')})
    return rows, following
