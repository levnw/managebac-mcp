import json
import httpx
from bs4 import BeautifulSoup
from .config import BASE_URL, EMAIL, PASSWORD, SESSION_FILE


def _load_cookies() -> dict:
    if SESSION_FILE.exists():
        return json.loads(SESSION_FILE.read_text())
    return {}


def _save_cookies(cookies: dict) -> None:
    SESSION_FILE.write_text(json.dumps(cookies))


async def login(client: httpx.AsyncClient) -> None:
    # Get CSRF token
    r = await client.get(f"{BASE_URL}/login")
    soup = BeautifulSoup(r.text, "lxml")
    csrf = soup.find("meta", {"name": "csrf-token"})
    token = csrf["content"] if csrf else ""

    # POST login — form posts to /sessions with plain field names
    r = await client.post(
        f"{BASE_URL}/sessions",
        data={
            "login": EMAIL,
            "password": PASSWORD,
            "authenticity_token": token,
            "commit": "Sign in",
        },
        follow_redirects=True,
    )

    if "/login" in str(r.url):
        raise RuntimeError("ManageBac login failed — check credentials in .env")

    _save_cookies(dict(client.cookies))


async def get_client() -> httpx.AsyncClient:
    cookies = _load_cookies()
    client = httpx.AsyncClient(
        base_url=BASE_URL,
        cookies=cookies,
        follow_redirects=True,
        timeout=30,
        headers={"User-Agent": "Mozilla/5.0 (compatible; ManageBac-MCP/1.0)"},
    )
    return client


async def authed_get(client: httpx.AsyncClient, path: str) -> httpx.Response:
    r = await client.get(path)
    # Detect session expiry — Rails redirects to /login
    if "/login" in str(r.url) or r.status_code == 401:
        await login(client)
        _save_cookies(dict(client.cookies))
        r = await client.get(path)
    return r
