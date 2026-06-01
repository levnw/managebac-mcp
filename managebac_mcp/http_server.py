"""
Multi-user HTTP transport.

Each request carries a per-user token (the ?key= in the connector URL). The
server looks the token up, pins that user to the request context, and only
then dispatches to the tools — so every fetch and cache read is scoped to that
one user. Unknown token => 401. No token context => tools refuse (fail closed).

Also serves a self-service /enroll page where a new user enters their own
ManageBac login; on success they get their personal connector URL.
"""
import html as _html
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.responses import HTMLResponse, PlainTextResponse
from starlette.types import Scope, Receive, Send

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from . import users, config
from .context import set_current_user, reset_user
from .server import server


# ---------------------------------------------------------------------------
# Token extraction
# ---------------------------------------------------------------------------

def _provided_token(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            v = value.decode("latin-1")
            if v.lower().startswith("bearer "):
                return v[7:].strip()
    qs = scope.get("query_string", b"").decode("latin-1")
    for pair in qs.split("&"):
        if pair.startswith("key="):
            from urllib.parse import unquote
            return unquote(pair[4:])
    return None


# ---------------------------------------------------------------------------
# Enroll page
# ---------------------------------------------------------------------------

_ENROLL_FORM = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connect your ManageBac</title>
<style>
 body{{font-family:system-ui,sans-serif;max-width:30rem;margin:3rem auto;padding:0 1rem;color:#222}}
 h1{{font-size:1.4rem}} label{{display:block;margin:1rem 0 .25rem;font-weight:600}}
 input{{width:100%;padding:.6rem;border:1px solid #ccc;border-radius:.4rem;font-size:1rem}}
 button{{margin-top:1.5rem;padding:.7rem 1.2rem;background:#0a7;color:#fff;border:0;border-radius:.4rem;font-size:1rem;cursor:pointer}}
 .note{{background:#f6f6f6;padding:1rem;border-radius:.5rem;font-size:.85rem;color:#555;margin-top:2rem}}
 .err{{background:#fdd;color:#900;padding:.8rem;border-radius:.4rem;margin-bottom:1rem}}
</style></head><body>
<h1>Connect your ManageBac account</h1>
{error}
<form method="post" action="/enroll">
 <label>ManageBac URL</label>
 <input name="mb_url" value="https://es.managebac.com" required>
 <label>Email</label>
 <input name="email" type="email" required autocomplete="off">
 <label>Password</label>
 <input name="password" type="password" required autocomplete="off">
 {invite_field}
 <button type="submit">Connect</button>
</form>
<div class="note">Your login is used only to read your own ManageBac data and is
stored encrypted. You will get a private URL to paste into ChatGPT. Never share
that URL — anyone who has it can see your account.</div>
</body></html>"""

_SUCCESS_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connected</title>
<style>
 body{{font-family:system-ui,sans-serif;max-width:34rem;margin:3rem auto;padding:0 1rem;color:#222}}
 code{{display:block;background:#f6f6f6;padding:1rem;border-radius:.5rem;word-break:break-all;margin:1rem 0;font-size:.9rem}}
 .warn{{background:#fff3cd;padding:1rem;border-radius:.5rem;font-size:.9rem}}
</style></head><body>
<h1>✓ Connected, {label}</h1>
<p>Add this as a custom MCP connector in ChatGPT:</p>
<code>{connector_url}</code>
<div class="warn"><b>Keep this URL private.</b> Anyone who has it can read your
ManageBac account. If it leaks, re-enroll to get a new one.</div>
</body></html>"""


def _enroll_form(error: str = "") -> str:
    invite_field = ""
    if config.SIGNUP_CODE:
        invite_field = ('<label>Invite code</label>'
                        '<input name="invite" required autocomplete="off">')
    err_html = f'<div class="err">{_html.escape(error)}</div>' if error else ""
    return _ENROLL_FORM.format(error=err_html, invite_field=invite_field)


async def _handle_enroll_get(request):
    return HTMLResponse(_enroll_form())


async def _handle_enroll_post(request):
    form = await request.form()
    mb_url = (form.get("mb_url") or "").strip()
    email = (form.get("email") or "").strip()
    password = (form.get("password") or "").strip()
    invite = (form.get("invite") or "").strip()

    if config.SIGNUP_CODE and invite != config.SIGNUP_CODE:
        return HTMLResponse(_enroll_form("Invalid invite code."), status_code=403)
    if not (mb_url and email and password):
        return HTMLResponse(_enroll_form("All fields are required."), status_code=400)

    # Reuse an existing record for this URL+email, else create a fresh one.
    existing = users.get_user_by_email(mb_url, email)
    if existing:
        users.update_password(existing.id, password)
        user = users.get_user_by_token(existing.token)  # reload with new password
    else:
        user = users.create_user(label=email, mb_url=mb_url, email=email, password=password)

    # Verify the credentials by attempting a real login (scoped to this user).
    from .auth import get_client, login
    ctx = set_current_user(user)
    try:
        async with await get_client() as client:
            await login(client)
    except Exception:
        if not existing:
            users.delete_user(user.id)
        return HTMLResponse(
            _enroll_form("Could not log in to ManageBac — check the URL, email, and password."),
            status_code=401,
        )
    finally:
        reset_user(ctx)

    base = str(request.base_url).rstrip("/")
    connector_url = f"{base}/mcp?key={user.token}"
    return HTMLResponse(_SUCCESS_PAGE.format(label=_html.escape(user.label), connector_url=connector_url))


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

def build_app(*, stateless: bool = True):
    session_manager = StreamableHTTPSessionManager(
        app=server,
        stateless=stateless,
        json_response=False,
    )

    async def handle_mcp(scope: Scope, receive: Receive, send: Send) -> None:
        token = _provided_token(scope)
        user = users.get_user_by_token(token) if token else None
        if user is None:
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body",
                        "body": b'{"error":"unauthorized - unknown or missing token"}'})
            return
        # The streamable-HTTP transport handles the request at whatever path it
        # sees; normalize to "/" so /mcp and /mcp/ behave identically.
        scope = dict(scope)
        scope["path"] = "/"
        scope["raw_path"] = b"/"
        ctx = set_current_user(user)
        try:
            await session_manager.handle_request(scope, receive, send)
        finally:
            reset_user(ctx)

    async def health(request):
        return PlainTextResponse("ManageBac MCP server is running. Visit /enroll to connect an account.")

    @asynccontextmanager
    async def lifespan(app):
        async with session_manager.run():
            yield

    # Starlette handles the human-facing routes (/, /enroll) including form parsing.
    inner = Starlette(
        routes=[
            Route("/", health, methods=["GET"]),
            Route("/enroll", _handle_enroll_get, methods=["GET"]),
            Route("/enroll", _handle_enroll_post, methods=["POST"]),
        ],
        lifespan=lifespan,
    )

    # Top-level ASGI dispatch: anything under /mcp goes straight to the MCP
    # handler (raw ASGI, no Mount/redirect — a 307 on POST breaks ChatGPT).
    # lifespan + everything else falls through to Starlette.
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path == "/mcp" or path.startswith("/mcp/") or path == "/mcp/":
                await handle_mcp(scope, receive, send)
                return
        await inner(scope, receive, send)

    return app


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn
    uvicorn.run(build_app(), host=host, port=port, log_level="info")
