import logging
from typing import Any, Dict, Optional
from backend.strategy.history import append_strategy_event

logger = logging.getLogger("darkstar.strategy")

# Weather volatility bumps - kept small to avoid overriding user's risk_appetite
# These add marginal safety buffer during uncertain weather, not dominate the target SOC
MAX_PV_DEFICIT_WEIGHT_BUMP = 0.1  # Was 0.4 - too aggressive, caused 37% target always
MAX_TEMP_WEIGHT_BUMP = 0.05       # Was 0.2 - keep small to respect risk_appetite


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
            append_strategy_event(
                "STRATEGY_CHANGE",
                "Vacation Mode active. Water heating disabled.",
                {"vacation_mode": True}
            )

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
            append_strategy_event(
                "WEATHER_ADJUSTMENT",
                f"High volatility (Cloud: {cloud_vol:.2f}, Temp: {temp_vol:.2f}). Raised S-Index weights.",
                {
                    "cloud_vol": cloud_vol,
                    "temp_vol": temp_vol,
                    "pv_weight_adj": pv_weight_adj,
                    "temp_weight_adj": temp_weight_adj
                }
            )

        # --- Rule: Price Volatility (Kepler Tuning) ---
        prices = input_data.get("prices", [])
        if prices:
            volatility_data = self._analyze_price_volatility(prices)
            spread = volatility_data.get("spread", 0.0)
            
            # Default config values (baseline)
            # We need to fetch them from self.config if available, else defaults
            # But here we only set overrides if we deviate from "Standard" behavior.
            
            # Logic:
            # High Spread (> 1.5 SEK): Aggressive Mode.
            #   - Wear Cost -> 0 (Cycle hard)
            #   - Ramping Cost -> Low (React fast)
            #   - Export Threshold -> Low (Capture all profit)
            
            # Low Spread (< 0.5 SEK): Conservative Mode.
            #   - Wear Cost -> High (Save battery)
            #   - Ramping Cost -> High (Smooth)
            #   - Export Threshold -> High (Don't bother)
            
            kepler_overrides = {}
            
            if spread > 1.5:
                logger.info(f"Strategy: High Price Volatility (Spread {spread:.2f} SEK). Engaging Aggressive Mode.")
                kepler_overrides["wear_cost_sek_per_kwh"] = 0.0
                kepler_overrides["ramping_cost_sek_per_kw"] = 0.01 # Very low
                kepler_overrides["export_threshold_sek_per_kwh"] = 0.05
                append_strategy_event(
                    "PRICE_VOLATILITY",
                    f"High Price Spread ({spread:.2f} SEK). Aggressive Mode engaged.",
                    {"spread": spread, "mode": "aggressive"}
                )
                
            elif spread < 0.5:
                logger.info(f"Strategy: Low Price Volatility (Spread {spread:.2f} SEK). Engaging Conservative Mode.")
                # Assuming default wear cost is around 0.5-1.0 in config.
                # We force it higher to discourage usage.
                kepler_overrides["wear_cost_sek_per_kwh"] = 1.0 
                kepler_overrides["ramping_cost_sek_per_kw"] = 0.5 # High damping
                kepler_overrides["export_threshold_sek_per_kwh"] = 0.2 # Need 20 ore spread
                append_strategy_event(
                    "PRICE_VOLATILITY",
                    f"Low Price Spread ({spread:.2f} SEK). Conservative Mode engaged.",
                    {"spread": spread, "mode": "conservative"}
                )
            
            if kepler_overrides:
                overrides["kepler"] = kepler_overrides

        if overrides:
            logger.info(f"Strategy Engine active. Applying overrides: {overrides}")

        return overrides

    def _analyze_price_volatility(self, prices: list) -> Dict[str, float]:
        """
        Calculate price volatility metrics.
        Expects list of dicts with 'value' key (SEK/kWh).
        """
        if not prices:
            return {"spread": 0.0}
            
        values = [p.get("value", 0.0) for p in prices]
        if not values:
            return {"spread": 0.0}
            
        min_p = min(values)
        max_p = max(values)
        spread = max_p - min_p
        
        return {"spread": spread, "min": min_p, "max": max_p}
