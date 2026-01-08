"""
Planner Package - Rev K13 Modular Architecture

The planner package provides modular components for battery scheduling optimization.

Public API:
- PlannerPipeline: Main orchestrator for schedule generation
- generate_schedule: Convenience function for simple usage

Sub-packages:
- inputs: Data preparation and input types
- strategy: S-Index calculation and strategy functions
- scheduling: Water heating and scheduling logic
- solver: Kepler MILP solver
- output: Schedule formatting and JSON output
- observability: Logging and debugging utilities
"""

from __future__ import annotations

# Input processing
from planner.inputs.data_prep import (
    build_forecast_dataframe,
    build_price_dataframe,
    normalize_timestamp,
    prepare_df,
)

# Core types
from planner.inputs.types import (
    BatteryConfig,
    PlannerInput,
    SlotData,
    StrategyContext,
)

# Output formatting
from planner.output.formatter import dataframe_to_json_response

# Pipeline (orchestrator)
from planner.pipeline import PlannerPipeline, generate_schedule
from planner.solver.adapter import (
    config_to_kepler_config,
    kepler_result_to_dataframe,
    planner_to_kepler_input,
)

# Solver
from planner.solver.kepler import KeplerSolver
from planner.solver.types import (
    KeplerConfig,
    KeplerInput,
    KeplerInputSlot,
    KeplerResult,
    KeplerResultSlot,
)
from planner.strategy.manual_plan import apply_manual_plan

# Strategy functions
from planner.strategy.s_index import (
    calculate_dynamic_s_index,
    calculate_dynamic_target_soc,
    calculate_future_risk_factor,
    calculate_target_soc_risk_factor,
)
from planner.strategy.terminal_value import (
    calculate_terminal_value,
)

__all__ = [
    "BatteryConfig",
    "KeplerConfig",
    "KeplerInput",
    "KeplerInputSlot",
    "KeplerResult",
    "KeplerResultSlot",
    # Solver
    "KeplerSolver",
    "PlannerInput",
    # Pipeline
    "PlannerPipeline",
    # Types
    "SlotData",
    "StrategyContext",
    "apply_manual_plan",
    "build_forecast_dataframe",
    "build_price_dataframe",
    # Strategy
    "calculate_dynamic_s_index",
    "calculate_dynamic_target_soc",
    "calculate_future_risk_factor",
    "calculate_target_soc_risk_factor",
    "calculate_terminal_value",
    "config_to_kepler_config",
    # Output
    "dataframe_to_json_response",
    "generate_schedule",
    "kepler_result_to_dataframe",
    # Input processing
    "normalize_timestamp",
    "planner_to_kepler_input",
    "prepare_df",
]
