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
from .server import server, _TASK_WIDGETS, set_server_public_url

# Public URL for UI component links (set by build_app)
_PUBLIC_URL = "http://localhost:8000"

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

_STYLE = """
 *{{box-sizing:border-box}}
 body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
   background:#f9fafb;color:#101828;margin:0;padding:40px 16px;line-height:1.5;
   -webkit-font-smoothing:antialiased}}
 .card{{max-width:440px;margin:0 auto;background:#fff;border:1px solid #eaecf0;border-radius:12px;
   box-shadow:0 1px 3px rgba(16,24,40,.06),0 1px 2px rgba(16,24,40,.04);padding:32px}}
 .brand{{font-size:13px;font-weight:600;letter-spacing:.02em;color:#1570ef;margin-bottom:18px}}
 h1{{font-size:22px;font-weight:600;margin:0 0 6px}}
 .sub{{color:#475467;font-size:14px;margin:0 0 22px}}
 .steps{{background:#f9fafb;border:1px solid #eaecf0;border-radius:8px;padding:14px 16px;margin:0 0 22px}}
 .steps p{{margin:0 0 6px;font-size:13px;font-weight:600;color:#344054}}
 .steps ol{{margin:0;padding-left:18px;color:#475467;font-size:13px}}
 .steps li{{margin:3px 0}}
 label{{display:block;font-size:14px;font-weight:500;color:#344054;margin:14px 0 6px}}
 input{{width:100%;padding:10px 12px;border:1px solid #d0d5dd;border-radius:8px;font-size:16px;color:#101828;
   background:#fff;outline:none;transition:border-color .15s,box-shadow .15s}}
 input:focus{{border-color:#84caff;box-shadow:0 0 0 4px rgba(21,112,239,.15)}}
 input::placeholder{{color:#98a2b3}}
 button{{width:100%;margin-top:22px;padding:11px;background:#1570ef;color:#fff;border:0;border-radius:8px;
   font-size:15px;font-weight:600;cursor:pointer;transition:background .15s}}
 button:hover{{background:#175cd3}}
 .note{{margin-top:20px;font-size:12px;color:#667085;text-align:center}}
 .err{{background:#fef3f2;border:1px solid #fecdca;color:#b42318;padding:10px 12px;border-radius:8px;
   font-size:13px;margin-bottom:16px}}
 code{{display:block;background:#f9fafb;border:1px solid #eaecf0;padding:12px;border-radius:8px;
   word-break:break-all;margin:14px 0;font-size:13px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#101828}}
 .warn{{background:#fffaeb;border:1px solid #fedf89;color:#b54708;padding:12px;border-radius:8px;font-size:13px}}
"""

_ENROLL_FORM = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connect ManageBac</title>
<style>""" + _STYLE + """</style></head><body>
<div class="card">
 <div class="brand">MANAGEBAC ASSISTANT</div>
 <h1>Connect your account</h1>
 <p class="sub">Link your ManageBac to an AI assistant (ChatGPT) so you can just ask
 about your classes, tasks, deadlines, grades and files.</p>

 <div class="steps">
  <p>How it works</p>
  <ol>
   <li>Sign in below with your ManageBac details and your invite code.</li>
   <li>You'll get a private link.</li>
   <li>Paste that link into ChatGPT as a connector — then ask it anything about your schoolwork.</li>
  </ol>
 </div>

 {error}
 <form method="post" action="/enroll">
  <label>ManageBac URL</label>
  <input name="mb_url" value="https://es.managebac.com" required>
  <label>Email</label>
  <input name="email" type="email" placeholder="you@school.edu" required autocomplete="off">
  <label>Password</label>
  <input name="password" type="password" placeholder="Your ManageBac password" required autocomplete="off">
  <label>Invite code</label>
  <input name="invite" value="{invite_value}" placeholder="Ask the admin for a code" autocomplete="off">
  <button type="submit">Connect</button>
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
 <div class="brand">MANAGEBAC ASSISTANT</div>
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
 <div class="warn"><b>Keep this link private.</b> Anyone who has it can read your
 ManageBac account. If it leaks, ask the admin to regenerate it.</div>
</div>
</body></html>"""

_PENDING_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Request received</title>
<style>""" + _STYLE + """</style></head><body>
<div class="card">
 <div class="brand">MANAGEBAC ASSISTANT</div>
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
 <div class="warn"><b>Keep this link private.</b> It won't work until you're approved.
 Anyone who has it can read your ManageBac account.</div>
</div>
</body></html>"""


def _enroll_form(error: str = "", code: str = "") -> str:
    err_html = f'<div class="err">{_html.escape(error)}</div>' if error else ""
    return _ENROLL_FORM.format(error=err_html, invite_value=_html.escape(code, quote=True))


async def _handle_enroll_get(request):
    # A shared invite link carries the code: /enroll?code=XXXX — pre-fill it.
    return HTMLResponse(_enroll_form(code=request.query_params.get("code", "")))


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
            return HTMLResponse(_enroll_form("An invite code is required to sign up.", code=invite), status_code=403)
        if not admin.code_unused(invite):
            return HTMLResponse(_enroll_form("That invite code is invalid or already used.", code=invite), status_code=403)

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
            _enroll_form("Could not log in to ManageBac — check the URL, email, and password.", code=invite),
            status_code=401,
        )
    finally:
        reset_user(ctx)

    # Login succeeded — now consume the one-time code (atomic; guards races).
    if not existing:
        if not admin.redeem_code(invite, user.id, email):
            users.delete_user(user.id)
            return HTMLResponse(_enroll_form("That invite code was just used. Ask for a new one.", code=invite), status_code=403)

    # Warm their cache in the background so the first question is instant.
    # Fire-and-forget — the response below returns immediately.
    import asyncio as _asyncio
    from . import scraper
    _asyncio.create_task(scraper.prewarm(user))

    base = str(request.base_url).rstrip("/")
    connector_url = f"{base}/mcp?key={user.token}"
    # No approval gate — the link works immediately for everyone (new and
    # returning). A valid invite code was already required above to sign up.
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

    if email:
        users.update_email(user_id, email)
    if password:
        users.update_password(user_id, password)
    # Old cookies are tied to the old login — clear so the next fetch re-logs-in.
    users.save_cookies(user_id, {})

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
            Route("/admin/users/{user_id}/approve", _admin_user_approve, methods=["POST"]),
            Route("/admin/users/{user_id}/note", _admin_user_note, methods=["POST"]),
            Route("/admin/users/{user_id}/credentials", _admin_user_credentials, methods=["POST"]),
            Route("/admin/users/{user_id}/activity", _admin_user_activity, methods=["GET"]),
            Route("/admin/activity", _admin_activity, methods=["GET"]),
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
        await inner(scope, receive, send)

    return app


def run(host: str = "127.0.0.1", port: int = 8000, public_url: str | None = None) -> None:
    import uvicorn
    uvicorn.run(build_app(public_url=public_url), host=host, port=port, log_level="info")
