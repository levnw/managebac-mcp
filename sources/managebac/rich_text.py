"""Semantic HTML-to-JSON with ordered content and a deduplicated asset catalogue.

References describe source material; this module never downloads or executes it.
"""
import hashlib
import re
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, unquote_plus
from bs4 import Comment, NavigableString, Tag
from onboarding.transport import FlowError
from diagnostics import event

MAX_NODES = 6000
MAX_TEXT = 120_000
MAX_ASSETS = 300
MARKS = {'strong': 'bold', 'b': 'bold', 'em': 'italic', 'i': 'italic', 'u': 'underline',
         's': 'strikethrough', 'del': 'strikethrough', 'sub': 'subscript', 'sup': 'superscript', 'code': 'code'}
BLOCKS = {'p': 'paragraph', 'div': 'group', 'section': 'group', 'article': 'group',
          'blockquote': 'quote', 'ul': 'list', 'ol': 'list', 'li': 'list_item',
          'table': 'table', 'thead': 'table_head', 'tbody': 'table_body', 'tfoot': 'table_foot',
          'tr': 'table_row', 'td': 'table_cell', 'th': 'table_cell', 'caption': 'caption',
          'figure': 'figure', 'figcaption': 'caption', 'dl': 'definition_list',
          'dt': 'term', 'dd': 'definition', 'details': 'details', 'summary': 'summary'}
SCHOOL_HOST = re.compile(r'(?:[a-z0-9-]+\.)*managebac\.(?:com|cn)')
STORED = ('file', 'image', 'preview')
AUTH_QUERY = re.compile(
    r'^(?:signature|token|access_token|expires|policy|key-pair-id|'
    r'x-amz-(?:algorithm|credential|date|expires|signedheaders|signature|security-token)|'
    r'x-goog-(?:algorithm|credential|date|expires|signedheaders|signature|security-token))$', re.I)


def resource_identity(url: str) -> str:
    """Remove known authorization parameters only; keep resource selectors verbatim.

    Order, duplicates, blank values and encoding of non-auth query components are
    retained. This is a URL-derived reference, not a native or globally stable ID.
    """
    parts = urlsplit(url)
    query = '&'.join(part for part in parts.query.split('&')
                     if not AUTH_QUERY.fullmatch(unquote_plus(part.split('=', 1)[0])))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ''))


def file_id(url: str) -> str:
    """Opaque URL-derived reference stable across known auth-parameter rotation.

    Not a download capability. Changed resource paths/selectors yield new IDs.
    """
    return 'f_' + hashlib.sha256(resource_identity(url).encode()).hexdigest()[:16]


class RichText:
    def __init__(self, origin: str, page_url: str):
        self.origin, self.page_url = origin, page_url
        self.assets, self.noted = [], set()
        self.nodes, self.characters = 0, 0

    def warn(self, code: str):
        """Developer-report note (e.g. media not read); never part of model output."""
        if code not in self.noted:
            self.noted.add(code)
            event('rich.' + code)

    def asset(self, raw: str, kind: str, name: str = '', **metadata) -> str | None:
        raw = str(raw or '').strip()
        if not raw or any(ord(c) < 32 for c in raw):
            self.warn('missing_or_invalid_asset_url')
            return None
        url = urljoin(self.page_url, raw)
        try:
            p = urlsplit(url)
            valid = p.scheme in ('https', 'http', 'mailto') and not p.username and not p.password
            if p.scheme != 'mailto': valid = valid and bool(p.hostname)
            if not valid or len(url) > 8192: raise ValueError()
        except ValueError:
            self.warn('unsafe_asset_url_omitted')
            return None
        temporary = any(AUTH_QUERY.fullmatch(k) for k, _ in parse_qsl(p.query))
        stable = resource_identity(url)
        ref = 'r_' + hashlib.sha256((kind + '\0' + stable).encode()).hexdigest()[:20]
        if not any(a['ref'] == ref for a in self.assets):
            if len(self.assets) >= MAX_ASSETS:
                raise FlowError('content_too_large', 'Too many attached resources; the task was not truncated.')
            value = {'ref': ref, 'kind': kind, 'url': url}
            if name: value['name'] = name
            value.update({k: v for k, v in metadata.items() if v is not None and v != ''})
            if kind in STORED and (temporary or SCHOOL_HOST.fullmatch(p.hostname or '')):
                value['file_id'] = file_id(stable)
            if temporary:
                value['temporary_url'] = True
                self.warn('temporary_resource_urls_refresh_before_use')
            self.assets.append(value)
        return ref

    def parse(self, root) -> list[dict]:
        return self._children(root, (), 0) if root else []

    def _children(self, root, marks, depth):
        result = []
        for child in root.children:
            result.extend(self._node(child, marks, depth + 1))
        return result

    def _node(self, node, marks, depth):
        self.nodes += 1
        if depth > 40 or self.nodes > MAX_NODES:
            raise FlowError('content_too_large', 'Rich content exceeds its nesting or node limit.')
        if isinstance(node, Comment): return []
        if isinstance(node, NavigableString):
            value = re.sub(r'\s+', ' ', str(node))
            if not value.strip(): return [{'type': 'text', 'text': ' '}] if value else []
            self.characters += len(value)
            if self.characters > MAX_TEXT:
                raise FlowError('content_too_large', 'Rich text exceeds 120,000 characters; nothing was truncated.')
            result = {'type': 'text', 'text': value}
            if marks: result['marks'] = list(dict.fromkeys(marks))
            # Plain-text URLs remain ordered text, with an explicit link reference.
            if not any(p.name in ('a', 'pre', 'code') for p in node.parents):
                pieces, end = [], 0
                for match in re.finditer(r'https?://[^\s<>"\']+', value):
                    raw = match[0].rstrip('.,;!')
                    if not raw: continue
                    if match.start() > end: pieces.append({**result, 'text': value[end:match.start()]})
                    ref = self.asset(raw, 'link')
                    leaf = {**result, 'text': raw}
                    pieces.append({'type': 'link', 'ref': ref, 'children': [leaf]} if ref else leaf)
                    end = match.start() + len(raw)
                if pieces:
                    if end < len(value): pieces.append({**result, 'text': value[end:]})
                    return pieces
            return [result]
        if not isinstance(node, Tag): return []
        tag = node.name
        if tag in ('script', 'style', 'noscript', 'form', 'button', 'input', 'select', 'textarea', 'nav'):
            return []
        # Editors commonly encode emphasis as inline CSS instead of semantic tags.
        # Interpret only text semantics; never execute or return arbitrary CSS.
        style = dict(re.findall(r'([\w-]+)\s*:\s*([^;]+)', node.get('style', '').lower()))
        extra_marks = []
        if style.get('font-weight', '').strip() in ('bold', 'bolder', '600', '700', '800', '900'):
            extra_marks.append('bold')
        if style.get('font-style', '').strip() in ('italic', 'oblique'):
            extra_marks.append('italic')
        decoration = style.get('text-decoration', '') + ' ' + style.get('text-decoration-line', '')
        if 'underline' in decoration: extra_marks.append('underline')
        if 'line-through' in decoration: extra_marks.append('strikethrough')
        marks = (*marks, *extra_marks)
        if tag in MARKS:
            return self._children(node, (*marks, MARKS[tag]), depth)
        if tag == 'br': return [{'type': 'line_break'}]
        if tag == 'hr': return [{'type': 'separator'}]
        if tag == 'pre':
            value = node.get_text()
            self.characters += len(value)
            if self.characters > MAX_TEXT: raise FlowError('content_too_large', 'Code block is too large.')
            return [{'type': 'code_block', 'text': value}]
        if tag == 'a':
            children = self._children(node, marks, depth)
            kind = 'file' if ('fr-file' in node.get('class', []) or node.has_attr('download')
                or node.get('data-name') or re.search(r'/uploads/asset/file/\d+', str(node.get('href', '')))) else 'link'
            size = node.select_one('.fr-file-size')
            ref = self.asset(node.get('href'), kind, node.get('data-name') or node.get_text(' ', strip=True),
                             size_display=size.get_text(' ', strip=True) if size is not None else None)
            return [{'type': kind, 'ref': ref, 'children': children}] if ref else children
        if tag == 'img':
            ref = self.asset(node.get('data-src') or node.get('src'), 'image', node.get('alt', ''),
                             title=node.get('title'))
            result = {'type': 'image'}
            if ref: result['ref'] = ref
            if node.get('alt'): result['alt'] = node['alt']
            variants = []
            for source in str(node.get('srcset', '')).split(','):
                fields = source.strip().split()
                if fields:
                    candidate = self.asset(fields[0], 'image', node.get('alt', ''))
                    if candidate: variants.append({'ref': candidate, **({'size': fields[1]} if len(fields) > 1 else {})})
            if variants: result['variants'] = variants
            if not ref and not variants: result['unavailable'] = True
            return [result]
        if tag in ('iframe', 'video', 'audio', 'object', 'embed'):
            refs = []
            for raw in [node.get('src') or node.get('data'), *(n.get('src') for n in node.select('source[src],track[src]'))]:
                if raw:
                    ref = self.asset(raw, 'embed', node.get('title', ''), media_type=tag)
                    if ref: refs.append(ref)
            self.warn('embedded_media_not_read')
            return [{'type': 'embed', 'media_type': tag, 'refs': list(dict.fromkeys(refs))}]
        if tag in ('math', 'svg', 'canvas'):
            value = node.get('aria-label') or node.get('data-latex') or node.get_text(' ', strip=True)
            self.warn('visual_or_math_content_needs_review')
            return [{'type': tag, **({'text': value} if value else {'unavailable': True})}]
        children = self._children(node, marks, depth)
        if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            return [{'type': 'heading', 'level': int(tag[1]), 'children': children}]
        if tag in BLOCKS:
            result = {'type': BLOCKS[tag], 'children': children}
            if tag in ('ul', 'ol'):
                result['ordered'] = tag == 'ol'
                if node.get('start', '').lstrip('-').isdigit(): result['start'] = int(node['start'])
            if tag in ('td', 'th'):
                if tag == 'th': result['header'] = True
                for attribute in ('rowspan', 'colspan'):
                    if node.get(attribute, '').isdigit(): result[attribute] = int(node[attribute])
            return [result]
        if tag not in ('span', 'picture', 'small', 'font', 'label', 'time', 'abbr', 'mark'):
            self.warn('unrecognized_rich_element_flattened')
        return children

    def finish(self, payload: dict) -> dict:
        if self.assets: payload['assets'] = self.assets
        return payload
