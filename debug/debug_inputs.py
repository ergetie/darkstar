from datetime import datetime

# Import your actual inputs module
from inputs import get_all_input_data


def check_inputs():
    print("🔍 Fetching input data (this mimics a real planner run)...")
    try:
        data = get_all_input_data()

        daily_pv = data.get("daily_pv_forecast", {})
        daily_load = data.get("daily_load_forecast", {})

        print(f"\n📊 PV Forecast Days: {len(daily_pv)}")
        for date_str, val in sorted(daily_pv.items()):
            print(f"   {date_str}: {val:.2f} kWh")

        print(f"\n🏠 Load Forecast Days: {len(daily_load)}")
        for date_str, val in sorted(daily_load.items()):
            print(f"   {date_str}: {val:.2f} kWh")

        # Check if we have Saturday (Day 2)
        today = datetime.now().date()
        print(f"\n📅 Today: {today}")

    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    check_inputs()
