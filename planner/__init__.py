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

# Core types
from planner.inputs.types import (
    SlotData,
    PlannerInput,
    StrategyContext,
    BatteryConfig,
)

from planner.solver.types import (
    KeplerConfig,
    KeplerInput,
    KeplerInputSlot,
    KeplerResult,
    KeplerResultSlot,
)

# Strategy functions
from planner.strategy.s_index import (
    calculate_dynamic_s_index,
    calculate_future_risk_factor,
    calculate_target_soc_risk_factor,
)
from planner.strategy.terminal_value import (
    calculate_terminal_value,
    calculate_dynamic_target_soc,
)
from planner.strategy.manual_plan import apply_manual_plan

# Input processing
from planner.inputs.data_prep import (
    normalize_timestamp,
    build_price_dataframe,
    build_forecast_dataframe,
    prepare_df,
)

# Solver
from planner.solver.kepler import KeplerSolver
from planner.solver.adapter import (
    planner_to_kepler_input,
    config_to_kepler_config,
    kepler_result_to_dataframe,
)

# Output formatting
from planner.output.formatter import dataframe_to_json_response

# Pipeline (orchestrator)
from planner.pipeline import PlannerPipeline, generate_schedule


__all__ = [
    # Types
    "SlotData",
    "PlannerInput", 
    "StrategyContext",
    "BatteryConfig",
    "KeplerConfig",
    "KeplerInput",
    "KeplerInputSlot",
    "KeplerResult",
    "KeplerResultSlot",
    # Strategy
    "calculate_dynamic_s_index",
    "calculate_future_risk_factor",
    "calculate_target_soc_risk_factor",
    "calculate_terminal_value",
    "calculate_dynamic_target_soc",
    "apply_manual_plan",
    # Input processing
    "normalize_timestamp",
    "build_price_dataframe",
    "build_forecast_dataframe",
    "prepare_df",
    # Solver
    "KeplerSolver",
    "planner_to_kepler_input",
    "config_to_kepler_config",
    "kepler_result_to_dataframe",
    # Output
    "dataframe_to_json_response",
    # Pipeline
    "PlannerPipeline",
    "generate_schedule",
]
