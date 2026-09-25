from typing import Literal
from sources.managebac.collections import collect
from sources.managebac.upcoming import parse_upcoming
from .contracts import NoArguments, definition, STRING
from .retrieval import execute
from .output_schemas import array, SCOPED_TASK


class Arguments(NoArguments):
    view: Literal['upcoming', 'overdue', 'past'] = 'upcoming'


DEFINITION = definition('get_upcoming', Arguments,
    'Read ManageBac consolidated deadlines across classes in the selected upcoming, overdue or past view. '
    'Does not crawl every class or fetch task details. Relative dates retain their source wording.',
    {'view': {'enum': ['upcoming', 'overdue', 'past']}, 'url': STRING, 'tasks': array(SCOPED_TASK)},
    title='Get deadlines', invoking='Reading deadlines…', invoked='Read deadlines')


async def get_upcoming(client, origin, arguments):
    async def run(args):
        path = '/student/tasks_and_deadlines?view=' + args.view
        return {'view': args.view, 'url': origin + path,
                'tasks': await collect(client, origin, path,
                                      lambda html, url: parse_upcoming(html, origin, args.view, url))}
    return await execute(Arguments, arguments, run)
