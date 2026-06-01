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
    """GET a path, transparently re-logging in the current user on session expiry."""
    user = require_user()
    r = await client.get(path)
    if "/login" in str(r.url) or r.status_code == 401:
        await login(client)
        users.save_cookies(user.id, dict(client.cookies))
        r = await client.get(path)
    return r
