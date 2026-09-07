import httpx
import pytest

from managebac_mcp import auth
from managebac_mcp.context import ManageBacError, User, reset_user, set_current_user


LOGIN_HTML = """
<html><head><meta name="csrf-token" content="csrf-value"></head>
<body><form action="/sessions"><input name="password"></form></body></html>
"""


def response(status: int, url: str, html: str = "") -> httpx.Response:
    return httpx.Response(status, text=html, request=httpx.Request("GET", url))


class LoginClient:
    def __init__(self, post_response: httpx.Response):
        self.post_response = post_response
        self.cookies = httpx.Cookies({"_managebac_session": "opaque"})

    async def get(self, _url):
        return response(200, "https://school.managebac.com/login", LOGIN_HTML)

    async def post(self, _url, **_kwargs):
        self.cookies.set("_managebac_session", "opaque")
        return self.post_response


@pytest.fixture
def current_user():
    user = User("user-1", "legacy", "student", "https://school.managebac.com", "student@example.com", "secret")
    token = set_current_user(user)
    auth._login_failures.clear()
    try:
        yield user
    finally:
        auth._login_failures.clear()
        reset_user(token)


@pytest.mark.asyncio
async def test_login_rejects_http_200_sessions_page(monkeypatch, current_user):
    saved = []
    monkeypatch.setattr(auth.users, "save_cookies", lambda *_args: saved.append(True))
    client = LoginClient(response(200, "https://school.managebac.com/sessions", LOGIN_HTML))

    with pytest.raises(ManageBacError, match="rejected the stored credentials"):
        await auth.login(client)

    assert saved == []
    assert auth._recent_login_failure(current_user.id)


@pytest.mark.asyncio
async def test_login_surfaces_account_lock(monkeypatch, current_user):
    monkeypatch.setattr(auth.users, "save_cookies", lambda *_args: pytest.fail("must not save rejected cookies"))
    locked_html = LOGIN_HTML.replace(
        "</body>",
        '<div class="alert">Account temporarily locked due to 5 consecutive failed login attempts.</div></body>',
    )
    client = LoginClient(response(200, "https://school.managebac.com/sessions", locked_html))

    with pytest.raises(ManageBacError, match="temporarily locked"):
        await auth.login(client)


@pytest.mark.asyncio
async def test_login_saves_only_after_success(monkeypatch, current_user):
    saved = []
    monkeypatch.setattr(auth.users, "save_cookies", lambda user_id, cookies: saved.append((user_id, cookies)))
    client = LoginClient(response(200, "https://school.managebac.com/student", "<title>ManageBac</title>"))

    await auth.login(client)

    assert saved and saved[0][0] == current_user.id
    assert "_managebac_session" in saved[0][1]


@pytest.mark.asyncio
async def test_authed_get_honors_recent_failure_without_new_login(monkeypatch, current_user):
    class StaleClient:
        def __init__(self):
            self.cookies = httpx.Cookies()
            self.calls = 0

        async def get(self, _path):
            self.calls += 1
            return response(401, "https://school.managebac.com/student/classes/my")

    client = StaleClient()
    monkeypatch.setattr(auth.users, "load_cookies", lambda _user_id: {})
    auth._remember_login_failure(current_user.id, "known login rejection")

    with pytest.raises(ManageBacError, match="known login rejection"):
        await auth.authed_get(client, "/student/classes/my")

    assert client.calls == 2
