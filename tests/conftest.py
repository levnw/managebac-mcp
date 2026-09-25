import pytest


@pytest.fixture(autouse=True)
def no_retry_pause(monkeypatch):
    """Retries are exercised in tests; their jittered pause is not."""
    monkeypatch.setattr('sources.managebac.pages.RETRY_DELAY_SECONDS', (0, 0))
    monkeypatch.setattr('sources.managebac.pages.MAX_RETRY_AFTER_SECONDS', 0)
