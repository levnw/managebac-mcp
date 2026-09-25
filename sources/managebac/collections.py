"""Shared complete-list traversal. Parsers remain pure and entity-specific."""
from urllib.parse import urlsplit
from diagnostics import event
from onboarding.transport import FlowError
from .pages import fetch_html, MAX_PAGES

MAX_RECORDS = 1000


async def collect(client, origin, path, parser, *, max_pages=MAX_PAGES, max_records=MAX_RECORDS,
                  merge_identical=False):
    """Read every page of one listing, or raise; never return a partial list.

    `parser(html, url)` returns `(rows, next_url)` or `(rows, source_total, next_url)`.
    A source total, when shown, must stay constant and match the records read.
    Repeated IDs mean the list changed, unless `merge_identical` allows a page
    to repeat an identical record (observed on enrolled-class pages).
    """
    current, visited, records, index, total, weight = origin + path, set(), [], {}, None, 0
    while current:
        if current in visited or len(visited) >= max_pages:
            raise FlowError('pagination_loop', f'The listing repeats or exceeds {max_pages} pages.')
        visited.add(current)
        p = urlsplit(current)
        page = parser(await fetch_html(client, origin, p.path + ('?' + p.query if p.query else '')), current)
        rows, expected, current = (page[0], None, page[1]) if len(page) == 2 else page
        if expected is not None:
            if total is not None and expected != total:
                raise FlowError('list_changed', 'The listing total changed during retrieval.')
            total = expected
            if total > max_records:
                raise FlowError('result_too_large', f'The listing exceeds {max_records} records. No partial list was returned.')
        for row in rows:
            key = (row.get('class_id'), row['id'])
            if key in index:
                if merge_identical and index[key] == row: continue
                raise FlowError('list_changed', 'Duplicate or conflicting records were found; no partial result was returned.')
            index[key] = row
            records.append(row)
            weight += 1 + len(row.get('replies', []))
        if weight > max_records:
            raise FlowError('result_too_large', f'The listing exceeds {max_records} records.')
        if total is not None and len(records) > total:
            raise FlowError('count_mismatch', 'More records were read than the source reports. No partial list was returned.')
    if total is not None and len(records) != total:
        raise FlowError('count_mismatch', 'Retrieved records do not match the source total. No partial list was returned.')
    if total is None:
        event('list.source_total_unavailable_pagination_followed', count=len(records))
    return records
