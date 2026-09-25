"""Explicitly scoped search composed from the same task-list reader."""
from pydantic import Field, model_validator
from onboarding.transport import FlowError
from .contracts import NoArguments, definition
from .tasks import get_tasks
from .retrieval import execute
from .output_schemas import array, SCOPED_TASK


class Arguments(NoArguments):
    class_ids: list[str] = Field(min_length=1, max_length=10,
                                description='Explicit class IDs from get_classes; at most 10, no implicit school-wide crawl.')
    query: str = Field(default='', max_length=100, description='Case-insensitive title substring.')
    tag: str = Field(default='', max_length=100, description='Case-insensitive exact tag or assessment type.')

    @model_validator(mode='after')
    def validate_scope(self):
        from sources.managebac.pages import identifier
        for value in self.class_ids: identifier(value)
        if len(set(self.class_ids)) != len(self.class_ids): raise ValueError('Duplicate class IDs')
        if not self.query.strip() and not self.tag.strip(): raise ValueError('Search requires query or tag')
        return self


DEFINITION = definition('search_tasks', Arguments,
    'Search task titles and/or exact tags in explicitly selected classes. Both filters apply when provided. '
    'Replaces legacy find_task and tag_search. Fetches complete task lists sequentially, not details. '
    'Any class failure fails the whole search; never presents incomplete matches as complete.',
    {'tasks': array(SCOPED_TASK)}, limits='10 classes, 50 pages and 1000 tasks per class, 1000 matches',
    title='Search tasks', invoking='Searching tasks…', invoked='Searched tasks')


async def search_tasks(client, origin, arguments):
    async def run(args):
        found = []
        for class_id in args.class_ids:
            response = await get_tasks(client, origin, {'class_id': class_id})
            if 'error' in response:
                raise FlowError(response['error']['code'], 'One selected class could not be searched. No partial matches were returned.')
            for task in response['tasks']:
                tags = [str(v).casefold() for v in task.get('tags', [])] + [task.get('assessment_type', '').casefold()]
                if args.query.strip().casefold() not in task['title'].casefold(): continue
                if args.tag.strip() and args.tag.strip().casefold() not in tags: continue
                found.append({'class_id': class_id, **task})
                if len(found) > 1000: raise FlowError('result_too_large', 'More than 1000 matches; narrow the search.')
        return {'tasks': found}
    return await execute(Arguments, arguments, run)
