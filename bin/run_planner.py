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

    # Optional Antares shadow-mode plan (Phase 4)
    antares_cfg = config.get("antares", {}) or {}
    enable_shadow = bool(antares_cfg.get("enable_shadow_mode", False))
    if enable_shadow:
        try:
            from db_writer import write_antares_shadow_to_mariadb
            from ml.policy.shadow_runner import run_shadow_for_schedule

            policy_type = str(antares_cfg.get("shadow_policy_type", "lightgbm")).lower()
            if policy_type not in {"lightgbm", "rl"}:
                policy_type = "lightgbm"

            shadow_payload = run_shadow_for_schedule(df, policy_type=policy_type)
            if shadow_payload is None:
                print("[planner] Antares shadow mode enabled but no policy; skipping shadow write")
            else:
                secrets = load_yaml("secrets.yaml")
                planner_version = get_version_string()
                rows = write_antares_shadow_to_mariadb(
                    shadow_payload,
                    planner_version,
                    config,
                    secrets,
                )
                if rows > 0:
                    print(
                        "[planner] Wrote Antares shadow plan to MariaDB "
                        f"antares_plan_history (plan_date={shadow_payload.get('plan_date')})"
                    )
                else:
                    print(
                        "[planner] Antares shadow mode enabled but MariaDB write was skipped "
                        "(missing or incomplete secrets)"
                    )
        except Exception as exc:
            print(f"[planner] Warning: Failed to generate/write Antares shadow plan: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
