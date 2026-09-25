"""Enrolled class pages only. No authentication, checks, or class detail requests."""
import re
from urllib.parse import urljoin, urlsplit
from onboarding.transport import FlowError, school_origin
from .pages import document, listing_url, next_page, text

ROUTE = '/student/classes/my'


def page_url(origin: str, link: str) -> str:
    return listing_url(origin, ROUTE, link)


def parse_page(html: str, origin: str, current: str | None = None):
    page = document(html)
    totals = [int(m[1]) for h in page.select('h2') if (m := re.fullmatch(r'My Classes\s*\((\d+)\)', text(h)))]
    if len(totals) != 1:
        raise FlowError('layout_changed', 'The enrolled-class list was not recognized. This is not an empty result.')
    tiles = page.select('.f-class-tile')
    if len(tiles) > 50:
        raise FlowError('page_too_large', 'This class page exceeds the safe record limit; nothing was silently truncated.')
    rows = []
    for tile in tiles:
        a = tile.select_one('.f-tile__title a[href]')
        if not a:
            raise FlowError('layout_changed', 'A class tile has no recognizable class link.')
        link = urljoin(origin, a['href'])
        p = urlsplit(link)
        m = re.fullmatch(r'/student/classes/(\d{1,20})', p.path)
        name = text(a)
        if not m or school_origin(link) != origin or p.query or p.fragment or not name or len(name) > 300:
            raise FlowError('invalid_class', 'A class record could not be validated.')
        rows.append({'id': m[1], 'name': name, 'url': origin + p.path})
    if not rows and totals[0] != 0:
        raise FlowError('layout_changed', 'ManageBac reports classes but no class records could be extracted.')
    return rows, totals[0], next_page(page, origin, ROUTE, current or origin + ROUTE)

