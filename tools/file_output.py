"""Compact class-file presentation, separate from HTML extraction/traversal."""
from onboarding.transport import FlowError
from .task_output import TaskView, public_asset


def compact_files(page: dict) -> list[dict]:
    assets = {asset['ref']: asset for asset in page.get('assets', [])}
    view = TaskView(page.get('assets', []))
    files = []
    for source in page['files']:
        asset = assets.get(source['ref'])
        if asset is None:
            raise FlowError('invalid_file', 'A file is missing its download reference. No partial listing was returned.')
        item = {key: source[key] for key in (
            'id', 'name', 'folder_id', 'size_bytes', 'size_display',
            'content_type', 'updated_at', 'uploaded_by', 'tags'
        ) if key in source and source[key] is not None}
        item.update({key: value for key, value in public_asset(asset).items() if key in ('url', 'file_id')})
        if 'description' in source:
            description = view.content(source['description'])
            if description['text']:
                item['description'] = description['text']
            item.update({key: value for key, value in description.items() if key != 'text'})
        files.append(item)
    return files
