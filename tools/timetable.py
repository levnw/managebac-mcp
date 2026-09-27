from sources.managebac.pages import fetch_html
from sources.managebac.timetable import parse_timetable
from .contracts import NoArguments, definition, STRING
from .retrieval import execute
from .output_schemas import array, SLOT, NOTE

DEFINITION = definition('get_timetable', NoArguments,
    "The student's timetable for the week ManageBac is currently showing (other weeks are not available). "
    'Days and times are exactly as ManageBac shows them.',
    {'url': STRING, 'days': {'type': 'array', 'items': STRING}, 'slots': array(SLOT), 'notes': array(NOTE)},
    required=['url', 'days', 'slots'],
    title='Get timetable', invoking='Reading your timetable…', invoked='Read your timetable')


async def get_timetable(client, origin, arguments):
    async def run(args):
        path = '/student/timetables'
        return {'url': origin + path, **parse_timetable(await fetch_html(client, origin, path), origin)}
    return await execute(NoArguments, arguments, run)
