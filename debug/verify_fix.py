import json

def verify_schedule():
    try:
        with open('schedule.json', 'r') as f:
            data = json.load(f)
        
        schedule = data.get('schedule', [])
        print(f"📅 Loaded {len(schedule)} slots from schedule.json")
        
        print("\n🔎 Checking slots for Tomorrow Afternoon (16:00 - 19:00):")
        print(f"{'Time':<10} | {'Price':<6} | {'Action':<10} | {'Chg kW':<6} | {'Reason':<15}")
        print("-" * 60)
        
        found_issues = 0
        
        for slot in schedule:
            ts = slot['start_time']
            # Filter for tomorrow afternoon (21st Nov) based on your previous logs
            if "2025-11-21T16" in ts or "2025-11-21T17" in ts or "2025-11-21T18" in ts:
                price = slot.get('import_price_sek_kwh', 0)
                chg = slot.get('battery_charge_kw', 0)
                # Determine visual action
                if chg > 0:
                    action = "CHARGE" 
                elif slot.get('battery_discharge_kw', 0) > 0:
                    action = "Discharge"
                else:
                    action = "Hold"
                
                reason = slot.get('reason', '')
                
                print(f"{ts[11:16]:<10} | {price:<6.2f} | {action:<10} | {chg:<6.2f} | {reason:<15}")
                
                # Check for the bug: Charging when price is high (> 2.0 SEK)
                if price > 2.0 and chg > 0:
                    found_issues += 1

        print("-" * 60)
        if found_issues == 0:
            print("✅ SUCCESS: No phantom charging detected during peak hours!")
        else:
            print(f"❌ FAIL: Found {found_issues} slots still charging during high prices.")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    verify_schedule()