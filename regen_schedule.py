#!/usr/bin/env python3
"""Regenerate schedule.json to capture latest code changes."""
import yaml
from inputs import get_all_input_data
from planner.pipeline import PlannerPipeline

with open("config.yaml") as f:
    config = yaml.safe_load(f)

print("Regenerating schedule...")
input_data = get_all_input_data("config.yaml")
pipeline = PlannerPipeline(config)
df = pipeline.generate_schedule(input_data, mode="full", save_to_file=True)
print("Done! Schedule saved to schedule.json")
