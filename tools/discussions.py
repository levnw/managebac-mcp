from pydantic import Field
from sources.managebac.collections import collect
from sources.managebac.conversations import discussion_page
from .contracts import ClassArguments, definition, STRING
from .content_output import content
from .retrieval import execute
from .output_schemas import array, DISCUSSION


class Arguments(ClassArguments):
    task_id: str = Field(pattern=r'^[0-9]{1,20}$', description='ID from get_tasks.')


DEFINITION = definition('get_discussions', Arguments,
    'Read discussion posts and replies for one task. Preserves authors, dates and rich content. '
    'Separate from task instructions; never posts a message or fetches attached file contents.',
    {'class_id': STRING, 'task_id': STRING, 'url': STRING, 'discussions': array(DISCUSSION)},
    limits='50 pages, 1000 posts and replies combined',
    title='Get task discussions', invoking='Reading discussions…', invoked='Read discussions')


async def get_discussions(client, origin, arguments):
    async def run(args):
        path = f'/student/classes/{args.class_id}/core_tasks/{args.task_id}/discussions'
        def compact(row, url):
            row.update(content(row.pop('_body'), origin, url))
            for reply in row.get('replies', []): compact(reply, url)
        def parse(html, url):
            rows, following = discussion_page(html, origin, args.class_id, args.task_id, url)
            for row in rows: compact(row, url)
            return rows, following
        return {'class_id': args.class_id, 'task_id': args.task_id, 'url': origin + path,
                'discussions': await collect(client, origin, path, parse)}
    return await execute(Arguments, arguments, run)
