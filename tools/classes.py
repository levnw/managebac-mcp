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
    "List the student's classes with their IDs and names. Use the IDs with the other tools.",
    {'classes': array(CLASS)}, title='Get classes',
    invoking='Reading your classes…', invoked='Read your classes',)


async def get_classes(client, origin: str, arguments: dict) -> dict:
    """Return {classes: [...]} after full traversal, otherwise {error: ...}."""
    async def run(args):
        # Limits are read at call time so operators and tests can tighten them.
        rows = await collect(client, origin, ROUTE, lambda html, url: parse_page(html, origin, url),
                             max_pages=MAX_PAGES, max_records=MAX_CLASSES, merge_identical=True)
        event('classes.output', count=len(rows))
        return ClassResult(classes=rows).model_dump()
    return await execute(Arguments, arguments, run, max_bytes=MAX_RESULT_BYTES, timeout=TOTAL_TIMEOUT_SECONDS)
