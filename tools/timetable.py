from sources.managebac.pages import fetch_html
from sources.managebac.timetable import parse_timetable
from .contracts import NoArguments, definition, STRING
from .retrieval import execute
from .output_schemas import array, SLOT, NOTE

DEFINITION = definition('get_timetable', NoArguments,
    'Read the currently displayed timetable. Day and time labels remain exactly as displayed; '
    'do not infer a year or timezone. Does not claim to retrieve a requested historical or future week.',
    {'url': STRING, 'days': {'type': 'array', 'items': STRING}, 'slots': array(SLOT), 'notes': array(NOTE)},
    required=['url', 'days', 'slots'], limits='1 page, 1000 class slots and notes combined',
    title='Get timetable', invoking='Reading your timetable…', invoked='Read your timetable')


async def get_timetable(client, origin, arguments):
    async def run(args):
        path = '/student/timetables'
        return {'url': origin + path, **parse_timetable(await fetch_html(client, origin, path), origin)}
    return await execute(NoArguments, arguments, run)
