from __future__ import annotations

import asyncio
import json
import threading
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from fastapi import HTTPException

from backend.api.routers.config import _validate_config_for_save, save_config
from backend.config_migration import template_aware_merge
from backend.services import installation_stats_state
from backend.services.installation_stats_contract import (
    DEFAULT_INSTALLATION_STATS_ENDPOINT,
    build_installation_stats_payload,
    classify_execution_mode,
    classify_installation_type,
    classify_release_channel,
    effective_installation_stats,
    is_valid_payload,
    is_valid_telemetry_endpoint,
    normalize_architecture,
)
from backend.services.installation_stats_service import InstallationStatsService
from backend.services.installation_stats_state import (
    InstallationStatsState,
    InstallationStatsStateError,
)

if TYPE_CHECKING:
    from pathlib import Path

NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def stable_test_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DARKSTAR_RELEASE_CHANNEL", "stable")


class FakeClock:
    def __init__(self, initial: datetime = NOW) -> None:
        self.current = initial
        self.elapsed = 0.0

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.elapsed += seconds
        self.current += timedelta(seconds=seconds)


class FakeResponse:
    def __init__(self, status_code: int = 204) -> None:
        self.status_code = status_code


class FakeClient:
    def __init__(
        self,
        clock: FakeClock | None = None,
        *,
        outcomes: list[int | Exception] | None = None,
        blocked_calls: dict[int, asyncio.Event] | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.call_times: list[datetime] = []
        self.closed = False
        self.called = asyncio.Event()
        self.call_changed = asyncio.Event()
        self.clock = clock
        self.time_at_first_call: datetime | None = None
        self.outcomes = list(outcomes or [])
        self.blocked_calls = blocked_calls or {}

    async def post(self, endpoint: str, *, json: dict[str, str]) -> FakeResponse:
        self.calls.append((endpoint, json))
        if self.clock is not None:
            call_time = self.clock()
            self.call_times.append(call_time)
            if self.time_at_first_call is None:
                self.time_at_first_call = call_time
        self.called.set()
        self.call_changed.set()
        gate = self.blocked_calls.get(len(self.calls))
        if gate is not None:
            await gate.wait()
        outcome = self.outcomes.pop(0) if self.outcomes else 204
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)

    async def wait_for_calls(self, count: int) -> None:
        while len(self.calls) < count:
            self.call_changed.clear()
            if len(self.calls) >= count:
                return
            await self.call_changed.wait()

    async def aclose(self) -> None:
        self.closed = True


class AutoAdvanceService(InstallationStatsService):
    def __init__(self, *args: Any, clock: FakeClock, **kwargs: Any) -> None:
        super().__init__(*args, now=clock, **kwargs)
        self.clock = clock
        self.waited: list[float] = []

    async def _wait(self, seconds: float) -> None:
        self.waited.append(seconds)
        self.clock.advance(seconds)
        await asyncio.sleep(0.001)


class BlockingService(InstallationStatsService):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.wait_started = asyncio.Event()
        self.release_wait = asyncio.Event()
        self.waited: list[float] = []

    async def _wait(self, seconds: float) -> None:
        self.waited.append(seconds)
        self.wait_started.set()
        await self.release_wait.wait()


def test_effective_defaults_and_template_merge_preserve_opt_out() -> None:
    assert effective_installation_stats({}) == {
        "enabled": True,
        "endpoint": DEFAULT_INSTALLATION_STATS_ENDPOINT,
    }
    defaults = {
        "installation_stats": {"enabled": True, "endpoint": DEFAULT_INSTALLATION_STATS_ENDPOINT}
    }
    user_config = {
        "installation_stats": {"enabled": False, "endpoint": "https://stats.example/ping"}
    }

    template_aware_merge(defaults, user_config)

    assert defaults["installation_stats"] == user_config["installation_stats"]
    assert effective_installation_stats(user_config) == user_config["installation_stats"]


def test_endpoint_validation_and_config_save_validation() -> None:
    assert is_valid_telemetry_endpoint("https://stats.example/api/ping")
    for value in (
        "http://stats.example/ping",
        "/api/ping",
        "https://user:pass@stats.example/ping",
        "https://stats.example/ping?secret=1",
        "https://stats.example/ping#fragment",
        "https://stats.example/a path",
        "https://stats.example:invalid/ping",
        "https://stats.example:65536/ping",
        "https://@stats.example/ping",
        "https://stats.example\\private/ping",
        "https://stats.example/ping\x7f",
    ):
        assert not is_valid_telemetry_endpoint(value)

    issues = _validate_config_for_save(
        {"installation_stats": {"enabled": "false", "endpoint": "http://stats.example/ping"}}
    )
    assert any("installation_stats.enabled" in issue["message"] for issue in issues)
    assert any("installation_stats.endpoint" in issue["message"] for issue in issues)


@pytest.mark.asyncio
async def test_config_save_rejects_string_boolean_before_coercion() -> None:
    with pytest.raises(HTTPException) as result:
        await save_config({"installation_stats": {"enabled": "false"}})
    assert result.value.status_code == 400
    assert "installation_stats.enabled" in str(result.value.detail)


def test_payload_is_allowlisted_and_classifies_profile_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DARKSTAR_RELEASE_CHANNEL", "stable")
    monkeypatch.setenv("DARKSTAR_INSTALLATION_TYPE", "ha_addon")
    monkeypatch.setenv("DARKSTAR_ARCH", "x86_64")
    payload = build_installation_stats_payload(
        {
            "system": {"inverter_profile": "<user profile>"},
            "executor": {"shadow_mode": True, "token": "excluded"},
            "input_sensors": {"grid_power": "sensor.private"},
        },
        "e78ed3fc-4c2e-44db-a7a4-537d0d0b6273",
        version="2.8.0-beta",
    )

    assert set(payload) == {
        "installation_id",
        "version",
        "release_channel",
        "installation_type",
        "architecture",
        "inverter_profile",
        "execution_mode",
    }
    assert payload == {
        "installation_id": "e78ed3fc-4c2e-44db-a7a4-537d0d0b6273",
        "version": "2.8.0-beta",
        "release_channel": "stable",
        "installation_type": "ha_addon",
        "architecture": "amd64",
        "inverter_profile": "custom",
        "execution_mode": "shadow",
    }
    assert is_valid_payload(payload)
    assert classify_execution_mode({"executor": {"shadow_mode": True}}) == "shadow"
    assert classify_execution_mode({"executor": {"shadow_mode": False}}) == "live"
    assert classify_execution_mode({}) == "unknown"
    assert classify_execution_mode({"executor": {"shadow_mode": "false"}}) == "unknown"
    assert (
        build_installation_stats_payload({}, payload["installation_id"], version="v")[
            "inverter_profile"
        ]
        == "unknown"
    )
    assert classify_release_channel("dev") == "dev"
    assert classify_installation_type("docker") == "docker"
    assert normalize_architecture("arm64") == "aarch64"
    assert normalize_architecture("mips") == "unknown"


def test_source_checkout_metadata_defaults_to_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DARKSTAR_RELEASE_CHANNEL", raising=False)
    monkeypatch.delenv("DARKSTAR_INSTALLATION_TYPE", raising=False)
    assert classify_release_channel() == "unknown"
    assert classify_installation_type() == "unknown"


def test_empty_docker_architecture_metadata_falls_back_to_machine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DARKSTAR_ARCH", "")
    monkeypatch.setattr(
        "backend.services.installation_stats_contract.platform.machine", lambda: "aarch64"
    )
    assert normalize_architecture() == "aarch64"


def test_state_is_channel_scoped_and_corruption_fails_closed(tmp_path: Path) -> None:
    stable = InstallationStatsState(tmp_path / "installation_stats.stable.json")
    dev = InstallationStatsState(tmp_path / "installation_stats.dev.json")
    stable.load()
    dev.load()
    assert stable.installation_id != dev.installation_id

    corrupt_path = tmp_path / "installation_stats.unknown.json"
    corrupt_path.write_text("{broken", encoding="utf-8")
    with pytest.raises(InstallationStatsStateError):
        InstallationStatsState(corrupt_path).load()
    assert corrupt_path.read_text(encoding="utf-8") == "{broken"

    blocker = tmp_path / "not-a-directory"
    blocker.write_text("file", encoding="utf-8")
    with pytest.raises(InstallationStatsStateError):
        InstallationStatsState(blocker / "state.json").load()


def test_state_attempt_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "installation_stats.stable.json"
    state = InstallationStatsState(path)
    state.load()
    state.record_attempt(NOW)
    saved_id = state.installation_id

    restarted = InstallationStatsState(path)
    restarted.load()

    assert restarted.installation_id == saved_id
    assert restarted.last_attempt == NOW
    assert json.loads(path.read_text(encoding="utf-8"))["last_attempt_utc"] == NOW.isoformat()


@pytest.mark.asyncio
async def test_first_send_is_immediate_and_sends_seven_fields(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    client = FakeClient(clock)
    service = AutoAdvanceService(
        data_dir=tmp_path,
        config_loader=lambda: {
            "installation_stats": {"enabled": True, "endpoint": "https://test.invalid/ping"}
        },
        client_factory=lambda: client,  # type: ignore[arg-type]
        clock=clock,
        randint=lambda low, high: 120,
    )

    await service.start()
    await asyncio.wait_for(client.called.wait(), timeout=1)
    await service.stop()

    assert client.time_at_first_call == NOW
    assert set(client.calls[0][1]) == {
        "installation_id",
        "version",
        "release_channel",
        "installation_type",
        "architecture",
        "inverter_profile",
        "execution_mode",
    }
    assert client.calls[0][1]["execution_mode"] == "unknown"
    assert client.calls[0][0] == "https://test.invalid/ping"


@pytest.mark.asyncio
async def test_restart_retries_an_unconfirmed_attempt_after_five_minutes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "installation_stats.stable.json"
    state = InstallationStatsState(path)
    state.load()
    state.record_attempt(NOW - timedelta(hours=1))
    clock = FakeClock()
    client = FakeClient(clock)
    service = AutoAdvanceService(
        data_dir=tmp_path,
        config_loader=lambda: {
            "installation_stats": {"enabled": True, "endpoint": "https://test.invalid/ping"}
        },
        client_factory=lambda: client,  # type: ignore[arg-type]
        clock=clock,
        randint=lambda low, high: 0,
    )

    await service.start()
    await asyncio.wait_for(client.called.wait(), timeout=1)
    await service.stop()

    assert client.time_at_first_call == NOW
    assert len(client.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("attempt_age", "expected_call_time"),
    [
        (timedelta(minutes=10), NOW),
        (timedelta(minutes=2), NOW + timedelta(minutes=3)),
    ],
    ids=["already-eligible", "waits-out-remainder"],
)
async def test_legacy_state_keeps_id_and_retries_after_five_minutes(
    tmp_path: Path, attempt_age: timedelta, expected_call_time: datetime
) -> None:
    path = tmp_path / "installation_stats.stable.json"
    installation_id = "e78ed3fc-4c2e-44db-a7a4-537d0d0b6273"
    path.write_text(
        json.dumps(
            {
                "installation_id": installation_id,
                "last_attempt_utc": (NOW - attempt_age).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    clock = FakeClock()
    client = FakeClient(clock)
    service = AutoAdvanceService(
        data_dir=tmp_path,
        config_loader=lambda: {
            "installation_stats": {"enabled": True, "endpoint": "https://test.invalid/ping"}
        },
        client_factory=lambda: client,  # type: ignore[arg-type]
        clock=clock,
        randint=lambda low, high: 0,
    )

    await service.start()
    await asyncio.wait_for(client.called.wait(), timeout=1)
    await service.stop()

    assert client.time_at_first_call == expected_call_time
    assert client.calls[0][1]["installation_id"] == installation_id
    restarted = InstallationStatsState(path)
    restarted.load()
    assert restarted.installation_id == installation_id
    assert restarted.last_attempt == expected_call_time
    assert restarted.last_success is None


@pytest.mark.asyncio
async def test_failure_retries_after_five_minutes_then_success_waits_daily(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "backend.services.installation_stats_service.CONFIG_CHECK_SECONDS", 100_000.0
    )
    clock = FakeClock()
    release_third_call = asyncio.Event()
    client = FakeClient(
        clock,
        outcomes=[503, 204, 204],
        blocked_calls={3: release_third_call},
    )
    service = AutoAdvanceService(
        data_dir=tmp_path,
        config_loader=lambda: {
            "installation_stats": {"enabled": True, "endpoint": "https://test.invalid/ping"}
        },
        client_factory=lambda: client,  # type: ignore[arg-type]
        clock=clock,
        randint=lambda low, high: 120,
    )

    await service.start()
    try:
        await asyncio.wait_for(client.wait_for_calls(3), timeout=10)
    finally:
        await service.stop()

    assert client.call_times == [
        NOW,
        NOW + timedelta(minutes=5),
        NOW + timedelta(minutes=5, hours=24, seconds=120),
    ]
    ids = [payload["installation_id"] for _, payload in client.calls]
    assert ids[0] == ids[1] == ids[2]
    persisted = InstallationStatsState(tmp_path / "installation_stats.stable.json")
    persisted.load()
    assert persisted.last_success == NOW + timedelta(minutes=5)
    assert persisted.last_attempt == NOW + timedelta(minutes=5, hours=24, seconds=120)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome",
    [400, 503, 307, httpx.ReadTimeout("synthetic timeout")],
    ids=["client-error", "server-error", "redirect", "timeout"],
)
async def test_unsuccessful_http_outcomes_retry_after_five_minutes(
    tmp_path: Path, outcome: int | Exception
) -> None:
    clock = FakeClock()
    client = FakeClient(clock, outcomes=[outcome, 204], blocked_calls={2: asyncio.Event()})
    service = AutoAdvanceService(
        data_dir=tmp_path,
        config_loader=lambda: {
            "installation_stats": {"enabled": True, "endpoint": "https://test.invalid/ping"}
        },
        client_factory=lambda: client,  # type: ignore[arg-type]
        clock=clock,
        randint=lambda low, high: 0,
    )

    await service.start()
    try:
        await asyncio.wait_for(client.wait_for_calls(2), timeout=5)
    finally:
        await service.stop()

    assert client.call_times == [NOW, NOW + timedelta(minutes=5)]
    assert client.calls[0][1]["installation_id"] == client.calls[1][1]["installation_id"]


@pytest.mark.asyncio
async def test_failed_attempt_after_prior_success_uses_five_minute_retry(
    tmp_path: Path,
) -> None:
    state = InstallationStatsState(tmp_path / "installation_stats.stable.json")
    state.load()
    old_success = NOW - timedelta(days=2)
    state.record_attempt(old_success)
    state.record_success(old_success, old_success + timedelta(hours=24, minutes=3))
    state.record_attempt(NOW - timedelta(minutes=1))

    clock = FakeClock()
    client = FakeClient(clock, blocked_calls={1: asyncio.Event()})
    service = AutoAdvanceService(
        data_dir=tmp_path,
        config_loader=lambda: {
            "installation_stats": {"enabled": True, "endpoint": "https://test.invalid/ping"}
        },
        client_factory=lambda: client,  # type: ignore[arg-type]
        clock=clock,
        randint=lambda low, high: 0,
    )
    await service.start()
    try:
        await asyncio.wait_for(client.called.wait(), timeout=2)
    finally:
        await service.stop()

    assert client.time_at_first_call == NOW + timedelta(minutes=4)


@pytest.mark.asyncio
async def test_attempt_state_write_failure_skips_request_without_retry_spin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = InstallationStatsState(tmp_path / "installation_stats.stable.json")
    state.load()
    state.record_attempt(NOW - timedelta(days=2))
    writes = 0

    def fail_write(path: Path, payload: object) -> None:
        nonlocal writes
        writes += 1
        raise OSError("synthetic disk failure")

    monkeypatch.setattr("backend.services.installation_stats_state.write_json_atomic", fail_write)
    client = FakeClient()
    service = BlockingService(
        data_dir=tmp_path,
        config_loader=lambda: {
            "installation_stats": {"enabled": True, "endpoint": "https://test.invalid/ping"}
        },
        client_factory=lambda: client,  # type: ignore[arg-type]
        now=lambda: NOW,
        randint=lambda low, high: 0,
    )

    await service.start()
    await asyncio.wait_for(service.wait_started.wait(), timeout=1)
    await service.stop()

    assert writes == 1
    assert client.calls == []


@pytest.mark.asyncio
async def test_success_state_write_failure_waits_before_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = InstallationStatsState(tmp_path / "installation_stats.stable.json")
    state.load()
    original_write = installation_stats_state.write_json_atomic
    writes = 0

    def fail_success_write(path: Path, payload: object) -> None:
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("synthetic success state failure")
        original_write(path, payload)

    monkeypatch.setattr(
        "backend.services.installation_stats_state.write_json_atomic", fail_success_write
    )
    client = FakeClient()
    service = BlockingService(
        data_dir=tmp_path,
        config_loader=lambda: {
            "installation_stats": {"enabled": True, "endpoint": "https://test.invalid/ping"}
        },
        client_factory=lambda: client,  # type: ignore[arg-type]
        now=lambda: NOW,
        randint=lambda low, high: 0,
    )

    await service.start()
    await asyncio.wait_for(client.called.wait(), timeout=1)
    await asyncio.wait_for(service.wait_started.wait(), timeout=1)
    await service.stop()

    assert writes == 2
    assert len(client.calls) == 1
    persisted = InstallationStatsState(tmp_path / "installation_stats.stable.json")
    persisted.load()
    assert persisted.last_attempt == NOW
    assert persisted.last_success is None


@pytest.mark.asyncio
async def test_restart_uses_persisted_due_time_after_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "backend.services.installation_stats_service.CONFIG_CHECK_SECONDS", 100_000.0
    )
    clock = FakeClock()
    first_client = FakeClient(clock)
    first_service = BlockingService(
        data_dir=tmp_path,
        config_loader=lambda: {
            "installation_stats": {"enabled": True, "endpoint": "https://test.invalid/ping"}
        },
        client_factory=lambda: first_client,  # type: ignore[arg-type]
        now=clock,
        randint=lambda low, high: 120,
    )
    await first_service.start()
    await asyncio.wait_for(first_client.called.wait(), timeout=1)
    await asyncio.wait_for(first_service.wait_started.wait(), timeout=1)
    await first_service.stop()

    clock = FakeClock(NOW + timedelta(hours=1))
    second_client = FakeClient(clock, blocked_calls={1: asyncio.Event()})
    second_service = AutoAdvanceService(
        data_dir=tmp_path,
        config_loader=lambda: {
            "installation_stats": {"enabled": True, "endpoint": "https://test.invalid/ping"}
        },
        client_factory=lambda: second_client,  # type: ignore[arg-type]
        clock=clock,
        randint=lambda low, high: 900,
    )
    await second_service.start()
    try:
        await asyncio.wait_for(second_client.called.wait(), timeout=5)
    finally:
        await second_service.stop()

    assert second_client.time_at_first_call == NOW + timedelta(hours=24, seconds=120)
    assert (
        first_client.calls[0][1]["installation_id"] == second_client.calls[0][1]["installation_id"]
    )


@pytest.mark.asyncio
async def test_disable_at_dispatch_recheck_suppresses_request(tmp_path: Path) -> None:
    path = tmp_path / "installation_stats.stable.json"
    state = InstallationStatsState(path)
    state.load()
    state.record_attempt(NOW - timedelta(hours=25))
    config_reads = 0

    def config_loader() -> dict[str, object]:
        nonlocal config_reads
        config_reads += 1
        enabled = config_reads == 1
        return {"installation_stats": {"enabled": enabled, "endpoint": "https://test.invalid/ping"}}

    client = FakeClient()
    service = BlockingService(
        data_dir=tmp_path,
        config_loader=config_loader,
        client_factory=lambda: client,  # type: ignore[arg-type]
        now=lambda: NOW,
        randint=lambda low, high: 0,
    )

    await service.start()
    await asyncio.wait_for(service.wait_started.wait(), timeout=1)
    await service.stop()

    assert config_reads >= 2
    assert client.calls == []
    assert InstallationStatsState(path).path.exists()


@pytest.mark.asyncio
async def test_latest_endpoint_is_used_at_dispatch(tmp_path: Path) -> None:
    path = tmp_path / "installation_stats.stable.json"
    state = InstallationStatsState(path)
    state.load()
    state.record_attempt(NOW - timedelta(hours=25))
    reads = 0

    def config_loader() -> dict[str, object]:
        nonlocal reads
        reads += 1
        endpoint = "https://old.invalid/ping" if reads == 1 else "https://new.invalid/ping"
        return {"installation_stats": {"enabled": True, "endpoint": endpoint}}

    clock = FakeClock()
    client = FakeClient(clock)
    service = AutoAdvanceService(
        data_dir=tmp_path,
        config_loader=config_loader,
        client_factory=lambda: client,  # type: ignore[arg-type]
        clock=clock,
        randint=lambda low, high: 0,
    )

    await service.start()
    await asyncio.wait_for(client.called.wait(), timeout=1)
    await service.stop()

    assert reads >= 2
    assert client.calls[0][0] == "https://new.invalid/ping"


@pytest.mark.asyncio
@pytest.mark.parametrize("new_enabled", [False, True])
async def test_config_change_during_state_write_controls_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, new_enabled: bool
) -> None:
    state = InstallationStatsState(tmp_path / "installation_stats.stable.json")
    state.load()
    state.record_attempt(NOW - timedelta(hours=25))
    config = {"installation_stats": {"enabled": True, "endpoint": "https://old.invalid/ping"}}
    write_started = threading.Event()
    write_release = threading.Event()
    original_record = InstallationStatsState.record_attempt

    def blocked_record(self: InstallationStatsState, attempted_at: datetime) -> None:
        write_started.set()
        assert write_release.wait(timeout=3)
        original_record(self, attempted_at)

    monkeypatch.setattr(InstallationStatsState, "record_attempt", blocked_record)
    client = FakeClient()
    service = BlockingService(
        data_dir=tmp_path,
        config_loader=lambda: {"installation_stats": dict(config["installation_stats"])},
        client_factory=lambda: client,  # type: ignore[arg-type]
        now=lambda: NOW,
        randint=lambda low, high: 0,
    )
    await service.start()
    try:
        assert await asyncio.to_thread(write_started.wait, 1)
        config["installation_stats"] = {
            "enabled": new_enabled,
            "endpoint": "https://new.invalid/ping",
        }
        service.notify_config_changed()
        write_release.set()
        await asyncio.wait_for(service.wait_started.wait(), timeout=1)
    finally:
        write_release.set()
        await service.stop()
    if new_enabled:
        assert len(client.calls) == 1
        assert client.calls[0][0] == "https://new.invalid/ping"
    else:
        assert client.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config",
    [
        {"installation_stats": {"enabled": "false"}},
        {"installation_stats": {"enabled": True, "endpoint": "http://invalid.test/ping"}},
    ],
)
async def test_runtime_invalid_config_is_isolated(
    tmp_path: Path, config: dict[str, object]
) -> None:
    client = FakeClient()
    service = BlockingService(
        data_dir=tmp_path,
        config_loader=lambda: config,
        client_factory=lambda: client,  # type: ignore[arg-type]
    )
    await service.start()
    await asyncio.wait_for(service.wait_started.wait(), timeout=1)
    assert service._task is not None and not service._task.done()
    await service.stop()
    assert client.calls == []
    assert client.closed


@pytest.mark.asyncio
async def test_shutdown_cancels_in_flight_request(tmp_path: Path) -> None:
    state = InstallationStatsState(tmp_path / "installation_stats.stable.json")
    state.load()
    state.record_attempt(NOW - timedelta(hours=25))
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocked_request(request: httpx.Request) -> httpx.Response:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return httpx.Response(204)

    client = httpx.AsyncClient(transport=httpx.MockTransport(blocked_request))
    service = InstallationStatsService(
        data_dir=tmp_path,
        config_loader=lambda: {},
        client_factory=lambda: client,
        now=lambda: NOW,
        randint=lambda low, high: 0,
    )
    await service.start()
    await asyncio.wait_for(started.wait(), timeout=1)
    await asyncio.wait_for(service.stop(), timeout=1)
    assert cancelled.is_set()
    assert client.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["redirect", "timeout"])
async def test_http_redirect_and_timeout_are_not_followed_or_retried_immediately(
    tmp_path: Path, outcome: str
) -> None:
    path = tmp_path / "installation_stats.stable.json"
    state = InstallationStatsState(path)
    state.load()
    state.record_attempt(NOW - timedelta(hours=25))
    requests: list[httpx.Request] = []
    called = asyncio.Event()

    async def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        called.set()
        if outcome == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        return httpx.Response(307, headers={"location": "https://redirect.invalid/ping"})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handle), follow_redirects=False, timeout=5.0
    )
    service = InstallationStatsService(
        data_dir=tmp_path,
        config_loader=lambda: {
            "installation_stats": {"enabled": True, "endpoint": "https://test.invalid/ping"}
        },
        client_factory=lambda: client,
        now=lambda: NOW,
        randint=lambda low, high: 0,
    )

    await service.start()
    await asyncio.wait_for(called.wait(), timeout=1)
    await service.stop()

    assert len(requests) == 1
    assert str(requests[0].url) == "https://test.invalid/ping"


@pytest.mark.asyncio
async def test_shutdown_cancels_wait_and_closes_client(tmp_path: Path) -> None:
    state = InstallationStatsState(tmp_path / "installation_stats.stable.json")
    state.load()
    previous_success = NOW - timedelta(hours=1)
    state.record_attempt(previous_success)
    state.record_success(previous_success, NOW + timedelta(hours=23))
    client = FakeClient()
    service = BlockingService(
        data_dir=tmp_path,
        config_loader=lambda: {
            "installation_stats": {"enabled": True, "endpoint": "https://test.invalid/ping"}
        },
        client_factory=lambda: client,  # type: ignore[arg-type]
        now=lambda: NOW,
        randint=lambda low, high: 900,
    )

    await service.start()
    await asyncio.wait_for(service.wait_started.wait(), timeout=1)
    await service.stop()

    assert client.closed
    assert service._task is None
    assert client.calls == []
