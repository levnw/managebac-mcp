"""Unit summaries and explicit detail fragments, based on legacy observed markup."""
import re
from urllib.parse import urlsplit
from onboarding.transport import FlowError
from .pages import document, text, next_page, verify_identity


def parse_units(html, origin, class_id, current):
    soup = document(html)
    verify_identity(soup, origin, urlsplit(current).path)
    rows = []
    pattern = re.compile(r'ib_class_' + re.escape(class_id) + r'_core_unit_([0-9]{1,20})$')
    for node in soup.find_all(id=pattern):
        unit_id = pattern.fullmatch(node['id'])[1]
        component = node.select_one('.unit-component')
        title = text(component.select_one('p.h4 a')) if component else ''
        if not title:
            raise FlowError('layout_changed', 'A unit title could not be identified.')
        row = {'id': unit_id, 'title': title,
               'url': origin + f'/student/classes/{class_id}/units/{unit_id}/presentations'}
        for key, selector in (('start_display', '.label-start'), ('duration', '.unit-duration')):
            value = text(component.select_one(selector))
            if value: row[key] = value
        # Absence of a status class does not prove that the unit is upcoming.
        statuses = set(component.get('class', [])) & {'current', 'completed', 'upcoming'}
        if len(statuses) > 1: raise FlowError('layout_changed', 'Conflicting unit statuses were found.')
        if statuses: row['status'] = statuses.pop()
        rows.append(row)
    if not rows and not any(re.fullmatch(r'No units(?: available| found)?[.!]?', text(n), re.I)
                            for n in soup.select('.empty-state, .blank-slate, .no-results')):
        raise FlowError('layout_changed', 'No recognized units or explicit empty-unit state were found.')
    return rows, next_page(soup, origin, f'/student/classes/{class_id}/units', current)


def parse_unit(html, origin, class_id, unit_id):
    soup = document(html)
    verify_identity(soup, origin, f'/student/classes/{class_id}/units/{unit_id}/popup')
    sections = []
    for section in soup.select('.section'):
        header = section.select_one('.unit-component-header')
        if not header: continue
        title = text(header)
        header.extract()
        if title: sections.append((title, section))
    fields = {text(dt): text(dt.find_next_sibling('dd')) for dt in soup.select('dt')
              if text(dt) and dt.find_next_sibling('dd') is not None}
    if not sections and not fields:
        raise FlowError('layout_changed', 'The unit detail layout was not recognized.')
    if len(sections) + len(fields) > 1000:
        raise FlowError('result_too_large', 'The unit contains more than 1000 sections and fields.')
    return fields, sections
