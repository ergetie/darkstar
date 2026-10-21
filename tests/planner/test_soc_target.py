"""min-soc-floor-tracking D7: soc_target_percent stays consistent with recovery plans."""

from typing import Any

import pandas as pd

from planner.output.soc_target import apply_soc_target_percent

CONFIG: dict[str, Any] = {"battery": {"min_soc_percent": 12.0, "max_soc_percent": 95.0}}


def _schedule(rows: list[tuple[str, float, float]]) -> pd.DataFrame:
    """Rows of (action, entry SoC %, projected end SoC %) on 15-minute slots."""
    index = pd.date_range("2026-10-21 00:00", periods=len(rows), freq="15min", tz="UTC")
    return pd.DataFrame(
        {
            "action": [r[0] for r in rows],
            "_entry_soc_percent": [r[1] for r in rows],
            "projected_soc_percent": [r[2] for r in rows],
        },
        index=index,
    )


def _targets(rows: list[tuple[str, float, float]]) -> list[int]:
    df = apply_soc_target_percent(_schedule(rows), CONFIG)
    return df["soc_target_percent"].tolist()


def test_partial_recovery_charge_block_not_raised_to_min():
    targets = _targets([("Hold", 11.0, 11.0), ("Charge", 11.0, 11.2), ("Charge", 11.2, 11.4)])
    assert targets[1:] == [11, 11]


def test_normal_charge_block_unchanged():
    targets = _targets([("Charge", 40.0, 60.0), ("Charge", 60.0, 80.0)])
    assert targets == [80, 80]


def test_charge_block_clamped_to_max():
    targets = _targets([("Charge", 80.0, 90.0), ("Charge", 90.0, 99.0)])
    assert targets == [95, 95]


def test_hold_during_recovery_keeps_entry():
    targets = _targets([("Hold", 11.0, 11.0), ("Hold", 11.0, 11.0)])
    assert targets == [11, 11]


def test_discharge_slot_targets_min_soc():
    targets = _targets([("Hold", 50.0, 50.0), ("Discharge", 50.0, 45.0)])
    assert targets[1] == 12


def test_charge_block_without_projection_falls_back_to_min():
    df = _schedule([("Hold", 11.0, 11.0), ("Charge", 11.0, 11.4)])
    df["projected_soc_percent"] = [None, None]
    df["_entry_soc_percent"] = [11.0, 11.0]
    out = apply_soc_target_percent(df, CONFIG)
    assert out["soc_target_percent"].tolist()[1] == 12
