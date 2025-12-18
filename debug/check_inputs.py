import sys
import os

sys.path.append(os.getcwd())

from inputs import get_all_input_data, get_initial_state

print("--- Checking Initial State directly ---")
state = get_initial_state()
print(f"Direct get_initial_state(): {state}")

print("\n--- Checking via get_all_input_data ---")
data = get_all_input_data()
initial = data.get("initial_state", {})
print(f"Via get_all_input_data(): {initial}")

print("\n--- Config Check ---")
import yaml

with open("config.yaml") as f:
    config = yaml.safe_load(f)
    print(f"Battery Capacity: {config.get('battery', {}).get('capacity_kwh')}")
    print(
        f"System Battery Capacity: {config.get('system', {}).get('battery', {}).get('capacity_kwh')}"
    )
