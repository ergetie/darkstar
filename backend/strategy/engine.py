import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("darkstar.strategy")

MAX_PV_DEFICIT_WEIGHT_BUMP = 0.4
MAX_TEMP_WEIGHT_BUMP = 0.2


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

            overrides["water_heating"] = {"min_hours_per_day": 0.0, "min_kwh_per_day": 0.0}

        weather_volatility = context.get("weather_volatility") or {}
        cloud_vol = float(weather_volatility.get("cloud", 0.0) or 0.0)
        temp_vol = float(weather_volatility.get("temp", 0.0) or 0.0)

        cloud_vol = max(0.0, min(1.0, cloud_vol))
        temp_vol = max(0.0, min(1.0, temp_vol))

        if cloud_vol > 0.0 or temp_vol > 0.0:
            s_index_cfg = self.config.get("s_index", {}) or {}
            base_pv_weight = float(s_index_cfg.get("pv_deficit_weight", 0.0) or 0.0)
            base_temp_weight = float(s_index_cfg.get("temp_weight", 0.0) or 0.0)

            pv_weight_adj = base_pv_weight
            temp_weight_adj = base_temp_weight

            if cloud_vol > 0.0 and MAX_PV_DEFICIT_WEIGHT_BUMP > 0.0:
                pv_weight_adj = base_pv_weight + cloud_vol * MAX_PV_DEFICIT_WEIGHT_BUMP

            if temp_vol > 0.0 and MAX_TEMP_WEIGHT_BUMP > 0.0:
                temp_weight_adj = base_temp_weight + temp_vol * MAX_TEMP_WEIGHT_BUMP

            pv_weight_adj = max(base_pv_weight, round(pv_weight_adj, 2))
            temp_weight_adj = max(base_temp_weight, round(temp_weight_adj, 2))

            overrides.setdefault("s_index", {})
            overrides["s_index"]["pv_deficit_weight"] = pv_weight_adj
            overrides["s_index"]["temp_weight"] = temp_weight_adj

            logger.info(
                "Strategy: Weather volatility cloud=%.2f temp=%.2f. "
                "Adjusting s_index.pv_deficit_weight from %.2f to %.2f, "
                "temp_weight from %.2f to %.2f.",
                cloud_vol,
                temp_vol,
                base_pv_weight,
                pv_weight_adj,
                base_temp_weight,
                temp_weight_adj,
            )

        if overrides:
            logger.info(f"Strategy Engine active. Applying overrides: {overrides}")

        return overrides
