"""Single catalogue for registration, session dispatch and developer workbench."""
from . import classes, tasks, task, class_files, timetable

TOOLS = {module.DEFINITION.name: module for module in (classes, tasks, task, class_files, timetable)}


def definitions():
    return [module.DEFINITION for module in TOOLS.values()]


async def invoke(name, client, origin, arguments):
    module = TOOLS.get(name)
    if module is None:
        return {'error': {'code': 'unknown_tool', 'message': 'Use a tool name from the catalogue.'}}
    return await getattr(module, name)(client, origin, arguments)
