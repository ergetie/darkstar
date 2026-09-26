import logging
from typing import Any

from backend.strategy.history import append_strategy_event

logger = logging.getLogger("darkstar.strategy")

# Risk-based baseline shifts for dynamic export threshold (in SEK/kWh)
RISK_BASELINE_SHIFTS = {
    1: 0.15,  # Conservative: always maintain higher margin
    2: 0.10,  # Cautious
    3: 0.05,  # Balanced (default)
    4: 0.02,  # Aggressive
    5: 0.00,  # Maximum: can go to zero on high volatility days
}


class StrategyEngine:
    """
    The 'Brain' of Aurora v2.
    Determines dynamic configuration overrides based on system context
    (Weather, Vacation, Alarm, Prices, etc.).
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config

    def decide(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """
        Analyze inputs and return a dictionary of config overrides.

        Args:
            input_data: The same data packet sent to the planner
                (prices, forecast, initial_state).

        Returns:
            Dict[str, Any]: A deep dictionary of overrides matching config.yaml structure.
                Example: {'water_heating': {'min_hours_per_day': 0}}
        """
        overrides: dict[str, Any] = {}
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
                {"vacation_mode": True},
            )

        # --- Rule: Price Volatility (Kepler Tuning) ---
        prices: list[dict[str, Any]] = input_data.get("prices", [])
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

            # Dynamic export threshold with continuous scaling based on price spread and risk appetite
            risk_appetite = int(self.config.get("s_index", {}).get("risk_appetite", 3))
            baseline = RISK_BASELINE_SHIFTS.get(risk_appetite, 0.05)

            # Normalize spread: 0.0 at spread=0.3, 1.0 at spread=2.0
            spread_norm = max(0.0, min(1.0, (spread - 0.3) / 1.7))

            # Calculate threshold: 0.50 at low spread → baseline at high spread
            export_threshold = round(0.50 - (0.50 - baseline) * spread_norm, 3)

            kepler_overrides["export_threshold_sek_per_kwh"] = export_threshold

            if spread > 1.5:
                logger.info(
                    f"Strategy: High Price Volatility (Spread {spread:.2f} SEK). Engaging Aggressive Mode."
                )
                kepler_overrides["wear_cost_sek_per_kwh"] = 0.0
                kepler_overrides["ramping_cost_sek_per_kw"] = 0.01  # Very low
                append_strategy_event(
                    "PRICE_VOLATILITY",
                    f"High Price Spread ({spread:.2f} SEK). Aggressive Mode engaged.",
                    {"spread": spread, "mode": "aggressive", "threshold": export_threshold},
                )

            elif spread < 0.5:
                logger.info(
                    f"Strategy: Low Price Volatility (Spread {spread:.2f} SEK). Engaging Conservative Mode."
                )
                kepler_overrides["wear_cost_sek_per_kwh"] = 1.0
                kepler_overrides["ramping_cost_sek_per_kw"] = 0.5  # High damping
                append_strategy_event(
                    "PRICE_VOLATILITY",
                    f"Low Price Spread ({spread:.2f} SEK). Conservative Mode engaged.",
                    {"spread": spread, "mode": "conservative", "threshold": export_threshold},
                )
            else:
                # Medium volatility: apply wear/ramping costs but with the dynamic threshold
                # Use linear interpolation for wear/ramping between low (0.5) and high (1.5)
                med_norm = (spread - 0.5) / 1.0  # 0.0 at 0.5, 1.0 at 1.5
                kepler_overrides["wear_cost_sek_per_kwh"] = round(1.0 - med_norm * 1.0, 2)
                kepler_overrides["ramping_cost_sek_per_kw"] = round(0.5 - med_norm * 0.49, 2)
                logger.info(
                    f"Strategy: Medium Price Volatility (Spread {spread:.2f} SEK). Using continuous scaling."
                )

            if kepler_overrides:
                overrides["kepler"] = kepler_overrides

        if overrides:
            logger.info(f"Strategy Engine active. Applying overrides: {overrides}")

        return overrides

    def _analyze_price_volatility(self, prices: list[dict[str, Any]]) -> dict[str, float]:
        """
        Calculate price volatility metrics.
        Expects list of dicts with 'value' key (SEK/kWh).
        """
        if not prices:
            return {"spread": 0.0}

        values: list[float] = [float(p.get("value", 0.0)) for p in prices]
        if not values:
            return {"spread": 0.0}

        min_p = min(values)
        max_p = max(values)
        spread = max_p - min_p

        return {"spread": spread, "min": min_p, "max": max_p}
