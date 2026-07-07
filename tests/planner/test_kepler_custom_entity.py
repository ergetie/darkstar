from datetime import datetime, timedelta

from planner.solver.kepler import KeplerSolver
from planner.solver.types import (
    ExcessPVSinkEntry,
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


def _custom_entity_priority(reward: float, power_kw: float) -> list[ExcessPVSinkEntry]:
    return [
        ExcessPVSinkEntry(
            type="custom_entity",
            effective_reward_sek_per_kwh=reward,
            power_kw=power_kw,
        )
    ]


def _custom_entity_active(slot) -> bool:
    """A slot's custom_entity_active is now a dict keyed by priority-list rank."""
    return any(slot.custom_entity_active.values())


class TestCustomEntitySolverVariable:
    def test_solver_prefers_export_when_reward_is_low(self):
        """With high SoC target penalty, solver won't discharge for export.
        Entity activation then directly competes with export for surplus PV."""
        capacity = 10.0
        initial_soc = capacity * 0.97

        # PV=3.0, load=1.0 → 2.0 kWh surplus per slot
        # Without entity: export 2.0 kWh @ 5.0 = 10.0 SEK/slot
        # With entity: export 1.5 kWh @ 5.0 + reward 0.5*2.0*0.25 = 7.5 + 0.25 = 7.75 SEK
        # Solver should NOT activate entity
        slots = _make_slots(n=8, pv_kwh=3.0, load_kwh=1.0, export_price=5.0)

        config = KeplerConfig(
            capacity_kwh=capacity,
            max_charge_power_kw=5.0,
            max_discharge_power_kw=5.0,
            charge_efficiency=1.0,
            discharge_efficiency=1.0,
            min_soc_percent=0.0,
            max_soc_percent=100.0,
            wear_cost_sek_per_kwh=0.01,
            enable_export=True,
            max_export_power_kw=10.0,
            target_soc_kwh=initial_soc,
            target_soc_penalty_sek=1000.0,
            excess_pv_slots=[True] * 8,
            excess_pv_priority=_custom_entity_priority(reward=0.5, power_kw=2.0),
            excess_pv_soc_threshold_percent=95.0,
        )
        input_data = KeplerInput(slots=slots, initial_soc_kwh=initial_soc)

        result = KeplerSolver().solve(input_data, config)
        assert result.is_optimal

        for s in result.slots:
            assert not _custom_entity_active(s), (
                f"Custom entity should NOT activate — it costs 0.5 kWh export revenue "
                f"(2.5 SEK) for only 0.25 SEK reward."
            )

    def test_solver_activates_entity_when_reward_exceeds_export(self):
        """Same scenario but reward >> export price. Solver activates entity."""
        capacity = 10.0
        initial_soc = capacity * 0.97

        slots = _make_slots(n=8, pv_kwh=3.0, load_kwh=1.0, export_price=0.1)

        config = KeplerConfig(
            capacity_kwh=capacity,
            max_charge_power_kw=5.0,
            max_discharge_power_kw=5.0,
            charge_efficiency=1.0,
            discharge_efficiency=1.0,
            min_soc_percent=0.0,
            max_soc_percent=100.0,
            wear_cost_sek_per_kwh=0.01,
            enable_export=True,
            max_export_power_kw=10.0,
            target_soc_kwh=initial_soc,
            target_soc_penalty_sek=1000.0,
            excess_pv_slots=[True] * 8,
            excess_pv_priority=_custom_entity_priority(reward=2.0, power_kw=2.0),
            excess_pv_soc_threshold_percent=95.0,
        )
        input_data = KeplerInput(slots=slots, initial_soc_kwh=initial_soc)

        result = KeplerSolver().solve(input_data, config)
        assert result.is_optimal

        active_slots = [s for s in result.slots if _custom_entity_active(s)]
        assert len(active_slots) > 0, (
            "Custom entity should activate when reward (2.0) >> export price (0.1)"
        )

    def test_custom_entity_power_kw_sizes_reward(self):
        capacity = 10.0
        initial_soc = capacity * 0.97

        slots = _make_slots(n=8, pv_kwh=3.0, load_kwh=1.0, export_price=0.5)

        base_kwargs = dict(
            capacity_kwh=capacity,
            max_charge_power_kw=5.0,
            max_discharge_power_kw=5.0,
            charge_efficiency=1.0,
            discharge_efficiency=1.0,
            min_soc_percent=0.0,
            max_soc_percent=100.0,
            wear_cost_sek_per_kwh=0.01,
            enable_export=True,
            max_export_power_kw=10.0,
            target_soc_kwh=initial_soc,
            target_soc_penalty_sek=1000.0,
            excess_pv_slots=[True] * 8,
            excess_pv_soc_threshold_percent=95.0,
        )

        config_high = KeplerConfig(
            **base_kwargs,
            excess_pv_priority=_custom_entity_priority(reward=1.0, power_kw=5.0),
        )
        config_low = KeplerConfig(
            **base_kwargs,
            excess_pv_priority=_custom_entity_priority(reward=1.0, power_kw=0.1),
        )

        input_data = KeplerInput(slots=slots, initial_soc_kwh=initial_soc)

        result_high = KeplerSolver().solve(input_data, config_high)
        result_low = KeplerSolver().solve(input_data, config_low)

        assert result_high.is_optimal
        assert result_low.is_optimal

        high_active = sum(1 for s in result_high.slots if _custom_entity_active(s))
        low_active = sum(1 for s in result_low.slots if _custom_entity_active(s))
        assert high_active >= low_active, (
            f"Higher power_kw should produce equal or more activation slots. "
            f"Got high_power active={high_active}, low_power active={low_active}"
        )
