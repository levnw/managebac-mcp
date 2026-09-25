"""Complete enrolled-class list in one JSON response; no protocol formatting here."""
from pydantic import BaseModel, ConfigDict

from diagnostics import event
from sources.managebac.classes import ROUTE, parse_page
from sources.managebac.collections import collect
from .contracts import NoArguments, definition
from .output_schemas import array, CLASS
from .retrieval import execute

MAX_PAGES = 100
MAX_CLASSES = 5000
MAX_RESULT_BYTES = 1_000_000
TOTAL_TIMEOUT_SECONDS = 60

Arguments = NoArguments


class ClassRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str
    name: str
    url: str


class ClassResult(BaseModel):
    model_config = ConfigDict(extra='forbid')
    classes: list[ClassRecord]


DEFINITION = definition('get_classes', Arguments,
    'List all enrolled classes for the signed-in student in one JSON response: '
    'classes contains IDs, full displayed names and links only. Takes no arguments. '
    'Reads every enrolled-class list page internally and validates the total before returning. '
    'Does not retrieve tasks, units, teachers, journals or files, browse other classes, or log in. '
    'On failure returns an error instead of an incomplete class list. Never infer no classes from an error.',
    {'classes': array(CLASS)}, title='Get classes',
    invoking='Reading your classes…', invoked='Read your classes',
    limits=f'{MAX_PAGES} pages, {MAX_CLASSES} classes', max_bytes=MAX_RESULT_BYTES,
    timeout=TOTAL_TIMEOUT_SECONDS)


async def get_classes(client, origin: str, arguments: dict) -> dict:
    """Return {classes: [...]} after full traversal, otherwise {error: ...}."""
    async def run(args):
        # Limits are read at call time so operators and tests can tighten them.
        rows = await collect(client, origin, ROUTE, lambda html, url: parse_page(html, origin, url),
                             max_pages=MAX_PAGES, max_records=MAX_CLASSES, merge_identical=True)
        event('classes.output', count=len(rows))
        return ClassResult(classes=rows).model_dump()
    return await execute(Arguments, arguments, run, max_bytes=MAX_RESULT_BYTES, timeout=TOTAL_TIMEOUT_SECONDS)
