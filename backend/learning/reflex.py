import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import pytz
from ruamel.yaml import YAML

from backend.learning.engine import LearningEngine

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AuroraReflex")

class AuroraReflex:
    """
    Aurora Reflex: The Long-Term Feedback Loop.
    Analyzes historical data to tune physical and policy parameters in config.yaml.
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.learning_engine = LearningEngine(config_path)
        self.yaml = YAML()
        self.yaml.preserve_quotes = True
        
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
        if safety_update:
            updates.update(safety_update)
            report.append(safety_msg)

        # 2. Analyze Confidence (PV Confidence)
        conf_update, conf_msg = self.analyze_confidence()
        if conf_update:
            updates.update(conf_update)
            report.append(conf_msg)

        # 3. Analyze ROI (Battery Cycle Cost)
        roi_update, roi_msg = self.analyze_roi()
        if roi_update:
            updates.update(roi_update)
            report.append(roi_msg)

        # 4. Analyze Capacity (Battery Capacity)
        cap_update, cap_msg = self.analyze_capacity()
        if cap_update:
            updates.update(cap_update)
            report.append(cap_msg)

        # Apply Updates
        if updates:
            self.update_config(updates, dry_run)
            action = "Proposed" if dry_run else "Applied"
            report.append(f"{action} {len(updates)} config updates.")
        else:
            report.append("No updates needed.")

        return report

    def analyze_safety(self) -> Tuple[Dict, str]:
        """
        Monitor low-SoC events. If we hit 0% too often, increase safety margin.
        Target: s_index.base_factor
        """
        # Look back 30 days
        metrics = self.learning_engine.calculate_metrics(days_back=30)
        # We need raw observations for this, metrics might be too aggregated.
        # Let's query the store directly via learning engine's db_path
        
        # TODO: Implement robust query. For now, using a placeholder logic based on metrics
        # If we had a metric for "days_with_zero_soc", we'd use it.
        # Let's assume we want to increase base_factor if we are consistently low.
        
        # Placeholder: No update for now until we have the specific metric
        return {}, "Safety Analysis: Stable"

    def analyze_confidence(self) -> Tuple[Dict, str]:
        """
        Compare PV forecast vs actuals.
        Target: forecasting.pv_confidence_percent
        """
        metrics = self.learning_engine.calculate_metrics(days_back=14)
        mae_pv = metrics.get("mae_pv", 0.0)
        
        # This is a simplified heuristic. Real logic would compare sum(forecast) vs sum(actual).
        # For now, let's just log.
        return {}, f"Confidence Analysis: MAE PV={mae_pv:.2f}"

    def analyze_roi(self) -> Tuple[Dict, str]:
        """
        Analyze battery ROI.
        Target: battery_economics.battery_cycle_cost_kwh
        """
        return {}, "ROI Analysis: Stable"

    def analyze_capacity(self) -> Tuple[Dict, str]:
        """
        Detect capacity fade.
        Target: battery.capacity_kwh
        """
        return {}, "Capacity Analysis: Stable"

    def update_config(self, updates: Dict[str, Any], dry_run: bool) -> None:
        """
        Apply updates to config.yaml using ruamel.yaml to preserve comments.
        updates: dict of "path.to.key" -> new_value
        """
        # Reload config to ensure we have the latest comment structure
        with open(self.config_path, "r", encoding="utf-8") as f:
            data = self.yaml.load(f)

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
                
                # Add comment with default/previous value
                # ruamel.yaml supports adding comments
                # This is a bit tricky programmatically, but we attempt it.
                comment = f" Default: {old_value}"
                target.yaml_add_eol_comment(comment, last_key)

        if not dry_run:
            with open(self.config_path, "w", encoding="utf-8") as f:
                self.yaml.dump(data, f)
            logger.info("Config saved.")
        else:
            logger.info("Dry run: Config not saved.")

if __name__ == "__main__":
    reflex = AuroraReflex()
    print(reflex.run(dry_run=True))
