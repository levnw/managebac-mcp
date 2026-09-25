"""Published assessment blocks only, never invented averages or predicted grades."""
from onboarding.transport import FlowError
from sources.managebac.grades import parse_grades
from sources.managebac.collections import collect
from .contracts import ClassArguments, definition, STRING
from .content_output import content
from .retrieval import execute
from .output_schemas import array, ASSESSMENT

DEFINITION = definition('get_grades', ClassArguments,
    'Read explicitly marked assessment/grade blocks displayed on one class task list. '
    'Returns source content, not calculated averages, predicted grades or a report card. '
    'Pending or unmarked tasks without assessment blocks have no published grade on this page and are omitted. '
    'Recognizable but unsupported assessment markup returns an error. '
    'This view is limited to the task list, not proof about grades elsewhere in ManageBac.',
    {'class_id': STRING, 'url': STRING, 'scope': STRING, 'assessments': array(ASSESSMENT)},
    title='Get published grades', invoking='Reading published grades…', invoked='Read published grades')


async def get_grades(client, origin, arguments):
    async def run(args):
        path = f'/student/classes/{args.class_id}/core_tasks'
        def parse(html, url):
            rows, following = parse_grades(html, origin, args.class_id, url)
            for row in rows:
                value = content(row.pop('_assessment'), origin, url)
                if not value: raise FlowError('layout_changed', 'An assessment block could not be read.')
                row['assessment'] = value
                feedback = row.pop('_feedback')
                if feedback is not None:
                    value = content(feedback, origin, url)
                    if value: row['feedback'] = value
            return rows, following
        return {'class_id': args.class_id, 'url': origin + path,
                'scope': 'assessment blocks displayed on the class task list',
                'assessments': await collect(client, origin, path, parse)}
    return await execute(ClassArguments, arguments, run)
