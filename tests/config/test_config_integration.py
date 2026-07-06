"""
Config Integration Test
=======================
Verifies that config.default.yaml values are correctly mapped
to KeplerConfig via the adapter.
"""

from pathlib import Path

import pytest
import yaml

from planner.solver.adapter import config_to_kepler_config


@pytest.fixture
def default_config():
    """Load the default config YAML."""
    config_path = Path(__file__).parent.parent.parent / "config.default.yaml"
    with config_path.open() as f:
        return yaml.safe_load(f)


def test_config_mapping(default_config):
    """Test that all exposed keys in config.default.yaml map to KeplerConfig correctly."""
    raw_config = default_config

    # Create dummy slots/overrides
    k_config = config_to_kepler_config(raw_config)

    # 2. Curtailment Penalty
    assert k_config.curtailment_penalty_sek == raw_config["kepler"]["curtailment_penalty_sek"]

    # 3. Water Reliability Penalty
    # Note: Adapter applies Comfort Level 3 (Neutral) by default, overriding raw config.
    # New Level 3 value set by user in adapter.py: 15.0 (was 25.0)
    assert k_config.water_reliability_penalty_sek == 15.0

    # 4. Water Block Penalty
    # Level 3 default: 0.50
    assert k_config.water_block_penalty_sek == 2.0

    # 5. Wear Cost
    # Note: Adapter looks at battery_economics first
    assert (
        k_config.wear_cost_sek_per_kwh == raw_config["battery_economics"]["battery_cycle_cost_kwh"]
    )

    # 6. Basic Battery Parameters
    assert k_config.min_soc_percent == raw_config["battery"]["min_soc_percent"]
    assert k_config.max_soc_percent == raw_config["battery"]["max_soc_percent"]
    assert k_config.charge_efficiency == raw_config["battery"]["charge_efficiency"]

    # 7. Water Block Start Penalty
    # Level 3 default: 3.0
    assert k_config.water_block_start_penalty_sek == 3.0

    # 8. Defer Hours
    assert k_config.defer_up_to_hours == raw_config["water_heating"]["defer_up_to_hours"]

    # 9. Ramping Cost
    assert k_config.ramping_cost_sek_per_kw == raw_config["kepler"]["ramping_cost_sek_per_kw"]


def test_config_loading_ignores_removed_water_penalty_keys(default_config):
    """The four water_heating.* keys removed in fix-water-comfort-truthfulness
    (#15) were never read by the adapter. A user config.yaml that still has
    them (pre-upgrade) must load without error and produce an identical
    KeplerConfig to one without them — no migration required."""
    raw_config = default_config
    baseline = config_to_kepler_config(raw_config)

    stale_config = dict(raw_config)
    stale_config["water_heating"] = {
        **raw_config["water_heating"],
        "block_start_penalty_sek": 3.0,
        "spacing_penalty_sek": 0.20,
        "reliability_penalty_sek": 1000.0,
        "block_penalty_sek": 0.50,
    }

    with_stale_keys = config_to_kepler_config(stale_config)

    assert with_stale_keys.water_reliability_penalty_sek == baseline.water_reliability_penalty_sek
    assert with_stale_keys.water_block_penalty_sek == baseline.water_block_penalty_sek
    assert (
        with_stale_keys.water_block_start_penalty_sek
        == baseline.water_block_start_penalty_sek
    )
    assert with_stale_keys.water_gap_penalty_sek == baseline.water_gap_penalty_sek
