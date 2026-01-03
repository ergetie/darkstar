
import sys
import os
import logging
from datetime import datetime, timedelta

# Setup paths
sys.path.append(os.getcwd())

# Logging
logging.basicConfig(level=logging.DEBUG)

try:
    print("Importing get_learning_engine...")
    from backend.learning import get_learning_engine
    
    print("Calling get_learning_engine()...")
    engine = get_learning_engine()
    print(f"Engine: {engine}")
    
    print("Importing get_forecast_slots...")
    from ml.api import get_forecast_slots
    
    start = datetime.now()
    end = start + timedelta(hours=48)
    print(f"Calling get_forecast_slots({start}, {end}, 'aurora')...")
    
    slots = get_forecast_slots(start, end, "aurora")
    print(f"Slots found: {len(slots)}")
    if len(slots) > 0:
        print(f"First slot: {slots[0]}")
        
    print("SUCCESS")

except Exception as e:
    print(f"FAILURE: {e}")
    import traceback
    traceback.print_exc()
