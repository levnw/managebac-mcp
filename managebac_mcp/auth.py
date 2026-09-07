"""
Per-user authentication. Every client/session is bound to the current user
from the request context — there is no shared/global session in this build.
"""
import asyncio
import time
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from . import users
from .context import require_user, ManageBacError

# One login at a time per user. Without this, a burst of concurrent fetches
# (prewarm, get_grades, tag_search → 17 classes at once) all try to log in
# simultaneously; ManageBac rotates the session on each login, so the parallel
# logins invalidate each other and some requests get the login page back
# (which parses to an empty list and then gets cached). Serializing fixes it.
_login_locks: dict[str, asyncio.Lock] = {}

# A rejected login must not be retried on every tool call. ManageBac locks an
# account after a small number of consecutive failures, so remember the last
# rejection briefly and fail closed until the operator/student fixes it.
_LOGIN_FAILURE_COOLDOWN = 5 * 60
_login_failures: dict[str, tuple[float, str]] = {}


def _login_lock(user_id: str) -> asyncio.Lock:
    lock = _login_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _login_locks[user_id] = lock
    return lock


# Cap how many requests hit ManageBac at once. Tools like get_grades / prewarm /
# tag_search fan out to ~17 classes; firing all of them simultaneously makes
# ManageBac reject/redirect most of the burst (those pages then parse to empty
# and get cached). A small limit keeps every request succeeding.
_REQUEST_SEM = asyncio.Semaphore(4)


async def _throttled_get(client: httpx.AsyncClient, path: str) -> httpx.Response:
    async with _REQUEST_SEM:
        return await client.get(path)


def _remember_login_failure(user_id: str, reason: str) -> None:
    _login_failures[user_id] = (time.monotonic(), reason)


def _recent_login_failure(user_id: str) -> str | None:
    failure = _login_failures.get(user_id)
    if failure is None:
        return None
    failed_at, reason = failure
    if time.monotonic() - failed_at < _LOGIN_FAILURE_COOLDOWN:
        return reason
    _login_failures.pop(user_id, None)
    return None


def _login_rejection_reason(response: httpx.Response) -> str | None:
    """Recognize ManageBac's HTTP-200 login rejection page safely."""
    soup = BeautifulSoup(response.text or "", "lxml")
    text = " ".join(soup.get_text(" ", strip=True).lower().split())
    path = urlparse(str(response.url)).path.rstrip("/") or "/"
    has_login_form = bool(
        soup.select_one('form[action*="/sessions"] input[name="password"]')
    )

    if "temporarily locked" in text or "consecutive failed login" in text:
        return (
            "ManageBac says this account is temporarily locked after repeated "
            "failed sign-ins. Stop retrying, unlock or reset the ManageBac "
            "password, then update the enrolled credentials."
        )
    if response.status_code in (401, 403) or path in ("/login", "/sessions") or has_login_form:
        return (
            "ManageBac rejected the stored credentials. Stop retrying and "
            "update the enrolled password before trying again."
        )
    return None


async def login(client: httpx.AsyncClient) -> None:
    """Log the CURRENT user into ManageBac and persist their cookies."""
    user = require_user()

    # Start from a clean cookie jar — stale or duplicate _managebac_session
    # cookies are exactly what cause the "too many redirects" login loop.
    client.cookies.clear()

    # Get CSRF token
    r = await client.get(f"{user.mb_url}/login")
    if r.status_code >= 400:
        reason = f"ManageBac login page returned HTTP {r.status_code}; sign-in was not attempted."
        _remember_login_failure(user.id, reason)
        raise ManageBacError(reason)
    soup = BeautifulSoup(r.text, "lxml")
    csrf = soup.find("meta", {"name": "csrf-token"})
    token = csrf["content"] if csrf else ""
    if not token:
        reason = "ManageBac login page did not contain the expected CSRF token; sign-in was not attempted."
        _remember_login_failure(user.id, reason)
        raise ManageBacError(reason)

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

    rejection = _login_rejection_reason(r)
    if rejection:
        _remember_login_failure(user.id, rejection)
        raise ManageBacError(rejection)

    _login_failures.pop(user.id, None)
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
        headers={
            # Use a real browser User-Agent: ManageBac serves a REDUCED page to
            # non-browser UAs (e.g. the class Files page comes back without its
            # folders — only the root files — so get_files used to miss everything
            # inside folders). A normal Chrome UA gets the full server-rendered page.
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Origin": user.mb_url,
            "Referer": user.mb_url + "/student",
        },
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
        r = await _throttled_get(client, path)
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
            r = await _throttled_get(client, path)
            if "/login" not in str(r.url) and r.status_code != 401:
                return r
        except httpx.TooManyRedirects:
            pass
        recent_failure = _recent_login_failure(user.id)
        if recent_failure:
            raise ManageBacError(recent_failure)
        # Still bad — do a real login (clears cookies, signs in, saves).
        await login(client)
        # Validate the new session before releasing the per-user login lock. A
        # waiting request can then reuse the persisted cookies instead of racing
        # another login against this one.
        r = await _throttled_get(client, path)
        if "/login" in str(r.url) or r.status_code == 401:
            reason = (
                "ManageBac accepted the sign-in request but did not create a usable "
                "session. Automatic login retries are paused for 5 minutes; verify "
                "the account in a browser, then update the enrolled credentials if needed."
            )
            _remember_login_failure(user.id, reason)
            raise ManageBacError(reason)
        return r
