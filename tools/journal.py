from sources.managebac.collections import collect
from sources.managebac.conversations import journal_page
from .contracts import ClassArguments, definition, STRING
from .content_output import content
from .retrieval import execute
from .output_schemas import array, JOURNAL

DEFINITION = definition('get_journal', ClassArguments,
    'Read journal reflections for one selected class, with dates, learning outcomes and rich content. '
    'Does not scan other classes for journals or change entries. A missing or inaccessible page is an error.',
    {'class_id': STRING, 'url': STRING, 'entries': array(JOURNAL)},
    title='Get class journal', invoking='Reading journal entries…', invoked='Read journal entries')


async def get_journal(client, origin, arguments):
    async def run(args):
        path = f'/student/classes/{args.class_id}/learner_portfolio/reflections'
        def parse(html, url):
            rows, following = journal_page(html, origin, args.class_id, url)
            for row in rows: row.update(content(row.pop('_body'), origin, url))
            return rows, following
        return {'class_id': args.class_id, 'url': origin + path,
                'entries': await collect(client, origin, path, parse)}
    return await execute(ClassArguments, arguments, run)
