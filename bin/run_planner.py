import json
import os
import subprocess
from datetime import datetime

import yaml

from planner import HeliosPlanner
from inputs import get_all_input_data


def load_yaml(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def get_version_string():
    # Try git describe, fallback to env or static string
    try:
        out = subprocess.check_output(
            ["git", "describe", "--tags", "--always"], stderr=subprocess.DEVNULL
        )
        return out.decode("utf-8").strip()
    except Exception:
        return os.environ.get("DARKSTAR_VERSION", "dev")


def write_schedule_json(df, out_path="schedule.json"):
    from planner import dataframe_to_json_response

    payload = {"schedule": dataframe_to_json_response(df)}
    # Attach meta with planner_version and timestamp
    payload["meta"] = payload.get("meta", {})
    payload["meta"]["planner_version"] = get_version_string()
    payload["meta"]["planned_at"] = datetime.now().isoformat()
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return out_path


def write_to_mariadb(schedule_path, config_path="config.yaml", secrets_path="secrets.yaml"):
    from db_writer import write_schedule_to_db_with_preservation

    config = load_yaml(config_path)
    secrets = load_yaml(secrets_path)
    planner_version = get_version_string()
    return write_schedule_to_db_with_preservation(schedule_path, planner_version, config, secrets)


def main():
    config = load_yaml("config.yaml")
    automation = config.get("automation", {})
    if not automation.get("enable_scheduler", False):
        print("[planner] Scheduler disabled by config. Exiting.")
        return 0

    # Build inputs and run planner
    input_data = get_all_input_data("config.yaml")
    planner = HeliosPlanner("config.yaml")
    df = planner.generate_schedule(input_data, record_training_episode=True)

    # Save schedule.json with meta
    schedule_path = write_schedule_json(df, "schedule.json")
    print(f"[planner] Wrote schedule to {schedule_path}")

    # Optional DB write
    if automation.get("write_to_mariadb", False):
        inserted = write_to_mariadb(schedule_path)
        print(f"[planner] Wrote {inserted} rows to MariaDB current_schedule/plan_history")
    else:
        print("[planner] Skipped DB write (automation.write_to_mariadb is false)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
