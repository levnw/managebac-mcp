"""Compact model view of task content; never serialize the internal DOM tree."""
import re


def public_asset(asset: dict) -> dict:
    """Model-facing reference. Expiring signed links are credentials that ChatGPT
    cannot open and that would linger in transcripts: keep only the file_id."""
    hidden = {'ref', 'temporary_url'} | ({'url'} if asset.get('temporary_url') else set())
    return {k: v for k, v in asset.items() if k not in hidden}


class TaskView:
    def __init__(self, assets):
        self.assets = {a['ref']: a for a in assets}

    def content(self, nodes):
        media, tables = {}, []

        def reference(ref):
            asset = self.assets.get(ref)
            if not asset:
                return '[Unavailable resource]'
            if ref not in media:
                label = f"{asset['kind']}_{len(media) + 1}"
                media[ref] = {'id': label, **public_asset(asset)}
            return '[' + media[ref]['id'] + ']'

        def render(n):
            kind = n['type']
            children = n.get('children', [])
            if kind == 'text':
                value = n['text']
                for mark in n.get('marks', []):
                    if mark in ('bold', 'italic', 'strikethrough', 'code'):
                        delimiter = {'bold':'**', 'italic':'*', 'strikethrough':'~~', 'code':'`'}[mark]
                        value = delimiter + value + delimiter
                    elif mark in ('subscript', 'superscript', 'underline'):
                        tag = {'subscript':'sub','superscript':'sup','underline':'u'}[mark]
                        value = f'<{tag}>{value}</{tag}>'
                return value
            if kind == 'code_block':
                # Preserve code exactly, including blank lines and indentation.
                fence = '`' * max(3, 1 + max((len(m[0]) for m in re.finditer(r'`+', n['text'])), default=0))
                return '\n\n' + fence + '\n' + n['text'] + '\n' + fence + '\n\n'
            if kind == 'table':
                rows = []
                def visit(items):
                    for item in items:
                        if item['type'] == 'table_row':
                            cells = []
                            for cell in item.get('children', []):
                                if cell['type'] != 'table_cell': continue
                                data = {'text': ''.join(render(c) for c in cell.get('children', [])).strip()}
                                data.update({k:cell[k] for k in ('header','rowspan','colspan') if k in cell})
                                cells.append(data)
                            rows.append(cells)
                        else: visit(item.get('children', []))
                visit(children)
                label = 'table_' + str(len(tables)+1)
                table = {'id':label, 'rows':rows}
                captions = [render(c).strip() for c in children if c['type']=='caption']
                if captions: table['caption'] = ' '.join(captions)
                tables.append(table)
                return '\n\n[' + label + ']\n\n'
            if kind in ('image', 'file', 'link'):
                label = ''.join(render(c) for c in children).strip() or n.get('alt', '')
                marker = reference(n['ref']) if n.get('ref') else '[Image unavailable]'
                if n.get('variants'):
                    marker += ' ' + ' '.join(reference(v['ref']) for v in n['variants'])
                return (label + ' ' if label else '') + marker
            if kind == 'embed':
                return ' '.join(reference(ref) for ref in n.get('refs', [])) or '[Embedded media unavailable]'
            if kind in ('svg','math','canvas'):
                return n.get('text') or '[Visual content requires viewing the source]'
            if kind == 'line_break': return '\n'
            if kind == 'separator': return '\n\n---\n\n'
            if kind == 'list':
                index = n.get('start', 1)
                lines = []
                for child in children:
                    if child['type'] != 'list_item': continue
                    value = render(child).strip().replace('\n', '\n  ')
                    prefix = str(index)+'. ' if n.get('ordered') else '- '
                    lines.append(prefix + value); index += 1
                return '\n' + '\n'.join(lines) + '\n'
            body = ''.join(render(c) for c in children)
            if kind == 'heading': return '\n\n' + '#' * n['level'] + ' ' + body.strip() + '\n\n'
            if kind == 'quote': return '\n\n> ' + body.strip().replace('\n', '\n> ') + '\n\n'
            if kind in ('paragraph','group','figure','caption','definition_list','term','definition','details','summary'):
                return '\n\n' + body.strip() + '\n\n' if body.strip() else ''
            return body

        # Normalize layout whitespace outside fenced code, never within code.
        rendered = ''.join(render(n) for n in nodes).strip()
        chunks = re.split(r'(^`{3,}[^\n]*\n.*?^`{3,}\s*$)', rendered, flags=re.M|re.S)
        for i in range(0, len(chunks), 2):
            chunks[i] = re.sub(r'\n(?:[ \t]*\n){2,}', '\n\n', chunks[i])
        result = {'text': ''.join(chunks).strip()}
        if media: result['media'] = list(media.values())
        if tables: result['tables'] = tables
        return result


def compact_task(task):
    view = TaskView(task.get('assets', []))
    result = {k:task[k] for k in ('id','class_id','title','url','status','assessment_type','tags','fields') if k in task}
    if task.get('due_source') or task.get('due_display'):
        result['due'] = task.get('due_source') or task['due_display']
    description = view.content(task['description'])
    result['description'] = description.pop('text')
    result.update(description)
    result['submission'] = dict(task.get('submission_box', {'box':'not_detected'}))
    for source, destination in (('resources','teacher_resources'),('submissions','files'),('feedback','feedback'),('assessment','assessment')):
        section = task[source]
        if section['state'] != 'present': continue
        if 'items' in section:
            entries = []
            for entry in section['items']:
                content = view.content(entry['content'])
                value = {k:v for k,v in entry.items() if k not in ('content','preview_refs')}
                value.update({k:v for k,v in content.items() if v})
                previews = [view.assets[r] for r in entry.get('preview_refs',[]) if r in view.assets]
                if previews: value['previews'] = [public_asset(a) for a in previews]
                if value: entries.append(value)
            if entries:
                if source == 'submissions': result['submission']['files'] = entries
                else: result[destination] = entries
        else:
            content = {k:v for k,v in view.content(section['content']).items() if v}
            if content:
                if source == 'submissions': result['submission']['details'] = content
                else: result[destination] = content
    return result
