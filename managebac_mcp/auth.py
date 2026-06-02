"""
Per-user authentication. Every client/session is bound to the current user
from the request context — there is no shared/global session in this build.
"""
import asyncio
import httpx
from bs4 import BeautifulSoup

from . import users
from .context import require_user

# One login at a time per user. Without this, a burst of concurrent fetches
# (prewarm, get_grades, tag_search → 17 classes at once) all try to log in
# simultaneously; ManageBac rotates the session on each login, so the parallel
# logins invalidate each other and some requests get the login page back
# (which parses to an empty list and then gets cached). Serializing fixes it.
_login_locks: dict[str, asyncio.Lock] = {}


def _login_lock(user_id: str) -> asyncio.Lock:
    lock = _login_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _login_locks[user_id] = lock
    return lock


async def login(client: httpx.AsyncClient) -> None:
    """Log the CURRENT user into ManageBac and persist their cookies."""
    user = require_user()

    # Start from a clean cookie jar — stale or duplicate _managebac_session
    # cookies are exactly what cause the "too many redirects" login loop.
    client.cookies.clear()

    # Get CSRF token
    r = await client.get(f"{user.mb_url}/login")
    soup = BeautifulSoup(r.text, "lxml")
    csrf = soup.find("meta", {"name": "csrf-token"})
    token = csrf["content"] if csrf else ""

    # POST login — form posts to /sessions with plain field names
    r = await client.post(
        f"{user.mb_url}/sessions",
        data={
            "login": user.email,
            "password": user.password,
            "authenticity_token": token,
            "commit": "Sign in",
        },
        follow_redirects=True,
    )

    if "/login" in str(r.url):
        raise RuntimeError(f"ManageBac login failed for {user.label} — check their credentials")

    users.save_cookies(user.id, dict(client.cookies))


async def get_client() -> httpx.AsyncClient:
    """Build an HTTP client preloaded with the CURRENT user's cookies."""
    user = require_user()
    cookies = users.load_cookies(user.id)
    return httpx.AsyncClient(
        base_url=user.mb_url,
        cookies=cookies,
        follow_redirects=True,
        timeout=30,
        headers={"User-Agent": "Mozilla/5.0 (compatible; ManageBac-MCP/1.0)"},
    )


async def authed_get(client: httpx.AsyncClient, path: str) -> httpx.Response:
    """
    GET a path, transparently re-logging in the current user when the session
    is missing, expired, or stale.

    Stale cookies can make ManageBac bounce between pages until httpx raises
    TooManyRedirects — so we treat that, a redirect to /login, and a 401 all as
    "session is bad": clear it, log in fresh, and retry once.
    """
    user = require_user()
    try:
        r = await client.get(path)
        if "/login" not in str(r.url) and r.status_code != 401:
            return r
    except httpx.TooManyRedirects:
        pass

    # Session looks bad. Serialize re-login per user so concurrent fetches don't
    # stampede the login (which rotates the session and breaks the others).
    async with _login_lock(user.id):
        # Someone else may have just re-logged in while we waited for the lock —
        # try their fresh cookies before logging in again.
        client.cookies = httpx.Cookies(users.load_cookies(user.id))
        try:
            r = await client.get(path)
            if "/login" not in str(r.url) and r.status_code != 401:
                return r
        except httpx.TooManyRedirects:
            pass
        # Still bad — do a real login (clears cookies, signs in, saves).
        await login(client)
    return await client.get(path)
