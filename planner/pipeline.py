"""
Planner Pipeline

Main orchestrator for the modular planner pipeline.
Coordinates Input → Strategy → Solver → Output flow.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import pandas as pd

logger = logging.getLogger("darkstar.planner")


class PlannerPipeline:
    """
    Orchestrator for the modular planner pipeline.
    
    Modes:
        - "full": Aurora overlays + Strategy + Kepler (production)
        - "baseline": Kepler only, no Aurora overlays (for A/B comparison)
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the pipeline with configuration.
        
        Args:
            config: Configuration dictionary (from config.yaml)
        """
        self.config = config
        self._validate_config()
    
    def _validate_config(self) -> None:
        """Validate critical configuration values."""
        required_sections = ["battery", "battery_economics"]
        for section in required_sections:
            if section not in self.config:
                raise ValueError(f"Missing required config section: {section}")
    
    def generate_schedule(
        self,
        input_data: Dict[str, Any],
        mode: str = "full",
        save_to_file: bool = True,
    ) -> pd.DataFrame:
        """
        Generate an optimal battery schedule.
        
        Args:
            input_data: Dictionary with price_data, forecast_data, initial_state
            mode: "full" (Aurora + Kepler) or "baseline" (Kepler only)
            save_to_file: Whether to save schedule.json
            
        Returns:
            DataFrame with the complete schedule
        """
        logger.info("PlannerPipeline.generate_schedule(mode=%s)", mode)
        
        # Placeholder - will be implemented as modules are extracted
        # For now, delegate to legacy HeliosPlanner (planner_legacy.py)
        # This import is here to avoid circular imports during transition
        import planner_legacy
        
        legacy = planner_legacy.HeliosPlanner("config.yaml")
        return legacy.generate_schedule(
            input_data,
            save_to_file=save_to_file,
        )


def generate_schedule(
    input_data: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
    mode: str = "full",
) -> pd.DataFrame:
    """
    Convenience function to generate a schedule.
    
    Args:
        input_data: Dictionary with price_data, forecast_data, initial_state
        config: Optional config dict (loads from config.yaml if not provided)
        mode: "full" or "baseline"
        
    Returns:
        DataFrame with the complete schedule
    """
    if config is None:
        from inputs import _load_yaml
        config = _load_yaml("config.yaml")
    
    pipeline = PlannerPipeline(config)
    return pipeline.generate_schedule(input_data, mode=mode)
