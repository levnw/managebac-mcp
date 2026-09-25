"""Compact task list for one explicitly selected class."""
from pydantic import Field
from sources.managebac.collections import collect
from sources.managebac.tasks import parse_list
from .contracts import NoArguments, definition
from .output_schemas import array, ID, URL, TASK
from .retrieval import execute


class Arguments(NoArguments):
    class_id: str = Field(pattern=r'^\d{1,20}$', description='Class ID from get_classes; one class per call.')


DEFINITION = definition('get_tasks', Arguments,
    'List task summaries for one class: IDs, titles, source URLs and explicitly shown due dates, status, '
    'assessment type and tags. The top-level url opens the class task list; each task url opens that task. '
    'Follows list pagination internally. Use get_task(class_id, task_id) for instructions, images, files, '
    'resources and submissions. No task details, discussions, other classes, login or file downloads are requested. '
    'Dates remain as shown; do not infer a year or timezone.',
    {'class_id': ID, 'url': {**URL, 'description': 'The class task list in ManageBac.'}, 'tasks': array(TASK)},
    title='Get class tasks', invoking='Reading the task list…', invoked='Read the task list',
    limits='50 pages, 1000 tasks')


async def get_tasks(client, origin: str, arguments: dict):
    async def run(args):
        path = f'/student/classes/{args.class_id}/core_tasks'
        tasks = await collect(client, origin, path, lambda html, url: parse_list(html, origin, args.class_id, url))
        return {'class_id': args.class_id, 'url': origin + path, 'tasks': tasks}
    return await execute(Arguments, arguments, run)
