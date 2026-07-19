"""
Multi-user HTTP transport with OAuth 2.1 sign-in.

/mcp requires `Authorization: Bearer <access token>` issued by this server's
own OAuth flow: ChatGPT discovers auth via /.well-known/oauth-protected-resource,
opens /authorize in a popup (the student signs in with their real ManageBac
credentials — full enrollment for new users, invite code required), exchanges
the code at /token, and every request then pins that user to the request
context so all fetches/cache reads are user-scoped. Missing/invalid token =>
401 + WWW-Authenticate challenge (this is what makes ChatGPT show "Sign in").

Also serves the legacy self-service /enroll page and the admin panel/API.
"""
import html as _html
from contextlib import asynccontextmanager
from urllib.parse import urlencode

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import HTMLResponse, PlainTextResponse, JSONResponse, RedirectResponse, Response
from starlette.types import Scope, Receive, Send

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from . import users, config, backoffice, branding, oauth
from .context import set_current_user, reset_user
from .server import server, set_server_public_url

# Public URL for UI component links (set by build_app)
_PUBLIC_URL = "http://localhost:8000"

import time as _time
_SERVER_START_TIME = _time.time()

# ---------------------------------------------------------------------------
# Token extraction
# ---------------------------------------------------------------------------

def _bearer_token(scope: Scope) -> str | None:
    """OAuth access token from the Authorization header. (The old ?key= query
    credential is gone — OAuth is the only way in.)"""
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            v = value.decode("latin-1")
            if v.lower().startswith("bearer "):
                return v[7:].strip()
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
 .tip{{position:relative;cursor:default;color:#98a2b3;font-size:13px;font-weight:400;line-height:1;user-select:none}}
 .tip:hover{{color:#1570ef}}
 .tip-box{{display:none;position:absolute;right:0;top:calc(100% + 6px);width:220px;background:#101828;
   color:#f2f4f7;font-size:12px;font-weight:400;padding:8px 10px;border-radius:6px;line-height:1.5;
   z-index:20;white-space:normal;pointer-events:none;box-shadow:0 4px 12px rgba(0,0,0,.25)}}
 .tip-box b{{color:#fff}}
 .tip-box code{{background:rgba(255,255,255,.15);border-radius:3px;padding:1px 4px;
   font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px}}
 .tip:hover .tip-box{{display:block}}
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
   <div class="labelrow"><label>ManageBac URL<span class="req">*</span></label><span class="tip">ⓘ<span class="tip-box"><b>Where to find this:</b> Open your school's ManageBac login page in a browser and copy the URL from the address bar. You only need the base address — any path after the domain is stripped automatically.<br>Example: <code>https://es.managebac.com</code></span></span></div>
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

_SUCCESS_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connected</title>
<style>""" + _STYLE + """</style></head><body>
<div class="card">
 {head}
 <div class="body">
  <h1>You're connected, {label}</h1>
  <p class="sub">Add the connector below to ChatGPT — it will ask you to sign in
  with the same ManageBac login you just used.</p>
  <div class="steps">
   <p>Add it to ChatGPT</p>
   <ol>
    <li>ChatGPT → Settings → Connectors → Add custom connector.</li>
    <li>Paste the link below as the Server URL, then create.</li>
    <li>Click <b>Sign in</b> when ChatGPT asks, and log in with your ManageBac account.</li>
   </ol>
  </div>
  <code>{connector_url}</code>
 </div>
</div>
</body></html>"""

def _enroll_form(error: str = "", code: str = "", brand: dict | None = None) -> str:
    err_html = f'<div class="err">{_html.escape(error)}</div>' if error else ""
    return _ENROLL_FORM.format(head=_head(brand), error=err_html, invite_value=_html.escape(code, quote=True))


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
    the web /enroll form and the OAuth /authorize sign-in.
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
        if not backoffice.redeem_code(invite, user.id, email):
            users.delete_user(user.id)
            return None, "That invite code was just used. Ask for a new one."

    # Warm their cache in the background so the first question is instant.
    # Fire-and-forget.
    import asyncio as _asyncio
    from . import scraper
    _asyncio.create_task(scraper.prewarm(user))
    return user, None


def _normalize_mb_url(raw: str) -> str:
    from urllib.parse import urlparse
    raw = (raw or "").strip()
    if not raw:
        return ""
    if not raw.startswith("http"):
        raw = "https://" + raw
    parsed = urlparse(raw)
    return f"{parsed.scheme}://{parsed.netloc}"


async def _handle_enroll_post(request):
    form = await request.form()
    mb_url = _normalize_mb_url(form.get("mb_url") or "")
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
        if not backoffice.code_unused(invite):
            return HTMLResponse(_enroll_form("That invite code is invalid or already used.", code=invite, brand=brand), status_code=403)

    user, error = await _create_and_verify(mb_url, email, password, invite, existing)
    if error:
        status = 401 if "log in" in error else 403
        return HTMLResponse(_enroll_form(error, code=invite, brand=brand), status_code=status)

    connector_url = f"{_PUBLIC_URL}/mcp"
    return HTMLResponse(_SUCCESS_PAGE.format(head=_head(brand), label=_html.escape(user.label), connector_url=connector_url))


# ---------------------------------------------------------------------------
# OAuth 2.1 authorization server (the ChatGPT "Sign in" popup)
# ---------------------------------------------------------------------------

# The popup login page: the enroll form plus the OAuth request parameters
# carried through as hidden fields. Signing in IS the consent step — the page
# says plainly what linking does.
_AUTHORIZE_FORM = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in to ManageBac</title>
<style>""" + _STYLE + """</style></head><body>
<div class="card">
 {head}
 <form method="post" action="/authorize">
  <input type="hidden" name="client_id" value="{client_id}">
  <input type="hidden" name="redirect_uri" value="{redirect_uri}">
  <input type="hidden" name="state" value="{state}">
  <input type="hidden" name="code_challenge" value="{code_challenge}">
  <input type="hidden" name="scope" value="{scope}">
  <input type="hidden" name="resource" value="{resource}">
  <div class="body">
   {error}
   <p class="sub">Sign in with your ManageBac account to let ChatGPT read your
   classes, tasks, deadlines, grades and files.</p>
   <div class="labelrow"><label>ManageBac URL<span class="req">*</span></label><span class="tip">ⓘ<span class="tip-box"><b>Where to find this:</b> Open your school's ManageBac login page in a browser and copy the URL from the address bar. You only need the base address.<br>Example: <code>https://es.managebac.com</code></span></span></div>
   <div class="field"><input name="mb_url" value="{mb_url}" required>""" + _IC_GLOBE + """</div>
   <div class="labelrow"><label>Login<span class="req">*</span></label></div>
   <div class="field"><input name="email" type="email" value="{email}" placeholder="you@school.edu" required autocomplete="off">""" + _IC_MAIL + """</div>
   <div class="labelrow"><label>Password<span class="req">*</span></label></div>
   <div class="field"><input name="password" type="password" placeholder="Your ManageBac password" required autocomplete="off">""" + _IC_LOCK + """</div>
   <div class="labelrow"><label>Invite code</label><span class="tip">ⓘ<span class="tip-box"><b>New users only.</b> Ask the admin for a one-time code. Already connected before? Leave this empty.</span></span></div>
   <div class="field"><input name="invite" value="{invite_value}" placeholder="New users only" autocomplete="off">""" + _IC_KEY + """</div>
  </div>
  <div class="actions"><button type="submit">Sign in &amp; connect</button></div>
 </form>
 <p class="note">Read-only. Your login is stored encrypted and used only to read
 your own ManageBac data. You can disconnect any time from ChatGPT's settings.</p>
</div>
</body></html>"""

_OAUTH_ERROR_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign-in error</title>
<style>""" + _STYLE + """</style></head><body>
<div class="card">
 {head}
 <div class="body">
  <h1>Can't start sign-in</h1>
  <div class="err">{error}</div>
  <p class="sub">Close this window and try connecting again from ChatGPT.</p>
 </div>
</div>
</body></html>"""


def _authorize_form(params: dict, error: str = "", brand: dict | None = None,
                    mb_url: str = "", email: str = "", invite: str = "") -> str:
    err_html = f'<div class="err">{_html.escape(error)}</div>' if error else ""
    esc = lambda v: _html.escape(v or "", quote=True)
    return _AUTHORIZE_FORM.format(
        head=_head(brand), error=err_html,
        client_id=esc(params.get("client_id")), redirect_uri=esc(params.get("redirect_uri")),
        state=esc(params.get("state")), code_challenge=esc(params.get("code_challenge")),
        scope=esc(params.get("scope") or oauth.SCOPE), resource=esc(params.get("resource")),
        mb_url=esc(mb_url or config.BASE_URL), email=esc(email), invite_value=esc(invite),
    )


async def _oauth_error_page(error: str, status: int = 400):
    brand = await branding.get_branding(config.BASE_URL)
    return HTMLResponse(_OAUTH_ERROR_PAGE.format(head=_head(brand), error=_html.escape(error)),
                        status_code=status)


def _cors(resp: Response) -> Response:
    """Permissive CORS for the metadata/token/register endpoints only — needed
    by browser-based clients like MCP Inspector; ChatGPT calls these
    server-side. Never applied to /mcp or /authorize."""
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, mcp-protocol-version"
    return resp


async def _oauth_preflight(request):
    return _cors(Response(status_code=204))


async def _oauth_protected_resource(request):
    return _cors(JSONResponse({
        "resource": f"{_PUBLIC_URL}/mcp",
        "authorization_servers": [_PUBLIC_URL],
        "scopes_supported": [oauth.SCOPE],
        "bearer_methods_supported": ["header"],
    }))


async def _oauth_as_metadata(request):
    return _cors(JSONResponse({
        "issuer": _PUBLIC_URL,
        "authorization_endpoint": f"{_PUBLIC_URL}/authorize",
        "token_endpoint": f"{_PUBLIC_URL}/token",
        "registration_endpoint": f"{_PUBLIC_URL}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": [oauth.SCOPE],
        "client_id_metadata_document_supported": True,
    }))


def _authorize_params(source) -> dict:
    return {k: (source.get(k) or "").strip() for k in
            ("response_type", "client_id", "redirect_uri", "state",
             "code_challenge", "code_challenge_method", "scope", "resource")}


async def _validate_authorize_client(params: dict):
    """Resolve + validate client_id/redirect_uri. Returns (client, error_page).
    An unknown client or unregistered redirect_uri must NEVER be redirected to
    (RFC 6749 §4.1.2.1) — we render a 400 page instead."""
    client = await oauth.resolve_client(params["client_id"])
    if client is None:
        return None, await _oauth_error_page("Unknown application (client_id). ")
    if not oauth.redirect_uri_allowed(client, params["redirect_uri"]):
        return None, await _oauth_error_page("The application's redirect address isn't registered.")
    return client, None


def _authorize_redirect_error(params: dict, error: str, description: str):
    q = {"error": error, "error_description": description}
    if params.get("state"):
        q["state"] = params["state"]
    return RedirectResponse(f"{params['redirect_uri']}?{urlencode(q)}", status_code=302,
                            headers={"Cache-Control": "no-store"})


async def _handle_authorize_get(request):
    params = _authorize_params(request.query_params)
    client, err = await _validate_authorize_client(params)
    if err:
        return err
    # redirect_uri is trusted from here on — protocol errors go back to it.
    if params["response_type"] != "code":
        return _authorize_redirect_error(params, "unsupported_response_type",
                                         "Only response_type=code is supported")
    if not params["code_challenge"] or params["code_challenge_method"] != "S256":
        return _authorize_redirect_error(params, "invalid_request",
                                         "PKCE with code_challenge_method=S256 is required")
    brand = await branding.get_branding(config.BASE_URL)
    return HTMLResponse(_authorize_form(params, brand=brand),
                        headers={"Cache-Control": "no-store"})


async def _handle_authorize_post(request):
    form = await request.form()
    params = _authorize_params(form)
    # Re-validate against the store — never trust the hidden fields alone.
    client, err = await _validate_authorize_client(params)
    if err:
        return err
    if not params["code_challenge"]:
        return _authorize_redirect_error(params, "invalid_request", "Missing PKCE challenge")

    ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "")
    if not oauth.check_rate(ip):
        return await _oauth_error_page("Too many attempts. Wait a few minutes and try again.", 429)

    mb_url = _normalize_mb_url(form.get("mb_url") or "")
    email = (form.get("email") or "").strip()
    password = (form.get("password") or "").strip()
    invite = (form.get("invite") or "").strip()
    brand = await branding.get_branding(mb_url or config.BASE_URL)

    def retry(error, status=400):
        return HTMLResponse(_authorize_form(params, error=error, brand=brand,
                                            mb_url=mb_url, email=email, invite=invite),
                            status_code=status, headers={"Cache-Control": "no-store"})

    if not (mb_url and email and password):
        return retry("All fields are required.")

    existing = users.get_user_by_email(mb_url, email)
    if not existing:
        if not invite:
            return retry("An invite code is required for first-time sign-in.", 403)
        if not backoffice.code_unused(invite):
            return retry("That invite code is invalid or already used.", 403)

    user, error = await _create_and_verify(mb_url, email, password, invite, existing)
    if error:
        return retry(error, 401 if "log in" in error else 403)

    code = oauth.create_auth_code(
        user_id=user.id, client_id=params["client_id"],
        redirect_uri=params["redirect_uri"], code_challenge=params["code_challenge"],
        scope=params.get("scope") or oauth.SCOPE, resource=params.get("resource") or None,
    )
    q = {"code": code}
    if params.get("state"):
        q["state"] = params["state"]
    return RedirectResponse(f"{params['redirect_uri']}?{urlencode(q)}", status_code=302,
                            headers={"Cache-Control": "no-store"})


def _token_error(error: str, description: str, status: int = 400):
    return _cors(JSONResponse({"error": error, "error_description": description},
                              status_code=status,
                              headers={"Cache-Control": "no-store", "Pragma": "no-cache"}))


async def _handle_token(request):
    try:
        form = await request.form()
    except Exception:
        return _token_error("invalid_request", "Body must be form-encoded")
    grant = (form.get("grant_type") or "").strip()
    client_id = (form.get("client_id") or "").strip()

    if grant == "authorization_code":
        code = (form.get("code") or "").strip()
        verifier = (form.get("code_verifier") or "").strip()
        redirect_uri = (form.get("redirect_uri") or "").strip()
        if not (code and verifier and redirect_uri and client_id):
            return _token_error("invalid_request",
                                "code, code_verifier, redirect_uri and client_id are required")
        data = oauth.consume_auth_code(code)
        if data is None:
            return _token_error("invalid_grant", "Authorization code is invalid, expired, or already used")
        if data["client_id"] != client_id or data["redirect_uri"] != redirect_uri:
            return _token_error("invalid_grant", "client_id/redirect_uri mismatch")
        if not oauth.verify_pkce(verifier, data["code_challenge"]):
            return _token_error("invalid_grant", "PKCE verification failed")
        resource = (form.get("resource") or "").strip()
        if resource and resource.rstrip("/") not in (_PUBLIC_URL, f"{_PUBLIC_URL}/mcp"):
            return _token_error("invalid_target", "Unknown resource")
        tokens = oauth.issue_tokens(user_id=data["user_id"], client_id=client_id,
                                    scope=data["scope"])
        return _cors(JSONResponse(tokens, headers={"Cache-Control": "no-store", "Pragma": "no-cache"}))

    if grant == "refresh_token":
        refresh = (form.get("refresh_token") or "").strip()
        if not (refresh and client_id):
            return _token_error("invalid_request", "refresh_token and client_id are required")
        tokens = oauth.rotate_refresh(refresh, client_id)
        if tokens is None:
            return _token_error("invalid_grant", "Refresh token is invalid, expired, or revoked")
        return _cors(JSONResponse(tokens, headers={"Cache-Control": "no-store", "Pragma": "no-cache"}))

    return _token_error("unsupported_grant_type", "Use authorization_code or refresh_token")


async def _handle_register(request):
    try:
        body = await request.json()
    except Exception:
        return _token_error("invalid_client_metadata", "Body must be JSON")
    result = oauth.register_dcr_client(body)
    if result is None:
        return _token_error("invalid_client_metadata",
                            "redirect_uris must be a non-empty list of https (or localhost) URLs")
    return _cors(JSONResponse(result, status_code=201,
                              headers={"Cache-Control": "no-store"}))


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

def build_app(*, stateless: bool = True, public_url: str | None = None):
    global _PUBLIC_URL
    if public_url:
        _PUBLIC_URL = public_url.rstrip("/")
    if _PUBLIC_URL.startswith("http://localhost") or _PUBLIC_URL.startswith("http://127."):
        import sys
        print("WARNING: serving with a localhost public URL — OAuth discovery "
              "metadata will advertise it. Pass --public-url for production.",
              file=sys.stderr)
    # Tell server.py the public URL so widget resource URLs use the right origin.
    set_server_public_url(_PUBLIC_URL)

    session_manager = StreamableHTTPSessionManager(
        app=server,
        stateless=stateless,
        json_response=False,
    )

    async def handle_mcp(scope: Scope, receive: Receive, send: Send) -> None:
        token = _bearer_token(scope)
        # OAuth access token → user. user_for_access_token resolves paused users
        # too (users.get_user_by_id), so they still reach call_tool and get the
        # suspension prompt rather than a bare 401.
        user = oauth.user_for_access_token(token) if token else None
        if user is None:
            # RFC 6750: bare challenge when no token was presented; add error
            # attrs when an invalid/expired one was. The resource_metadata URL
            # is what makes ChatGPT open the OAuth sign-in popup.
            www = f'Bearer resource_metadata="{_PUBLIC_URL}/.well-known/oauth-protected-resource"'
            if token:
                www += ', error="invalid_token", error_description="The access token is invalid or expired"'
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"www-authenticate", www.encode("latin-1"))]})
            await send({"type": "http.response.body",
                        "body": b'{"error":"unauthorized - sign in via OAuth"}'})
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
            # OAuth 2.1 (ChatGPT sign-in popup): discovery + authorize + token + DCR
            Route("/.well-known/oauth-protected-resource", _oauth_protected_resource, methods=["GET"]),
            Route("/.well-known/oauth-protected-resource/mcp", _oauth_protected_resource, methods=["GET"]),
            Route("/.well-known/oauth-authorization-server", _oauth_as_metadata, methods=["GET"]),
            Route("/.well-known/oauth-authorization-server/mcp", _oauth_as_metadata, methods=["GET"]),
            Route("/.well-known/openid-configuration", _oauth_as_metadata, methods=["GET"]),
            Route("/authorize", _handle_authorize_get, methods=["GET"]),
            Route("/authorize", _handle_authorize_post, methods=["POST"]),
            Route("/token", _handle_token, methods=["POST"]),
            Route("/token", _oauth_preflight, methods=["OPTIONS"]),
            Route("/register", _handle_register, methods=["POST"]),
            Route("/register", _oauth_preflight, methods=["OPTIONS"]),
        ],
        lifespan=lifespan,
    )

    # Top-level ASGI dispatch: anything under /mcp goes straight to the MCP
    # handler (raw ASGI, no Mount/redirect — a 307 on POST breaks ChatGPT).
    # lifespan + everything else falls through to Starlette.
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path == "/mcp" or path == "/mcp/":
                await handle_mcp(scope, receive, send)
                return
            # Discovery probes issued relative to the MCP URL
            # (e.g. /mcp/.well-known/oauth-authorization-server) map to the
            # root well-known routes.
            if path.startswith("/mcp/.well-known/"):
                scope = dict(scope)
                scope["path"] = path[len("/mcp"):]
                scope["raw_path"] = scope["path"].encode("latin-1")
        await inner(scope, receive, send)

    return app


def run(host: str = "127.0.0.1", port: int = 8000, public_url: str | None = None) -> None:
    import uvicorn
    uvicorn.run(build_app(public_url=public_url), host=host, port=port, log_level="info")
