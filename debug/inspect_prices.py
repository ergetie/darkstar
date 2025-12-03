import sys
import sqlite3
import pandas as pd
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from backend.learning import get_learning_engine

def main():
    print("🔍 Inspecting Prices & Energy (Last 7 Days)...")
    
    try:
        engine = get_learning_engine("config.yaml")
        
        with sqlite3.connect(engine.db_path) as conn:
            query = """
                SELECT 
                    DATE(slot_start) as day,
                    COUNT(*) as slots,
                    SUM(import_kwh) as total_import,
                    SUM(export_kwh) as total_export,
                    SUM(load_kwh) as total_load,
                    SUM(pv_kwh) as total_pv,
                    AVG(import_price_sek_kwh) as avg_price,
                    SUM(import_kwh * import_price_sek_kwh) as import_cost,
                    SUM(export_kwh * export_price_sek_kwh) as export_revenue,
                    SUM(import_kwh * import_price_sek_kwh - export_kwh * export_price_sek_kwh) as net_cost
                FROM slot_observations
                WHERE DATE(slot_start) >= DATE('now', '-7 days')
                GROUP BY day
                ORDER BY day ASC
            """
            df = pd.read_sql(query, conn)
            
            print("\n📊 Daily Breakdown:")
            print(df.round(2))
            
            print("\n📈 Totals (7 Days):")
            print(f"   Total Import: {df['total_import'].sum():.2f} kWh")
            print(f"   Total Load:   {df['total_load'].sum():.2f} kWh")
            print(f"   Total PV:     {df['total_pv'].sum():.2f} kWh")
            print(f"   Total Cost:   {df['net_cost'].sum():.2f} SEK")
            print(f"   Avg Price:    {df['avg_price'].mean():.2f} SEK/kWh")
            print(f"   Avg Daily:    {df['net_cost'].mean():.2f} SEK/day")
            
            # Check for high price outliers
            print("\n⚠️  Price Outliers (> 5.0 SEK):")
            outliers = pd.read_sql("""
                SELECT slot_start, import_price_sek_kwh 
                FROM slot_observations 
                WHERE import_price_sek_kwh > 5.0 
                  AND DATE(slot_start) >= DATE('now', '-7 days')
            """, conn)
            if not outliers.empty:
                print(outliers)
            else:
                print("   None found.")

    except Exception as e:
        print(f"❌ Inspection failed: {e}")

if __name__ == "__main__":
    main()
