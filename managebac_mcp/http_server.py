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

from . import users, config, admin, cache, branding
from .context import set_current_user, reset_user, User
from .server import server, _TASK_WIDGETS, set_server_public_url
from .enroll_server import enroll_server, set_enroll_public_url

# Public URL for UI component links (set by build_app)
_PUBLIC_URL = "http://localhost:8000"

import time as _time
_SERVER_START_TIME = _time.time()

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

# Styled to match ManageBac's own login page: Open Sans, blue-50 background
# (#eff8ff), a 420px white card with the rounded school logo overlapping its top,
# a school-name header with a bottom border, blue primary buttons (#1570ef).
_STYLE = """
 @import url('https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;600;700&display=swap');
 *{{box-sizing:border-box}}
 body{{font-family:'Open Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
   background:#eff8ff;color:#101828;margin:0;padding:90px 16px 48px;line-height:1.429;
   -webkit-font-smoothing:antialiased}}
 .card{{position:relative;width:420px;max-width:100%;margin:0 auto;
   background:hsla(0,0%,100%,.94);border-radius:6px;box-shadow:0 0 5px rgba(0,0,0,.1);
   padding:62px 0 0}}
 .school-logo{{position:absolute;left:50%;top:-50px;width:100px;height:100px;border-radius:24px;
   background:#fff;box-shadow:0 0 10px rgba(0,0,0,.1);transform:translateX(-50%);overflow:hidden}}
 .school-logo img{{position:absolute;top:50%;left:50%;max-width:100%;max-height:100%;
   transform:translate(-50%,-50%)}}
 .head{{text-align:center;border-bottom:1px solid #eaecf0;padding:0 24px 16px;margin-bottom:4px}}
 .head h3{{font-size:18px;font-weight:700;letter-spacing:.04em;margin:0;color:#101828;text-transform:uppercase}}
 .head .sub{{color:#475467;font-size:13px;margin:6px 0 0}}
 .body{{padding:18px 24px 4px}}
 h1{{font-size:20px;font-weight:600;margin:0 0 6px;text-align:center}}
 .sub{{color:#475467;font-size:14px;margin:0 0 18px;text-align:center}}
 .steps{{background:#eff8ff;border:1px solid #d1e9ff;border-radius:6px;padding:14px 16px;margin:0 0 20px}}
 .steps p{{margin:0 0 6px;font-size:13px;font-weight:600;color:#175cd3}}
 .steps ol{{margin:0;padding-left:18px;color:#344054;font-size:13px}}
 .steps li{{margin:3px 0}}
 label{{display:block;font-size:14px;font-weight:600;color:#344054;margin:16px 0 6px}}
 .labelrow{{display:flex;justify-content:space-between;align-items:baseline;margin:16px 0 6px}}
 .labelrow label{{margin:0}}
 .req{{color:#d92d20;margin-left:2px;font-weight:600}}
 .field{{position:relative}}
 .field .icon{{position:absolute;right:14px;top:50%;transform:translateY(-50%);width:18px;height:18px;
   color:#98a2b3;pointer-events:none;transition:color .15s}}
 .field:focus-within .icon{{color:#1570ef}}
 input{{width:100%;padding:10px 42px 10px 16px;min-height:42px;border:1px solid #d0d5dd;border-radius:6px;
   font-size:15px;color:#101828;background:#fff;box-shadow:0 1px 2px rgba(16,24,40,.05);outline:none;
   transition:border-color .15s,box-shadow .15s}}
 input:focus{{border-color:#1570ef;box-shadow:0 1px 2px rgba(16,24,40,.05),inset 0 0 0 1px #1570ef}}
 input::placeholder{{color:#667085}}
 input[readonly]{{background:#f9fafb;color:#475467}}
 .actions{{border-top:1px solid #eaecf0;background:hsla(0,0%,100%,.4);
   border-radius:0 0 6px 6px;padding:18px 24px;margin-top:20px}}
 button{{width:100%;padding:10px;background:#1570ef;color:#fff;border:0;border-radius:6px;
   font-size:15px;font-weight:600;cursor:pointer;transition:background .15s}}
 button:hover{{background:#1259cb}}
 .note{{padding:0 24px 22px;font-size:12px;color:#667085;text-align:center}}
 .err{{background:#fef3f2;border:1px solid #fecdca;color:#b42318;padding:10px 12px;border-radius:6px;
   font-size:13px;margin-bottom:16px}}
 code{{display:block;background:#f9fafb;border:1px solid #eaecf0;padding:12px;border-radius:6px;
   word-break:break-all;margin:14px 0;font-size:13px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#101828}}
 .warn{{background:#fffaeb;border:1px solid #fedf89;color:#b54708;padding:12px;border-radius:6px;font-size:13px;
   margin:0 24px 22px}}
"""

# Field icons matching ManageBac's login (mail in Login, lock in Password); URL
# and invite get apt globe/key glyphs. Stroke=currentColor so they pick up the
# focus-blue via .field:focus-within .icon.
_IC_MAIL = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg>'
_IC_LOCK = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>'
_IC_GLOBE = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a15 15 0 0 1 0 18 15 15 0 0 1 0-18"/></svg>'
_IC_KEY = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="15" r="4"/><path d="m10.5 12.5 7-7"/><path d="M16 6l2 2"/><path d="M19 3l2 2"/></svg>'

def _head(brand: dict | None) -> str:
    """Render the per-school logo + name header from a branding dict."""
    brand = brand or {}
    name = _html.escape(brand.get("name") or "ManageBac")
    logo = brand.get("logo") or ""
    logo_html = (
        f'<div class="school-logo"><img src="{_html.escape(logo, quote=True)}" alt="School logo"></div>'
        if logo else ""
    )
    return f'{logo_html}\n <div class="head"><h3>{name}</h3><p class="sub">AI Assistant</p></div>'

_ENROLL_FORM = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connect ManageBac</title>
<style>""" + _STYLE + """</style></head><body>
<div class="card">
 {head}
 <form method="post" action="/enroll">
  <div class="body">
   {error}
   <p class="sub">Connect your ManageBac so you can ask ChatGPT about your classes,
   tasks, deadlines, grades and files.</p>
   <div class="labelrow"><label>ManageBac URL<span class="req">*</span></label></div>
   <div class="field"><input name="mb_url" value="https://es.managebac.com" required>""" + _IC_GLOBE + """</div>
   <div class="labelrow"><label>Login<span class="req">*</span></label></div>
   <div class="field"><input name="email" type="email" placeholder="you@school.edu" required autocomplete="off">""" + _IC_MAIL + """</div>
   <div class="labelrow"><label>Password<span class="req">*</span></label></div>
   <div class="field"><input name="password" type="password" placeholder="Your ManageBac password" required autocomplete="off">""" + _IC_LOCK + """</div>
   <div class="labelrow"><label>Invite code<span class="req">*</span></label></div>
   <div class="field"><input name="invite" value="{invite_value}" placeholder="Ask the admin for a code" autocomplete="off">""" + _IC_KEY + """</div>
  </div>
  <div class="actions"><button type="submit">Connect</button></div>
 </form>
 <p class="note">Read-only. Your login is stored encrypted and used only to read your
 own ManageBac data. Your link is private — never share it.</p>
</div>
</body></html>"""

_SET_PASSWORD_FORM = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Finish connecting</title>
<style>""" + _STYLE + """</style></head><body>
<div class="card">
 {head}
 <form method="post" action="/set-password">
  <input type="hidden" name="t" value="{token}">
  <div class="body">
   {error}
   <div class="labelrow"><label>Login</label></div>
   <div class="field"><input value="{email}" readonly>""" + _IC_MAIL + """</div>
   <div class="labelrow"><label>Password<span class="req">*</span></label></div>
   <div class="field"><input name="password" type="password" placeholder="Your ManageBac password" required autofocus autocomplete="off">""" + _IC_LOCK + """</div>
  </div>
  <div class="actions"><button type="submit">Finish connecting</button></div>
 </form>
 <p class="note">Read-only. Your login is stored encrypted and used only to read your
 own ManageBac data.</p>
</div>
</body></html>"""

_SUCCESS_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connected</title>
<style>""" + _STYLE + """</style></head><body>
<div class="card">
 {head}
 <div class="body">
  <h1>You're connected, {label}</h1>
  <p class="sub">Here's your personal connector link. Add it to ChatGPT to start.</p>
  <div class="steps">
   <p>Add it to ChatGPT</p>
   <ol>
    <li>ChatGPT → Settings → Connectors → Add custom connector.</li>
    <li>Paste the link below as the Server URL.</li>
    <li>Set Authentication to "No authentication", then create.</li>
   </ol>
  </div>
  <code>{connector_url}</code>
 </div>
 <div class="warn"><b>Keep this link private.</b> Anyone who has it can read your
 ManageBac account. If it leaks, ask the admin to regenerate it.</div>
</div>
</body></html>"""

_PENDING_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Request received</title>
<style>""" + _STYLE + """</style></head><body>
<div class="card">
 {head}
 <div class="body">
  <h1>Request received, {label}</h1>
  <p class="sub">Your account is connected and waiting for the admin to approve you.
  As soon as they do, the link below will start working in ChatGPT.</p>
  <div class="steps">
   <p>What happens next</p>
   <ol>
    <li>The admin approves your request.</li>
    <li>Add the link below to ChatGPT (Settings → Connectors → Add custom connector, "No authentication").</li>
    <li>Ask ChatGPT about your classes, tasks and deadlines.</li>
   </ol>
  </div>
  <code>{connector_url}</code>
 </div>
 <div class="warn"><b>Keep this link private.</b> It won't work until you're approved.
 Anyone who has it can read your ManageBac account.</div>
</div>
</body></html>"""


def _enroll_form(error: str = "", code: str = "", brand: dict | None = None) -> str:
    err_html = f'<div class="err">{_html.escape(error)}</div>' if error else ""
    return _ENROLL_FORM.format(head=_head(brand), error=err_html, invite_value=_html.escape(code, quote=True))


def _set_password_form(token: str, email: str, error: str = "", brand: dict | None = None) -> str:
    err_html = f'<div class="err">{_html.escape(error)}</div>' if error else ""
    return _SET_PASSWORD_FORM.format(
        head=_head(brand),
        token=_html.escape(token, quote=True),
        email=_html.escape(email, quote=True),
        error=err_html,
    )


async def _handle_enroll_get(request):
    # A shared invite link carries the code: /enroll?code=XXXX — pre-fill it.
    # Brand the page from a school URL if one is supplied (?school=…), else the
    # server's default school.
    school = request.query_params.get("school") or config.BASE_URL
    brand = await branding.get_branding(school)
    return HTMLResponse(_enroll_form(code=request.query_params.get("code", ""), brand=brand))


async def _create_and_verify(mb_url, email, password, invite, existing):
    """
    Shared enrollment finish: create/update the user, verify the login against
    ManageBac, consume the one-time invite code, and warm the cache. Returns
    (user, None) on success or (None, error_message) on failure. Used by both
    the web /enroll form and the in-chat /set-password handoff.
    """
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
        return None, "Could not log in to ManageBac — check the URL, email, and password."
    finally:
        reset_user(ctx)

    # Login succeeded — now consume the one-time code (atomic; guards races).
    if not existing:
        if not admin.redeem_code(invite, user.id, email):
            users.delete_user(user.id)
            return None, "That invite code was just used. Ask for a new one."

    # Warm their cache in the background so the first question is instant.
    # Fire-and-forget.
    import asyncio as _asyncio
    from . import scraper
    _asyncio.create_task(scraper.prewarm(user))
    return user, None


async def _handle_enroll_post(request):
    form = await request.form()
    mb_url = (form.get("mb_url") or "").strip()
    email = (form.get("email") or "").strip()
    password = (form.get("password") or "").strip()
    invite = (form.get("invite") or "").strip()

    brand = await branding.get_branding(mb_url or config.BASE_URL)

    if not (mb_url and email and password):
        return HTMLResponse(_enroll_form("All fields are required.", brand=brand), status_code=400)

    existing = users.get_user_by_email(mb_url, email)

    # New users must present a valid, unused one-time invite code. Returning
    # users (already enrolled) can re-enroll to update their password without one.
    if not existing:
        if not invite:
            return HTMLResponse(_enroll_form("An invite code is required to connect.", code=invite, brand=brand), status_code=403)
        if not admin.code_unused(invite):
            return HTMLResponse(_enroll_form("That invite code is invalid or already used.", code=invite, brand=brand), status_code=403)

    user, error = await _create_and_verify(mb_url, email, password, invite, existing)
    if error:
        status = 401 if "log in" in error else 403
        return HTMLResponse(_enroll_form(error, code=invite, brand=brand), status_code=status)

    base = str(request.base_url).rstrip("/")
    connector_url = f"{base}/mcp?key={user.token}"
    return HTMLResponse(_SUCCESS_PAGE.format(head=_head(brand), label=_html.escape(user.label), connector_url=connector_url))


_PENDING_EXPIRED = (
    "This link has expired or has already been used. Start again from ChatGPT by "
    "asking to enroll, and you'll get a fresh link."
)


async def _handle_set_password_get(request):
    """Secure one-time page where an in-chat enrollee types their ManageBac password."""
    token = request.query_params.get("t", "")
    pending = admin.get_pending(token)
    if pending is None:
        return HTMLResponse(_enroll_form(_PENDING_EXPIRED, brand=await branding.get_branding(config.BASE_URL)), status_code=410)
    brand = await branding.get_branding(pending["mb_url"])
    return HTMLResponse(_set_password_form(token, pending["email"], brand=brand))


async def _handle_set_password_post(request):
    form = await request.form()
    token = (form.get("t") or "").strip()
    password = (form.get("password") or "").strip()

    pending = admin.get_pending(token)
    if pending is None:
        return HTMLResponse(_enroll_form(_PENDING_EXPIRED, brand=await branding.get_branding(config.BASE_URL)), status_code=410)

    mb_url, email, invite = pending["mb_url"], pending["email"], pending["invite"]
    brand = await branding.get_branding(mb_url)
    if not password:
        return HTMLResponse(_set_password_form(token, email, "Password is required.", brand=brand), status_code=400)

    existing = users.get_user_by_email(mb_url, email)
    # Guard: if the code was consumed between the chat step and now.
    if not existing and not admin.code_unused(invite):
        admin.delete_pending(token)
        return HTMLResponse(_set_password_form(token, email,
            "That invite code is no longer valid. Ask the admin for a new one.", brand=brand), status_code=403)

    user, error = await _create_and_verify(mb_url, email, password, invite, existing)
    if error:
        # Keep the link alive on a wrong password so they can retry; drop it on
        # a consumed-code race (unrecoverable here).
        if "invite code" in error:
            admin.delete_pending(token)
            return HTMLResponse(_set_password_form(token, email, error, brand=brand), status_code=403)
        return HTMLResponse(_set_password_form(token, email, error, brand=brand), status_code=401)

    admin.delete_pending(token)
    base = str(request.base_url).rstrip("/")
    connector_url = f"{base}/mcp?key={user.token}"
    return HTMLResponse(_SUCCESS_PAGE.format(head=_head(brand), label=_html.escape(user.label), connector_url=connector_url))


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
        admin.log_audit(username or "unknown", "login_failed")
        return JSONResponse({"error": "Invalid username or password"}, status_code=401)
    session = admin.create_session(username)
    admin.log_audit(username, "login")
    return JSONResponse(session)


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
    result = admin.create_code(note)
    actor = _require_admin(request)
    admin.log_audit(actor, "create_invite_code", {"code": result["code"], "note": note})
    return JSONResponse(result)


async def _admin_code_delete(request):
    actor = _require_admin(request)
    if not actor:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    code = request.path_params["code"]
    admin.delete_code(code)
    admin.log_audit(actor, "revoke_invite_code", {"code": code})
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
    u = users.get_user_by_id(user_id)
    actor = _require_admin(request)
    users.delete_user(user_id)
    admin.log_audit(actor, "delete_user", {"user_id": user_id, "email": u.email if u else None})
    return JSONResponse({"ok": True})


async def _admin_user_pause(request):
    if not _require_admin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    enabled = bool(body.get("enabled", False))
    user_id = request.path_params["user_id"]
    users.set_enabled(user_id, enabled)
    actor = _require_admin(request)
    u = users.get_user_by_id(user_id)
    admin.log_audit(actor, "resume_user" if enabled else "pause_user",
                    {"user_id": user_id, "email": u.email if u else None})
    return JSONResponse({"ok": True, "enabled": enabled})


async def _admin_user_regenerate(request):
    if not _require_admin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    new_token = users.regenerate_token(request.path_params["user_id"])
    if not new_token:
        return JSONResponse({"error": "user not found"}, status_code=404)
    return JSONResponse({"ok": True, "token": new_token})


async def _admin_user_approve(request):
    if not _require_admin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    approved = bool(body.get("approved", True))
    users.set_approved(request.path_params["user_id"], approved)
    return JSONResponse({"ok": True, "approved": approved})


async def _admin_user_note(request):
    if not _require_admin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    users.set_note(request.path_params["user_id"], (body.get("note") or ""))
    return JSONResponse({"ok": True})


async def _admin_user_credentials(request):
    """Admin: change a user's ManageBac email and/or password. Clears their
    stale session, then (unless verify=false) tries a real login with the new
    credentials and reports whether it worked — so the admin gets immediate
    feedback instead of finding out via a failed tool call later."""
    if not _require_admin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_id = request.path_params["user_id"]
    email = (body.get("email") or "").strip()
    password = body.get("password") or ""
    verify = body.get("verify", True)

    if not users.get_user_by_id(user_id):
        return JSONResponse({"error": "user not found"}, status_code=404)
    if not email and not password:
        return JSONResponse({"error": "Provide a new email and/or password."}, status_code=400)

    old_user = users.get_user_by_id(user_id)
    if email:
        users.update_email(user_id, email)
    if password:
        users.update_password(user_id, password)
    # Old cookies are tied to the old login — clear so the next fetch re-logs-in.
    users.save_cookies(user_id, {})
    actor = _require_admin(request)
    if email:
        admin.log_audit(actor, "edit_email", {"user_id": user_id,
                        "old_email": old_user.email if old_user else None, "new_email": email})
    if password:
        admin.log_audit(actor, "reset_password", {"user_id": user_id,
                        "email": old_user.email if old_user else None})

    result = {"ok": True}
    if verify:
        user = users.get_user_by_id(user_id)   # reload with the new credentials
        from .auth import get_client, login
        ctx = set_current_user(user)
        try:
            async with await get_client() as client:
                await login(client)
            result["login_ok"] = True
        except Exception as e:
            result["login_ok"] = False
            result["login_error"] = str(e)
        finally:
            reset_user(ctx)
    return JSONResponse(result)


async def _admin_user_activity(request):
    if not _require_admin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    user_id = request.path_params["user_id"]
    return JSONResponse({"activity": cache.admin_activity(user_id=user_id, limit=100)})


async def _admin_activity(request):
    if not _require_admin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse({"activity": cache.admin_activity(limit=100)})


async def _admin_logout(request):
    token = _bearer(request)
    if token:
        actor = admin.validate_session(token) or "unknown"
        admin.revoke_session(token)
        admin.log_audit(actor, "logout")
    return JSONResponse({"ok": True})


async def _admin_health(request):
    if not _require_admin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    import time, os
    try:
        import psutil
        proc = psutil.Process(os.getpid())
        mem_mb = proc.memory_info().rss / (1024 * 1024)
        cpu = proc.cpu_percent(interval=0.1)
    except ImportError:
        mem_mb = 0.0
        cpu = 0.0
    uptime_s = int(time.time() - _SERVER_START_TIME)
    stats = cache.admin_health_stats()
    return JSONResponse({
        "status": "running",
        "uptime_s": uptime_s,
        "memory_mb": round(mem_mb, 1),
        "cpu_pct": round(cpu, 1),
        **stats,
    })


async def _admin_user_get(request):
    if not _require_admin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    user_id = request.path_params["user_id"]
    u = users.get_user_by_id(user_id)
    if not u:
        return JSONResponse({"error": "not found"}, status_code=404)
    stats = cache.admin_user_stats(user_id)
    cache_entries = cache.admin_cache_entries(user_id)
    u_dict = vars(u) if hasattr(u, "__dict__") else dict(u._asdict())
    return JSONResponse({"user": {**u_dict, **stats}, "cache": cache_entries})


async def _admin_user_password_get(request):
    if not _require_admin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    user_id = request.path_params["user_id"]
    u = users.get_user_by_id(user_id)
    if not u:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"password": u.password})


async def _admin_user_cache_get(request):
    if not _require_admin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse({"cache": cache.admin_cache_entries(request.path_params["user_id"])})


async def _admin_user_cache_delete(request):
    if not _require_admin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    user_id = request.path_params["user_id"]
    key = request.path_params.get("key")
    cache.admin_expire_cache(user_id, key or None)
    return JSONResponse({"ok": True})


async def _admin_change_password(request):
    if not _require_admin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    new_pw = body.get("password") or ""
    if not new_pw:
        return JSONResponse({"error": "password required"}, status_code=400)
    username = _require_admin(request)
    admin.set_admin(username, new_pw)
    admin.log_audit(username, "change_admin_password")
    return JSONResponse({"ok": True})


async def _admin_messages_get(request):
    if not _require_admin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse({"messages": admin.list_messages()})


async def _admin_broadcast(request):
    if not _require_admin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    text = (body.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "text required"}, status_code=400)
    msg = admin.create_message(text=text, target_user_id=None)
    actor = _require_admin(request)
    admin.log_audit(actor, "broadcast", {"text": text[:100]})
    return JSONResponse(msg)


async def _admin_user_message(request):
    if not _require_admin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    text = (body.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "text required"}, status_code=400)
    user_id = request.path_params["user_id"]
    u = users.get_user_by_id(user_id)
    actor = _require_admin(request)
    msg = admin.create_message(text=text, target_user_id=user_id)
    admin.log_audit(actor, "send_message",
                    {"user_id": user_id, "email": u.email if u else None, "text": text[:100]})
    return JSONResponse(msg)


async def _admin_audit(request):
    if not _require_admin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse({"audit": admin.list_audit(limit=200)})


async def _admin_panel(request):
    """Serve the admin panel SPA."""
    import pathlib
    html_path = pathlib.Path(__file__).parent / "admin_panel" / "index.html"
    return HTMLResponse(html_path.read_text())


# ---------------------------------------------------------------------------
# UI Components (served to ChatGPT iframes)
# ---------------------------------------------------------------------------

async def _ui_test(request):
    """Serve a simple test UI to verify the infrastructure works."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Test UI</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="m-0 p-0 bg-white dark:bg-slate-950">
    <div class="p-8 max-w-2xl mx-auto">
        <div class="bg-green-50 dark:bg-green-900/20 border-2 border-green-500 rounded-lg p-6 text-center">
            <h1 class="text-4xl font-bold text-green-700 dark:text-green-400 mb-4">✅ UI IS WORKING!</h1>
            <p class="text-xl text-slate-700 dark:text-slate-300 mb-6">The iframe loaded successfully and is receiving data.</p>

            <div class="bg-slate-100 dark:bg-slate-800 rounded p-4 mb-6 text-left">
                <p class="text-sm font-mono text-slate-600 dark:text-slate-400 mb-2"><strong>Tool Input:</strong></p>
                <pre id="input" class="text-xs overflow-auto">Loading...</pre>
                <p class="text-sm font-mono text-slate-600 dark:text-slate-400 mt-4 mb-2"><strong>Tool Output:</strong></p>
                <pre id="output" class="text-xs overflow-auto">Loading...</pre>
            </div>

            <p class="text-sm text-slate-500 dark:text-slate-400">
                If you see this, the UI infrastructure is working correctly.
            </p>
        </div>
    </div>

    <script>
        // Display tool input and output
        document.getElementById('input').textContent = JSON.stringify(window.openai?.toolInput || {}, null, 2);
        document.getElementById('output').textContent = JSON.stringify(window.openai?.toolOutput || {}, null, 2);

        // Listen for updates
        window.addEventListener('message', (event) => {
            if (event.source !== window.parent) return;
            const msg = event.data;
            if (msg.method === 'ui/notifications/tool-result') {
                document.getElementById('output').textContent = JSON.stringify(msg.params?.structuredContent || {}, null, 2);
            }
        }, { passive: true });

        // Listen for theme changes
        window.addEventListener('openai:set_globals', (event) => {
            if (event.detail?.globals?.theme === 'dark') {
                document.documentElement.classList.add('dark');
            } else {
                document.documentElement.classList.remove('dark');
            }
        }, { passive: true });
    </script>
</body>
</html>"""
    return HTMLResponse(html)


async def _ui_task_detail(request):
    """Serve the task-detail UI component page."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Task Detail</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        html, body { margin: 0; padding: 0; height: 100%; }
        body { display: flex; flex-direction: column; overflow: hidden; }
        #root { flex: 1; overflow: auto; }
        .file-list { display: flex; flex-direction: column; gap: 0.5rem; }
        .file-item { display: flex; justify-content: space-between; align-items: center; padding: 0.75rem; border-radius: 0.5rem; border: 1px solid; }
        .file-item.attachment { background-color: #f1f5f9; border-color: #e2e8f0; }
        .file-item.submitted { background-color: #f0fdf4; border-color: #dcfce7; }
        .dark .file-item.attachment { background-color: #1e293b; border-color: #334155; }
        .dark .file-item.submitted { background-color: #052e16; border-color: #166534; }
        .prose { max-width: 100%; }
    </style>
</head>
<body class="bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-50">
    <div id="root">
        <div class="p-4 text-center text-gray-500">Loading task...</div>
    </div>

    <script>
        // Render task detail
        function render(task) {
            if (!task) {
                document.getElementById('root').innerHTML = '<div class="p-4 text-center text-gray-500">No task data</div>';
                return;
            }

            let html = '<div class="overflow-auto p-6 max-w-4xl mx-auto">';

            // Header
            html += '<div class="mb-6">';
            html += '<h1 class="text-3xl font-bold mb-2">' + _escape(task.title || 'Task') + '</h1>';
            if (task.status) {
                const statusClass = task.status.includes('submitted')
                    ? 'bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-100'
                    : task.status.includes('not submitted')
                    ? 'bg-orange-100 dark:bg-orange-900 text-orange-800 dark:text-orange-100'
                    : 'bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-100';
                html += '<span class="inline-block px-3 py-1 rounded-full text-sm font-medium ' + statusClass + '">' + _escape(task.status) + '</span>';
            }
            html += '</div>';

            // Due date
            if (task.due_date) {
                html += '<div class="mb-4 p-3 bg-slate-50 dark:bg-slate-900 rounded-lg">';
                html += '<p class="text-sm text-slate-600 dark:text-slate-400">Due: <strong>' + _escape(task.due_date) + '</strong></p>';
                html += '</div>';
            }

            // Description
            if (task.description) {
                html += '<div class="mb-6">';
                html += '<h2 class="text-xl font-semibold mb-3">Description</h2>';
                if (typeof task.description === 'string') {
                    html += '<p>' + _escape(task.description) + '</p>';
                } else if (task.description.text) {
                    html += '<div class="prose dark:prose-invert">' + task.description.text + '</div>';
                }
                if (task.description.links && task.description.links.length > 0) {
                    html += '<div class="mt-3 pt-3 border-t border-slate-200 dark:border-slate-700">';
                    html += '<p class="text-sm font-medium mb-2">Links:</p>';
                    html += '<ul class="space-y-2">';
                    for (const link of task.description.links) {
                        html += '<li><a href="' + _escape(link) + '" target="_blank" rel="noopener noreferrer" class="text-blue-600 dark:text-blue-400 hover:underline break-all">' + _escape(link) + '</a></li>';
                    }
                    html += '</ul></div>';
                }
                html += '</div>';
            }

            // Attachments
            if (task.attachments && task.attachments.length > 0) {
                html += '<div class="mb-6">';
                html += '<h2 class="text-xl font-semibold mb-3">Attachments</h2>';
                html += '<div class="file-list">';
                for (const file of task.attachments) {
                    html += '<div class="file-item attachment">';
                    html += '<div><p class="font-medium">' + _escape(file.name) + '</p>';
                    if (file.size) html += '<p class="text-sm text-slate-600 dark:text-slate-400">' + _escape(file.size) + '</p>';
                    html += '</div>';
                    if (file.url) {
                        html += '<a href="' + _escape(file.url) + '" target="_blank" rel="noopener noreferrer" class="text-blue-600 dark:text-blue-400 hover:underline text-sm">Download</a>';
                    }
                    html += '</div>';
                }
                html += '</div></div>';
            }

            // Submitted files
            if (task.submitted_files && task.submitted_files.length > 0) {
                html += '<div class="mb-6">';
                html += '<h2 class="text-xl font-semibold mb-3">Your Submissions</h2>';
                html += '<div class="file-list">';
                for (const file of task.submitted_files) {
                    html += '<div class="file-item submitted">';
                    html += '<div><p class="font-medium">' + _escape(file.name) + '</p>';
                    if (file.size) html += '<p class="text-sm text-slate-600 dark:text-slate-400">' + _escape(file.size) + '</p>';
                    html += '</div>';
                    if (file.url) {
                        html += '<button class="text-blue-600 dark:text-blue-400 hover:underline text-sm font-medium view-file" data-url="' + _escape(file.url) + '">View</button>';
                    }
                    html += '</div>';
                }
                html += '</div></div>';
            }

            // Open in ManageBac button
            if (task.url) {
                html += '<div class="mt-8 pt-6 border-t border-slate-200 dark:border-slate-700">';
                html += '<a href="' + _escape(task.url) + '" target="_blank" rel="noopener noreferrer" class="inline-block px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium">Open in ManageBac</a>';
                html += '</div>';
            }

            html += '</div>';
            document.getElementById('root').innerHTML = html;

            // Attach event listeners to view file buttons
            document.querySelectorAll('.view-file').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    const url = e.target.dataset.url;
                    window.parent.postMessage({
                        jsonrpc: "2.0",
                        id: Math.random(),
                        method: "tools/call",
                        params: { name: "get_file_content", arguments: { url: url } }
                    }, "*");
                });
            });
        }

        function _escape(text) {
            if (!text) return '';
            return String(text)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');
        }

        // Listen for tool results
        window.addEventListener('message', (event) => {
            if (event.source !== window.parent) return;
            const msg = event.data;
            if (msg.method === 'ui/notifications/tool-result') {
                render(msg.params?.structuredContent);
            }
        }, { passive: true });

        // Listen for theme changes
        window.addEventListener('openai:set_globals', (event) => {
            const theme = event.detail?.globals?.theme;
            if (theme === 'dark') {
                document.documentElement.classList.add('dark');
            } else if (theme === 'light') {
                document.documentElement.classList.remove('dark');
            }
        }, { passive: true });

        // Initial render from window.openai
        if (window.openai?.toolOutput) {
            render(window.openai.toolOutput);
        }

        // Set initial theme
        if (window.openai?.globals?.theme === 'dark') {
            document.documentElement.classList.add('dark');
        }
    </script>
</body>
</html>"""
    return HTMLResponse(html)


async def _ui_task(request):
    """Serve a baked task card widget by hash — called by ChatGPT to render the iframe."""
    h = request.path_params.get("hash", "")
    info = _TASK_WIDGETS.get(h)
    if info is None:
        return PlainTextResponse("Widget not found", status_code=404)
    return HTMLResponse(info["html"])


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

def build_app(*, stateless: bool = True, public_url: str | None = None):
    global _PUBLIC_URL
    if public_url:
        _PUBLIC_URL = public_url.rstrip("/")
    # Tell server.py the public URL so _make_task_widget generates correct HTTPS URLs
    set_server_public_url(_PUBLIC_URL)
    set_enroll_public_url(_PUBLIC_URL)

    session_manager = StreamableHTTPSessionManager(
        app=server,
        stateless=stateless,
        json_response=False,
    )

    # Separate, keyless MCP server for the in-chat enroll flow (/connect).
    enroll_session_manager = StreamableHTTPSessionManager(
        app=enroll_server,
        stateless=stateless,
        json_response=False,
    )

    async def handle_mcp(scope: Scope, receive: Receive, send: Send) -> None:
        token = _provided_token(scope)
        # Use get_user_by_token_any so paused users still reach call_tool and
        # receive the suspension prompt rather than a bare 401.
        user = users.get_user_by_token_any(token) if token else None
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

    def _normalize_mcp_scope(scope: Scope) -> Scope:
        scope = dict(scope)
        scope["path"] = "/"
        scope["raw_path"] = b"/"
        headers = [(k, v) for (k, v) in scope["headers"]
                   if k.lower() not in (b"accept", b"content-type")]
        headers.append((b"accept", b"application/json, text/event-stream"))
        headers.append((b"content-type", b"application/json"))
        scope["headers"] = headers
        return scope

    async def handle_connect(scope: Scope, receive: Receive, send: Send) -> None:
        # Keyless onboarding connector — no user context. Only the `enroll` tool
        # is exposed here; it never touches a student's ManageBac data.
        await enroll_session_manager.handle_request(_normalize_mcp_scope(scope), receive, send)

    async def health(request):
        return PlainTextResponse("ManageBac MCP server is running. Visit /enroll to connect an account.")

    @asynccontextmanager
    async def lifespan(app):
        async with session_manager.run(), enroll_session_manager.run():
            yield

    # Starlette handles the human-facing routes (/, /enroll) including form parsing.
    inner = Starlette(
        routes=[
            Route("/", health, methods=["GET"]),
            Route("/enroll", _handle_enroll_get, methods=["GET"]),
            Route("/enroll", _handle_enroll_post, methods=["POST"]),
            Route("/set-password", _handle_set_password_get, methods=["GET"]),
            Route("/set-password", _handle_set_password_post, methods=["POST"]),
            # Admin panel SPA
            Route("/admin", _admin_panel, methods=["GET"]),
            # Admin API (consumed by the admin panel)
            Route("/admin/login", _admin_login, methods=["POST"]),
            Route("/admin/logout", _admin_logout, methods=["POST"]),
            Route("/admin/health", _admin_health, methods=["GET"]),
            Route("/admin/change-password", _admin_change_password, methods=["POST"]),
            Route("/admin/codes", _admin_codes_get, methods=["GET"]),
            Route("/admin/codes", _admin_codes_post, methods=["POST"]),
            Route("/admin/codes/{code}", _admin_code_delete, methods=["DELETE"]),
            Route("/admin/users", _admin_users_get, methods=["GET"]),
            Route("/admin/users/{user_id}", _admin_user_get, methods=["GET"]),
            Route("/admin/users/{user_id}", _admin_user_delete, methods=["DELETE"]),
            Route("/admin/users/{user_id}/pause", _admin_user_pause, methods=["POST"]),
            Route("/admin/users/{user_id}/regenerate", _admin_user_regenerate, methods=["POST"]),
            Route("/admin/users/{user_id}/approve", _admin_user_approve, methods=["POST"]),
            Route("/admin/users/{user_id}/note", _admin_user_note, methods=["POST"]),
            Route("/admin/users/{user_id}/credentials", _admin_user_credentials, methods=["POST"]),
            Route("/admin/users/{user_id}/activity", _admin_user_activity, methods=["GET"]),
            Route("/admin/users/{user_id}/password", _admin_user_password_get, methods=["GET"]),
            Route("/admin/users/{user_id}/cache", _admin_user_cache_get, methods=["GET"]),
            Route("/admin/users/{user_id}/cache", _admin_user_cache_delete, methods=["DELETE"]),
            Route("/admin/users/{user_id}/cache/{key}", _admin_user_cache_delete, methods=["DELETE"]),
            Route("/admin/users/{user_id}/message", _admin_user_message, methods=["POST"]),
            Route("/admin/activity", _admin_activity, methods=["GET"]),
            Route("/admin/audit", _admin_audit, methods=["GET"]),
            Route("/admin/messages", _admin_messages_get, methods=["GET"]),
            Route("/admin/broadcast", _admin_broadcast, methods=["POST"]),
            # UI components (served to ChatGPT iframes)
            Route("/ui/test", _ui_test, methods=["GET"]),
            Route("/ui/task-detail", _ui_task_detail, methods=["GET"]),
            Route("/ui/task/{hash}", _ui_task, methods=["GET"]),
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
            if path == "/connect" or path == "/connect/":
                await handle_connect(scope, receive, send)
                return
        await inner(scope, receive, send)

    return app


def run(host: str = "127.0.0.1", port: int = 8000, public_url: str | None = None) -> None:
    import uvicorn
    uvicorn.run(build_app(public_url=public_url), host=host, port=port, log_level="info")
