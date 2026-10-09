from datetime import UTC, datetime

import pytest
import pytz

from backend.core.water_heating import (
    normalize_active_power_kw,
    validate_water_heating_config,
    water_quota_window,
)


def test_normalizes_units_and_preserves_bidirectional_power():
    assert normalize_active_power_kw(60, "W", 0.1) == 0.0
    assert normalize_active_power_kw(100, "W", 0.1) == pytest.approx(0.1)
    assert normalize_active_power_kw(0.1, "kW", 0.1) == pytest.approx(0.1)
    assert normalize_active_power_kw(-60, "W", 0.1) == pytest.approx(-0.06)
    assert normalize_active_power_kw(float("nan"), "kW", 0.0) is None


@pytest.mark.parametrize(
    ("moment", "defer", "expected"),
    [
        (datetime(2026, 1, 15, 0, 0), 0, datetime(2026, 1, 15, 0, 0)),
        (datetime(2026, 1, 15, 2, 0), 6, datetime(2026, 1, 14, 6, 0)),
        (datetime(2026, 1, 15, 5, 45), 5.5, datetime(2026, 1, 15, 5, 30)),
    ],
)
def test_quota_window_uses_local_boundary(moment, defer, expected):
    tz = pytz.timezone("Europe/Stockholm")
    start, end = water_quota_window(moment, defer, tz)
    assert start.replace(tzinfo=None) == expected
    assert end.date() > start.date()


def test_quota_window_moves_skipped_dst_boundary_to_first_valid_instant():
    tz = pytz.timezone("Europe/Stockholm")
    # The 02:30 boundary does not exist on the spring transition day.
    start, _ = water_quota_window(datetime(2026, 3, 29, 3, 15, tzinfo=UTC), 2.5, tz)
    assert start.isoformat() == "2026-03-29T03:00:00+02:00"


def test_repeated_dst_boundary_uses_one_shared_quota_window():
    tz = pytz.timezone("Europe/Stockholm")
    first_occurrence = tz.localize(datetime(2026, 10, 25, 2, 45), is_dst=True)
    second_occurrence = tz.localize(datetime(2026, 10, 25, 2, 45), is_dst=False)

    first_window = water_quota_window(first_occurrence, 2.5, tz)
    second_window = water_quota_window(second_occurrence, 2.5, tz)

    assert first_window == second_window
    assert (first_window[1] - first_window[0]).total_seconds() == 25 * 3600


@pytest.mark.parametrize("defer", [0, 23])
def test_water_config_accepts_deferral_endpoints_and_long_gap(defer):
    validate_water_heating_config(
        {
            "water_heating": {"defer_up_to_hours": defer},
            "water_heaters": [
                {"id": "tank", "max_hours_between_heating": 28, "idle_power_threshold_kw": 0.1}
            ],
        }
    )


@pytest.mark.parametrize("defer", [30, float("inf"), float("nan"), -0.1])
def test_water_config_rejects_invalid_deferral(defer):
    with pytest.raises(ValueError, match=r"water_heating.defer_up_to_hours.*0 and 23"):
        validate_water_heating_config({"water_heating": {"defer_up_to_hours": defer}})


@pytest.mark.parametrize("cutoff", [-0.1, float("inf"), float("nan")])
def test_water_config_rejects_invalid_idle_cutoff(cutoff):
    with pytest.raises(ValueError, match="idle_power_threshold_kw"):
        validate_water_heating_config(
            {"water_heaters": [{"id": "tank", "idle_power_threshold_kw": cutoff}]}
        )


def test_omitted_cutoff_defaults_to_legacy_inclusion():
    validate_water_heating_config({"water_heaters": [{"id": "tank"}]})
    assert normalize_active_power_kw(0.06, "kW") == pytest.approx(0.06)


@pytest.mark.parametrize("field", ["source", "coverage"])
@pytest.mark.parametrize("malformed", [[], {}])
def test_malformed_device_metadata_remains_unknown(field, malformed):
    from backend.core.water_heating import parse_water_heater_energy_metadata

    entry = {
        "energy_kwh": 0.0,
        "source": "power_history",
        "coverage": "complete",
        "idle_power_threshold_kw": 0.1,
    }
    entry[field] = malformed
    result = parse_water_heater_energy_metadata(
        {"schema_version": 1, "semantics": "active-water-energy-v1", "devices": {"tank": entry}}
    )
    assert result is not None
    assert not result["devices"].get("tank", {}).get("coverage")


def test_water_provenance_is_independent_of_unrelated_unknown_components():
    from backend.core.water_heating import water_component_recording
    from backend.measurement_provenance import recording_metadata

    flags = {
        "recording": recording_metadata(
            {},
            {
                "water": {"method": "power_history", "owner": "recorder"},
                "pv": {"method": "unknown", "owner": "recorder"},
            },
            "unavailable",
        )
    }
    assert water_component_recording(flags) is not None
    flags["recording"]["components"]["water"]["method"] = "unknown"
    assert water_component_recording(flags) is None


def test_invalid_water_spike_cannot_credit_device_progress_or_a_measured_zero():
    from backend.core.water_heating import (
        parse_water_heater_energy_metadata,
        water_component_recording,
    )
    from backend.measurement_provenance import recording_metadata
    from backend.validation import validate_energy_values

    flags = {
        "recording": recording_metadata(
            {}, {"water": {"method": "power_history", "owner": "recorder"}}, "unavailable"
        ),
        "water_heater_energy": {
            "schema_version": 1,
            "semantics": "active-water-energy-v1",
            "devices": {
                "tank": {
                    "energy_kwh": 1000,
                    "source": "power_history",
                    "coverage": "complete",
                    "idle_power_threshold_kw": 0.1,
                }
            },
        },
    }
    validated = validate_energy_values({"water_kwh": 1000, "quality_flags": flags}, 8)
    assert validated["water_kwh"] == 0
    assert water_component_recording(validated["quality_flags"]) is None
    metadata = parse_water_heater_energy_metadata(validated["quality_flags"]["water_heater_energy"])
    assert metadata["devices"]["tank"]["energy_kwh"] is None
    assert metadata["devices"]["tank"]["coverage"] is False
    assert flags["water_heater_energy"]["devices"]["tank"]["energy_kwh"] == 1000
