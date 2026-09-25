"""Single catalogue for registration, session dispatch and developer workbench."""
from . import classes, tasks, task, class_files, units, unit, timetable, upcoming
from . import search_tasks, grades

TOOLS = {module.DEFINITION.name: module for module in
         (classes, tasks, task, class_files, units, unit, timetable, upcoming,
          search_tasks, grades)}


def definitions():
    return [module.DEFINITION for module in TOOLS.values()]


async def invoke(name, client, origin, arguments):
    module = TOOLS.get(name)
    if module is None:
        return {'error': {'code': 'unknown_tool', 'message': 'Use a tool name from the catalogue.'}}
    return await getattr(module, name)(client, origin, arguments)
