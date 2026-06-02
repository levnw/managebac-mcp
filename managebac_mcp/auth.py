"""
Per-user authentication. Every client/session is bound to the current user
from the request context — there is no shared/global session in this build.
"""
import httpx
from bs4 import BeautifulSoup

from . import users
from .context import require_user


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

    # Session is bad — drop the stored cookies, log in fresh, retry once.
    users.save_cookies(user.id, {})
    await login(client)
    return await client.get(path)
