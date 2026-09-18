import asyncio
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from executor.engine import ExecutorEngine


def _bare_engine() -> ExecutorEngine:
    engine = object.__new__(ExecutorEngine)
    engine._tick_lock = threading.Lock()
    engine.status = SimpleNamespace(last_run_status=None, last_skip_reason=None)
    return engine


def test_tick_skips_concurrent_entrant_from_another_thread() -> None:
    engine = _bare_engine()
    started = threading.Event()
    release = threading.Event()
    body_calls = 0

    async def body() -> dict[str, Any]:
        nonlocal body_calls
        body_calls += 1
        started.set()
        await asyncio.to_thread(release.wait)
        return {"success": True}

    engine._tick_unlocked = body
    first_result: dict[str, Any] = {}

    def run_first() -> None:
        first_result.update(asyncio.run(engine._tick()))

    first_thread = threading.Thread(target=run_first)
    first_thread.start()
    assert started.wait(timeout=1)

    second_result = asyncio.run(engine._tick())
    assert second_result == {"success": False, "skipped": True, "reason": "tick_already_running"}
    assert engine.status.last_run_status == "skipped"
    assert engine.status.last_skip_reason == "tick_already_running"
    assert body_calls == 1

    release.set()
    first_thread.join(timeout=1)
    assert not first_thread.is_alive()
    assert first_result == {"success": True}


def test_tick_releases_lock_when_body_raises() -> None:
    engine = _bare_engine()
    body_calls = 0

    async def failing_body() -> None:
        nonlocal body_calls
        body_calls += 1
        raise RuntimeError("tick failed")

    engine._tick_unlocked = failing_body
    with pytest.raises(RuntimeError, match="tick failed"):
        asyncio.run(engine._tick())

    async def successful_body() -> dict[str, bool]:
        nonlocal body_calls
        body_calls += 1
        return {"success": True}

    engine._tick_unlocked = successful_body
    assert asyncio.run(engine._tick()) == {"success": True}
    assert body_calls == 2
