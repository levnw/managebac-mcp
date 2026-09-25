from pydantic import Field
from sources.managebac.pages import fetch_html
from sources.managebac.units import parse_unit
from .contracts import ClassArguments, definition
from .content_output import content
from .retrieval import execute
from .output_schemas import UNIT


class Arguments(ClassArguments):
    unit_id: str = Field(pattern=r'^[0-9]{1,20}$', description='ID from get_units.')


DEFINITION = definition('get_unit', Arguments,
    'Read one unit: source-labelled framework sections and schedule metadata. '
    'Preserves rich text, table structure and media references. Does not download media or retrieve tasks.',
    {'unit': UNIT}, limits='1 page, 1000 sections and fields',
    title='Get unit details', invoking='Reading the unit…', invoked='Read the unit')


async def get_unit(client, origin, arguments):
    async def run(args):
        path = f'/student/classes/{args.class_id}/units/{args.unit_id}/popup'
        fields, sections = parse_unit(await fetch_html(client, origin, path), origin, args.class_id, args.unit_id)
        result = {'id': args.unit_id, 'class_id': args.class_id,
                  'url': origin + path.replace('/popup', '/presentations')}
        if fields: result['fields'] = fields
        if sections:
            result['sections'] = [{'title': title, **content(node, origin, origin + path)}
                                  for title, node in sections]
        return {'unit': result}
    return await execute(Arguments, arguments, run)
