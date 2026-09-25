"""Loopback-only functional onboarding workbench. Not a deployed OAuth server."""
import asyncio
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from .transport import FlowError, email_value
from .auth import Authenticator
from .school_discovery import SchoolDiscovery
from .store import Store
from diagnostics import capture, event, ReportWriter
from tools.session import ToolSession
from tools.catalogue import definitions, TOOLS

STATIC = Path(__file__).parent / "static"
ORIGIN = "http://127.0.0.1:8765"


def create_app(authenticator=None, school_discovery=None, directory=None, developer_mode=None):
    authenticator = authenticator or Authenticator()
    school_discovery = school_discovery or SchoolDiscovery()
    sessions, jobs = {}, set()
    developer_mode = (os.environ.get('MBV2_DEVELOPER_MODE') == '1') if developer_mode is None else developer_mode
    state_directory = Path(directory or os.environ.get('MBV2_STATE_DIR', str(Path.home() / '.managebac-v2')))
    report_directory = (state_directory / 'Test Reports') if directory is not None else Path(
        os.environ.get('MBV2_REPORT_DIR', str(Path(__file__).resolve().parents[1] / 'Test Reports')))
    report_writer = ReportWriter(report_directory, developer_mode)
    store = None

    def retire(s):
        """Close a replaced or expired account session's connections."""
        old, s['tool_session'] = s.get('tool_session'), None
        if old is not None:
            job = asyncio.create_task(old.aclose())
            jobs.add(job)
            job.add_done_callback(jobs.discard)

    async def record_response(s, diagnostic, response):
        diagnostic['export'] = await asyncio.to_thread(report_writer.save, diagnostic, response)
        s['reports'] = (s['reports'] + [diagnostic])[-5:]

    @asynccontextmanager
    async def lifespan(app):
        nonlocal store
        store = Store(directory or os.environ.get("MBV2_STATE_DIR", str(Path.home() / ".managebac-v2")))
        async def expire_sessions():
            while True:
                await asyncio.sleep(30)
                for key in list(sessions):
                    if sessions[key]['expires'] < time.time() and not sessions[key]['busy']:
                        retire(sessions.pop(key))
        reaper = asyncio.create_task(expire_sessions())
        try:
            yield
        finally:
            reaper.cancel()
            for job in jobs:
                job.cancel()
            for s in sessions.values():
                if s.get('tool_session') is not None:
                    await s['tool_session'].aclose()
            await asyncio.gather(reaper, *jobs, return_exceptions=True)
            sessions.clear()

    def session(request, mutation=False):
        token = request.cookies.get("mbv2_session", "")
        s = sessions.get(token)
        if not s or s["expires"] < time.time():
            raise FlowError("session_expired", "This setup session expired. Reload the page to start again.")
        if mutation and (request.headers.get("origin") != ORIGIN or
                         not secrets.compare_digest(request.headers.get("x-csrf-token", ""), s["csrf"])):
            raise FlowError("invalid_request", "This request could not be verified. Reload this page.")
        return s

    async def body(request):
        raw = await request.body()
        if len(raw) > 4096:
            raise FlowError("invalid_request", "The submitted form is too large.")
        try:
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except (ValueError, TypeError):
            raise FlowError("invalid_request", "The submitted form could not be read.")

    async def home(request):
        return FileResponse(STATIC / "index.html")

    async def script(request):
        return FileResponse(STATIC / "app.js", media_type="text/javascript")

    async def file_browser_script(request):
        return FileResponse(STATIC / "file-browser.js", media_type="text/javascript")

    async def bootstrap(request):
        now = time.time()
        existing = sessions.get(request.cookies.get('mbv2_session',''))
        if existing and existing['expires'] >= now:
            return JSONResponse({'csrf':existing['csrf'], 'mode':'local-development',
                'connection_enabled':False, 'developer_mode':developer_mode})
        for key in list(sessions):
            if sessions[key]["expires"] < now and not sessions[key]["busy"]:
                retire(sessions.pop(key))
        if len(sessions) >= 100:
            raise FlowError("busy", "Too many setup sessions. Try again later.")
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        sessions[token] = {"csrf": csrf, "expires": now + 1800, "school": None,
                           "email": None, "busy": False, "steps": [], "last_discovery": 0,
                           "revision": 0, "error": None, "authenticated": False, "verification": None,
                           "tool_session": None, "reports": []}
        r = JSONResponse({"csrf": csrf, "mode": "local-development", "connection_enabled": False,
                          "developer_mode":developer_mode})
        r.set_cookie("mbv2_session", token, httponly=True, samesite="strict", max_age=1800)
        return r

    async def discovery(request):
        s = session(request, True)
        data = await body(request)
        if s["busy"]:
            raise FlowError("busy", "Wait for the current check to finish.")
        email = email_value(str(data.get("email", "")))
        if time.time() - s["last_discovery"] < 1:
            raise FlowError("slow_down", "Wait a moment before searching again.")
        s["last_discovery"] = time.time()
        s["revision"] += 1
        revision = s["revision"]
        s["school"], s["email"] = None, None
        retire(s)
        s.update(authenticated=False, reports=[])
        with capture('school_discovery', developer_mode) as report:
            try:
                school = await school_discovery.discover(email)
            finally:
                if report and revision == s['revision']:
                    s['reports'] = (s['reports'] + [report.export()])[-5:]
        if s["revision"] != revision:
            raise FlowError("superseded", "A newer email lookup replaced this one.")
        s["school"], s["email"] = school, email
        return JSONResponse({"school": school})

    async def run(s, password):
        with capture('login', developer_mode) as report:
            try:
                await run_login(s, password)
            finally:
                if report:
                    # Compact safe status: absent fields are omitted, never null.
                    status = {'authenticated': s['authenticated'], 'verification': s['verification'],
                              'error': s['error']}
                    await record_response(s, report.export(), {k: v for k, v in status.items() if v is not None})

    async def run_login(s, password):
        def progress(name, state, message):
            row = {"name": name, "state": state, "message": message}
            for i, old in enumerate(s["steps"]):
                if old["name"] == name:
                    s["steps"][i] = row
                    return
            s["steps"].append(row)
        try:
            async with authenticator.client() as client:
                progress("signin", "running", "Signing into ManageBac…")
                identity = await authenticator.authenticate(client, s["school"]["origin"], s["email"], password)
                password = None
                progress("signin", "passed", "ManageBac sign-in verified using account controls. No school-data checks were run.")
                store.account(s["email"], s["school"]["origin"])
                s["authenticated"] = identity["authenticated"]
                s["verification"] = identity["verification"]
                s['tool_session'] = ToolSession(s['school']['origin'], client.cookies, authenticator.client,
                    developer_mode=developer_mode, report_directory=report_directory)
        except FlowError as e:
            s["error"] = {"code": e.code, "message": e.message, "diagnostic_id": secrets.token_hex(6)}
        except Exception:
            # Never include exception strings, upstream HTML, credentials or URLs in errors.
            s["error"] = {"code": "signin_failed", "message": "Sign-in verification could not finish. No automatic retry was made.", "diagnostic_id": secrets.token_hex(6)}
        finally:
            password = None
            for step in s["steps"]:
                if step["state"] == "running":
                    step["state"] = "failed"
            s["busy"] = False

    async def signin(request):
        s = session(request, True)
        data = await body(request)
        if s["busy"]:
            raise FlowError("busy", "A sign-in is already in progress.")
        if not s["school"] or data.get("email") != s["email"]:
            raise FlowError("discover_first", "Find the school for this email before signing in.")
        mode = data.get("mode")
        if mode not in ("signup", "login"):
            raise FlowError("invalid_request", "Choose sign up or sign in.")
        if mode == "signup" and data.get("understood") is not True:
            raise FlowError("overview_required", "Read the short setup overview before signing up.")
        password = data.get("password")
        if not isinstance(password, str) or not password or len(password) > 1024:
            raise FlowError("password_required", "Enter your ManageBac password.")
        exists = store.exists(s["email"], s["school"]["origin"])
        if mode == "login" and not exists:
            raise FlowError("signup_required", "No V2 setup exists for this account. Choose Sign up first.")
        if mode == "signup" and exists:
            raise FlowError("login_required", "This V2 account already exists. Choose Sign in.")
        if not store.reserve_attempt(s["email"]):
            raise FlowError("signin_cooldown", "A sign-in was recently attempted. Wait five minutes to protect your school account.")
        retire(s)
        s.update(busy=True, steps=[], error=None, authenticated=False, verification=None)
        job = asyncio.create_task(run(s, password))
        jobs.add(job)
        job.add_done_callback(jobs.discard)
        return JSONResponse({"started": True}, status_code=202)

    async def state(request):
        s = session(request)
        return JSONResponse({"busy": s["busy"], "steps": s["steps"], "error": s["error"],
                             "authenticated": s["authenticated"], "verification": s["verification"],
                             "capability_checks": "not_implemented", "connection_enabled": False,
                             "developer_mode":developer_mode,
                             "connection_note": "V2 OAuth/MCP connection is not implemented yet. This does not connect the old service."})

    async def reports(request):
        s = session(request)
        if not developer_mode:
            return JSONResponse({'developer_mode':False,'reports':[], 'message':'Developer mode was off; no report was collected.'})
        status = await asyncio.to_thread(report_writer.status)
        return JSONResponse({'developer_mode':True, 'export_status':status, 'reports':s['reports']})

    async def tool_catalogue(request):
        session(request)
        return JSONResponse({'tools': [d.model_dump(mode='json', by_alias=True, exclude_none=True) for d in definitions()]})

    async def retrieve_tool(request):
        s = session(request, True)
        name = request.path_params['tool_name']
        if name not in TOOLS:
            raise FlowError('unknown_tool', 'Choose a tool from the catalogue.')
        if not s['authenticated'] or not s['tool_session']:
            raise FlowError('login_required', 'Sign in before requesting school data.')
        if s['busy']:
            raise FlowError('busy', 'Wait for the current operation to finish.')
        arguments = await body(request)
        s['busy'] = True
        try:
            def record(report, result):
                s['reports'] = (s['reports'] + [{**report, 'tool_result': result}])[-5:]
            payload = await s['tool_session'].call(name, arguments, record=record)
            if payload.get('error', {}).get('code') == 'session_expired':
                retire(s)
                s.update(authenticated=False)
            return JSONResponse(payload)
        finally:
            s['busy'] = False

    async def flow_error(request, exc):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=400)

    async def network_error(request, exc):
        return JSONResponse({"error": {"code": "upstream_unavailable", "message": "ManageBac could not be reached. Try again later."}}, status_code=502)

    app = Starlette(lifespan=lifespan, routes=[Route("/", home), Route("/app.js", script),
        Route('/file-browser.js', file_browser_script),
        Route("/api/bootstrap", bootstrap), Route("/api/discover", discovery, methods=["POST"]),
        Route("/api/signin", signin, methods=["POST"]), Route("/api/state", state),
        Route('/api/reports',reports),
        Route('/api/tools',tool_catalogue), Route('/api/tools/{tool_name}',retrieve_tool,methods=['POST'])],
        exception_handlers={FlowError: flow_error, httpx.HTTPError: network_error})
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1"])

    async def headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'self'; img-src 'self' https:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"})
        return response
    app.add_middleware(BaseHTTPMiddleware, dispatch=headers)
    return app


app = create_app()
