import os
import sys

sys.path.append(os.getcwd())
from inputs import get_initial_state

print("Fetching initial state...")
try:
    state = get_initial_state()
    print(f"State: {state}")
except Exception as e:
    print(f"Error: {e}")
