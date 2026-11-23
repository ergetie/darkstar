"""Per-entity revert detection in ActionDispatcher (inverter-revert-warning)."""

from unittest.mock import AsyncMock, patch

import pytest

from executor.actions import REVERT_MIN_AGE_S, ActionDispatcher
from executor.config import ExecutorConfig, InverterConfig
from executor.controller import ControllerDecision
from executor.profiles import load_profile

WORK_MODE = "select.inverter_work_mode"
GRID_CHARGING = "switch.inverter_battery_grid_charging"
STEP = REVERT_MIN_AGE_S * 10  # one "tick" of fake time, well past the age guard


class FakeHA:
    """Minimal HA stand-in: writes land in `states` unless `ignore_writes` is set."""

    def __init__(self, states):
        self.states = dict(states)
        self.ignore_writes = False

    async def get_state(self, entity_id):
        if entity_id not in self.states:
            return None
        return {"state": self.states[entity_id], "attributes": {}}

    async def get_state_value(self, entity_id):
        return self.states.get(entity_id)

    async def set_select_option(self, entity_id, option):
        if not self.ignore_writes:
            self.states[entity_id] = option
        return True

    async def set_switch(self, entity_id, state):
        if not self.ignore_writes:
            self.states[entity_id] = "on" if state else "off"
        return True

    async def send_notification(self, *args, **kwargs):
        return True

    async def set_number(self, entity_id, value):
        if not self.ignore_writes:
            self.states[entity_id] = str(value)
        return True


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds=STEP):
        self.now += seconds


@pytest.fixture
def clock():
    clock = Clock()
    with (
        patch("executor.actions.time.monotonic", clock),
        patch("executor.actions.asyncio.sleep", new_callable=AsyncMock),
    ):
        yield clock


def _dispatcher(profile_name="deye", states=None, config=None):
    ha = FakeHA(states or {})
    dispatcher = ActionDispatcher(
        ha, config or ExecutorConfig(), shadow_mode=False, profile=load_profile(profile_name)
    )
    return dispatcher, ha


async def _tick(dispatcher, clock, mode="self_consumption"):
    clock.advance()
    await dispatcher.execute(ControllerDecision(mode_intent=mode))
    return dispatcher.drain_revert_events()


async def test_revert_counted_per_entity(clock):
    dispatcher, ha = _dispatcher(states={WORK_MODE: "Export First", GRID_CHARGING: "on"})
    assert await _tick(dispatcher, clock) == []  # writes and verifies, sets baselines
    ha.states[WORK_MODE] = "Export First"  # inverter reverts the select
    events = await _tick(dispatcher, clock)
    assert [(e.entity_id, e.commanded, e.observed) for e in events] == [
        (WORK_MODE, "Zero Export To CT", "Export First")
    ]


async def test_deye_switch_revert_counted_on_switch_only(clock):
    dispatcher, ha = _dispatcher(states={WORK_MODE: "x", GRID_CHARGING: "off"})
    await _tick(dispatcher, clock, "charge")
    ha.states[GRID_CHARGING] = "off"  # switch reverts, select stays
    events = await _tick(dispatcher, clock, "charge")
    assert [e.entity_id for e in events] == [GRID_CHARGING]
    assert (events[0].commanded, events[0].observed) == ("True", "off")


async def test_plan_transition_is_not_a_revert(clock):
    dispatcher, ha = _dispatcher(states={WORK_MODE: "x", GRID_CHARGING: "off"})
    await _tick(dispatcher, clock, "charge")
    assert await _tick(dispatcher, clock, "export") == []  # target changes, state does not
    assert await _tick(dispatcher, clock, "self_consumption") == []


async def test_own_write_and_young_baseline_not_counted(clock):
    dispatcher, ha = _dispatcher(states={WORK_MODE: "x", GRID_CHARGING: "off"})
    await _tick(dispatcher, clock)
    ha.states[WORK_MODE] = "Export First"
    clock.advance(REVERT_MIN_AGE_S - 1)  # inside the 30 s guard
    await dispatcher.execute(ControllerDecision(mode_intent="self_consumption"))
    assert dispatcher.drain_revert_events() == []


async def test_unverified_write_sets_no_baseline(clock):
    dispatcher, ha = _dispatcher(states={WORK_MODE: "x", GRID_CHARGING: "off"})
    ha.states[GRID_CHARGING] = "on"
    ha.ignore_writes = True  # write succeeds but read-back never matches
    await _tick(dispatcher, clock)
    assert dispatcher._verified_command == {}
    ha.states[WORK_MODE] = "Export First"
    assert await _tick(dispatcher, clock) == []


async def test_failed_write_removes_baseline(clock):
    dispatcher, ha = _dispatcher(states={WORK_MODE: "x", GRID_CHARGING: "off"})
    await _tick(dispatcher, clock)
    assert WORK_MODE in dispatcher._verified_command
    ha.states[WORK_MODE] = "Export First"
    ha.set_select_option = AsyncMock(return_value=False)
    assert len(await _tick(dispatcher, clock)) == 1  # the revert itself is counted once
    assert WORK_MODE not in dispatcher._verified_command


@pytest.mark.parametrize("state", ["unavailable", "unknown", ""])
async def test_unavailable_state_is_ignored(clock, state):
    dispatcher, ha = _dispatcher(states={WORK_MODE: "x", GRID_CHARGING: "off"})
    await _tick(dispatcher, clock)
    ha.states[WORK_MODE] = state
    assert await _tick(dispatcher, clock) == []


async def test_already_at_target_refreshes_baseline_without_counting(clock):
    dispatcher, ha = _dispatcher(states={WORK_MODE: "x", GRID_CHARGING: "off"})
    await _tick(dispatcher, clock)
    first = dispatcher._verified_command[WORK_MODE][1]
    assert await _tick(dispatcher, clock) == []  # state equals target, skipped
    assert dispatcher._verified_command[WORK_MODE][0] == "Zero Export To CT"
    # The write time is kept, so the 30 s guard measures time since the write.
    assert dispatcher._verified_command[WORK_MODE][1] == first


async def test_revert_after_short_interval_refreshes_is_counted(clock):
    dispatcher, ha = _dispatcher(states={WORK_MODE: "x", GRID_CHARGING: "off"})
    await _tick(dispatcher, clock)
    clock.advance(REVERT_MIN_AGE_S - 10)
    await _tick(dispatcher, clock)  # refresh only, 20 s after the write
    ha.states[WORK_MODE] = "Export First"
    clock.advance(20)  # 40 s after the write, 20 s after the refresh
    events = await _tick(dispatcher, clock)
    assert [e.entity_id for e in events] == [WORK_MODE]


async def test_configure_me_is_skipped(clock):
    config = ExecutorConfig(inverter=InverterConfig(work_mode="select.generic_mode"))
    dispatcher, ha = _dispatcher(
        "generic", states={"select.generic_mode": "CONFIGURE_ME"}, config=config
    )
    ha.states["select.generic_mode"] = "other"
    await _tick(dispatcher, clock)
    ha.states["select.generic_mode"] = "changed"
    assert await _tick(dispatcher, clock) == []
    assert "select.generic_mode" not in dispatcher._verified_command


async def test_numeric_entity_is_never_tracked(clock):
    dispatcher, ha = _dispatcher(states={WORK_MODE: "x", GRID_CHARGING: "off"})
    await _tick(dispatcher, clock)
    tracked = set(dispatcher._verified_command)
    assert tracked <= {WORK_MODE, GRID_CHARGING}
    assert not any(e.startswith("number.") for e in tracked)


async def test_shadow_mode_tracks_nothing(clock):
    dispatcher, ha = _dispatcher(states={WORK_MODE: "x", GRID_CHARGING: "off"})
    await _tick(dispatcher, clock)
    dispatcher.shadow_mode = True
    ha.states[WORK_MODE] = "Export First"
    assert await _tick(dispatcher, clock) == []
    assert dispatcher._verified_command == {}


async def test_clear_baselines_prevents_event(clock):
    dispatcher, ha = _dispatcher(states={WORK_MODE: "x", GRID_CHARGING: "off"})
    await _tick(dispatcher, clock)
    ha.states[WORK_MODE] = "Export First"
    dispatcher.clear_baselines()
    assert await _tick(dispatcher, clock) == []


async def test_sungrow_export_switch_baseline_dropped_outside_export_mode(clock):
    switch = "switch.export_power_limit"
    dispatcher, ha = _dispatcher("sungrow", states={switch: "off"})
    await _tick(dispatcher, clock, "export")
    assert switch in dispatcher._verified_command
    await _tick(dispatcher, clock, "self_consumption")
    assert switch not in dispatcher._verified_command  # not part of that mode's actions
    ha.states[switch] = "off"  # user/inverter changes it legitimately
    assert await _tick(dispatcher, clock, "export") == []  # fresh baseline, no event


async def test_update_config_clears_baselines_on_mapping_change(clock):
    dispatcher, ha = _dispatcher(states={WORK_MODE: "x", GRID_CHARGING: "off"})
    await _tick(dispatcher, clock)
    dispatcher.update_config(ExecutorConfig(), dispatcher.profile)  # same mapping
    assert dispatcher._verified_command
    remapped = ExecutorConfig(inverter=InverterConfig(work_mode="select.other_mode"))
    dispatcher.update_config(remapped, dispatcher.profile)
    assert dispatcher._verified_command == {}


async def test_update_config_clears_baselines_on_profile_change(clock):
    dispatcher, ha = _dispatcher(states={WORK_MODE: "x", GRID_CHARGING: "off"})
    await _tick(dispatcher, clock)
    dispatcher.update_config(ExecutorConfig(), load_profile("sungrow"))
    assert dispatcher._verified_command == {}


async def test_drain_clears_events(clock):
    dispatcher, ha = _dispatcher(states={WORK_MODE: "x", GRID_CHARGING: "off"})
    await _tick(dispatcher, clock)
    ha.states[WORK_MODE] = "Export First"
    clock.advance()
    await dispatcher.execute(ControllerDecision(mode_intent="self_consumption"))
    assert len(dispatcher.drain_revert_events()) == 1
    assert dispatcher.drain_revert_events() == []
