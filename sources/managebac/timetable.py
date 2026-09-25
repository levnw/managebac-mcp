"""Current timetable only; never guess the year or silently substitute a week."""
import re
from urllib.parse import urlsplit, parse_qs
from onboarding.transport import FlowError
from diagnostics import layout_evidence
from .pages import document, text, verify_identity


def cell_records(cell, days, period):
    items = cell.select('a.f-timetable-item')
    if not items:
        if text(cell).casefold() in ('', '-', '—', 'no classes'): return []
        if cell.select_one('a[href], [data-bs-content-url], .f-box-item__body'):
            raise FlowError('layout_changed', 'A timetable class-like item has an unsupported layout.')
        return [{'day_display': day, 'period': period, 'text': text(cell)} for day in days]
    records = []
    for item in items:
        content = item.select_one('.f-box-item__body')
        name = text(content.select_one('p.fw-semibold')) if content else ''
        if not name:
            # Live (25 Sep): timetable items without a class name exist (the legacy
            # reader skipped them). Keep their displayed text as a note, never a class.
            layout_evidence(unnamed_timetable_item=['.'.join([n.name, *n.get('class', [])])
                                                    for n in [item, *item.select('*')]])
            if text(item):
                records.append({'day_display': days[0], 'period': period, 'text': text(item)})
            continue
        slot = {'day_display': days[0], 'period': period, 'class_name': name}
        times = text(content.select_one('small.color-secondary'))
        if times: slot['time_display'] = times
        values = parse_qs(urlsplit(item.get('data-bs-content-url', '')).query).get('ib_class_id', [])
        if len(values) == 1 and re.fullmatch(r'[0-9]{1,20}', values[0]):
            slot['class_id'] = values[0]
        # Preserve display lines without guessing whether a line is a teacher or a room.
        details = [text(p) for p in content.select('p')
                   if not {'fw-semibold', 'mt-1'} & set(p.get('class', [])) and text(p)]
        if details: slot['details'] = details
        records.append(slot)
    return records


def parse_timetable(html, origin):
    soup = document(html)
    verify_identity(soup, origin, '/student/timetables')
    table = soup.select_one('table.f-timetable')
    if table is None: raise FlowError('layout_changed', 'The timetable table was not recognized.')
    headers = table.select('thead tr th')[1:]
    days = [text(h) for h in headers]
    body = table.select_one('tbody')
    if not days or any(not day for day in days) or body is None:
        raise FlowError('layout_changed', 'The timetable day headers or body were not recognized.')
    slots, notes = [], []
    # Merged cells are placed on the displayed grid. A class spanning periods is
    # one slot with period..period_end, never repeated or guessed per period.
    covering = {}  # column -> [records from the merged cell, remaining rows]
    for row in body.find_all('tr', recursive=False):
        period = text(row.find('th', recursive=False))
        if not period:
            raise FlowError('layout_changed', 'A timetable row has no period label.')
        grid, sources, started = [None] * len(days), iter(row.find_all('td', recursive=False)), {}
        for column in range(len(days)):
            if grid[column] is not None: continue
            if column in covering:
                records, remaining = covering.pop(column)
                for record in records: record['period_end'] = period
                if remaining > 1: started[column] = [records, remaining - 1]
                grid[column] = True
                continue
            cell = next(sources, None)
            if cell is None:
                raise FlowError('layout_changed', 'A timetable row does not align with its day headers.')
            spans = [cell.get(name, '1') for name in ('colspan', 'rowspan')]
            if not all(re.fullmatch(r'[1-9][0-9]?', str(span)) for span in spans):
                raise FlowError('layout_changed', 'Unsupported timetable cell span; no dates were guessed.')
            columns, rows = map(int, spans)
            if column + columns > len(days) or (columns > 1 and cell.select_one('a.f-timetable-item')):
                raise FlowError('layout_changed', 'A timetable cell spans days ambiguously.')
            records = cell_records(cell, days[column:column + columns], period)
            for offset in range(columns):
                grid[column + offset] = cell
                if rows > 1:
                    started[column + offset] = [[r for r in records if r['day_display'] == days[column + offset]], rows - 1]
            for record in records:
                (slots if 'class_name' in record else notes).append(record)
        if next(sources, None) is not None:
            raise FlowError('layout_changed', 'A timetable row does not align with its day headers.')
        covering = started
    if covering:
        raise FlowError('layout_changed', 'A merged timetable cell extends past the last period.')
    if len(slots) + len(notes) > 1000: raise FlowError('result_too_large', 'The timetable exceeds 1000 entries.')
    return {'days': days, 'slots': slots, **({'notes': notes} if notes else {})}
