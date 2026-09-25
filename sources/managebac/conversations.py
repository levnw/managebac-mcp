"""Journal and discussion boundaries. No star/edit/delete/submission actions."""
import re
from urllib.parse import urlsplit
from onboarding.transport import FlowError
from .pages import document, text, next_page, verify_identity


def journal_page(html, origin, class_id, current):
    soup = document(html)
    verify_identity(soup, origin, urlsplit(current).path)
    entries = []
    for node in soup.select('.journal-evidence'):
        match = re.fullmatch(r'evidence-([0-9]{1,20})', node.get('id', ''))
        body = node.select_one('.fix-body-margins')
        if not match or body is None:
            raise FlowError('layout_changed', 'A journal entry could not be read completely.')
        item = {'id': match[1], '_body': body}
        when = text(node.select_one('.title .padding-right'))
        if when: item['date_display'] = when
        outcomes = list(dict.fromkeys(text(n) for n in node.select('.label-outcome') if text(n)))
        if outcomes: item['learning_outcomes'] = outcomes
        entries.append(item)
    if not entries and not any(re.fullmatch(r'No (?:journal entries|reflections)(?: yet)?[.!]?', text(n), re.I)
                               for n in soup.select('.empty-state, .blank-slate, .no-results')):
        raise FlowError('layout_changed', 'No journal entries or explicit empty-journal state were recognized.')
    return entries, next_page(soup, origin, f'/student/classes/{class_id}/learner_portfolio/reflections', current)


def discussion_page(html, origin, class_id, task_id, current):
    soup = document(html)
    verify_identity(soup, origin, urlsplit(current).path)

    def read(node, require_id=False):
        # Exclude nested replies from the parent message, not from the reply list.
        body = next((n for n in node.select('.body') if n.find_parent(class_='reply') is node
                     or (not n.find_parent(class_='reply') and 'reply' not in node.get('class', []))), None)
        if body is None: raise FlowError('layout_changed', 'A discussion message has no recognized body.')
        value = {'_body': body}
        if require_id:
            match = re.fullmatch(r'discussion_([0-9]{1,20})', node.get('id', ''))
            if not match: raise FlowError('layout_changed', 'A discussion ID was not recognized.')
            value['id'] = match[1]
        for key, selector in (('author', '.author'), ('posted_at', '.date')):
            field = next((n for n in node.select(selector) if not n.find_parent(class_='reply')
                          or n.find_parent(class_='reply') is node), None)
            if text(field): value[key] = text(field)
        return value

    rows = []
    for node in soup.select('.discussion'):
        value = read(node, True)
        replies = [read(reply) for reply in node.select('.reply')
                   if 'form' not in reply.get('class', []) and reply.name != 'form']
        if replies: value['replies'] = replies
        # A reply inside the body must not appear twice in the model response.
        for reply in value['_body'].select('.reply'): reply.extract()
        rows.append(value)
        if len(rows) + sum(len(row.get('replies', [])) for row in rows) > 1000:
            raise FlowError('result_too_large', 'The discussion page exceeds 1000 posts and replies.')
    if not rows and not any(re.fullmatch(r'No (?:discussions|comments|posts)(?: yet)?[.!]?', text(n), re.I)
                           for n in soup.select('.empty-state, .blank-slate, .no-results')):
        raise FlowError('layout_changed', 'No discussions or explicit empty-discussion state were recognized.')
    return rows, next_page(soup, origin, f'/student/classes/{class_id}/core_tasks/{task_id}/discussions', current)
