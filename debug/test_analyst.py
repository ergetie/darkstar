#!/usr/bin/env python3
"""Test analyst stores values correctly."""

import sqlite3

import yaml

from backend.learning.analyst import Analyst

with open("config.yaml") as f:
    config = yaml.safe_load(f)

print("=== Running Analyst ===")
analyst = Analyst(config)
analyst.update_learning_overlays()

print()
print("=== DB after analyst run ===")
with sqlite3.connect("data/planner_learning.db") as conn:
    cur = conn.cursor()
    cur.execute(
        "SELECT date, s_index_base_factor FROM learning_daily_metrics ORDER BY date DESC LIMIT 5"
    )
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]}")
