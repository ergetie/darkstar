import sys
import time
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent.resolve()))

from datetime import datetime, timedelta

from backend.learning import LearningEngine
from ml.corrector import predict_corrections
from ml.forward import _load_models, generate_forward_slots
from ml.weather import get_weather_series


def profile(name, func, *args, **kwargs):
    start = time.time()
    try:
        res = func(*args, **kwargs)
        dur = time.time() - start
        print(f"[{name}] Done in {dur:.4f}s")
        return res, dur
    except Exception as e:
        dur = time.time() - start
        print(f"[{name}] Failed in {dur:.4f}s: {e}")
        return None, dur

def main():
    print("="*60)
    print("ML COMPONENT PROFILING")
    print("="*60)

    engine = LearningEngine()
    tz = engine.timezone
    now = datetime.now(tz)
    start = now
    end = now + timedelta(hours=48)

    # 1. Test Weather API
    print("\n1. Testing Weather API (Open-Meteo)...")
    _, w_dur = profile("Weather API", get_weather_series, start, end, config=engine.config)

    # 2. Test Model Loading
    print("\n2. Testing Model Loading (LightGBM)...")
    _, m_dur = profile("Model Load", _load_models)

    # 3. Test Full Forward Pass
    print("\n3. Testing Forward Forecast (End-to-End)...")
    profile("Forward Gen", generate_forward_slots, horizon_hours=48)

    # 4. Test Corrector
    print("\n4. Testing Corrector (End-to-End)...")
    profile("Corrector", predict_corrections, horizon_hours=48)

    print("\n" + "="*60)
    print("SUMMARY")
    print(f"Weather Fetch: {w_dur:.4f}s")
    print(f"Model Load:    {m_dur:.4f}s")
    print("="*60)

if __name__ == "__main__":
    main()
