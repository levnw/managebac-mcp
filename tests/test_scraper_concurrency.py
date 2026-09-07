import asyncio
from types import SimpleNamespace

import pytest

from managebac_mcp import scraper
from managebac_mcp.context import User, reset_user, set_current_user


@pytest.mark.asyncio
async def test_fetch_classes_lock_covers_live_fetch(monkeypatch):
    store = {}
    clients_created = 0

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    async def fake_get_client():
        nonlocal clients_created
        clients_created += 1
        return Client()

    async def fake_authed_get(_client, path):
        await asyncio.sleep(0.02)
        return SimpleNamespace(text="class page" if path == "/student/classes/my" else "learner_portfolio")

    monkeypatch.setattr(scraper.cache, "get", lambda key: store.get(key))
    monkeypatch.setattr(scraper.cache, "set", lambda key, value, _tool: store.__setitem__(key, value))
    monkeypatch.setattr(scraper, "get_client", fake_get_client)
    monkeypatch.setattr(scraper, "authed_get", fake_authed_get)
    monkeypatch.setattr(scraper, "parse_classes", lambda _html: [{"id": "1", "name": "Class"}])
    scraper._fetch_classes_locks.clear()

    token = set_current_user(User("same-user", "legacy", "student", "https://school.managebac.com", "student@example.com", "secret"))
    try:
        first, second = await asyncio.gather(scraper.fetch_classes(), scraper.fetch_classes())
    finally:
        reset_user(token)

    assert first == second
    assert clients_created == 1
