"""excess-pv-priority-dispatch 2.8: EV surplus solver variables and priority ordering."""

from datetime import datetime, timedelta

from planner.solver.kepler import KeplerSolver
from planner.solver.types import (
    EVChargerInput,
    ExcessPVSinkEntry,
    IncentiveBucket,
    KeplerConfig,
    KeplerInput,
    KeplerInputSlot,
)


def _make_slots(
    n: int = 8,
    pv_kwh: float = 10.0,
    load_kwh: float = 1.0,
    export_price: float = 0.0,
    import_price: float = 1.0,
) -> list[KeplerInputSlot]:
    start = datetime(2025, 6, 1, 12, 0)
    return [
        KeplerInputSlot(
            start_time=start + timedelta(minutes=15 * i),
            end_time=start + timedelta(minutes=15 * (i + 1)),
            load_kwh=load_kwh,
            pv_kwh=pv_kwh,
            import_price_sek_kwh=import_price,
            export_price_sek_kwh=export_price,
        )
        for i in range(n)
    ]


def _ev_charger(
    id: str = "goe",
    max_power_kw: float = 7.4,
    plugged_in: bool = True,
    control_type: str = "current",
) -> EVChargerInput:
    return EVChargerInput(
        id=id,
        max_power_kw=max_power_kw,
        battery_capacity_kwh=60.0,
        current_soc_percent=50.0,
        plugged_in=plugged_in,
        deadline=None,
        control_type=control_type,
    )


def _ev_priority(charger_id: str, reward: float) -> ExcessPVSinkEntry:
    return ExcessPVSinkEntry(type="ev", effective_reward_sek_per_kwh=reward, charger_id=charger_id)


def _custom_entity_priority(reward: float, power_kw: float = 2.0) -> ExcessPVSinkEntry:
    return ExcessPVSinkEntry(
        type="custom_entity", effective_reward_sek_per_kwh=reward, power_kw=power_kw
    )


def _base_config(**overrides) -> dict:
    base = dict(
        capacity_kwh=10.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        wear_cost_sek_per_kwh=0.01,
        enable_export=True,
        max_export_power_kw=10.0,
    )
    base.update(overrides)
    return base


class TestEVSurplusGating:
    def test_no_surplus_when_soc_below_threshold(self):
        capacity = 10.0
        initial_soc = capacity * 0.50  # Well below the 95% threshold

        slots = _make_slots(n=4, pv_kwh=2.0, load_kwh=1.0, export_price=0.0)
        config = KeplerConfig(
            **_base_config(capacity_kwh=capacity),
            excess_pv_slots=[True] * 4,
            excess_pv_priority=[_ev_priority("goe", reward=2.0)],
            excess_pv_soc_threshold_percent=95.0,
            ev_chargers=[_ev_charger()],
        )
        result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=initial_soc), config)
        assert result.is_optimal

        for s in result.slots:
            assert s.ev_surplus_kw.get("goe", 0.0) == 0.0, (
                "EV surplus must not activate while SoC is below the threshold"
            )

    def test_no_surplus_when_excess_flag_false(self):
        capacity = 10.0
        initial_soc = capacity * 0.97  # Above threshold

        slots = _make_slots(n=4, pv_kwh=0.0, load_kwh=1.0, export_price=0.0)
        config = KeplerConfig(
            **_base_config(capacity_kwh=capacity),
            excess_pv_slots=[False] * 4,
            excess_pv_priority=[_ev_priority("goe", reward=2.0)],
            excess_pv_soc_threshold_percent=95.0,
            ev_chargers=[_ev_charger()],
        )
        result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=initial_soc), config)
        assert result.is_optimal

        for s in result.slots:
            assert s.ev_surplus_kw.get("goe", 0.0) == 0.0, (
                "EV surplus must not activate when the excess-PV flag is False"
            )

    def test_surplus_allocated_when_soc_above_threshold_and_flag_true(self):
        capacity = 10.0
        initial_soc = capacity * 0.97

        # Low export price + high reward -> solver should prefer EV surplus over export.
        slots = _make_slots(n=8, pv_kwh=10.0, load_kwh=1.0, export_price=0.05)
        config = KeplerConfig(
            **_base_config(capacity_kwh=capacity),
            excess_pv_slots=[True] * 8,
            excess_pv_priority=[_ev_priority("goe", reward=2.0)],
            excess_pv_soc_threshold_percent=95.0,
            ev_chargers=[_ev_charger()],
        )
        result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=initial_soc), config)
        assert result.is_optimal

        total_surplus = sum(s.ev_surplus_kw.get("goe", 0.0) for s in result.slots)
        assert total_surplus > 0, "EV surplus should activate once SoC clears the threshold"


class TestEVSurplusPriorityOrdering:
    def test_scarce_surplus_goes_to_rank_zero_only(self):
        """With scarce surplus, the higher-priority (rank 0) sink absorbs it all;
        the lower-priority sink stays untouched."""
        capacity = 10.0
        initial_soc = capacity * 0.97

        # PV=1.2, load=1.0 -> ~0.2 kWh scarce surplus per slot (~0.8 kW average)
        slots = _make_slots(n=8, pv_kwh=1.2, load_kwh=1.0, export_price=0.05)
        config = KeplerConfig(
            **_base_config(capacity_kwh=capacity),
            excess_pv_slots=[True] * 8,
            excess_pv_priority=[
                _ev_priority("primary", reward=2.0),
                _ev_priority("secondary", reward=1.0),
            ],
            excess_pv_soc_threshold_percent=95.0,
            ev_chargers=[
                _ev_charger(id="primary", max_power_kw=7.4),
                _ev_charger(id="secondary", max_power_kw=7.4),
            ],
        )
        result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=initial_soc), config)
        assert result.is_optimal

        primary_total = sum(s.ev_surplus_kw.get("primary", 0.0) for s in result.slots)
        secondary_total = sum(s.ev_surplus_kw.get("secondary", 0.0) for s in result.slots)
        assert primary_total > 0, "Rank-0 sink should absorb the scarce surplus"
        assert secondary_total == 0, "Rank-1 sink should stay idle while surplus is scarce"

    def test_abundant_surplus_activates_two_sinks(self):
        """With abundant surplus exceeding the rank-0 charger's max power, the
        overflow spills into the rank-1 sink."""
        capacity = 10.0
        initial_soc = capacity * 0.97

        # PV=12, load=1.0 -> 11 kWh abundant surplus per slot (44 kW average),
        # far exceeding either charger's 7.4kW cap.
        slots = _make_slots(n=8, pv_kwh=12.0, load_kwh=1.0, export_price=0.05)
        config = KeplerConfig(
            **_base_config(capacity_kwh=capacity, max_charge_power_kw=1.0),
            excess_pv_slots=[True] * 8,
            excess_pv_priority=[
                _ev_priority("primary", reward=2.0),
                _ev_priority("secondary", reward=1.0),
            ],
            excess_pv_soc_threshold_percent=95.0,
            ev_chargers=[
                _ev_charger(id="primary", max_power_kw=7.4),
                _ev_charger(id="secondary", max_power_kw=7.4),
            ],
        )
        result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=initial_soc), config)
        assert result.is_optimal

        primary_total = sum(s.ev_surplus_kw.get("primary", 0.0) for s in result.slots)
        secondary_total = sum(s.ev_surplus_kw.get("secondary", 0.0) for s in result.slots)
        assert primary_total > 0
        assert secondary_total > 0, "Abundant surplus should spill into the rank-1 sink too"


class TestEVSurplusExclusivity:
    def test_no_slot_has_both_scheduled_charge_and_surplus(self):
        capacity = 10.0
        initial_soc = capacity * 0.97

        slots = _make_slots(n=8, pv_kwh=10.0, load_kwh=1.0, export_price=0.05, import_price=0.01)
        config = KeplerConfig(
            **_base_config(capacity_kwh=capacity),
            excess_pv_slots=[True] * 8,
            excess_pv_priority=[_ev_priority("goe", reward=2.0)],
            excess_pv_soc_threshold_percent=95.0,
            ev_chargers=[
                EVChargerInput(
                    id="goe",
                    max_power_kw=7.4,
                    battery_capacity_kwh=60.0,
                    current_soc_percent=10.0,
                    plugged_in=True,
                    deadline=None,
                    control_type="current",
                    # Strong incentive to charge on the cheap-import schedule too,
                    # so the solver is tempted to combine scheduled + surplus charging.
                    incentive_buckets=[IncentiveBucket(threshold_soc=90.0, value_sek=5.0)],
                )
            ],
        )
        result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=initial_soc), config)
        assert result.is_optimal

        for i, s in enumerate(result.slots):
            scheduled_kw = s.ev_charger_results.get("goe", 0.0)
            surplus_kw = s.ev_surplus_kw.get("goe", 0.0)
            assert not (scheduled_kw > 0.01 and surplus_kw > 0.01), (
                f"Slot {i} has both scheduled charging ({scheduled_kw} kW) and "
                f"surplus charging ({surplus_kw} kW) — exclusivity violated"
            )


class TestEVSurplusChargerFiltering:
    def test_unplugged_charger_produces_no_surplus(self):
        capacity = 10.0
        initial_soc = capacity * 0.97

        slots = _make_slots(n=4, pv_kwh=10.0, load_kwh=1.0, export_price=0.05)
        config = KeplerConfig(
            **_base_config(capacity_kwh=capacity),
            excess_pv_slots=[True] * 4,
            excess_pv_priority=[_ev_priority("goe", reward=2.0)],
            excess_pv_soc_threshold_percent=95.0,
            ev_chargers=[_ev_charger(plugged_in=False)],
        )
        result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=initial_soc), config)
        assert result.is_optimal

        for s in result.slots:
            assert "goe" not in s.ev_surplus_kw

    def test_binary_type_charger_produces_no_surplus(self):
        capacity = 10.0
        initial_soc = capacity * 0.97

        slots = _make_slots(n=4, pv_kwh=10.0, load_kwh=1.0, export_price=0.05)
        config = KeplerConfig(
            **_base_config(capacity_kwh=capacity),
            excess_pv_slots=[True] * 4,
            excess_pv_priority=[_ev_priority("goe", reward=2.0)],
            excess_pv_soc_threshold_percent=95.0,
            ev_chargers=[_ev_charger(control_type="binary")],
        )
        result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=initial_soc), config)
        assert result.is_optimal

        for s in result.slots:
            assert "goe" not in s.ev_surplus_kw


class TestEmptyPriorityList:
    def test_empty_priority_list_produces_no_sink_variables(self):
        capacity = 10.0
        initial_soc = capacity * 0.97

        slots = _make_slots(n=4, pv_kwh=10.0, load_kwh=1.0, export_price=0.05)
        config = KeplerConfig(
            **_base_config(capacity_kwh=capacity),
            excess_pv_slots=[True] * 4,
            excess_pv_priority=[],
            excess_pv_soc_threshold_percent=95.0,
            ev_chargers=[_ev_charger()],
        )
        result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=initial_soc), config)
        assert result.is_optimal

        for s in result.slots:
            assert s.ev_surplus_kw == {}
            assert s.custom_entity_active == {}
            assert s.water_heating_boost == {}


class TestMultipleCustomEntities:
    def test_two_custom_entities_are_independent(self):
        capacity = 10.0
        initial_soc = capacity * 0.97

        # Scarce, exportable surplus (2 kWh/slot < the 2.5 kWh export cap) so
        # activating a sink has a real opportunity cost (foregone export revenue).
        slots = _make_slots(n=8, pv_kwh=3.0, load_kwh=1.0, export_price=0.5)
        config = KeplerConfig(
            **_base_config(capacity_kwh=capacity),
            excess_pv_slots=[True] * 8,
            excess_pv_priority=[
                _custom_entity_priority(reward=0.1, power_kw=2.0),  # rank 0: too weak to activate
                _custom_entity_priority(reward=5.0, power_kw=2.0),  # rank 1: strong reward
            ],
            excess_pv_soc_threshold_percent=95.0,
        )
        result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=initial_soc), config)
        assert result.is_optimal

        for s in result.slots:
            assert set(s.custom_entity_active.keys()) == {"0", "1"}

        rank0_active = sum(1 for s in result.slots if s.custom_entity_active["0"])
        rank1_active = sum(1 for s in result.slots if s.custom_entity_active["1"])
        assert rank0_active == 0, "Weak-reward entry should not activate"
        assert rank1_active > 0, "Strong-reward entry should activate independently"


class TestEVSurplusScheduleOutput:
    def test_ev_surplus_kw_keyed_by_charger_id(self):
        capacity = 10.0
        initial_soc = capacity * 0.97

        slots = _make_slots(n=4, pv_kwh=10.0, load_kwh=1.0, export_price=0.05)
        config = KeplerConfig(
            **_base_config(capacity_kwh=capacity),
            excess_pv_slots=[True] * 4,
            excess_pv_priority=[_ev_priority("main_ev", reward=2.0)],
            excess_pv_soc_threshold_percent=95.0,
            ev_chargers=[_ev_charger(id="main_ev", max_power_kw=7.4)],
        )
        result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=initial_soc), config)
        assert result.is_optimal

        for s in result.slots:
            assert "main_ev" in s.ev_surplus_kw
            assert s.ev_surplus_kw["main_ev"] >= 0.0
            assert s.ev_surplus_kw["main_ev"] <= 7.4 + 1e-6
