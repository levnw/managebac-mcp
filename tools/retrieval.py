"""Shared execution boundary for every narrow retrieval tool."""
import asyncio
import json
import httpx
from pydantic import ValidationError
from diagnostics import event
from onboarding.transport import FlowError

MAX_RESULT_BYTES = 250_000
TIMEOUT_SECONDS = 60


def size_label(limit: int) -> str:
    if limit >= 1_000_000: return f'{limit // 1_000_000} MB'
    return f'{limit // 1000} KB' if limit >= 1000 else f'{limit} bytes'


async def execute(model, arguments, operation, *, max_bytes=None, timeout=None):
    # Module limits are read at call time so operators and tests can tighten them.
    max_bytes = MAX_RESULT_BYTES if max_bytes is None else max_bytes
    timeout = TIMEOUT_SECONDS if timeout is None else timeout
    try:
        args = model.model_validate(arguments)
        result = await asyncio.wait_for(operation(args), timeout)
        # Widget-only _meta (e.g. file bytes for the files card) never reaches the model.
        visible = {k: v for k, v in result.items() if k != '_meta'}
        if len(json.dumps(visible, ensure_ascii=False, separators=(',', ':')).encode()) > max_bytes:
            raise FlowError('result_too_large', f'The response exceeds {size_label(max_bytes)}. Select a smaller scope; no data was silently truncated.')
        event('retrieval.complete')
        return result
    except ValidationError:
        code, message = 'invalid_arguments', 'Check required fields, allowed values and limits in the tool schema. IDs must be numeric strings; extra arguments are not accepted.'
    except FlowError as exc:
        code, message = exc.code, exc.message
    except TimeoutError:
        code, message = 'retrieval_timeout', f'Retrieval exceeded {timeout:g} seconds; no partial result was returned.'
    except httpx.HTTPError:
        code, message = 'network_error', 'A school-page request failed. No automatic password retry was made.'
    except UnicodeError:
        code, message = 'unsupported_encoding', 'The page text could not be decoded without losing information.'
    except Exception:
        code, message = 'internal_error', 'Retrieval failed. No partial result was returned; inspect developer diagnostics.'
    event('retrieval.failed')
    return {'error': {'code': code, 'message': message}}
