import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from backend.learning.engine import LearningEngine
from backend.strategy.history import append_strategy_event
from backend.validation import get_max_energy_per_slot

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AuroraReflex")

# ============================================================================
# Bounds and Rate Limits for each tunable parameter
# ============================================================================
BOUNDS = {
    "s_index.base_factor": (1.0, 1.3),
    "forecasting.pv_confidence_percent": (70, 120),
    "battery.capacity_kwh": (0, None),  # Only decrease, min 0, max is nameplate
}

MAX_DAILY_CHANGE = {
    "s_index.base_factor": 0.02,
    "forecasting.pv_confidence_percent": 5.0,
    "battery.capacity_kwh": 0.5,
}

# Safety analyzer thresholds
SAFETY_LOW_SOC_THRESHOLD = 5.0  # SoC below this is critical
SAFETY_PEAK_HOURS = (16, 20)  # Peak demand window
SAFETY_CRITICAL_EVENT_COUNT = 3  # Events in 30d to trigger increase
SAFETY_RELAXATION_DAYS = 60  # No events for this long to trigger decrease

# Confidence analyzer thresholds
CONFIDENCE_BIAS_THRESHOLD = 0.5  # kWh/slot avg bias to trigger adjustment
CONFIDENCE_MIN_SAMPLES = 100  # Minimum data points for reliable bias calculation
CONFIDENCE_LOOKBACK_DAYS = 14  # Days to analyze for bias

# Capacity analyzer thresholds
CAPACITY_LOOKBACK_DAYS = 30  # Days to analyze
CAPACITY_FADE_THRESHOLD = 0.95  # Report fade if <95% of nameplate
CAPACITY_MIN_DATA_POINTS = 10  # Minimum observations needed


class AuroraReflex:
    """
    Aurora Reflex: The Long-Term Feedback Loop.
    Analyzes historical data to tune physical and policy parameters in config.yaml.
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = Path(config_path)
        self.learning_engine = LearningEngine(config_path)
        self.store = self.learning_engine.store
        self.yaml = YAML()
        self.yaml.preserve_quotes = True
        self.timezone = self.learning_engine.timezone

        # Load current config (Sync in constructor is generally okay if not high-frequency)
        with self.config_path.open(encoding="utf-8") as f:
            self.config: dict[str, Any] = self.yaml.load(f)  # type: ignore[reportUnknownMemberType]

    async def run(self, dry_run: bool = False) -> list[str]:
        """
        Run all analyzers and apply updates if needed.
        Returns a list of actions taken (or proposed).
        """
        if not self.config.get("learning", {}).get("reflex_enabled", False) and not dry_run:
            logger.info("Aurora Reflex is disabled in config.")
            return ["Skipped: Reflex disabled"]

        logger.info(f"Running Aurora Reflex (Dry Run: {dry_run})...")
        updates: dict[str, Any] = {}
        report: list[str] = []

        # 1. Analyze Safety (S-Index Base Factor)
        safety_update, safety_msg = await self.analyze_safety()
        report.append(safety_msg)
        if safety_update:
            updates.update(safety_update)

        # 2. Analyze Confidence (PV Confidence)
        conf_update, conf_msg = await self.analyze_confidence()
        report.append(conf_msg)
        if conf_update:
            updates.update(conf_update)

        # 3. Analyze Capacity (Battery Capacity)
        cap_update, cap_msg = await self.analyze_capacity()
        report.append(cap_msg)
        if cap_update:
            updates.update(cap_update)

        # Apply Updates
        if updates:
            await self.update_config(updates, dry_run)
            action = "Proposed" if dry_run else "Applied"
            report.append(f"{action} {len(updates)} config updates.")
        else:
            report.append("No updates needed.")

        return report

    async def _can_update(self, param_path: str) -> bool:
        """
        Check if we're allowed to update this parameter today (rate limiting).
        Returns True if no update was made today.
        """
        state = await self.store.get_reflex_state(param_path)
        if state is None:
            return True

        last_updated_str = state.get("last_updated")
        if not last_updated_str:
            return True

        try:
            last_updated = datetime.fromisoformat(last_updated_str)
            if last_updated.tzinfo is None:
                last_updated = last_updated.replace(tzinfo=self.timezone)
            else:
                last_updated = last_updated.astimezone(self.timezone)

            now = datetime.now(self.timezone)
            # Allow update if last update was before today
            return last_updated.date() < now.date()
        except (ValueError, TypeError):
            return True

    def _clamp_value(self, param_path: str, current_value: float, proposed_value: float) -> float:
        """
        Clamp the proposed value within bounds and rate limits.
        """
        min_val, max_val = BOUNDS.get(param_path, (None, None))
        max_change = MAX_DAILY_CHANGE.get(param_path, float("inf"))

        # Apply rate limit
        delta = proposed_value - current_value
        if abs(delta) > max_change:
            delta = max_change if delta > 0 else -max_change
        new_value = current_value + delta

        # Apply bounds
        if min_val is not None:
            new_value = max(new_value, min_val)
        if max_val is not None:
            new_value = min(new_value, max_val)

        return new_value

    async def analyze_safety(self) -> tuple[dict[str, Any], str]:
        """
        Monitor low-SoC events during peak hours.
        If SoC < 5% during 16:00-20:00 too often, increase s_index.base_factor.
        If no events for 60+ days, relax the buffer.

        Target: s_index.base_factor
        """
        param_path = "s_index.base_factor"

        # Check rate limit
        if not await self._can_update(param_path):
            return {}, "Safety: Rate limited (changed today already)"

        # Query low-SoC events
        events_30d = await self.store.get_low_soc_events(
            days_back=30,
            threshold_percent=SAFETY_LOW_SOC_THRESHOLD,
            peak_hours=SAFETY_PEAK_HOURS,
        )

        current_value = self.config.get("s_index", {}).get("base_factor", 1.1)
        min_val, max_val = BOUNDS[param_path]
        max_change = MAX_DAILY_CHANGE[param_path]
        num_events = len(events_30d)

        if num_events >= SAFETY_CRITICAL_EVENT_COUNT:
            # Too many low-SoC events → increase buffer
            proposed = current_value + max_change
            new_value = self._clamp_value(param_path, current_value, proposed)

            if new_value > current_value:
                logger.info(
                    f"Safety: {num_events} low-SoC events in 30d "
                    f"(threshold: {SAFETY_CRITICAL_EVENT_COUNT}) → "
                    f"increasing base_factor {current_value:.3f} → {new_value:.3f}"
                )
                return (
                    {param_path: round(new_value, 3)},
                    f"Safety: {num_events} low-SoC events in 30d → "
                    f"base_factor {current_value:.3f} → {new_value:.3f}",
                )
            else:
                return {}, f"Safety: {num_events} events but already at max ({max_val})"

        elif num_events == 0:
            # Check longer window for relaxation
            events_60d = await self.store.get_low_soc_events(
                days_back=SAFETY_RELAXATION_DAYS,
                threshold_percent=SAFETY_LOW_SOC_THRESHOLD,
                peak_hours=SAFETY_PEAK_HOURS,
            )

            if len(events_60d) == 0 and current_value > min_val:
                # Relax more slowly (half the rate)
                proposed = current_value - (max_change / 2)
                new_value = self._clamp_value(param_path, current_value, proposed)

                if new_value < current_value:
                    logger.info(
                        f"Safety: No low-SoC events in {SAFETY_RELAXATION_DAYS}d → "
                        f"relaxing base_factor {current_value:.3f} → {new_value:.3f}"
                    )
                    return (
                        {param_path: round(new_value, 3)},
                        f"Safety: No low-SoC events in {SAFETY_RELAXATION_DAYS}d → "
                        f"base_factor {current_value:.3f} → {new_value:.3f}",
                    )
                else:
                    return {}, f"Safety: Already at min ({min_val})"

        return (
            {},
            f"Safety: Stable ({num_events} events in 30d, base_factor={current_value:.3f})",
        )

    async def analyze_confidence(self) -> tuple[dict[str, Any], str]:
        """
        Compare PV forecast vs actuals to detect systematic bias.
        If over-predicting (positive bias), lower confidence to increase safety margin.
        If under-predicting (negative bias), increase confidence.

        Target: forecasting.pv_confidence_percent
        """
        param_path = "forecasting.pv_confidence_percent"

        # Check rate limit
        if not await self._can_update(param_path):
            return {}, "Confidence: Rate limited (changed today already)"

        # Get forecast vs actual data with spike filtering
        try:
            max_kwh = get_max_energy_per_slot(self.config)
        except ValueError:
            max_kwh = None

        df = await self.store.get_forecast_vs_actual(
            days_back=CONFIDENCE_LOOKBACK_DAYS,
            target="pv",
            max_kwh=max_kwh,
        )

        if len(df) < CONFIDENCE_MIN_SAMPLES:
            return (
                {},
                f"Confidence: Insufficient data ({len(df)} samples, need {CONFIDENCE_MIN_SAMPLES})",
            )

        # Calculate bias (positive = over-prediction, negative = under-prediction)
        mean_bias = df["error"].mean()
        mae = df["error"].abs().mean()

        current_value = self.config.get("forecasting", {}).get("pv_confidence_percent", 90)
        min_val, max_val = BOUNDS[param_path]
        max_change = MAX_DAILY_CHANGE[param_path]

        if mean_bias > CONFIDENCE_BIAS_THRESHOLD:
            # Systematic over-prediction → lower confidence (be more conservative)
            proposed = current_value - max_change
            new_value = self._clamp_value(param_path, current_value, proposed)

            if new_value < current_value:
                logger.info(
                    f"Confidence: Over-predicting PV (bias={mean_bias:.2f} kWh/slot) → "
                    f"lowering confidence {current_value:.1f}% → {new_value:.1f}%"
                )
                return (
                    {param_path: round(new_value, 1)},
                    f"Confidence: Over-predicting PV (bias=+{mean_bias:.2f} kWh) → "
                    f"confidence {current_value:.1f}% → {new_value:.1f}%",
                )
            else:
                return {}, f"Confidence: Over-predicting but already at min ({min_val}%)"

        elif mean_bias < -CONFIDENCE_BIAS_THRESHOLD:
            # Systematic under-prediction → raise confidence (we're too conservative)
            proposed = current_value + max_change
            new_value = self._clamp_value(param_path, current_value, proposed)

            if new_value > current_value:
                logger.info(
                    f"Confidence: Under-predicting PV (bias={mean_bias:.2f} kWh/slot) → "
                    f"raising confidence {current_value:.1f}% → {new_value:.1f}%"
                )
                return (
                    {param_path: round(new_value, 1)},
                    f"Confidence: Under-predicting PV (bias={mean_bias:.2f} kWh) → "
                    f"confidence {current_value:.1f}% → {new_value:.1f}%",
                )
            else:
                return {}, f"Confidence: Under-predicting but already at max ({max_val}%)"

        return (
            {},
            f"Confidence: Stable (bias={mean_bias:.2f} kWh, MAE={mae:.2f} kWh, {len(df)} samples)",
        )

    async def analyze_capacity(self) -> tuple[dict[str, Any], str]:
        """
        Detect battery capacity fade by analyzing discharge efficiency.

        Compares estimated effective capacity vs configured capacity.
        Only decreases (never increases beyond original nameplate).

        Target: battery.capacity_kwh
        """
        param_path = "battery.capacity_kwh"

        # Check rate limit
        if not await self._can_update(param_path):
            return {}, "Capacity: Rate limited (changed today already)"

        # Get capacity estimate
        estimated = await self.store.get_capacity_estimate(days_back=CAPACITY_LOOKBACK_DAYS)

        if estimated is None:
            return {}, "Capacity: Insufficient data for estimation"

        current_capacity = self.config.get("battery", {}).get("capacity_kwh", 34.0)
        max_change = MAX_DAILY_CHANGE[param_path]

        # Only decrease capacity (fade detection), never increase
        if estimated < current_capacity * CAPACITY_FADE_THRESHOLD:
            # Significant fade detected
            proposed = max(estimated, current_capacity - max_change)
            new_value = max(proposed, 0)  # Never go negative

            if new_value < current_capacity:
                fade_percent = ((current_capacity - estimated) / current_capacity) * 100
                logger.info(
                    f"Capacity: Fade detected ({fade_percent:.1f}%) → "
                    f"reducing {current_capacity:.1f} → {new_value:.1f} kWh"
                )
                return (
                    {param_path: round(new_value, 1)},
                    f"Capacity: Fade detected (estimated {estimated:.1f} kWh) → "
                    f"{current_capacity:.1f} → {new_value:.1f} kWh",
                )

        return (
            {},
            f"Capacity: Healthy (estimated {estimated:.1f} kWh, configured {current_capacity:.1f} kWh)",
        )

    async def update_config(self, updates: dict[str, Any], dry_run: bool) -> None:
        """
        Apply updates to config.yaml using ruamel.yaml to preserve comments.
        Also logs changes to strategy history and updates reflex state.
        """
        import asyncio

        def _apply_updates() -> tuple[Any, list[dict[str, Any]]]:
            # Reload config to ensure we have the latest comment structure
            with self.config_path.open(encoding="utf-8") as f:
                data: Any = self.yaml.load(f)  # type: ignore[reportUnknownMemberType]

            changes_made: list[dict[str, Any]] = []

            for key_path, new_value in updates.items():
                keys = key_path.split(".")
                target = data
                for k in keys[:-1]:
                    target = target.setdefault(k, {})

                last_key = keys[-1]
                old_value = target.get(last_key)

                if old_value != new_value:
                    logger.info(f"Updating {key_path}: {old_value} -> {new_value}")
                    target[last_key] = new_value

                    changes_made.append(
                        {
                            "param": key_path,
                            "old": old_value,
                            "new": new_value,
                        }
                    )

                    # Try to add comment with previous value
                    try:
                        comment = f" Reflex: was {old_value}"
                        target.yaml_add_eol_comment(comment, last_key)
                    except Exception as e:
                        logger.debug(f"Could not add YAML comment: {e}")
            return data, changes_made

        data, changes_made = await asyncio.to_thread(_apply_updates)

        if not dry_run:
            # Update reflex state in DB for each change
            for change in changes_made:
                await self.store.update_reflex_state(change["param"], float(change["new"]))

            def _write_config():
                with self.config_path.open("w", encoding="utf-8") as f:
                    self.yaml.dump(data, f)  # type: ignore[reportUnknownMemberType]

            await asyncio.to_thread(_write_config)
            logger.info("Config saved.")

            # Log to strategy history
            if changes_made:
                append_strategy_event(
                    event_type="REFLEX_UPDATE",
                    message=f"Aurora Reflex tuned {len(changes_made)} parameter(s)",
                    details={"changes": changes_made},
                )
        else:
            logger.info("Dry run: Config not saved.")
            # Still log the proposal
            if changes_made:
                append_strategy_event(
                    event_type="REFLEX_PROPOSAL",
                    message=f"Aurora Reflex proposes {len(changes_made)} change(s)",
                    details={"changes": changes_made, "dry_run": True},
                )


if __name__ == "__main__":
    import asyncio
    import sys

    async def main():
        dry_run = "--apply" not in sys.argv
        if dry_run:
            print("Running in DRY RUN mode. Use --apply to actually update config.")

        reflex = AuroraReflex()
        results = await reflex.run(dry_run=dry_run)

        print("\n=== Aurora Reflex Report ===")
        for line in results:
            print(f"  • {line}")

    asyncio.run(main())
