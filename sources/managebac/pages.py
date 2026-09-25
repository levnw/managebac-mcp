"""Bounded read-only page transport and strict entity/pagination destinations."""
import asyncio
import random
import re
from urllib.parse import urljoin, urlsplit, parse_qs, urlencode

import httpx
from bs4 import BeautifulSoup
from diagnostics import event
from onboarding.transport import FlowError, school_origin

MAX_HTML_BYTES = 2_000_000
MAX_PAGES = 50
# Page reads never set their own User-Agent: they inherit the session client's,
# which is the identity that signed in. Live evidence (25 Sep): ManageBac ended
# sessions when page requests presented a different User-Agent from sign-in.


def destination(origin: str, path: str) -> str:
    parsed = urlsplit(path)
    allowed = (re.fullmatch(r'/student/classes/[0-9]{1,20}/[A-Za-z0-9_/-]+', parsed.path)
               or parsed.path in ('/student/classes/my', '/student/timetables'))
    if (school_origin(origin) != origin or not allowed or parsed.scheme or parsed.netloc
            or parsed.fragment or any(ord(c) < 32 for c in path) or '..' in path or '\\' in path):
        raise FlowError('unsafe_destination', 'The requested school page could not be validated.')
    return origin + path


def listing_url(origin: str, base: str, link: str) -> str:
    """Allow page=N or /page/N, scoped to precisely one listing/folder."""
    p = urlsplit(urljoin(origin + base, link))
    q = parse_qs(p.query, keep_blank_values=True)
    if school_origin(p.geturl()) != origin or p.fragment or set(q) - {'page'}:
        raise FlowError('invalid_pagination', 'Pagination leaves the requested listing or changes its filters.')
    suffix = re.fullmatch(re.escape(base) + r'(?:/page/([1-9][0-9]{0,3}))?', p.path)
    if not suffix or len(q.get('page', [])) > 1 or (suffix[1] and q):
        raise FlowError('invalid_pagination', 'Pagination has an unexpected path or page number.')
    number = suffix[1] or q.get('page', ['1'])[0]
    if not re.fullmatch(r'[1-9][0-9]{0,3}', number):
        raise FlowError('invalid_pagination', 'Pagination has an invalid page number.')
    if suffix[1]:
        return origin + base + (f'/page/{number}' if number != '1' else '')
    return origin + base + ('?' + urlencode({'page': number}) if number != '1' else '')


def next_page(soup, origin: str, base: str, current: str) -> str | None:
    matches = {listing_url(origin, base, a['href']) for a in soup.select('.pagination a[href], a[rel~=next][href]')
               if 'next' in a.get('rel', []) or a.get_text(' ', strip=True).casefold() in ('next', 'next ›', 'next »')}
    if len(matches) > 1:
        raise FlowError('invalid_pagination', 'Conflicting next pages were found.')
    result = next(iter(matches), None)
    if result == current:
        raise FlowError('pagination_loop', 'The listing links back to the same page.')
    # Numbered pagination without a Next link must not silently stop early.
    number = int(parse_qs(urlsplit(current).query).get('page', [urlsplit(current).path.split('/page/')[-1]
                 if '/page/' in urlsplit(current).path else '1'])[0])
    for a in soup.select('.pagination a[href]'):
        label = a.get_text(strip=True)
        if label.isdecimal() and int(label) > number and result is None:
            raise FlowError('invalid_pagination', 'More listing pages exist, but no supported Next link was found.')
    return result


ERRORS = {401: ('session_expired', 'Sign in again to retrieve this page.'),
          403: ('access_denied', 'This account cannot access the requested page.'),
          404: ('not_found', 'The requested page was not found; verify its IDs.'),
          422: ('upstream_rejected', 'ManageBac rejected this page request (HTTP 422). Open the same page in the school portal and inspect developer diagnostics; no empty listing was assumed.'),
          429: ('rate_limited', 'ManageBac is limiting requests. Wait before retrying.')}
TRANSIENT = {502, 503, 504}
RETRY_DELAY_SECONDS = (0.3, 0.9)   # jittered pause before the single retry
MAX_RETRY_AFTER_SECONDS = 5        # longer Retry-After requests are reported, not waited out


class Retry(Exception):
    def __init__(self, delay):
        self.delay = delay


async def fetch_html(client, origin: str, path: str) -> str:
    """One page GET. Idempotent, so one retry for transient failures only:
    connection errors, 502/503/504, or 429 with a short Retry-After."""
    url = destination(origin, path)
    for attempt in (1, 2):
        try:
            return await _fetch_once(client, origin, url, retry_allowed=attempt == 1)
        except Retry as retry:
            event('page.retry')
            await asyncio.sleep(retry.delay)
        except httpx.TransportError:
            if attempt == 2: raise
            event('page.retry')
            await asyncio.sleep(random.uniform(*RETRY_DELAY_SECONDS))
    raise AssertionError('unreachable')


async def _fetch_once(client, origin: str, url: str, retry_allowed: bool) -> str:
    event('page.request')
    # Browser-like navigation: no Origin header on GET, no identity override.
    headers = {'Accept': 'text/html,application/xhtml+xml', 'Referer': origin + '/student'}
    async with client.stream('GET', url, headers=headers, follow_redirects=False) as response:
        status = response.status_code
        event('page.response', status=status)
        if response.is_redirect:
            target = urlsplit(urljoin(url, response.headers.get('location', '')))
            code = 'session_expired' if target.path in ('/login', '/sessions') else 'unexpected_redirect'
            raise FlowError(code, 'ManageBac redirected away from the requested page. Reconnect if sign-in is required.')
        if retry_allowed and status in TRANSIENT:
            raise Retry(random.uniform(*RETRY_DELAY_SECONDS))
        if retry_allowed and status == 429:
            wait = response.headers.get('retry-after', '')
            if wait.isdecimal() and int(wait) <= MAX_RETRY_AFTER_SECONDS:
                raise Retry(int(wait) + random.uniform(0, RETRY_DELAY_SECONDS[0]))
        if status in ERRORS:
            raise FlowError(*ERRORS[status])
        if status != 200:
            raise FlowError('upstream_unavailable', 'ManageBac could not serve the requested page.')
        content_type = response.headers.get('content-type', '').split(';')[0].strip().lower()
        if content_type and content_type not in ('text/html', 'application/xhtml+xml'):
            raise FlowError('unsupported_page', 'Expected a school HTML page; received a different content type.')
        parts, size = [], 0
        async for part in response.aiter_bytes():
            size += len(part)
            if size > MAX_HTML_BYTES:
                raise FlowError('page_too_large', 'The page exceeded 2 MB. No partial result was returned.')
            parts.append(part)
    return b''.join(parts).decode('utf-8', errors='strict')

def document(html: str):
    if len(html.encode()) > MAX_HTML_BYTES:
        raise FlowError('page_too_large', 'The page exceeded 2 MB.')
    soup = BeautifulSoup(html, 'html.parser')
    if soup.select_one('input[type=password], form[action="/sessions"]'):
        raise FlowError('session_expired', 'ManageBac returned a login form instead of the requested data.')
    return soup


def text(node) -> str:
    return node.get_text(' ', strip=True) if node else ''


def outermost(nodes) -> list:
    """Drop matches nested in another match: one record, not several wrappers.

    Uses identity; BeautifulSoup's Tag equality compares markup, so two
    identical-looking rows are still distinct records.
    """
    selected = {id(node) for node in nodes}
    return [node for node in nodes if not any(id(parent) in selected for parent in node.parents)]


def count_heading(scope, label: str) -> int | None:
    counts = {int(m[1]) for h in scope.select('h1,h2,h3')
              if (m := re.fullmatch(re.escape(label) + r'\s*\((\d+)\)', text(h), re.I))}
    if len(counts) > 1:
        raise FlowError('count_mismatch', 'Conflicting totals were shown for this listing.')
    return next(iter(counts), None)


def verify_identity(soup, origin: str, path: str):
    for link in soup.select('link[rel=canonical][href]'):
        p = urlsplit(urljoin(origin, link['href']))
        if school_origin(p.geturl()) != origin or p.path != path:
            raise FlowError('identity_mismatch', 'The returned page belongs to a different entity.')


MAX_FILE_BYTES = 10_000_000
# ManageBac serves files from the school host and hands signed links to its storage.
FILE_HOSTS = re.compile(r'(?:[a-z0-9-]+\.)*(?:managebac\.(?:com|cn)|amazonaws\.com|cloudfront\.net)')
FILE_ERRORS = {401: ('session_expired', 'Sign in again to download this file.'),
               403: ('file_link_expired', 'The file link was refused (it may have expired). Open the file again.'),
               404: ('not_found', 'The file was not found; it may have been removed.'),
               429: ('rate_limited', 'ManageBac is limiting requests. Wait before retrying.')}


async def fetch_file(client, origin: str, url: str) -> tuple[bytes, str]:
    """Download one school file already found on an authorised page. Returns (bytes, content type).

    Follows at most three redirects, HTTPS only, to ManageBac or its storage hosts.
    School cookies go only to the school's own host; they are stripped from every other request.
    """
    for _ in range(4):
        p = urlsplit(url)
        if p.scheme != 'https' or p.username or p.password or not FILE_HOSTS.fullmatch(p.hostname or ''):
            raise FlowError('unsupported_file_host', 'The file is stored somewhere this connector does not download from.')
        event('file.request')
        request = client.build_request('GET', url, headers={'Accept': '*/*', 'Referer': origin + '/student'})
        if f'https://{p.hostname}' != origin:
            # Storage hosts get no school cookies and no referrer, whatever the jar holds.
            request.headers.pop('cookie', None); request.headers.pop('referer', None)
        response = await client.send(request, stream=True, follow_redirects=False)
        try:
            event('file.response', status=response.status_code)
            if response.is_redirect:
                target = urljoin(url, response.headers.get('location', ''))
                if urlsplit(target).path in ('/login', '/sessions'):
                    raise FlowError('session_expired', 'ManageBac asked to sign in before sending the file.')
                url = target
                continue
            if response.status_code in FILE_ERRORS:
                raise FlowError(*FILE_ERRORS[response.status_code])
            if response.status_code != 200:
                raise FlowError('upstream_unavailable', 'The file could not be downloaded right now.')
            content_type = response.headers.get('content-type', '').split(';')[0].strip().lower()
            declared = response.headers.get('content-length', '')
            if declared.isdecimal() and int(declared) > MAX_FILE_BYTES:
                raise FlowError('file_too_large', 'The file is larger than 10 MB; open it in ManageBac instead.')
            parts, size = [], 0
            async for part in response.aiter_bytes():
                size += len(part)
                if size > MAX_FILE_BYTES:
                    raise FlowError('file_too_large', 'The file is larger than 10 MB; open it in ManageBac instead.')
                parts.append(part)
        finally:
            await response.aclose()
        data = b''.join(parts)
        if content_type in ('text/html', 'application/xhtml+xml') and b'type="password"' in data[:200_000]:
            raise FlowError('session_expired', 'ManageBac returned a sign-in page instead of the file.')
        return data, content_type or 'application/octet-stream'
    raise FlowError('redirect_loop', 'The file download redirected too many times.')
