from .contracts import ClassArguments, definition, STRING
from .retrieval import execute
from sources.managebac.collections import collect
from sources.managebac.units import parse_units
from .output_schemas import array, UNIT_SUMMARY

DEFINITION = definition('get_units', ClassArguments,
    'List unit IDs, titles and explicitly displayed schedule/status for one class. '
    'Does not fetch unit details, tasks or journals. Use get_unit for a selected unit.',
    {'class_id': STRING, 'url': STRING, 'units': array(UNIT_SUMMARY)},
    title='Get class units', invoking='Reading units…', invoked='Read units')


async def get_units(client, origin, arguments):
    async def run(args):
        path = f'/student/classes/{args.class_id}/units'
        rows = await collect(client, origin, path,
                             lambda html, url: parse_units(html, origin, args.class_id, url))
        return {'class_id': args.class_id, 'url': origin + path, 'units': rows}
    return await execute(ClassArguments, arguments, run)
