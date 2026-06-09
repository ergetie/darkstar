"""Tests for the export floor SoC constraint in the Kepler MILP solver."""

from datetime import datetime, timedelta

import pytest

from planner.solver.kepler import KeplerSolver
from planner.solver.types import KeplerConfig, KeplerInput, KeplerInputSlot, KeplerResult


def _make_slots(
    n: int,
    import_price: float = 1.0,
    export_price: float = 2.0,
    load_kwh: float = 0.0,
    pv_kwh: float = 0.0,
    start: datetime | None = None,
) -> list[KeplerInputSlot]:
    if start is None:
        start = datetime(2025, 1, 1, 12, 0)
    slots = []
    for i in range(n):
        slots.append(
            KeplerInputSlot(
                start_time=start + timedelta(minutes=15 * i),
                end_time=start + timedelta(minutes=15 * (i + 1)),
                load_kwh=load_kwh,
                pv_kwh=pv_kwh,
                import_price_sek_kwh=import_price,
                export_price_sek_kwh=export_price,
            )
        )
    return slots


def _base_config(
    capacity: float = 34.2,
    min_soc: float = 5.0,
    max_soc: float = 100.0,
    export_floor: float | None = 20.0,
    enable_export: bool = True,
    max_export_kw: float | None = 11.0,
    max_charge_kw: float = 11.0,
    max_discharge_kw: float = 11.0,
) -> KeplerConfig:
    return KeplerConfig(
        capacity_kwh=capacity,
        min_soc_percent=min_soc,
        max_soc_percent=max_soc,
        max_charge_power_kw=max_charge_kw,
        max_discharge_power_kw=max_discharge_kw,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        enable_export=enable_export,
        export_floor_soc_percent=export_floor,
        max_export_power_kw=max_export_kw,
    )


def _assert_exporting_slots_end_at_or_above_floor(
    result: KeplerResult, floor_kwh: float
) -> None:
    for slot in result.slots:
        if slot.grid_export_kwh > 0.01:
            assert slot.soc_kwh >= floor_kwh - 0.01


class TestExportFloorBlocksExportBelowFloor:
    def test_export_blocked_when_soc_below_floor(self):
        capacity = 34.2
        floor_pct = 20
        floor_kwh = capacity * floor_pct / 100.0  # 6.84

        slots = _make_slots(2, import_price=10.0, export_price=5.0)
        input_data = KeplerInput(slots=slots, initial_soc_kwh=5.0)  # below floor

        config = _base_config(capacity=capacity, export_floor=floor_pct)
        result = KeplerSolver().solve(input_data, config)

        assert result.is_optimal
        # With import at 10 SEK, charging above floor (1.84 kWh) costs 18.4 SEK
        # but exporting 2.75 kWh earns only 13.75 SEK. Net loss, so no export.
        for s in result.slots:
            assert s.grid_export_kwh == pytest.approx(0.0, abs=0.01)
        _assert_exporting_slots_end_at_or_above_floor(result, floor_kwh)


class TestExportFloorAllowedAboveFloor:
    def test_export_allowed_when_soc_above_floor(self):
        capacity = 34.2
        floor_pct = 20
        floor_kwh = capacity * floor_pct / 100.0  # 6.84

        slots = _make_slots(2, import_price=10.0, export_price=5.0)
        input_data = KeplerInput(slots=slots, initial_soc_kwh=10.0)  # above floor

        config = _base_config(capacity=capacity, export_floor=floor_pct)
        result = KeplerSolver().solve(input_data, config)

        assert result.is_optimal
        total_export = sum(s.grid_export_kwh for s in result.slots)
        assert total_export > 0.01
        _assert_exporting_slots_end_at_or_above_floor(result, floor_kwh)


class TestExportFloorBoundarySlot:
    def test_partial_export_lands_at_floor(self):
        capacity = 34.2
        floor_pct = 20
        floor_kwh = capacity * floor_pct / 100.0  # 6.84
        initial_soc_kwh = floor_kwh + 1.0
        max_export_kw = 11.0
        full_slot_export_kwh = max_export_kw * 0.25

        slots = _make_slots(1, import_price=10.0, export_price=5.0)
        input_data = KeplerInput(slots=slots, initial_soc_kwh=initial_soc_kwh)

        config = _base_config(
            capacity=capacity,
            export_floor=floor_pct,
            max_export_kw=max_export_kw,
            max_charge_kw=0.001,
        )
        result = KeplerSolver().solve(input_data, config)

        assert result.is_optimal
        slot = result.slots[0]
        assert slot.grid_export_kwh == pytest.approx(1.0, abs=0.01)
        assert 0.01 < slot.grid_export_kwh < full_slot_export_kwh - 0.01
        assert slot.soc_kwh == pytest.approx(floor_kwh, abs=0.01)
        _assert_exporting_slots_end_at_or_above_floor(result, floor_kwh)


class TestExportFloorProductionRegression:
    def test_high_power_export_does_not_overshoot_floor(self):
        capacity = 66.0
        floor_pct = 28.0
        floor_kwh = capacity * floor_pct / 100.0  # 18.48
        initial_soc_kwh = capacity * 0.283  # 28.3%, just above the floor
        max_export_kw = 16.5
        full_slot_export_kwh = max_export_kw * 0.25
        allowable_export_kwh = initial_soc_kwh - floor_kwh

        slots = _make_slots(1, import_price=10.0, export_price=5.0)
        input_data = KeplerInput(slots=slots, initial_soc_kwh=initial_soc_kwh)

        config = _base_config(
            capacity=capacity,
            export_floor=floor_pct,
            max_export_kw=max_export_kw,
            max_discharge_kw=max_export_kw,
            max_charge_kw=0.001,
        )
        result = KeplerSolver().solve(input_data, config)

        assert result.is_optimal
        slot = result.slots[0]
        assert slot.grid_export_kwh > 0.01
        assert slot.grid_export_kwh == pytest.approx(allowable_export_kwh, abs=0.01)
        assert slot.grid_export_kwh < full_slot_export_kwh - 0.01
        assert slot.soc_kwh == pytest.approx(floor_kwh, abs=0.01)
        assert slot.soc_kwh / capacity * 100.0 >= floor_pct - 0.01
        _assert_exporting_slots_end_at_or_above_floor(result, floor_kwh)


class TestExportFloorSoftViolation:
    def test_soft_violation_under_extreme_price(self):
        capacity = 34.2
        floor_pct = 20

        slots = _make_slots(2, export_price=50.0)  # extreme spike
        input_data = KeplerInput(slots=slots, initial_soc_kwh=5.0)  # below floor

        config = _base_config(capacity=capacity, export_floor=floor_pct)
        result = KeplerSolver().solve(input_data, config)

        assert result.is_optimal
        # Solver should export despite being below floor because price is extreme
        total_export = sum(s.grid_export_kwh for s in result.slots)
        assert total_export > 0.01


class TestExportFloorInactiveWhenDisabled:
    def test_inactive_when_enable_export_false(self):
        slots = _make_slots(2, export_price=50.0)
        input_data = KeplerInput(slots=slots, initial_soc_kwh=10.0)

        config = _base_config(
            export_floor=20.0, enable_export=False
        )
        result = KeplerSolver().solve(input_data, config)

        assert result.is_optimal
        for s in result.slots:
            assert s.grid_export_kwh == pytest.approx(0.0, abs=0.01)


class TestExportFloorInactiveWhenNone:
    def test_inactive_when_export_floor_none(self):
        slots = _make_slots(2, export_price=50.0)
        input_data = KeplerInput(slots=slots, initial_soc_kwh=5.0)

        config = _base_config(export_floor=None)
        result = KeplerSolver().solve(input_data, config)

        assert result.is_optimal
        # Should export even at low SoC since floor constraint is disabled
        total_export = sum(s.grid_export_kwh for s in result.slots)
        assert total_export > 0.01


class TestExportFloorPreservesMinSocForNonExport:
    def test_non_export_discharge_respects_min_soc_only(self):
        capacity = 34.2
        floor_pct = 20
        min_soc_pct = 5.0

        slots = _make_slots(2, export_price=0.0, load_kwh=2.0)  # load, no export price
        input_data = KeplerInput(slots=slots, initial_soc_kwh=capacity)

        config = _base_config(
            capacity=capacity,
            min_soc=min_soc_pct,
            export_floor=floor_pct,
        )
        result = KeplerSolver().solve(input_data, config)

        assert result.is_optimal
        min_soc_kwh = capacity * min_soc_pct / 100.0
        for s in result.slots:
            assert s.soc_kwh >= min_soc_kwh - 0.01


class TestExportFloorAdapterMapping:
    def test_export_floor_passed_through_adapter(self):
        from planner.solver.adapter import config_to_kepler_config

        planner_config = {
            "config_version": 2,
            "system": {
                "battery": {
                    "capacity_kwh": 34.2,
                    "min_soc_percent": 10.0,
                    "max_soc_percent": 100.0,
                    "max_charge_a": 185.0,
                    "max_discharge_a": 185.0,
                    "nominal_voltage_v": 48.0,
                    "charge_efficiency": 0.95,
                    "discharge_efficiency": 0.95,
                },
                "grid": {"max_power_kw": 11.0},
            },
            "export": {
                "enable_export": True,
                "export_floor_soc_percent": 25,
            },
            "battery_economics": {"battery_cycle_cost_kwh": 0.10},
            "executor": {"inverter": {"control_unit": "A"}},
        }

        kepler_cfg = config_to_kepler_config(planner_config)
        assert kepler_cfg.export_floor_soc_percent == 25.0
