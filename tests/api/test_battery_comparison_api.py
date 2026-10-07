from __future__ import annotations

import json
from datetime import UTC, datetime, time as datetime_time, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
import pytz

from backend.api.routers.energy import get_cost_series
from backend.battery_comparison import BatteryModel, CalibrationResult, FitDiagnostics, GridModel
from backend.learning.models import Base, SlotObservation
from backend.learning.store import LearningStore
from backend.measurement_provenance import ENERGY_SEMANTICS, boundary_fingerprint

TZ = pytz.timezone("Europe/Stockholm")
CONFIG = {
    "timezone": "Europe/Stockholm",
    "system": {
        "has_battery": True,
        "battery": {
            "capacity_kwh": 10.0,
            "min_soc_percent": 10,
            "max_soc_percent": 95,
            "max_charge_w": 2000,
            "max_discharge_w": 2000,
            "charge_efficiency": 0.95,
            "discharge_efficiency": 0.95,
        },
    },
    "battery_economics": {"battery_cycle_cost_kwh": 0.2},
}
DIAGNOSTICS = FitDiagnostics(
    GridModel(0.8, 0.9),
    BatteryModel(0.92, 0.9),
    960,
    240,
    200,
    50,
    "2026-09-01T00:00:00+00:00",
    "2026-09-20T00:00:00+00:00",
    "2026-09-20T00:15:00+00:00",
    "2026-09-30T00:00:00+00:00",
    0.1,
    0.0,
    0.1,
    0.0,
    0.0,
    10.0,
)


def trusted_flags(config: dict = CONFIG) -> str:
    return json.dumps(
        {
            "source": "recorder",
            "recording": {
                "schema_version": 1,
                "semantics": ENERGY_SEMANTICS,
                "boundary_fingerprint": boundary_fingerprint(config),
                "algorithm": "power-history-step-zoh-v1",
                "components": {
                    name: {"method": "power_history", "owner": "recorder"}
                    for name in (
                        "import",
                        "export",
                        "pv",
                        "load",
                        "water",
                        "ev",
                        "battery_charge",
                        "battery_discharge",
                    )
                },
                "soc": {"source": "live", "owner": "recorder"},
            },
        }
    )


@pytest_asyncio.fixture
async def store(tmp_path):
    value = LearningStore(str(tmp_path / "comparison-api.db"), TZ)
    async with value.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield value
    await value.close()


async def seed_yesterday(
    store: LearningStore,
    count: int = 96,
    *,
    first_soc: float | None = 50.0,
    legacy_unknown: bool = False,
):
    start = TZ.localize(
        datetime.combine(datetime.now(TZ).date() - timedelta(days=1), datetime.min.time())
    )
    async with store.AsyncSession() as session:
        for index in range(count):
            slot = TZ.normalize(start + timedelta(minutes=15 * index))
            session.add(
                SlotObservation(
                    slot_start=slot.isoformat(),
                    slot_end=(slot + timedelta(minutes=15)).isoformat(),
                    import_kwh=0.0,
                    export_kwh=0.0,
                    import_price_sek_kwh=2.0,
                    export_price_sek_kwh=1.0,
                    pv_kwh=1.0,
                    load_kwh=0.8,
                    water_kwh=0.0,
                    ev_charging_kwh=0.0,
                    batt_charge_kwh=0.0,
                    batt_discharge_kwh=0.0,
                    soc_start_percent=first_soc if index == 0 else 50.0,
                    soc_end_percent=50.0,
                    quality_flags=(
                        json.dumps({"source": "recorder"}) if legacy_unknown else trusted_flags()
                    ),
                )
            )
        await session.commit()


@pytest.mark.asyncio
async def test_configured_estimate_is_shown_before_calibration_and_keeps_metered_fields(store):
    await seed_yesterday(store, legacy_unknown=True)
    with patch("backend.api.routers.energy.load_yaml", return_value=CONFIG):
        result = await get_cost_series(period="yesterday", store=store)
    comparison = result["battery_comparison"]
    assert comparison["status"] == "estimated"
    assert comparison["basis"] == "configured_losses"
    assert comparison["calibration_status"] == "insufficient_data"
    assert comparison["calibration_reason"] == "unverified_history"
    assert "calibration" not in comparison
    assert "saving_sek" in comparison
    assert result["baseline"] is not None
    assert result["points"][-1]["cumulative_net_cost_sek"] == 0.0
    assert "baseline_cumulative_net_cost_sek" in result["points"][-1]


@pytest.mark.asyncio
async def test_unreliable_fit_keeps_real_diagnostics_beside_estimate(store):
    await seed_yesterday(store)
    fit = CalibrationResult("unreliable_model", "holdout_validation_failed", DIAGNOSTICS)
    with (
        patch("backend.api.routers.energy.load_yaml", return_value=CONFIG),
        patch("backend.api.routers.energy._calibrated_fit", new=AsyncMock(return_value=fit)),
    ):
        result = await get_cost_series(period="yesterday", store=store)
    comparison = result["battery_comparison"]
    assert comparison["status"] == "estimated"
    assert comparison["basis"] == "configured_losses"
    assert comparison["calibration_status"] == "unreliable_model"
    assert comparison["calibration_reason"] == "holdout_validation_failed"
    assert comparison["calibration"]["grid_rmse_kwh"] == pytest.approx(0.1)
    assert "saving_sek" in comparison and "points" in comparison


@pytest.mark.asyncio
async def test_available_api_comparison_reconciles_summaries_and_points(store):
    await seed_yesterday(store)
    fit = CalibrationResult("available", "validated", DIAGNOSTICS)
    with (
        patch("backend.api.routers.energy.load_yaml", return_value=CONFIG),
        patch("backend.api.routers.energy._calibrated_fit", new=AsyncMock(return_value=fit)),
    ):
        result = await get_cost_series(period="yesterday", store=store)
    comparison = result["battery_comparison"]
    assert comparison["status"] == "available"
    assert comparison["basis"] == "calibrated"
    assert comparison["label"] == "Verified"
    assert "saving_sek" in comparison and comparison["points"]
    assert comparison["darkstar"]["comparison_cost_sek"] == pytest.approx(0)
    assert comparison["self_use"]["comparison_cost_sek"] == pytest.approx(0)
    assert comparison["saving_sek"] == pytest.approx(0)
    assert comparison["points"][-1]["darkstar_cumulative_comparison_cost_sek"] == pytest.approx(
        comparison["darkstar"]["comparison_cost_sek"]
    )
    assert comparison["points"][-1]["self_use_cumulative_comparison_cost_sek"] == pytest.approx(
        comparison["self_use"]["comparison_cost_sek"]
    )
    assert result["points"][-1]["cumulative_net_cost_sek"] == 0


@pytest.mark.asyncio
async def test_missing_initial_soc_drops_first_slot_and_falls_back_to_estimate(store):
    await seed_yesterday(store, first_soc=None)
    fit = CalibrationResult("available", "validated", DIAGNOSTICS)
    with (
        patch("backend.api.routers.energy.load_yaml", return_value=CONFIG),
        patch("backend.api.routers.energy._calibrated_fit", new=AsyncMock(return_value=fit)),
    ):
        result = await get_cost_series(period="yesterday", store=store)
    comparison = result["battery_comparison"]
    # The first slot has no real start SoC: it is dropped and the run starts from its
    # measured end SoC. The calibrated path is not used for a partially covered period.
    assert comparison["status"] == "estimated"
    assert comparison["basis"] == "configured_losses"
    assert comparison["coverage"] == {
        "covered_slots": 95,
        "total_slots": 96,
        "excluded_slots": 1,
    }
    assert "saving_sek" in comparison


@pytest.mark.asyncio
async def test_missing_bucket_end_soc_slot_is_excluded_not_fatal(store):
    await seed_yesterday(store)
    async with store.AsyncSession() as session:
        slot = TZ.localize(
            datetime.combine(datetime.now(TZ).date() - timedelta(days=1), datetime.min.time())
        )
        row = await session.get(SlotObservation, slot.isoformat())
        assert row is not None
        row.soc_end_percent = None
        await session.commit()
    fit = CalibrationResult("available", "validated", DIAGNOSTICS)
    with (
        patch("backend.api.routers.energy.load_yaml", return_value=CONFIG),
        patch("backend.api.routers.energy._calibrated_fit", new=AsyncMock(return_value=fit)),
    ):
        result = await get_cost_series(period="yesterday", store=store)
    comparison = result["battery_comparison"]
    assert comparison["status"] == "estimated"
    assert comparison["coverage"]["excluded_slots"] == 1
    assert comparison["coverage"]["covered_slots"] == 95


@pytest.mark.asyncio
async def test_current_started_slot_stays_metered_but_is_excluded_from_comparison(store):
    today = TZ.localize(datetime.combine(datetime.now(TZ).date(), datetime_time.min))
    async with store.AsyncSession() as session:
        for index in range(49):
            slot = TZ.normalize(today + timedelta(minutes=15 * index))
            session.add(
                SlotObservation(
                    slot_start=slot.isoformat(),
                    slot_end=(slot + timedelta(minutes=15)).isoformat(),
                    import_kwh=0.0,
                    export_kwh=0.0,
                    import_price_sek_kwh=2.0,
                    export_price_sek_kwh=1.0,
                    pv_kwh=1.0,
                    load_kwh=0.8,
                    water_kwh=0.0,
                    ev_charging_kwh=0.0,
                    batt_charge_kwh=0.0,
                    batt_discharge_kwh=0.0,
                    soc_start_percent=50.0,
                    soc_end_percent=50.0,
                    quality_flags=trusted_flags(),
                )
            )
        await session.commit()
    fixed_local = TZ.localize(datetime.combine(today.date(), datetime_time(12, 7)))

    class FixedNow(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_local if tz is None else fixed_local.astimezone(tz)

    fit = CalibrationResult("available", "validated", DIAGNOSTICS)
    with (
        patch("backend.api.routers.energy.datetime", FixedNow),
        patch("backend.api.routers.energy.load_yaml", return_value=CONFIG),
        patch("backend.api.routers.energy._calibrated_fit", new=AsyncMock(return_value=fit)),
    ):
        result = await get_cost_series(period="today", store=store)
    comparison = result["battery_comparison"]
    assert comparison["status"] == "available"
    assert comparison["through"] == (today + timedelta(hours=12)).astimezone(UTC).isoformat()
    assert len(comparison["points"]) == 12
    assert result["points"][-1]["start"].startswith(today.strftime("%Y-%m-%dT12:00"))


@pytest.mark.asyncio
@pytest.mark.parametrize("day,count", [("2026-03-29", 92), ("2026-10-25", 100)])
async def test_completed_dst_day_uses_local_midnight_and_elapsed_slots(store, day, count):
    from backend.api.routers import energy

    start = TZ.localize(datetime.fromisoformat(day))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 27, 12, tzinfo=UTC).astimezone(tz)

    async with store.AsyncSession() as session:
        for index in range(count):
            slot = TZ.normalize(start + timedelta(minutes=15 * index))
            session.add(
                SlotObservation(
                    slot_start=slot.isoformat(),
                    slot_end=(slot + timedelta(minutes=15)).isoformat(),
                    import_kwh=0,
                    export_kwh=0,
                    import_price_sek_kwh=2,
                    export_price_sek_kwh=1,
                    pv_kwh=1,
                    load_kwh=0.8,
                    water_kwh=0,
                    ev_charging_kwh=0,
                    batt_charge_kwh=0,
                    batt_discharge_kwh=0,
                    soc_start_percent=50,
                    soc_end_percent=50,
                    quality_flags=trusted_flags(),
                )
            )
        await session.commit()
    fit = CalibrationResult("available", "validated", DIAGNOSTICS)
    with (
        patch.object(energy, "datetime", Clock),
        patch.object(energy, "load_yaml", return_value=CONFIG),
        patch.object(energy, "_calibrated_fit", new=AsyncMock(return_value=fit)),
    ):
        result = await get_cost_series(period="custom", start_date=day, end_date=day, store=store)
    comparison = result["battery_comparison"]
    assert comparison["status"] == "available"
    next_day = TZ.localize(datetime.fromisoformat(day) + timedelta(days=1))
    assert datetime.fromisoformat(comparison["through"]) == next_day
    assert len(comparison["points"]) == count // 4
    previous_day = datetime.fromisoformat(day) - timedelta(days=1)
    previous_start = TZ.localize(previous_day)
    async with store.AsyncSession() as session:
        for index in range(96):
            slot = previous_start + timedelta(minutes=15 * index)
            session.add(
                SlotObservation(
                    slot_start=slot.isoformat(),
                    slot_end=(slot + timedelta(minutes=15)).isoformat(),
                    import_kwh=0,
                    export_kwh=0,
                    import_price_sek_kwh=2,
                    export_price_sek_kwh=1,
                    pv_kwh=1,
                    load_kwh=0.8,
                    water_kwh=0,
                    ev_charging_kwh=0,
                    batt_charge_kwh=0,
                    batt_discharge_kwh=0,
                    soc_start_percent=50,
                    soc_end_percent=50,
                    quality_flags=trusted_flags(),
                )
            )
        await session.commit()
    with (
        patch.object(energy, "datetime", Clock),
        patch.object(energy, "load_yaml", return_value=CONFIG),
        patch.object(energy, "_calibrated_fit", new=AsyncMock(return_value=fit)),
    ):
        result = await get_cost_series(
            period="custom", start_date=previous_day.strftime("%Y-%m-%d"), end_date=day, store=store
        )
    assert result["battery_comparison"]["status"] == "available"
    assert len(result["battery_comparison"]["points"]) == 2
    # One local-midnight bucket per date, even when the date has two UTC offsets.
    assert result["battery_comparison"]["points"][-1]["start"] == start.isoformat()


@pytest.mark.asyncio
async def test_period_model_failure_uses_estimate_and_preserves_period_failure(store):
    await seed_yesterday(store)
    async with store.AsyncSession() as session:
        from sqlalchemy import update

        await session.execute(update(SlotObservation).values(import_kwh=1))
        await session.commit()
    fit = CalibrationResult("available", "validated", DIAGNOSTICS)
    with (
        patch("backend.api.routers.energy.load_yaml", return_value=CONFIG),
        patch("backend.api.routers.energy._calibrated_fit", new=AsyncMock(return_value=fit)),
    ):
        result = await get_cost_series(period="yesterday", store=store)
    assert result["battery_comparison"]["status"] == "estimated"
    assert result["battery_comparison"]["basis"] == "configured_losses"
    assert result["battery_comparison"]["calibration_status"] == "unreliable_model"
    assert result["battery_comparison"]["calibration_reason"] == "period_validation_failed"


@pytest.mark.asyncio
async def test_legacy_prior_soc_can_anchor_estimate_but_not_verified_result(store):
    await seed_yesterday(store, first_soc=None)
    yesterday_start = TZ.localize(
        datetime.combine(datetime.now(TZ).date() - timedelta(days=1), datetime.min.time())
    )
    async with store.AsyncSession() as session:
        session.add(
            SlotObservation(
                slot_start=(yesterday_start - timedelta(minutes=15)).isoformat(),
                slot_end=yesterday_start.isoformat(),
                import_kwh=0.0,
                export_kwh=0.0,
                import_price_sek_kwh=2.0,
                export_price_sek_kwh=1.0,
                pv_kwh=1.0,
                load_kwh=0.8,
                water_kwh=0.0,
                ev_charging_kwh=0.0,
                batt_charge_kwh=0.0,
                batt_discharge_kwh=0.0,
                soc_end_percent=50.0,
                quality_flags=json.dumps({"source": "recorder"}),
            )
        )
        await session.commit()
    fit = CalibrationResult("available", "validated", DIAGNOSTICS)
    with (
        patch("backend.api.routers.energy.load_yaml", return_value=CONFIG),
        patch("backend.api.routers.energy._calibrated_fit", new=AsyncMock(return_value=fit)),
    ):
        result = await get_cost_series(period="yesterday", store=store)
    comparison = result["battery_comparison"]
    assert comparison["status"] == "estimated"
    assert comparison["basis"] == "configured_losses"
    assert comparison["calibration_status"] == "available"
    assert comparison["calibration_reason"] == "missing_start_soc"


@pytest.mark.asyncio
@pytest.mark.parametrize("unsupported", ["snapshot", "cached_soc", "backfill"])
async def test_unsupported_period_inputs_are_reported_even_when_fit_needs_history(
    store, unsupported
):
    await seed_yesterday(store)
    flags = json.loads(trusted_flags())
    if unsupported == "snapshot":
        flags["recording"]["components"]["pv"]["method"] = "snapshot"
    elif unsupported == "cached_soc":
        flags["recording"]["soc"]["source"] = "cached"
    else:
        flags["source"] = "backfill"
    async with store.AsyncSession() as session:
        from sqlalchemy import update

        await session.execute(update(SlotObservation).values(quality_flags=json.dumps(flags)))
        await session.commit()
    fit = CalibrationResult("insufficient_data", "unverified_history")
    with (
        patch("backend.api.routers.energy.load_yaml", return_value=CONFIG),
        patch("backend.api.routers.energy._calibrated_fit", new=AsyncMock(return_value=fit)),
    ):
        result = await get_cost_series(period="yesterday", store=store)
    comparison = result["battery_comparison"]
    assert comparison["status"] == "incomplete_period"
    assert comparison["reason"] == "unsupported_period_measurements"
    assert comparison["calibration_status"] == "insufficient_data"
    assert "saving_sek" not in comparison


@pytest.mark.asyncio
async def test_naive_selected_timestamp_cannot_become_an_assumed_estimate(store):
    await seed_yesterday(store, legacy_unknown=True)
    from sqlalchemy import select, update

    async with store.AsyncSession() as session:
        starts = (
            (
                await session.execute(
                    select(SlotObservation.slot_start).order_by(SlotObservation.slot_start)
                )
            )
            .scalars()
            .all()
        )
        original = starts[10]
        await session.execute(
            update(SlotObservation)
            .where(SlotObservation.slot_start == original)
            .values(
                slot_start=datetime.fromisoformat(original).replace(tzinfo=None).isoformat(),
            )
        )
        await session.commit()
    with patch("backend.api.routers.energy.load_yaml", return_value=CONFIG):
        result = await get_cost_series(period="yesterday", store=store)
    comparison = result["battery_comparison"]
    # The naive-timestamp slot is excluded, never assumed; the rest is still compared.
    assert comparison["status"] == "estimated"
    assert comparison["coverage"] == {
        "covered_slots": 95,
        "total_slots": 96,
        "excluded_slots": 1,
    }
    # The legacy metered view still reports the stored observations as before.
    assert len(result["points"]) == 24


@pytest.mark.asyncio
@pytest.mark.parametrize("start_source", ["cached", "unknown"])
async def test_modern_start_endpoint_cannot_borrow_live_end_certainty(store, start_source):
    await seed_yesterday(store)
    from sqlalchemy import select, update

    async with store.AsyncSession() as session:
        first = (
            (
                await session.execute(
                    select(SlotObservation.slot_start).order_by(SlotObservation.slot_start)
                )
            )
            .scalars()
            .first()
        )
        flags = json.loads(trusted_flags())
        flags["recording"]["soc"] = {
            "source": "live",
            "owner": "recorder",
            "start": {"source": start_source, "owner": "recorder"},
            "end": {"source": "live", "owner": "recorder"},
        }
        await session.execute(
            update(SlotObservation)
            .where(SlotObservation.slot_start == first)
            .values(quality_flags=json.dumps(flags))
        )
        await session.commit()
    fit = CalibrationResult("available", "validated", DIAGNOSTICS)
    with (
        patch("backend.api.routers.energy.load_yaml", return_value=CONFIG),
        patch("backend.api.routers.energy._calibrated_fit", new=AsyncMock(return_value=fit)),
    ):
        result = await get_cost_series(period="yesterday", store=store)
    comparison = result["battery_comparison"]
    # A start endpoint that is not live cannot anchor the run: the first slot is dropped.
    assert comparison["status"] == "estimated"
    assert comparison["coverage"]["excluded_slots"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation", ["earlier_encoding", "changed_sensor", "unsupported_algorithm"]
)
async def test_earlier_soc_fingerprint_is_assumed_only_for_estimates(store, mutation):
    import copy

    from sqlalchemy import select, update

    from backend.measurement_provenance import legacy_estimate_boundary_fingerprint

    await seed_yesterday(store)
    flags = json.loads(trusted_flags())
    earlier_config = copy.deepcopy(CONFIG)
    if mutation == "changed_sensor":
        earlier_config["input_sensors"] = {"pv_power": "sensor.different_pv"}
    earlier_boundary = legacy_estimate_boundary_fingerprint(earlier_config)
    flags["recording"]["boundary_fingerprint"] = earlier_boundary
    for item in flags["recording"]["components"].values():
        item["boundary_fingerprint"] = earlier_boundary
    if mutation == "unsupported_algorithm":
        flags["recording"]["algorithm"] = "unsupported-history-v9"
    async with store.AsyncSession() as session:
        first = (
            (
                await session.execute(
                    select(SlotObservation.slot_start).order_by(SlotObservation.slot_start)
                )
            )
            .scalars()
            .first()
        )
        await session.execute(
            update(SlotObservation)
            .where(SlotObservation.slot_start == first)
            .values(quality_flags=json.dumps(flags))
        )
        await session.commit()
    fit = CalibrationResult("available", "validated", DIAGNOSTICS)
    with (
        patch("backend.api.routers.energy.load_yaml", return_value=CONFIG),
        patch("backend.api.routers.energy._calibrated_fit", new=AsyncMock(return_value=fit)),
    ):
        result = await get_cost_series(period="yesterday", store=store)
    comparison = result["battery_comparison"]
    if mutation == "earlier_encoding":
        assert comparison["status"] == "estimated" and comparison["basis"] == "configured_losses"
        assert comparison["input_assumptions"] == {
            "legacy_recording_slots": 0,
            "legacy_soc_mapping_slots": 1,
        }
        from backend.battery_comparison import RecordedObservation, trusted_row_provenance

        # The old boundary remains incompatible with strict calibration.
        row = RecordedObservation(
            datetime.fromisoformat(first), 0, 0, 2, 1, 1, 0.8, 0, 0, 0, 0, 50, 50, flags
        )
        assert trusted_row_provenance(row, boundary_fingerprint(CONFIG)) is None
        async with store.AsyncSession() as session:
            stored_flags = (
                await session.execute(
                    select(SlotObservation.quality_flags).where(SlotObservation.slot_start == first)
                )
            ).scalar_one()
        assert json.loads(stored_flags) == flags
    else:
        # The slot with an unsupported SoC fingerprint is excluded, not assumed.
        assert comparison["status"] == "estimated"
        assert comparison["coverage"]["excluded_slots"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "variant,expected_status",
    [
        ("cached_start", "available"),
        ("backfilled_start", "available"),
        ("snapshot_energy", "available"),
        ("backfilled_energy", "available"),
        ("cached_end", "partial_estimate"),
        ("backfilled_end", "partial_estimate"),
        ("wrong_end_boundary", "partial_estimate"),
        ("wrong_end_algorithm", "partial_estimate"),
        ("excluded", "partial_estimate"),
        ("comparison_excluded", "partial_estimate"),
        ("global_backfill", "partial_estimate"),
        ("wrong_boundary", "partial_estimate"),
        ("unsupported_schema", "partial_estimate"),
        ("unsupported_algorithm", "partial_estimate"),
        ("invalid_end", "partial_estimate"),
        ("noncontiguous", "partial_estimate"),
        ("legacy_unknown", "estimated"),
        ("earlier_soc_encoding", "estimated"),
    ],
)
async def test_prior_anchor_uses_only_its_independent_end_identity(store, variant, expected_status):
    from backend.measurement_provenance import legacy_estimate_boundary_fingerprint

    await seed_yesterday(store, first_soc=None)
    first = TZ.localize(
        datetime.combine(datetime.now(TZ).date() - timedelta(days=1), datetime.min.time())
    )
    flags = json.loads(trusted_flags())
    flags["recording"]["soc"] = {
        "source": "live",
        "owner": "recorder",
        "start": {"source": "live", "owner": "recorder"},
        "end": {"source": "live", "owner": "recorder"},
    }
    rec = flags["recording"]
    end_soc = 50.0
    if variant == "cached_start":
        rec["soc"]["start"]["source"] = "cached"
    elif variant == "backfilled_start":
        rec["soc"]["start"]["owner"] = "backfill"
    elif variant == "snapshot_energy":
        rec["components"]["pv"]["method"] = "snapshot"
    elif variant == "backfilled_energy":
        rec["components"]["pv"]["owner"] = "backfill"
    elif variant == "cached_end":
        rec["soc"]["end"]["source"] = "cached"
    elif variant == "backfilled_end":
        rec["soc"]["end"]["owner"] = "backfill"
    elif variant == "wrong_end_boundary":
        rec["soc"]["end"]["boundary_fingerprint"] = "b" * 64
    elif variant == "wrong_end_algorithm":
        rec["soc"]["end"]["algorithm"] = "future-algorithm"
    elif variant == "excluded":
        flags["exclude"] = True
    elif variant == "comparison_excluded":
        flags["comparison_history"] = {"disposition": "exclude_from_comparison"}
    elif variant == "global_backfill":
        flags["source"] = "backfill"
    elif variant == "wrong_boundary":
        rec["boundary_fingerprint"] = "b" * 64
    elif variant == "unsupported_schema":
        rec["schema_version"] = 2
    elif variant == "unsupported_algorithm":
        rec["algorithm"] = "future-algorithm"
    elif variant == "invalid_end":
        end_soc = float("inf")
    elif variant == "legacy_unknown":
        flags = {"source": "recorder"}
    elif variant == "earlier_soc_encoding":
        rec["boundary_fingerprint"] = legacy_estimate_boundary_fingerprint(CONFIG)
    prior_start = first - timedelta(minutes=30 if variant == "noncontiguous" else 15)
    async with store.AsyncSession() as session:
        session.add(
            SlotObservation(
                slot_start=prior_start.isoformat(),
                slot_end=(prior_start + timedelta(minutes=15)).isoformat(),
                import_kwh=0,
                export_kwh=0,
                import_price_sek_kwh=2,
                export_price_sek_kwh=1,
                pv_kwh=1,
                load_kwh=0.8,
                water_kwh=0,
                ev_charging_kwh=0,
                batt_charge_kwh=0,
                batt_discharge_kwh=0,
                soc_start_percent=40,
                soc_end_percent=end_soc,
                quality_flags=json.dumps(flags),
            )
        )
        await session.commit()
    fit = CalibrationResult("available", "validated", DIAGNOSTICS)
    with (
        patch("backend.api.routers.energy.load_yaml", return_value=CONFIG),
        patch("backend.api.routers.energy._calibrated_fit", new=AsyncMock(return_value=fit)),
    ):
        result = await get_cost_series(period="yesterday", store=store)
    c = result["battery_comparison"]
    if expected_status == "partial_estimate":
        # An untrusted prior anchor is never used: the first slot is dropped instead and the
        # run starts from its own measured end SoC (estimate, partial coverage).
        assert c["status"] == "estimated" and c["basis"] == "configured_losses"
        assert c["coverage"]["excluded_slots"] == 1
        assert c["coverage"]["covered_slots"] == 95
        return
    assert c["status"] == expected_status
    if expected_status == "available":
        assert c["basis"] == "calibrated"
    else:
        assert c["basis"] == "configured_losses" and c["calibration_reason"] == "missing_start_soc"


async def _delete_slots(store: LearningStore, indices: range) -> None:
    from sqlalchemy import delete

    start = TZ.localize(
        datetime.combine(datetime.now(TZ).date() - timedelta(days=1), datetime.min.time())
    )
    keys = [TZ.normalize(start + timedelta(minutes=15 * i)).isoformat() for i in indices]
    async with store.AsyncSession() as session:
        await session.execute(delete(SlotObservation).where(SlotObservation.slot_start.in_(keys)))
        await session.commit()


@pytest.mark.asyncio
async def test_gap_in_the_middle_is_segmented_instead_of_failing_the_period(store):
    await seed_yesterday(store)
    # Hour 10:00-11:00 never recorded: two runs of 40 and 52 slots.
    await _delete_slots(store, range(40, 44))
    fit = CalibrationResult("available", "validated", DIAGNOSTICS)
    with (
        patch("backend.api.routers.energy.load_yaml", return_value=CONFIG),
        patch("backend.api.routers.energy._calibrated_fit", new=AsyncMock(return_value=fit)),
    ):
        result = await get_cost_series(period="yesterday", store=store)
    comparison = result["battery_comparison"]
    # Verified is never claimed for a partially covered period.
    assert comparison["status"] == "estimated"
    assert comparison["basis"] == "configured_losses"
    assert comparison["coverage"] == {"covered_slots": 92, "total_slots": 96, "excluded_slots": 4}
    points = comparison["points"]
    starts = [point["start"] for point in points]
    assert len(starts) == len(set(starts)) == 23  # the fully excluded hour has no point
    assert not any("T10:00" in start for start in starts)
    assert points[-1]["darkstar_cumulative_comparison_cost_sek"] == pytest.approx(
        comparison["darkstar"]["comparison_cost_sek"]
    )
    assert points[-1]["self_use_cumulative_comparison_cost_sek"] == pytest.approx(
        comparison["self_use"]["comparison_cost_sek"]
    )
    assert comparison["saving_sek"] == pytest.approx(
        comparison["self_use"]["comparison_cost_sek"]
        - comparison["darkstar"]["comparison_cost_sek"],
        abs=0.002,
    )
    # The metered cash-flow series is unaffected by the gap.
    assert len(result["points"]) == 23


@pytest.mark.asyncio
async def test_all_slots_ineligible_keeps_the_unavailable_status(store):
    await seed_yesterday(store)
    async with store.AsyncSession() as session:
        from sqlalchemy import update

        await session.execute(
            update(SlotObservation).values(quality_flags=json.dumps({"source": "backfill"}))
        )
        await session.commit()
    with patch("backend.api.routers.energy.load_yaml", return_value=CONFIG):
        result = await get_cost_series(period="yesterday", store=store)
    comparison = result["battery_comparison"]
    assert comparison["status"] == "incomplete_period"
    assert comparison["reason"] == "unsupported_period_measurements"
    assert comparison["coverage"]["covered_slots"] == 0
    assert "saving_sek" not in comparison


@pytest.mark.asyncio
async def test_empty_placeholder_rows_are_excluded_and_runs_split_around_them(store):
    await seed_yesterday(store, legacy_unknown=True)
    start = TZ.localize(
        datetime.combine(datetime.now(TZ).date() - timedelta(days=1), datetime.min.time())
    )
    async with store.AsyncSession() as session:
        for index in (60, 61):
            row = await session.get(
                SlotObservation, TZ.normalize(start + timedelta(minutes=15 * index)).isoformat()
            )
            assert row is not None
            for field in ("pv_kwh", "load_kwh", "import_kwh", "export_kwh"):
                setattr(row, field, 0.0)
            row.soc_start_percent = None
            row.soc_end_percent = None
            row.quality_flags = None
        await session.commit()
    with patch("backend.api.routers.energy.load_yaml", return_value=CONFIG):
        result = await get_cost_series(period="yesterday", store=store)
    comparison = result["battery_comparison"]
    assert comparison["status"] == "estimated"
    assert comparison["coverage"] == {"covered_slots": 94, "total_slots": 96, "excluded_slots": 2}
