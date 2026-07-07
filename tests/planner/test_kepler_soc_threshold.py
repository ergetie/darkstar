from datetime import datetime, timedelta

from planner.solver.kepler import KeplerSolver
from planner.solver.types import (
    ExcessPVSinkEntry,
    KeplerConfig,
    KeplerInput,
    KeplerInputSlot,
    WaterHeaterInput,
)


def _boost_priority(reward: float) -> list[ExcessPVSinkEntry]:
    return [ExcessPVSinkEntry(type="water_heater_boost", effective_reward_sek_per_kwh=reward)]


def _custom_entity_priority(reward: float, power_kw: float) -> list[ExcessPVSinkEntry]:
    return [
        ExcessPVSinkEntry(
            type="custom_entity", effective_reward_sek_per_kwh=reward, power_kw=power_kw
        )
    ]


def _custom_entity_active(slot) -> bool:
    """A slot's custom_entity_active is now a dict keyed by priority-list rank."""
    return any(slot.custom_entity_active.values())


def _wh(id: str = "wh1", power_kw: float = 3.0, min_kwh_per_day: float = 0.0):
    return WaterHeaterInput(
        id=id,
        power_kw=power_kw,
        min_kwh_per_day=min_kwh_per_day,
        max_hours_between_heating=24.0,
        min_spacing_hours=0.0,
        heated_today_kwh=0.0,
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


class TestSoCThresholdBoost:
    def test_no_boost_when_soc_never_reaches_threshold(self):
        capacity = 10.0
        initial_soc = capacity * 0.50

        slots = _make_slots(n=4, pv_kwh=2.0, load_kwh=1.5, export_price=0.0)
        config = KeplerConfig(
            capacity_kwh=capacity,
            max_charge_power_kw=5.0,
            max_discharge_power_kw=5.0,
            charge_efficiency=1.0,
            discharge_efficiency=1.0,
            min_soc_percent=0.0,
            max_soc_percent=100.0,
            wear_cost_sek_per_kwh=0.01,
            excess_pv_slots=[True] * 4,
            excess_pv_priority=_boost_priority(reward=2.0),
            excess_pv_soc_threshold_percent=95.0,
            water_heaters=[_wh()],
        )
        input_data = KeplerInput(slots=slots, initial_soc_kwh=initial_soc)

        result = KeplerSolver().solve(input_data, config)
        assert result.is_optimal

        for i, s in enumerate(result.slots):
            assert s.water_heating_boost == {}, (
                f"Boost should NOT activate in slot {i} — SoC starts at 50% and "
                f"cannot reach 95% in 4 slots with only 0.5 kWh excess/slot. "
                f"Got boost={s.water_heating_boost} with SoC={s.soc_kwh:.2f}"
            )

    def test_boost_activates_when_soc_already_above_threshold(self):
        capacity = 10.0
        initial_soc = capacity * 0.96

        slots = _make_slots(n=8, pv_kwh=10.0, load_kwh=1.0, export_price=0.0)
        config = KeplerConfig(
            capacity_kwh=capacity,
            max_charge_power_kw=5.0,
            max_discharge_power_kw=5.0,
            charge_efficiency=1.0,
            discharge_efficiency=1.0,
            min_soc_percent=0.0,
            max_soc_percent=100.0,
            wear_cost_sek_per_kwh=0.01,
            excess_pv_slots=[True] * 8,
            excess_pv_priority=_boost_priority(reward=2.0),
            excess_pv_soc_threshold_percent=95.0,
            water_heaters=[_wh()],
        )
        input_data = KeplerInput(slots=slots, initial_soc_kwh=initial_soc)

        result = KeplerSolver().solve(input_data, config)
        assert result.is_optimal

        boost_slots = [s for s in result.slots if s.water_heating_boost.get("wh1", False)]
        assert len(boost_slots) > 0, (
            "Boost should activate when SoC starts at 96% (above 95% threshold), "
            "excess PV is available, and reward (2.0) exceeds export price (0.0)"
        )

    def test_configurable_threshold_lower_enables_earlier_activation(self):
        capacity = 10.0
        initial_soc = capacity * 0.88

        slots = _make_slots(n=8, pv_kwh=10.0, load_kwh=1.0, export_price=0.0)
        config = KeplerConfig(
            capacity_kwh=capacity,
            max_charge_power_kw=5.0,
            max_discharge_power_kw=5.0,
            charge_efficiency=1.0,
            discharge_efficiency=1.0,
            min_soc_percent=0.0,
            max_soc_percent=100.0,
            wear_cost_sek_per_kwh=0.01,
            excess_pv_slots=[True] * 8,
            excess_pv_priority=_boost_priority(reward=2.0),
            excess_pv_soc_threshold_percent=85.0,
            water_heaters=[_wh()],
        )
        input_data = KeplerInput(slots=slots, initial_soc_kwh=initial_soc)

        result = KeplerSolver().solve(input_data, config)
        assert result.is_optimal

        boost_slots = [s for s in result.slots if s.water_heating_boost.get("wh1", False)]
        assert len(boost_slots) > 0, (
            "Boost should activate at 88% SoC when threshold is lowered to 85%"
        )


class TestSoCThresholdCustomEntity:
    def test_no_custom_entity_when_soc_never_reaches_threshold(self):
        capacity = 10.0
        initial_soc = capacity * 0.50

        slots = _make_slots(n=4, pv_kwh=2.0, load_kwh=1.5, export_price=0.0)
        config = KeplerConfig(
            capacity_kwh=capacity,
            max_charge_power_kw=5.0,
            max_discharge_power_kw=5.0,
            charge_efficiency=1.0,
            discharge_efficiency=1.0,
            min_soc_percent=0.0,
            max_soc_percent=100.0,
            wear_cost_sek_per_kwh=0.01,
            excess_pv_slots=[True] * 4,
            excess_pv_priority=_custom_entity_priority(reward=2.0, power_kw=2.0),
            excess_pv_soc_threshold_percent=95.0,
        )
        input_data = KeplerInput(slots=slots, initial_soc_kwh=initial_soc)

        result = KeplerSolver().solve(input_data, config)
        assert result.is_optimal

        for i, s in enumerate(result.slots):
            assert not _custom_entity_active(s), (
                f"Custom entity should NOT activate in slot {i} — SoC starts at 50% "
                f"and cannot reach 95%. Got custom_entity_active={s.custom_entity_active}"
            )

    def test_custom_entity_activates_above_threshold(self):
        capacity = 10.0
        initial_soc = capacity * 0.96

        slots = _make_slots(n=8, pv_kwh=10.0, load_kwh=1.0, export_price=0.0)
        config = KeplerConfig(
            capacity_kwh=capacity,
            max_charge_power_kw=5.0,
            max_discharge_power_kw=5.0,
            charge_efficiency=1.0,
            discharge_efficiency=1.0,
            min_soc_percent=0.0,
            max_soc_percent=100.0,
            wear_cost_sek_per_kwh=0.01,
            excess_pv_slots=[True] * 8,
            excess_pv_priority=_custom_entity_priority(reward=2.0, power_kw=2.0),
            excess_pv_soc_threshold_percent=95.0,
        )
        input_data = KeplerInput(slots=slots, initial_soc_kwh=initial_soc)

        result = KeplerSolver().solve(input_data, config)
        assert result.is_optimal

        active_slots = [s for s in result.slots if _custom_entity_active(s)]
        assert len(active_slots) > 0, (
            "Custom entity should activate when SoC starts at 96% (above 95% threshold)"
        )

    def test_custom_entity_blocked_by_excess_pv_flag(self):
        capacity = 10.0
        initial_soc = capacity * 0.96

        slots = _make_slots(n=8, pv_kwh=0.0, load_kwh=1.0, export_price=0.0)
        config = KeplerConfig(
            capacity_kwh=capacity,
            max_charge_power_kw=5.0,
            max_discharge_power_kw=5.0,
            charge_efficiency=1.0,
            discharge_efficiency=1.0,
            min_soc_percent=0.0,
            max_soc_percent=100.0,
            wear_cost_sek_per_kwh=0.01,
            excess_pv_slots=[False] * 8,
            excess_pv_priority=_custom_entity_priority(reward=2.0, power_kw=2.0),
            excess_pv_soc_threshold_percent=95.0,
        )
        input_data = KeplerInput(slots=slots, initial_soc_kwh=initial_soc)

        result = KeplerSolver().solve(input_data, config)
        assert result.is_optimal

        for s in result.slots:
            assert not _custom_entity_active(s), (
                "Custom entity should NOT activate when excess PV flag is False"
            )

    def test_sink_only_activates_after_soc_crosses_threshold(self):
        capacity = 10.0
        initial_soc = capacity * 0.80

        slots = _make_slots(n=12, pv_kwh=10.0, load_kwh=1.0, export_price=0.0)
        config = KeplerConfig(
            capacity_kwh=capacity,
            max_charge_power_kw=5.0,
            max_discharge_power_kw=5.0,
            charge_efficiency=1.0,
            discharge_efficiency=1.0,
            min_soc_percent=0.0,
            max_soc_percent=100.0,
            wear_cost_sek_per_kwh=0.01,
            excess_pv_slots=[True] * 12,
            excess_pv_priority=_custom_entity_priority(reward=2.0, power_kw=2.0),
            excess_pv_soc_threshold_percent=95.0,
        )
        input_data = KeplerInput(slots=slots, initial_soc_kwh=initial_soc)

        result = KeplerSolver().solve(input_data, config)
        assert result.is_optimal

        threshold_kwh = capacity * 0.95
        below_threshold_slots = [
            (i, s) for i, s in enumerate(result.slots) if s.soc_kwh < threshold_kwh
        ]
        for i, s in below_threshold_slots:
            assert not _custom_entity_active(s), (
                f"Custom entity should NOT activate in slot {i} where SoC "
                f"({s.soc_kwh:.2f} kWh) is below threshold ({threshold_kwh:.2f} kWh)"
            )
