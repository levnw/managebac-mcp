"""Opened files → readable text for the model (markitdown), within the result budget.

ChatGPT only reliably sees what a tool returns, so the open layer returns each
file's text rather than the file. One converter handles PDF, Word, PowerPoint,
Excel, CSV, HTML and plain text. Nothing is fetched, stored or sent elsewhere:
conversion runs in-process on the bytes just downloaded, one file at a time,
off the event loop. Images and scanned PDFs have no text layer and say so.
"""
import asyncio
import io
import json
import threading
from pathlib import PurePosixPath

MAX_TEXT_BYTES = 180_000      # all opened files together; the tool result limit is 250 KB
_converter = None
_lock = threading.Lock()      # one conversion at a time bounds CPU and memory


def _convert(data: bytes, name: str, mime: str) -> str:
    global _converter
    from markitdown import MarkItDown, StreamInfo
    with _lock:
        if _converter is None:
            _converter = MarkItDown(enable_plugins=False)
        extension = PurePosixPath(name).suffix.lower() or None
        result = _converter.convert_stream(io.BytesIO(data), stream_info=StreamInfo(extension=extension, mimetype=mime))
    return (result.text_content or '').strip()


async def extract(data: bytes, name: str, mime: str) -> tuple[str, str | None]:
    """(text, problem). problem is None when text was found, else an error code."""
    if mime.startswith('image/'):
        return '', 'no_text_layer'
    try:
        text = await asyncio.to_thread(_convert, data, name, mime)
    except Exception as exc:
        return '', 'unsupported_format' if type(exc).__name__ == 'UnsupportedFormatException' else 'conversion_failed'
    if binary(text):
        return '', 'conversion_failed'   # a damaged file fell through to the plain-text reader
    return (text, None) if text else ('', 'no_text_layer')


def binary(text: str) -> bool:
    control = sum(1 for c in text[:20_000] if ord(c) < 32 and c not in '\n\r\t' or c == '\ufffd')
    return control > max(2, len(text[:20_000]) // 200)


def json_size(text: str) -> int:
    return len(json.dumps(text, ensure_ascii=False).encode())


def cut(text: str, limit: int) -> str:
    """Longest prefix whose JSON encoding fits `limit` bytes."""
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if json_size(text[:middle]) <= limit: low = middle
        else: high = middle - 1
    return text[:low]


def share(texts: list[str], budget: int = MAX_TEXT_BYTES) -> list[str]:
    """Fit all texts in the budget: short files whole, the rest split the remainder evenly."""
    sizes = [json_size(t) for t in texts]
    allowed, left, waiting = [0] * len(texts), budget, sorted(range(len(texts)), key=lambda i: sizes[i])
    while waiting:
        fair = left // len(waiting)
        index = waiting.pop(0)
        allowed[index] = min(sizes[index], fair)
        left -= allowed[index]
    return [t if json_size(t) <= a else cut(t, a) for t, a in zip(texts, allowed)]
