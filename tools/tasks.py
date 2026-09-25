"""Tasks in two layers: list 1–10 classes (with filters), or open up to 10 chosen tasks."""
import httpx
from pydantic import Field, model_validator
from sources.managebac.collections import collect, MAX_RECORDS
from sources.managebac.pages import fetch_html
from sources.managebac.task_detail import parse_detail
from sources.managebac.tasks import parse_list
from onboarding.transport import FlowError
from .contracts import NoArguments, definition
from .output_schemas import array, obj, ID, S, URL, TASK_IN_CLASS, TASK_DETAIL
from .retrieval import execute
from .task_output import compact_task

MAX_CLASSES = MAX_OPEN = 10
NUMERIC = r'^[0-9]{1,20}$'
# These end the whole call: retrying other tasks cannot succeed.
FATAL = {'session_expired', 'rate_limited', 'unsafe_destination'}


class TaskRef(NoArguments):
    class_id: str = Field(pattern=NUMERIC)
    task_id: str = Field(pattern=NUMERIC)


class Arguments(NoArguments):
    class_ids: list[str] = Field(default=[], max_length=MAX_CLASSES,
                                 description='List layer: class IDs from get_classes (1–10).')
    title: str = Field(default='', max_length=100, description='List filter: case-insensitive substring of the task title.')
    tag: str = Field(default='', max_length=100, description='List filter: exact tag or assessment type, case-insensitive.')
    status: str = Field(default='', max_length=50, description='List filter: exact status as shown, e.g. "Pending".')
    open: list[TaskRef] = Field(default=[], max_length=MAX_OPEN,
                                description='Detail layer: up to 10 {class_id, task_id} pairs taken from a task list.')

    @model_validator(mode='after')
    def one_layer(self):
        if bool(self.class_ids) == bool(self.open):
            raise ValueError('Give either class_ids (list) or open (detail), not both or neither.')
        if self.open and (self.title or self.tag or self.status):
            raise ValueError('Filters apply to the list layer only.')
        if any(not value.isdecimal() or len(value) > 20 for value in self.class_ids):
            raise ValueError('Class IDs are numeric strings from get_classes.')
        refs = [(ref.class_id, ref.task_id) for ref in self.open]
        if len(set(self.class_ids)) != len(self.class_ids) or len(set(refs)) != len(refs):
            raise ValueError('Duplicate class or task IDs.')
        return self


TASK_ERROR = obj({'class_id': ID, 'task_id': ID, 'error': obj({'code': S, 'message': S}, ('code', 'message'))},
                 ('class_id', 'task_id', 'error'))

DEFINITION = definition('get_tasks', Arguments,
    'Tasks in two layers. LIST: pass class_ids (1–10) and optional filters (title substring, exact tag, exact '
    'status; all apply together) to get IDs, titles, links and the due date, status, assessment type and tags '
    'exactly as shown, each with its class_id; classes gives each class task-list url. Every selected class is '
    'read completely or the call fails. DETAIL: pass open with up to 10 {class_id, task_id} pairs from a list to '
    'get each task\'s compact Markdown instructions, media and tables, teacher_resources, submission evidence and '
    'files, assessment and feedback. A task that cannot be read appears with its own error; signed-out or '
    'rate-limited sessions fail the whole call. Due dates are often shown without a date (e.g. "Friday at 6:00 PM"); '
    'do not infer a year, date or timezone. File and image references are not read; school-stored files carry a '
    'stable file_id and expiring download links are omitted (see get_files). submission.box=not_detected does not '
    'mean closed; upload_control describes a visible control only. Omitted sections are not evidence of absence.',
    {'classes': array(obj({'class_id': ID, 'url': {**URL, 'description': 'The class task list in ManageBac.'}},
                          ('class_id', 'url'))),
     'tasks': array({'anyOf': [TASK_IN_CLASS, TASK_DETAIL, TASK_ERROR]})},
    required=['tasks'], title='Get tasks', invoking='Reading tasks…', invoked='Read tasks',
    limits='list: 10 classes, 50 pages per class, 1000 tasks; detail: 10 tasks, one 2 MB page each')


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


async def read_task(client, origin: str, class_id: str, task_id: str) -> dict:
    """One task page → compact detail. Shared with get_files' task layer."""
    html = await fetch_html(client, origin, f'/student/classes/{class_id}/core_tasks/{task_id}')
    return compact_task(parse_detail(html, origin, class_id, task_id))


async def get_tasks(client, origin: str, arguments: dict):
    async def run(args):
        if args.open:
            details = []
            for ref in args.open:
                try:
                    details.append(await read_task(client, origin, ref.class_id, ref.task_id))
                except FlowError as exc:
                    if exc.code in FATAL: raise
                    details.append({'class_id': ref.class_id, 'task_id': ref.task_id,
                                    'error': {'code': exc.code, 'message': exc.message}})
            return {'tasks': details}
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
