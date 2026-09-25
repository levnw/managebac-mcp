"""One compact rich-content serializer shared by non-task entities."""
from sources.managebac.rich_text import RichText
from .task_output import TaskView


def content(node, origin, url):
    rich = RichText(origin, url)
    nodes = rich.parse(node)
    return {key: value for key, value in TaskView(rich.assets).content(nodes).items() if value}
