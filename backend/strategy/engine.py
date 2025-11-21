from typing import Any, Dict, Optional
import logging

logger = logging.getLogger("darkstar.strategy")

class StrategyEngine:
    """
    The 'Brain' of Aurora v2.
    Determines dynamic configuration overrides based on system context
    (Weather, Vacation, Alarm, Prices, etc.).
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def decide(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze inputs and return a dictionary of config overrides.

        Args:
            input_data: The same data packet sent to the planner
                (prices, forecast, initial_state).

        Returns:
            Dict[str, Any]: A deep dictionary of overrides matching config.yaml structure.
                Example: {'water_heating': {'min_hours_per_day': 0}}
        """
        overrides: Dict[str, Any] = {}
        context = input_data.get("context", {})

        # --- Rule: Vacation Mode ---
        # Only disable water heating if explicitly on Vacation.
        # Alarm status is ignored for strategy (but used by ML for load forecast).
        is_vacation = context.get("vacation_mode", False)

        if is_vacation:
            logger.info("Strategy: Disabling Water Heating due to Vacation Mode")

            overrides["water_heating"] = {
                "min_hours_per_day": 0.0,
                "min_kwh_per_day": 0.0
            }

        if overrides:
            logger.info(f"Strategy Engine active. Applying overrides: {overrides}")

        return overrides
