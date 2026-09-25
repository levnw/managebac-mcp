"""Account-scoped tool access. Cookies never enter diagnostics or disk.

One long-lived HTTP client per account reuses connections (no TLS handshake per
tool call) and shares one cookie jar. Calls run concurrently up to a small cap,
which also bounds how hard one account can press the school's server.
"""
import asyncio
import json
import logging
import re
import time
import httpx
from onboarding.transport import FlowError
from onboarding.auth import Authenticator
from .catalogue import invoke, TOOLS
from diagnostics import capture, event, ReportWriter

MAX_CONCURRENT_CALLS = 4
TARGET_KEYS = ('class_id', 'task_id', 'folder_id', 'unit_id')


def report_target(arguments) -> dict:
    """Attributable IDs only: never free text, URLs, cookies or academic content."""
    if not isinstance(arguments, dict): return {}
    target = {key: arguments[key] for key in TARGET_KEYS
              if isinstance(arguments.get(key), str) and re.fullmatch(r'[0-9]{1,20}', arguments[key])}
    class_ids = arguments.get('class_ids')
    if (isinstance(class_ids, list) and 1 <= len(class_ids) <= 10
            and all(isinstance(value, str) and re.fullmatch(r'[0-9]{1,20}', value) for value in class_ids)):
        target['class_ids'] = class_ids
    return target


class ToolSession:
    def __init__(self, origin, cookies, client_factory, developer_mode=False, report_directory=None,
                 max_concurrent=MAX_CONCURRENT_CALLS):
        self.origin = origin
        self.client_factory = client_factory
        self.developer_mode = developer_mode
        self.report_writer = ReportWriter(report_directory, developer_mode) if report_directory else None
        self._cookies = httpx.Cookies(cookies)
        self._client = None
        self._slots = asyncio.Semaphore(max_concurrent)
        self._started = time.monotonic()

    @property
    def cookies(self) -> httpx.Cookies:
        return httpx.Cookies(self._client.cookies if self._client else self._cookies)

    def _http(self):
        if self._client is None or self._client.is_closed:
            self._client = self.client_factory()
            self._client.cookies.update(self._cookies)
        return self._client

    async def aclose(self):
        if self._client is not None:
            self._cookies = httpx.Cookies(self._client.cookies)
            await self._client.aclose()
            self._client = None

    async def call(self, name, arguments, *, record=None):
        """Run one tool. `record(report, result)` receives the developer report, if any."""
        if self.report_writer is None:
            # A host that records its own diagnostics keeps its capture context.
            return await self._run(name, arguments)
        with capture(name, self.developer_mode) as diagnostic:
            result = await self._run(name, arguments)
        if diagnostic:
            # Reports keep what the model saw; widget-only bytes are summarised, not stored.
            saved = {k: v for k, v in result.items() if k != '_meta'}
            if '_meta' in result:
                saved['_meta_omitted'] = {'files': len(result['_meta'].get('managebac/files', []))}
            report = diagnostic.export()
            target = report_target(arguments)
            if target: report['target'] = target
            definition = TOOLS[name].DEFINITION if name in TOOLS else None
            if definition is not None:
                report['tool_definition'] = definition.model_dump(mode='json', by_alias=True, exclude_none=True)
            report['serialized_bytes'] = len(json.dumps(saved, ensure_ascii=False, separators=(',', ':')).encode())
            # File writes stay off the event loop.
            report['export'] = await asyncio.to_thread(self.report_writer.save, report, saved)
            if report['export'] and not report['export']['saved']:
                logging.getLogger(__name__).error('Developer report export failed; check private storage limits.')
            if record: record(report, saved)
        return result

    async def _run(self, name, arguments):
        async with self._slots:
            client = self._http()
            result = await invoke(name, client, self.origin, arguments)
            if result.get('error', {}).get('code') == 'session_expired':
                # A class-specific login redirect can be a route/permission problem.
                # Verify account controls before discarding the session. This never
                # submits credentials or retries the failed tool.
                try:
                    await Authenticator().verify_session(client, self.origin, existing_session=True)
                except (FlowError, httpx.HTTPError) as exc:
                    if isinstance(exc, FlowError) and exc.code == 'session_expired':
                        event('session.expired_confirmed', seconds=int(time.monotonic() - self._started))
                    else:
                        event('session.verification_unavailable')
                        result = {'error': {'code': 'session_verification_unavailable',
                                  'message': 'The requested page requires sign-in, but the account check was inconclusive. '
                                             'Your session has been retained. Retry later; this does not prove your login expired.'}}
                else:
                    result = {'error': {'code': 'page_unavailable_authenticated',
                              'message': 'Your account session is still signed in, but this page redirected to login. '
                                         'Its route, availability or permissions need review; signing in again is not the first fix.'}}
            return result
