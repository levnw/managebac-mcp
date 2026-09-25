"""Explicit compact output contracts. Free-form maps are limited to source labels."""
S = {'type': 'string'}
ID = {'type': 'string', 'pattern': r'^[0-9]{1,20}$'}
URL = {'type': 'string', 'format': 'uri'}


def array(items):
    return {'type': 'array', 'items': items}


def obj(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}


# url is omitted for expiring signed links; file_id stays stable across page reads.
FILE_ID = {'type': 'string', 'pattern': r'^f_[0-9a-f]{16}$'}
MEDIA = obj({'id': S, 'kind': {'enum': ['image', 'file', 'link', 'embed', 'preview']},
             'url': URL, 'file_id': FILE_ID, 'name': S, 'title': S, 'size_display': S, 'media_type': S},
            ('id', 'kind'))
CELL = obj({'text': S, 'header': {'type': 'boolean'}, 'rowspan': {'type': 'integer', 'minimum': 1},
            'colspan': {'type': 'integer', 'minimum': 1}}, ('text',))
TABLE = obj({'id': S, 'rows': array(array(CELL)), 'caption': S}, ('id', 'rows'))
CONTENT = {'text': S, 'media': array(MEDIA), 'tables': array(TABLE)}
FIELDS = {'type': 'object', 'additionalProperties': S}
TASK_FIELDS = {'id': ID, 'title': S, 'url': URL, 'due_display': S, 'due_source': S,
               'status': S, 'assessment_type': S, 'tags': array(S), 'fields': FIELDS}
TASK_IN_CLASS = obj({**TASK_FIELDS, 'class_id': ID}, ('id', 'class_id', 'title', 'url'))
SLOT = obj({'day_display': S, 'period': S, 'period_end': S, 'class_name': S, 'class_id': ID,
            'time_display': S, 'details': array(S)}, ('day_display', 'period', 'class_name'))
NOTE = obj({'day_display': S, 'period': S, 'period_end': S, 'text': S}, ('day_display', 'period', 'text'))

CLASS = obj({'id': ID, 'name': S, 'url': URL}, ('id', 'name', 'url'))
CONTENT_OBJECT = obj(CONTENT, ('text',))
RESOURCE = obj({'author': S, 'posted_display': S, 'title': S, **CONTENT,
                'previews': array(obj({k: v for k, v in MEDIA['properties'].items() if k != 'id'}, ('kind',)))})
SUBMISSION = obj({'box': {'enum': ['present', 'not_detected']},
                  'upload_control': {'enum': ['enabled', 'disabled']},
                  'files': array(RESOURCE), 'details': CONTENT_OBJECT}, ('box',))
TASK_DETAIL = obj({'id': ID, 'class_id': ID, 'title': S, 'url': URL, 'due': S, 'status': S,
                   'assessment_type': S, 'tags': array(S), 'fields': FIELDS,
                   'description': {'type': 'string', 'description': 'Faithful compact Markdown; media/table markers refer to the arrays alongside this text.'},
                   'media': array(MEDIA), 'tables': array(TABLE),
                   'teacher_resources': array(RESOURCE), 'submission': SUBMISSION,
                   'feedback': {'anyOf': [array(RESOURCE), CONTENT_OBJECT]},
                   'assessment': {'anyOf': [array(RESOURCE), CONTENT_OBJECT]}},
                  ('id', 'class_id', 'title', 'url', 'description', 'submission'))
FILE = obj({'id': ID, 'file_id': FILE_ID, 'name': S, 'url': URL, 'folder_id': ID, 'content_type': S,
            'created_at': S, 'updated_at': S, 'uploaded_by': S, 'size_display': S,
            'size_bytes': {'type': 'integer', 'minimum': 0}, 'tags': array(S), 'description': S,
            'media': array(MEDIA), 'tables': array(TABLE)}, ('name',))
FILE['anyOf'] = [{'required': ['url']}, {'required': ['file_id']}]
FOLDER = obj({'id': ID, 'name': S, 'parent_id': ID, 'url': URL}, ('id', 'name', 'url'))
