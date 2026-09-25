"""Exactly one task page, preserving rich content and resource relationships."""
from pydantic import Field
from sources.managebac.pages import fetch_html
from sources.managebac.task_detail import parse_detail
from .contracts import NoArguments, definition
from .output_schemas import TASK_DETAIL
from .retrieval import execute
from .task_output import compact_task


class Arguments(NoArguments):
    class_id: str = Field(pattern=r'^\d{1,20}$', description='Parent class ID returned by get_classes/get_tasks.')
    task_id: str = Field(pattern=r'^\d{1,20}$', description='Task ID from get_tasks in the specified class.')


DEFINITION = definition('get_task', Arguments,
    'Read one task page. Returns compact Markdown instructions, task metadata, teacher_resources, '
    'submission box evidence and uploaded files, feedback and assessment when present. History is omitted. '
    'Media/table markers resolve to entries in the same content object. Images, downloadable files, links, videos and '
    'previews are references only: their contents have not been read or downloaded. School-stored files carry a '
    'stable file_id; expiring signed download links are omitted, so open such files from the task url. '
    'Omitted sections are not evidence of absence. submission.box=not_detected does not mean closed; '
    'upload_control describes a visible control, not a guarantee the server will accept uploads. Discussions are not requested. '
    'No automatic list, class-file, discussion, login or attachment calls.',
    {'task': TASK_DETAIL}, title='Get task details',
    invoking='Reading the task…', invoked='Read the task',
    limits='one 2 MB page, 120000 text characters, 300 assets')


async def get_task(client, origin: str, arguments: dict):
    async def retrieve(args):
        path = f'/student/classes/{args.class_id}/core_tasks/{args.task_id}'
        html = await fetch_html(client, origin, path)
        return {'task': compact_task(parse_detail(html, origin, args.class_id, args.task_id))}
    return await execute(Arguments, arguments, retrieve)
