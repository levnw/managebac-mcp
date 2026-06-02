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
from starlette.responses import HTMLResponse, PlainTextResponse, JSONResponse
from starlette.types import Scope, Receive, Send

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from . import users, config, admin, cache
from .context import set_current_user, reset_user, User
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
 <label>Invite code</label>
 <input name="invite" placeholder="Ask the admin for a code" autocomplete="off">
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
    err_html = f'<div class="err">{_html.escape(error)}</div>' if error else ""
    return _ENROLL_FORM.format(error=err_html)


async def _handle_enroll_get(request):
    return HTMLResponse(_enroll_form())


async def _handle_enroll_post(request):
    form = await request.form()
    mb_url = (form.get("mb_url") or "").strip()
    email = (form.get("email") or "").strip()
    password = (form.get("password") or "").strip()
    invite = (form.get("invite") or "").strip()

    if not (mb_url and email and password):
        return HTMLResponse(_enroll_form("All fields are required."), status_code=400)

    existing = users.get_user_by_email(mb_url, email)

    # New users must present a valid, unused one-time invite code. Returning
    # users (already enrolled) can re-enroll to update their password without one.
    if not existing:
        if not invite:
            return HTMLResponse(_enroll_form("An invite code is required to sign up."), status_code=403)
        if not admin.code_unused(invite):
            return HTMLResponse(_enroll_form("That invite code is invalid or already used."), status_code=403)

    if existing:
        users.update_password(existing.id, password)
        users.set_enabled(existing.id, True)            # re-enrolling re-enables
        user = users.get_user_by_id(existing.id)        # reload with new password
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

    # Login succeeded — now consume the one-time code (atomic; guards races).
    if not existing:
        if not admin.redeem_code(invite, user.id, email):
            users.delete_user(user.id)
            return HTMLResponse(_enroll_form("That invite code was just used. Ask for a new one."), status_code=403)

    # Warm their cache in the background so the first question is instant.
    # Fire-and-forget — the response below returns immediately.
    import asyncio as _asyncio
    from . import scraper
    _asyncio.create_task(scraper.prewarm(user))

    base = str(request.base_url).rstrip("/")
    connector_url = f"{base}/mcp?key={user.token}"
    return HTMLResponse(_SUCCESS_PAGE.format(label=_html.escape(user.label), connector_url=connector_url))


# ---------------------------------------------------------------------------
# Admin API (used by the admin app)
# ---------------------------------------------------------------------------

def _bearer(request) -> str:
    auth = request.headers.get("authorization", "")
    return auth[7:].strip() if auth.lower().startswith("bearer ") else ""


def _require_admin(request) -> str | None:
    return admin.validate_session(_bearer(request))


async def _admin_login(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not admin.verify_admin(username, password):
        return JSONResponse({"error": "Invalid username or password"}, status_code=401)
    return JSONResponse(admin.create_session(username))


async def _admin_codes_get(request):
    if not _require_admin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse({"codes": admin.list_codes()})


async def _admin_codes_post(request):
    if not _require_admin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    note = (body.get("note") or "").strip()
    return JSONResponse(admin.create_code(note))


async def _admin_code_delete(request):
    if not _require_admin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    admin.delete_code(request.path_params["code"])
    return JSONResponse({"ok": True})


async def _admin_users_get(request):
    if not _require_admin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    out = []
    for u in users.list_users():
        if u["id"] == "local":
            continue
        stats = cache.admin_user_stats(u["id"])
        out.append({**u, **stats})
    return JSONResponse({"users": out})


async def _admin_user_delete(request):
    if not _require_admin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    user_id = request.path_params["user_id"]
    # Clear their cached data, then remove the account.
    ctx = set_current_user(User(id=user_id, token="", label="", mb_url="", email="", password=""))
    try:
        cache.clear_user()
    finally:
        reset_user(ctx)
    users.delete_user(user_id)
    return JSONResponse({"ok": True})


async def _admin_user_pause(request):
    if not _require_admin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    enabled = bool(body.get("enabled", False))
    users.set_enabled(request.path_params["user_id"], enabled)
    return JSONResponse({"ok": True, "enabled": enabled})


async def _admin_user_regenerate(request):
    if not _require_admin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    new_token = users.regenerate_token(request.path_params["user_id"])
    if not new_token:
        return JSONResponse({"error": "user not found"}, status_code=404)
    return JSONResponse({"ok": True, "token": new_token})


async def _admin_user_activity(request):
    if not _require_admin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    user_id = request.path_params["user_id"]
    return JSONResponse({"activity": cache.admin_activity(user_id=user_id, limit=100)})


async def _admin_activity(request):
    if not _require_admin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse({"activity": cache.admin_activity(limit=100)})


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
        scope = dict(scope)
        scope["path"] = "/"
        scope["raw_path"] = b"/"
        # Normalize Accept + Content-Type. The MCP streamable-HTTP transport is
        # strict (needs Content-Type: application/json and Accept containing both
        # application/json and text/event-stream). Some clients (ChatGPT) send
        # application/octet-stream / a narrower Accept, which the SDK rejects with
        # 400/406. The body is JSON-RPC regardless, so we force the headers the
        # transport expects.
        headers = [(k, v) for (k, v) in scope["headers"]
                   if k.lower() not in (b"accept", b"content-type")]
        headers.append((b"accept", b"application/json, text/event-stream"))
        headers.append((b"content-type", b"application/json"))
        scope["headers"] = headers
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
            # Admin API (consumed by the admin app)
            Route("/admin/login", _admin_login, methods=["POST"]),
            Route("/admin/codes", _admin_codes_get, methods=["GET"]),
            Route("/admin/codes", _admin_codes_post, methods=["POST"]),
            Route("/admin/codes/{code}", _admin_code_delete, methods=["DELETE"]),
            Route("/admin/users", _admin_users_get, methods=["GET"]),
            Route("/admin/users/{user_id}", _admin_user_delete, methods=["DELETE"]),
            Route("/admin/users/{user_id}/pause", _admin_user_pause, methods=["POST"]),
            Route("/admin/users/{user_id}/regenerate", _admin_user_regenerate, methods=["POST"]),
            Route("/admin/users/{user_id}/activity", _admin_user_activity, methods=["GET"]),
            Route("/admin/activity", _admin_activity, methods=["GET"]),
        ],
        lifespan=lifespan,
    )

    # Top-level ASGI dispatch: anything under /mcp goes straight to the MCP
    # handler (raw ASGI, no Mount/redirect — a 307 on POST breaks ChatGPT).
    # lifespan + everything else falls through to Starlette.
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope.get("path", "")
            # ONLY the exact MCP endpoint goes to the handler. Anything deeper
            # (e.g. /mcp/.well-known/oauth-authorization-server, which ChatGPT
            # probes) must fall through to a 404 — NOT 401 — so ChatGPT concludes
            # the server is no-auth instead of demanding OAuth.
            if path == "/mcp" or path == "/mcp/":
                await handle_mcp(scope, receive, send)
                return
        await inner(scope, receive, send)

    return app


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn
    uvicorn.run(build_app(), host=host, port=port, log_level="info")
