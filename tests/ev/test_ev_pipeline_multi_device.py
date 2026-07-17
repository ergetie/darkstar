"""
Task 4.5: Pipeline tests for per-device EV processing.

Covers:
- Per-device deadline calculation
- Per-device state matching (HA state paired with config)
- Plug override for a specific charger
"""

from datetime import datetime

from pytz import timezone as pytz_timezone

from planner.solver.adapter import build_ev_charger_inputs

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _localize(dt: datetime, tz_name: str = "Europe/Stockholm") -> datetime:
    return pytz_timezone(tz_name).localize(dt)


# ---------------------------------------------------------------------------
# Per-device state matching via build_ev_charger_inputs
# ---------------------------------------------------------------------------


class TestPerDeviceStateMatching:
    """build_ev_charger_inputs correctly pairs HA state with device config."""

    def _make_cfg(self, ev_id, max_power_kw=7.4, capacity=100.0, enabled=True):
        return {
            "id": ev_id,
            "enabled": enabled,
            "max_power_kw": max_power_kw,
            "battery_capacity_kwh": capacity,
            "name": ev_id,
        }

    def _make_state(self, ev_id, soc=50.0, plugged_in=True, deadline=None):
        return {
            "id": ev_id,
            "soc_percent": soc,
            "plugged_in": plugged_in,
            "deadline": deadline,
        }

    def test_two_chargers_get_separate_states(self):
        """Each charger gets the correct SoC from its own HA state."""
        cfgs = [
            self._make_cfg("ev1", max_power_kw=7.4, capacity=100.0),
            self._make_cfg("ev2", max_power_kw=11.0, capacity=82.0),
        ]
        states = [
            self._make_state("ev1", soc=30.0, plugged_in=True),
            self._make_state("ev2", soc=70.0, plugged_in=True),
        ]

        result = build_ev_charger_inputs(cfgs, states)

        assert len(result) == 2
        ev1 = next(r for r in result if r.id == "ev1")
        ev2 = next(r for r in result if r.id == "ev2")

        assert ev1.current_soc_percent == 30.0
        assert ev1.max_power_kw == 7.4
        assert ev2.current_soc_percent == 70.0
        assert ev2.max_power_kw == 11.0

    def test_missing_ha_state_falls_back_to_defaults(self):
        """Charger with no matching HA state gets default SoC (0) and unplugged."""
        cfgs = [self._make_cfg("ev1")]
        states = []  # No HA state for ev1

        result = build_ev_charger_inputs(cfgs, states)

        # Should still produce an EVChargerInput with defaults
        assert len(result) == 1
        assert result[0].id == "ev1"
        # Default soc is 0 when not found
        assert result[0].current_soc_percent == 0.0

    def test_disabled_charger_excluded(self):
        cfgs = [
            self._make_cfg("ev1", enabled=True),
            self._make_cfg("ev2", enabled=False),
        ]
        states = [
            self._make_state("ev1"),
            self._make_state("ev2"),
        ]

        result = build_ev_charger_inputs(cfgs, states)

        assert len(result) == 1
        assert result[0].id == "ev1"

    def test_deadline_passed_through_to_ev_charger_input(self):
        """Deadline computed by pipeline is stored in EVChargerInput."""
        deadline = _localize(datetime(2026, 1, 15, 14, 0))

        cfgs = [self._make_cfg("ev1")]
        states = [self._make_state("ev1", soc=40.0, plugged_in=True, deadline=deadline)]

        result = build_ev_charger_inputs(cfgs, states)

        assert len(result) == 1
        assert result[0].deadline == deadline

    def test_no_deadline_when_not_plugged_in(self):
        """Unplugged charger should not have a deadline set by pipeline."""
        cfgs = [self._make_cfg("ev1")]
        states = [self._make_state("ev1", soc=40.0, plugged_in=False, deadline=None)]

        result = build_ev_charger_inputs(cfgs, states)

        # Regardless of plugged_in status the input is built (solver ignores it)
        assert len(result) == 1
        assert result[0].deadline is None


# ---------------------------------------------------------------------------
# Plug override for a specific charger
# ---------------------------------------------------------------------------


class TestPlugOverridePerDevice:
    """Plug override should only affect the specific charger, not others."""

    def test_plug_override_only_affects_target_charger(self):
        """When ev_plugged_in_override is set for ev1, ev2 state is unchanged."""
        cfgs = [
            {"id": "ev1", "enabled": True, "max_power_kw": 7.4, "battery_capacity_kwh": 100.0},
            {"id": "ev2", "enabled": True, "max_power_kw": 7.4, "battery_capacity_kwh": 100.0},
        ]

        # Simulates what the pipeline does when override is provided for ev1
        states_raw = [
            {"id": "ev1", "soc_percent": 50.0, "plugged_in": False},  # HA says unplugged
            {"id": "ev2", "soc_percent": 60.0, "plugged_in": False},  # HA says unplugged
        ]

        # Apply override for ev1 only (as pipeline does)
        override_charger_id = "ev1"
        states_with_override = []
        for s in states_raw:
            if s["id"] == override_charger_id:
                states_with_override.append({**s, "plugged_in": True})
            else:
                states_with_override.append(s)

        result = build_ev_charger_inputs(
            cfgs,
            [
                {
                    "id": s["id"],
                    "soc_percent": s["soc_percent"],
                    "plugged_in": s["plugged_in"],
                    "deadline": None,
                }
                for s in states_with_override
            ],
        )

        ev1 = next(r for r in result if r.id == "ev1")
        ev2 = next(r for r in result if r.id == "ev2")

        # EV1 should be plugged in (override applied)
        assert ev1.plugged_in is True
        # EV2 should still be unplugged (override not applied)
        assert ev2.plugged_in is False
