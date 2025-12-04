import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import pytz
from ruamel.yaml import YAML

from backend.learning.engine import LearningEngine
from backend.learning.store import LearningStore
from backend.strategy.history import append_strategy_event

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AuroraReflex")

# ============================================================================
# Bounds and Rate Limits for each tunable parameter
# ============================================================================
BOUNDS = {
    "s_index.base_factor": (1.0, 1.3),
    "forecasting.pv_confidence_percent": (80, 100),
    "battery_economics.battery_cycle_cost_kwh": (0.1, 0.5),
    "battery.capacity_kwh": (0, None),  # Only decrease, min 0, max is nameplate
}

MAX_DAILY_CHANGE = {
    "s_index.base_factor": 0.02,
    "forecasting.pv_confidence_percent": 2.0,
    "battery_economics.battery_cycle_cost_kwh": 0.05,
    "battery.capacity_kwh": 0.5,
}

# Safety analyzer thresholds
SAFETY_LOW_SOC_THRESHOLD = 5.0  # SoC below this is critical
SAFETY_PEAK_HOURS = (16, 20)  # Peak demand window
SAFETY_CRITICAL_EVENT_COUNT = 3  # Events in 30d to trigger increase
SAFETY_RELAXATION_DAYS = 60  # No events for this long to trigger decrease


class AuroraReflex:
    """
    Aurora Reflex: The Long-Term Feedback Loop.
    Analyzes historical data to tune physical and policy parameters in config.yaml.
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.learning_engine = LearningEngine(config_path)
        self.store = self.learning_engine.store
        self.yaml = YAML()
        self.yaml.preserve_quotes = True
        self.timezone = self.learning_engine.timezone
        
        # Load current config
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = self.yaml.load(f)

    def run(self, dry_run: bool = False) -> List[str]:
        """
        Run all analyzers and apply updates if needed.
        Returns a list of actions taken (or proposed).
        """
        if not self.config.get("learning", {}).get("reflex_enabled", False) and not dry_run:
            logger.info("Aurora Reflex is disabled in config.")
            return ["Skipped: Reflex disabled"]

        logger.info(f"Running Aurora Reflex (Dry Run: {dry_run})...")
        updates = {}
        report = []

        # 1. Analyze Safety (S-Index Base Factor)
        safety_update, safety_msg = self.analyze_safety()
        report.append(safety_msg)
        if safety_update:
            updates.update(safety_update)

        # 2. Analyze Confidence (PV Confidence)
        conf_update, conf_msg = self.analyze_confidence()
        report.append(conf_msg)
        if conf_update:
            updates.update(conf_update)

        # 3. Analyze ROI (Battery Cycle Cost)
        roi_update, roi_msg = self.analyze_roi()
        report.append(roi_msg)
        if roi_update:
            updates.update(roi_update)

        # 4. Analyze Capacity (Battery Capacity)
        cap_update, cap_msg = self.analyze_capacity()
        report.append(cap_msg)
        if cap_update:
            updates.update(cap_update)

        # Apply Updates
        if updates:
            self.update_config(updates, dry_run)
            action = "Proposed" if dry_run else "Applied"
            report.append(f"{action} {len(updates)} config updates.")
        else:
            report.append("No updates needed.")

        return report

    def _can_update(self, param_path: str) -> bool:
        """
        Check if we're allowed to update this parameter today (rate limiting).
        Returns True if no update was made today.
        """
        state = self.store.get_reflex_state(param_path)
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

    def _clamp_value(
        self, param_path: str, current_value: float, proposed_value: float
    ) -> float:
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

    def analyze_safety(self) -> Tuple[Dict, str]:
        """
        Monitor low-SoC events during peak hours.
        If SoC < 5% during 16:00-20:00 too often, increase s_index.base_factor.
        If no events for 60+ days, relax the buffer.
        
        Target: s_index.base_factor
        """
        param_path = "s_index.base_factor"
        
        # Check rate limit
        if not self._can_update(param_path):
            return {}, f"Safety: Rate limited (changed today already)"
        
        # Query low-SoC events
        events_30d = self.store.get_low_soc_events(
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
            events_60d = self.store.get_low_soc_events(
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

    def analyze_confidence(self) -> Tuple[Dict, str]:
        """
        Compare PV forecast vs actuals.
        Target: forecasting.pv_confidence_percent
        
        TODO: Implement in Phase B
        """
        metrics = self.learning_engine.calculate_metrics(days_back=14)
        mae_pv = metrics.get("mae_pv", 0.0)
        
        return {}, f"Confidence: Stable (MAE PV={mae_pv:.2f} kWh)"

    def analyze_roi(self) -> Tuple[Dict, str]:
        """
        Analyze battery ROI.
        Target: battery_economics.battery_cycle_cost_kwh
        
        TODO: Implement in Phase C
        """
        return {}, "ROI: Stable (not implemented)"

    def analyze_capacity(self) -> Tuple[Dict, str]:
        """
        Detect capacity fade.
        Target: battery.capacity_kwh
        
        TODO: Implement in Phase D
        """
        return {}, "Capacity: Stable (not implemented)"

    def update_config(self, updates: Dict[str, Any], dry_run: bool) -> None:
        """
        Apply updates to config.yaml using ruamel.yaml to preserve comments.
        Also logs changes to strategy history and updates reflex state.
        
        updates: dict of "path.to.key" -> new_value
        """
        # Reload config to ensure we have the latest comment structure
        with open(self.config_path, "r", encoding="utf-8") as f:
            data = self.yaml.load(f)

        changes_made = []
        
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
                
                changes_made.append({
                    "param": key_path,
                    "old": old_value,
                    "new": new_value,
                })
                
                # Try to add comment with previous value
                try:
                    comment = f" Reflex: was {old_value}"
                    target.yaml_add_eol_comment(comment, last_key)
                except Exception as e:
                    logger.debug(f"Could not add YAML comment: {e}")
                
                # Update reflex state (even in dry run, for testing)
                if not dry_run:
                    self.store.update_reflex_state(key_path, float(new_value))

        if not dry_run:
            # Write config
            with open(self.config_path, "w", encoding="utf-8") as f:
                self.yaml.dump(data, f)
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
    import sys
    
    dry_run = "--apply" not in sys.argv
    if dry_run:
        print("Running in DRY RUN mode. Use --apply to actually update config.")
    
    reflex = AuroraReflex()
    results = reflex.run(dry_run=dry_run)
    
    print("\n=== Aurora Reflex Report ===")
    for line in results:
        print(f"  • {line}")
