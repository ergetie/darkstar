"""
Planner Package - Battery Schedule Optimization

This package provides a modular pipeline for generating optimal battery schedules
based on price forecasts, PV production, load predictions, and strategic overlays.

Public API:
    generate_schedule(input_data, config, mode="full") -> pd.DataFrame
"""

from planner.pipeline import PlannerPipeline, generate_schedule

__all__ = ["PlannerPipeline", "generate_schedule"]
