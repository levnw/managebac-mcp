"""Tasks in two layers: list 1–10 classes (with filters), or open up to 10 chosen tasks."""
import asyncio
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
from .dates import ISO_DATE, month_day, valid_range, within

MAX_CLASSES = MAX_OPEN = 10
NUMERIC = r'^[0-9]{1,20}$'
# These end the whole call: retrying other tasks cannot succeed.
PARALLEL_PAGES = 4   # task pages opened at once in the detail layer
FATAL = {'session_expired', 'rate_limited', 'unsafe_destination'}


class TaskRef(NoArguments):
    class_id: str = Field(pattern=NUMERIC)
    task_id: str = Field(pattern=NUMERIC)


class Arguments(NoArguments):
    class_ids: list[str] = Field(default=[], max_length=MAX_CLASSES,
                                 description='Class IDs from get_classes (up to 10) to list tasks from.')
    title: str = Field(default='', max_length=100, description='Only tasks whose title contains this text.')
    tag: str = Field(default='', max_length=100, description='Only tasks with this tag or assessment type, e.g. "Formative".')
    status: str = Field(default='', max_length=50, description='Only tasks with this status as ManageBac shows it, e.g. "Pending".')
    date_from: str = Field(default='', pattern=f'{ISO_DATE}|^$', description='Only tasks due on or after this day (YYYY-MM-DD).')
    date_to: str = Field(default='', pattern=f'{ISO_DATE}|^$', description='Only tasks due on or before this day (YYYY-MM-DD).')
    open: list[TaskRef] = Field(default=[], max_length=MAX_OPEN,
                                description='Up to 10 tasks to open, as {class_id, task_id} from a task list.')

    @model_validator(mode='after')
    def one_layer(self):
        if bool(self.class_ids) == bool(self.open):
            raise ValueError('Give either class_ids (list) or open (detail), not both or neither.')
        if self.open and (self.title or self.tag or self.status or self.date_from or self.date_to):
            raise ValueError('Filters apply to the list layer only.')
        valid_range(self.date_from, self.date_to)
        if any(not value.isdecimal() or len(value) > 20 for value in self.class_ids):
            raise ValueError('Class IDs are numeric strings from get_classes.')
        refs = [(ref.class_id, ref.task_id) for ref in self.open]
        if len(set(self.class_ids)) != len(self.class_ids) or len(set(refs)) != len(refs):
            raise ValueError('Duplicate class or task IDs.')
        return self


TASK_ERROR = obj({'class_id': ID, 'task_id': ID, 'error': obj({'code': S, 'message': S}, ('code', 'message'))},
                 ('class_id', 'task_id', 'error'))

DEFINITION = definition('get_tasks', Arguments,
    "The student's tasks (assignments). Two ways to call it:\n"
    '- class_ids: list the tasks in up to 10 classes, with due date, status and tags. Optional filters narrow the list.\n'
    '- open: full details of up to 10 tasks: instructions, teacher resources, the student\'s submission, '
    'assessment and feedback.\n'
    'ManageBac shows due dates without a year; due_date uses the nearest year.',
    {'classes': array(obj({'class_id': ID, 'url': {**URL, 'description': 'The class task list in ManageBac.'}},
                          ('class_id', 'url'))),
     'tasks': array({'anyOf': [TASK_IN_CLASS, TASK_DETAIL, TASK_ERROR]}),
     'undated': array(obj({'class_id': ID, 'id': ID, 'title': S}, ('class_id', 'id', 'title')))},
    required=['tasks'], title='Get tasks', invoking='Reading tasks…', invoked='Read tasks')


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
    parsed = parse_detail(html, origin, class_id, task_id)
    task = compact_task(parsed)
    due = month_day(parsed.get('due_month_day', ''))
    return {**task, 'due_date': due} if due else task


async def get_tasks(client, origin: str, arguments: dict):
    async def run(args):
        if args.open:
            gate = asyncio.Semaphore(PARALLEL_PAGES)
            async def one(ref):
                async with gate:
                    try:
                        return await read_task(client, origin, ref.class_id, ref.task_id)
                    except FlowError as exc:
                        if exc.code in FATAL: raise
                        return {'class_id': ref.class_id, 'task_id': ref.task_id,
                                'error': {'code': exc.code, 'message': exc.message}}
            return {'tasks': list(await asyncio.gather(*(one(ref) for ref in args.open)))}
        classes, found, undated = [], [], []
        dated = bool(args.date_from or args.date_to)
        for class_id in args.class_ids:
            path = f'/student/classes/{class_id}/core_tasks'
            tasks = await collect(client, origin, path, lambda html, url: parse_list(html, origin, class_id, url))
            classes.append({'class_id': class_id, 'url': origin + path})
            for task in tasks:
                due = month_day(task.pop('due_month_day', ''))
                task = {'class_id': class_id, **task, **({'due_date': due} if due else {})}
                if not matches(task, args): continue
                if dated and not due:
                    undated.append({'class_id': class_id, 'id': task['id'], 'title': task['title']})
                elif not dated or within(due, args.date_from, args.date_to):
                    found.append(task)
            if len(found) > MAX_RECORDS:
                raise FlowError('result_too_large', f'More than {MAX_RECORDS} tasks; select fewer classes or add a filter.')
        return {'classes': classes, 'tasks': found, **({'undated': undated} if undated else {})}
    return await execute(Arguments, arguments, run)
