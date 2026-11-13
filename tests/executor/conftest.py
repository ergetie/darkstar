import pytest


@pytest.fixture(autouse=True)
def fast_verify_polling(monkeypatch):
    """Keep ActionDispatcher._verify_action polling from really sleeping.

    Tests that assert on the polling behaviour override these values themselves.
    """
    import executor.actions as actions_mod

    monkeypatch.setattr(actions_mod, "VERIFY_POLL_INTERVAL_MS", 1)
    monkeypatch.setattr(actions_mod, "VERIFY_MAX_WAIT_MS", 10)


@pytest.fixture
def no_retry_backoff():
    """Skip the real backoff sleeps in executor.actions._retry_with_backoff."""
    from unittest.mock import AsyncMock, patch

    with patch("executor.actions.asyncio.sleep", new_callable=AsyncMock) as sleep:
        yield sleep
