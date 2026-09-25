"""Task lists for 1–10 explicitly selected classes, with optional filters."""
from pydantic import Field, field_validator
from sources.managebac.collections import collect, MAX_RECORDS
from sources.managebac.tasks import parse_list
from onboarding.transport import FlowError
from .contracts import NoArguments, definition
from .output_schemas import array, ID, URL, TASK_IN_CLASS
from .retrieval import execute

MAX_CLASSES = 10


class Arguments(NoArguments):
    class_ids: list[str] = Field(min_length=1, max_length=MAX_CLASSES,
                                 description='Class IDs from get_classes (1–10). No implicit school-wide crawl.')
    title: str = Field(default='', max_length=100, description='Optional: case-insensitive substring of the task title.')
    tag: str = Field(default='', max_length=100, description='Optional: exact tag or assessment type, case-insensitive.')
    status: str = Field(default='', max_length=50, description='Optional: exact status as shown, e.g. "Pending", case-insensitive.')

    @field_validator('class_ids')
    @classmethod
    def unique_numeric(cls, values):
        if any(not value.isdecimal() or len(value) > 20 for value in values):
            raise ValueError('Class IDs are numeric strings from get_classes.')
        if len(set(values)) != len(values):
            raise ValueError('Duplicate class IDs.')
        return values


DEFINITION = definition('get_tasks', Arguments,
    'List tasks for 1–10 classes: IDs, titles, links and the due date, status, assessment type and tags exactly '
    'as ManageBac shows them. Optional filters (title substring, exact tag, exact status) all apply together; '
    'without filters every task is returned. Each task carries its class_id; classes gives each class task-list '
    'url. Due dates are often shown without a date (e.g. "Friday at 6:00 PM"); do not infer a year, date or '
    'timezone, and there is no reliable upcoming/past filter. Use get_task(class_id, task_id) for instructions, '
    'files, resources, submissions, assessment and feedback. Every selected class is read completely or the call '
    'fails; no partial list is returned.',
    {'classes': array({'type': 'object', 'additionalProperties': False, 'required': ['class_id', 'url'],
                       'properties': {'class_id': ID, 'url': {**URL, 'description': 'The class task list in ManageBac.'}}}),
     'tasks': array(TASK_IN_CLASS)},
    title='Get tasks', invoking='Reading task lists…', invoked='Read task lists',
    limits='10 classes, 50 pages per class, 1000 tasks')


def matches(task, args) -> bool:
    fold = str.casefold
    if args.title.strip() and fold(args.title.strip()) not in fold(task['title']):
        return False
    if args.tag.strip() and fold(args.tag.strip()) not in {fold(str(v)) for v in
                                                           [*task.get('tags', []), task.get('assessment_type', '')]}:
        return False
    if args.status.strip() and fold(args.status.strip()) != fold(task.get('status', '')):
        return False
    return True


async def get_tasks(client, origin: str, arguments: dict):
    async def run(args):
        classes, found = [], []
        for class_id in args.class_ids:
            path = f'/student/classes/{class_id}/core_tasks'
            tasks = await collect(client, origin, path, lambda html, url: parse_list(html, origin, class_id, url))
            classes.append({'class_id': class_id, 'url': origin + path})
            found += [{'class_id': class_id, **task} for task in tasks if matches(task, args)]
            if len(found) > MAX_RECORDS:
                raise FlowError('result_too_large', f'More than {MAX_RECORDS} tasks; select fewer classes or add a filter.')
        return {'classes': classes, 'tasks': found}
    return await execute(Arguments, arguments, run)
