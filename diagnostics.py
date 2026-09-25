"""Bounded, opt-in diagnostic events. Never accepts arbitrary bodies/headers."""
from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import secrets
import time
import json
import os
from pathlib import Path


class ReportWriter:
    """Operator-only exports; never used as a retrieval cache.

    Callers supply an explicit safe response, never request/session objects.
    Stop at 1,000 runs rather than silently deleting developer evidence.
    """

    MAX_RUNS = 1000

    def __init__(self, directory, enabled=False):
        self.directory = Path(directory)
        self.enabled = enabled

    def status(self) -> dict:
        """Visible capacity, so a full evidence folder is never a silent stop."""
        if not self.enabled:
            return {'enabled': False}
        try:
            runs = sum(1 for _ in self.directory.iterdir()) if self.directory.is_dir() else 0
        except OSError:
            return {'enabled': True, 'state': 'unreadable'}
        state = 'full' if runs >= self.MAX_RUNS else 'nearly_full' if runs >= self.MAX_RUNS * 0.9 else 'ok'
        return {'enabled': True, 'state': state, 'runs': runs, 'limit': self.MAX_RUNS}

    def save(self, diagnostic, response):
        if not self.enabled:
            return None
        try:
            documents = {
                'response.json': json.dumps(response, ensure_ascii=False, indent=2) + '\n',
                'report.json': json.dumps(diagnostic, ensure_ascii=False, indent=2) + '\n',
            }
            if sum(len(value.encode('utf-8')) for value in documents.values()) > 2_000_000:
                raise ValueError('report size limit')
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            if self.directory.is_symlink():
                raise ValueError('unsafe report directory')
            self.directory.chmod(0o700)
            if sum(1 for _ in self.directory.iterdir()) >= self.MAX_RUNS:
                raise ValueError('report count limit')
            # Operation is internal, but still validate before using it in a filename.
            operation = diagnostic['operation']
            if operation != 'login':
                # Resolve at export time to avoid an import cycle. Registering a
                # tool once also enables its developer reports, without a second list.
                from tools.catalogue import TOOLS
                if operation not in TOOLS:
                    raise ValueError('unsupported report operation')
            run = self.directory / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
                                    + '-' + operation + '-' + secrets.token_hex(6))
            run.mkdir(mode=0o700)
            for name, document in documents.items():
                with open(os.open(run / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
                          'w', encoding='utf-8') as stream:
                    stream.write(document)
            return {'saved': True, 'response_file': str(run / 'response.json'),
                    'report_file': str(run / 'report.json')}
        except (OSError, ValueError, TypeError):
            # Do not leak exception text or fail the underlying login/tool call.
            return {'saved': False, 'error': 'Report export failed. Check directory permissions, disk space, and the 1,000-run/2 MB limits. A partial folder may remain.'}

@dataclass
class Report:
    operation: str
    id: str = field(default_factory=lambda: secrets.token_hex(12))
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started: float = field(default_factory=time.monotonic)
    events: list = field(default_factory=list)
    layout: dict = field(default_factory=dict)

    def export(self):
        value = {"id": self.id, "operation": self.operation, "started_at": self.started_at,
                 "duration_ms": round((time.monotonic()-self.started)*1000), "events": self.events}
        if self.layout: value["layout"] = self.layout
        return value

current = ContextVar('diagnostic_report', default=None)

@contextmanager
def capture(operation: str, enabled: bool):
    report = Report(operation) if enabled else None
    token = current.set(report)
    try:
        yield report
    finally:
        current.reset(token)

def event(stage: str, *, page: int | None = None, count: int | None = None,
          total: int | None = None, status: int | None = None, seconds: int | None = None):
    report = current.get()
    if report is not None and len(report.events) < 100:
        report.events.append({"stage": stage, **{k:v for k,v in
            {"page":page,"count":count,"total":total,"status":status,"seconds":seconds}.items() if v is not None}})


def layout_evidence(**fields):
    """Developer-mode page *structure* for unrecognised layouts: short UI labels and
    CSS class names only (each list <= 12 items, each string <= 80 chars). Callers
    must never pass instructional text, submissions, grades, URLs or HTML."""
    report = current.get()
    if report is None: return
    for key, values in fields.items():
        report.layout[key] = [str(v)[:300 if key == "interface_text" else 80] for v in list(values)[:12]]
