from fastapi import APIRouter, HTTPException
import requests
import os
from datetime import datetime, timedelta
import pytz

# Reuse existing helpers from inputs.py to ensure consistency
from inputs import (
    _load_yaml, 
    _get_ha_entity_state, 
    get_home_assistant_sensor_float,
    load_home_assistant_config, 
    _make_ha_headers
)

router_ha = APIRouter(prefix="/api/ha", tags=["ha"])
router_services = APIRouter(tags=["services"])

# --- Helper ---
def _fetch_ha_history_avg(entity_id: str, hours: int) -> float:
    """Fetch history from HA and calculate time-weighted average."""
    if not entity_id: return 0.0
    
    ha_config = load_home_assistant_config()
    url = ha_config.get("url")
    token = ha_config.get("token")
    if not url or not token: return 0.0
    
    headers = _make_ha_headers(token)
    
    end_time = datetime.now(pytz.UTC)
    start_time = end_time - timedelta(hours=hours)
    
    # HA History API
    api_url = f"{url.rstrip('/')}/api/history/period/{start_time.isoformat()}"
    params = {
        "filter_entity_id": entity_id,
        "end_time": end_time.isoformat(),
        "significant_changes_only": False,
        "minimal_response": False
    }
    
    try:
        resp = requests.get(api_url, headers=headers, params=params, timeout=10)
        if resp.status_code != 200: return 0.0
        
        data = resp.json()
        if not data or not data[0]: return 0.0
        
        # Calculate Average
        states = data[0]
        total_weighted_sum = 0.0
        total_duration_sec = 0.0
        
        prev_time = start_time
        prev_val = 0.0
        
        # Initial value from first state? Or fetch state at start_time?
        # Simplified: Use first state's value as starting point
        try:
             prev_val = float(states[0]["state"])
             prev_time = datetime.fromisoformat(states[0]["last_changed"])
        except: pass

        for s in states:
            try:
                curr_time = datetime.fromisoformat(s["last_changed"])
                val = float(s["state"])
                
                # Duration since last change
                duration = (curr_time - prev_time).total_seconds()
                if duration > 0:
                    total_weighted_sum += prev_val * duration
                    total_duration_sec += duration
                    
                prev_time = curr_time
                prev_val = val
            except: continue
            
        # Add remainder until now
        duration = (end_time - prev_time).total_seconds()
        if duration > 0:
            total_weighted_sum += prev_val * duration
            total_duration_sec += duration
            
        if total_duration_sec == 0: return 0.0
        
        return round(total_weighted_sum / total_duration_sec, 2)
        
    except Exception as e:
        print(f"Error fetching HA history for {entity_id}: {e}")
        return 0.0

@router_ha.get("/entity/{entity_id}")
async def get_ha_entity(entity_id: str):
    state = _get_ha_entity_state(entity_id)
    if not state:
        return {
             "entity_id": entity_id,
             "state": "unknown",
             "attributes": {"friendly_name": "Offline/Missing"},
             "last_changed": None
        }
    return state

@router_ha.get("/average")
async def get_ha_average(entity_id: str = None, hours: int = 24):
    """Calculate average value for an entity over the last N hours."""
    if not entity_id:
        return {"average": 0.0, "entity_id": None, "hours": hours}
    
    avg_val = _fetch_ha_history_avg(entity_id, hours)
    return {"average": avg_val, "entity_id": entity_id, "hours": hours}

@router_ha.get("/entities")
async def get_ha_entities():
    """List available HA entities."""
    # Fetch from HA states
    config = load_home_assistant_config()
    url = config.get("url")
    token = config.get("token")
    if not url or not token: return {"entities": []}
    
    try:
        headers = _make_ha_headers(token)
        resp = requests.get(f"{url.rstrip('/')}/api/states", headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            # Filter and format
            entities = []
            for s in data:
                eid = s.get("entity_id", "")
                if eid.startswith(("sensor.", "binary_sensor.", "input_boolean.", "switch.", "input_number.")):
                     entities.append({
                         "entity_id": eid,
                         "friendly_name": s.get("attributes", {}).get("friendly_name", eid),
                         "domain": eid.split(".")[0]
                     })
            return {"entities": entities}
    except Exception as e:
        print(f"Error fetching HA entities: {e}")
        
    return {"entities": []}

@router_services.get("/api/performance/data")
async def get_performance_data(days: int = 7):
    """Get performance metrics for Aurora card."""
    try:
        from backend.learning import get_learning_engine
        engine = get_learning_engine()
        if hasattr(engine, 'get_performance_series'):
            data = engine.get_performance_series(days_back=days)
            return data
        else:
            return {
                "soc_series": [],
                "cost_series": [],
                "mae_pv_aurora": None,
                "mae_pv_baseline": None,
                "mae_load_aurora": None,
                "mae_load_baseline": None
            }
    except Exception as e:
        return {
            "soc_series": [],
            "cost_series": [],
            "mae_pv_aurora": None,
            "mae_pv_baseline": None,
            "mae_load_aurora": None,
            "mae_load_baseline": None,
            "error": str(e)
        }

@router_ha.get("/water_today")
async def get_water_today():
    """Get today's water heating energy usage."""
    config = _load_yaml("config.yaml")
    sensors = config.get("input_sensors", {})
    entity_id = sensors.get("water_heater_consumption", "sensor.vvb_energy_daily")
    
    kwh = get_home_assistant_sensor_float(entity_id) or 0.0
    # Cost? Need price. Simplified: just returning kwh for now.
    return {"kwh": kwh, "cost": 0.0, "source": "home_assistant"}


# --- Services Endpoints ---

@router_services.get("/api/status")
async def get_system_status():
    """Get instantaneous system status (SoC, Power Flow)."""
    # Load sensors
    config = _load_yaml("config.yaml")
    sensors = config.get("input_sensors", {})
    
    def get_val(key, default=0.0):
        eid = sensors.get(key)
        if not eid: return default
        return get_home_assistant_sensor_float(eid) or default
        
    soc = get_val("battery_soc")
    pv_pow = get_val("pv_power")
    load_pow = get_val("load_power")
    batt_pow = get_val("battery_power")
    grid_pow = get_val("grid_power")
    
    # Check if we didn't get grid power but have import/export
    if grid_pow == 0.0:
        # Fallback or calculation if separate sensors exist?
        pass

    return {
        "status": "online", 
        "mode": "fastapi", 
        "rev": "ARC1",
        "soc_percent": round(soc, 1),
        "pv_power_kw": round(pv_pow / 1000.0, 3),   # Sensors usually in W or kW? Inputs.py assumes W??
        # get_home_assistant_sensor_float returns raw value. 
        # Usually HA power sensors from inverters are Watts. 
        # Let's assume W and convert to kW for consistency with dashboard expectations.
        "load_power_kw": round(load_pow / 1000.0, 3),
        "battery_power_kw": round(batt_pow / 1000.0, 3),
        "grid_power_kw": round(grid_pow / 1000.0, 3) 
    }

@router_services.get("/api/water/boost")
async def get_water_boost():
    # Placeholder - ideally read from executor state or a sensor
    return {"boost": False}

@router_services.post("/api/water/boost")
async def set_water_boost():
    return {"status": "not_implemented"}


@router_services.get("/api/energy/today")
async def get_energy_today():
    """Get today's energy summary from HA sensors."""
    config = _load_yaml("config.yaml")
    sensors = config.get("input_sensors", {})
    
    def get_val(key, default=0.0):
        eid = sensors.get(key)
        if not eid: return default
        return get_home_assistant_sensor_float(eid) or default

    # Mapped from config.yaml
    grid_imp_kwh = get_val("today_grid_import")
    grid_exp_kwh = get_val("today_grid_export")
    pv_kwh = get_val("today_pv_production")
    load_kwh = get_val("today_load_consumption")
    batt_chg_kwh = get_val("today_battery_charge")
    
    # Net cost
    net_cost = get_val("today_net_cost")
    
    return {
        "solar": round(pv_kwh, 2),
        "grid_import": round(grid_imp_kwh, 2),
        "grid_export": round(grid_exp_kwh, 2),
        "consumption": round(load_kwh, 2),
        
        # Snake case for frontend matching
        "grid_import_kwh": round(grid_imp_kwh, 2),
        "grid_export_kwh": round(grid_exp_kwh, 2),
        "battery_charge_kwh": round(batt_chg_kwh, 2),
        "battery_cycles": 0, # Not easily available as daily cycle count
        "pv_production_kwh": round(pv_kwh, 2),
        "load_consumption_kwh": round(load_kwh, 2),
        "net_cost_kr": round(net_cost, 2)
    }

@router_services.get("/api/energy/range")
async def get_energy_range(period: str = "today"):
    """Get energy range data."""
    
    config = _load_yaml("config.yaml")
    sensors = config.get("input_sensors", {})
    def get_val(key, default=0.0):
        eid = sensors.get(key)
        if not eid: return default
        return get_home_assistant_sensor_float(eid) or default

    if period == "today":
        grid_imp_kwh = get_val("today_grid_import")
        grid_exp_kwh = get_val("today_grid_export")
        pv_kwh = get_val("today_pv_production")
        load_kwh = get_val("today_load_consumption")
        batt_chg_kwh = get_val("today_battery_charge")
        batt_dis_kwh = get_val("today_battery_discharge") 
        water_kwh = get_val("water_heater_consumption") 
        net_cost = get_val("today_net_cost")
        
        return {
            "period": period,
            "start_date": datetime.now().date().isoformat(),
            "end_date": datetime.now().date().isoformat(),
            "grid_import_kwh": round(grid_imp_kwh, 2),
            "grid_export_kwh": round(grid_exp_kwh, 2),
            "battery_charge_kwh": round(batt_chg_kwh, 2),
            "battery_discharge_kwh": round(batt_dis_kwh, 2),
            "water_heating_kwh": round(water_kwh, 2),
            "pv_production_kwh": round(pv_kwh, 2),
            "load_consumption_kwh": round(load_kwh, 2),
            "import_cost_sek": 0.0,
            "export_revenue_sek": 0,
            "grid_charge_cost_sek": 0,
            "self_consumption_savings_sek": 0,
            "net_cost_sek": round(net_cost, 2),
            "slot_count": 96
        }
    
    # Historical periods from learning database
    try:
        from backend.learning import get_learning_engine
        import sqlite3
        import pytz
        
        engine = get_learning_engine()
        tz = pytz.timezone(config.get("timezone", "Europe/Stockholm"))
        now_local = datetime.now(tz)
        today_local = now_local.date()
        
        # Determine date range based on period (inclusive of start, exclusive of end usually, 
        # but here we compare DATE(slot_start))
        if period == "yesterday":
            end_date = today_local - timedelta(days=1)
            start_date = end_date
        elif period == "week":
            # Last 7 days including today? OR last 7 completed days? 
            # Usually "Week" implies last 7 days.
            end_date = today_local
            start_date = today_local - timedelta(days=6)
        elif period == "month":
            end_date = today_local
            start_date = today_local - timedelta(days=29)
        else:
            # Fallback
            start_date = end_date = today_local
        
        # Query
        with sqlite3.connect(engine.db_path, timeout=5.0) as conn:
            cursor = conn.cursor()
            # We filter by DATE(slot_start) which works if slot_start is ISO-8601 YYYY-MM-DD...
            row = cursor.execute("""
                SELECT 
                    SUM(COALESCE(import_kwh, 0)),
                    SUM(COALESCE(export_kwh, 0)),
                    SUM(COALESCE(batt_charge_kwh, 0)),
                    SUM(COALESCE(batt_discharge_kwh, 0)),
                    SUM(COALESCE(water_kwh, 0)),
                    SUM(COALESCE(pv_kwh, 0)),
                    SUM(COALESCE(load_kwh, 0)),
                    -- Costs
                -- Costs
                    SUM(COALESCE(import_kwh, 0) * COALESCE(import_price_sek_kwh, 0)),
                    SUM(COALESCE(export_kwh, 0) * COALESCE(export_price_sek_kwh, 0)),
                    -- Grid Charge Cost (Import excess of load)
                    SUM(MAX(0, COALESCE(import_kwh, 0) - COALESCE(load_kwh, 0)) * COALESCE(import_price_sek_kwh, 0)),
                    -- Self Consumption Savings (Load covered by non-grid sources)
                    SUM(MAX(0, COALESCE(load_kwh, 0) - COALESCE(import_kwh, 0)) * COALESCE(import_price_sek_kwh, 0)),
                    -- Count
                    COUNT(*)
                FROM slot_observations
                WHERE DATE(slot_start) >= ? AND DATE(slot_start) <= ?
            """, (start_date.isoformat(), end_date.isoformat())).fetchone()
        
        if not row:
             raise ValueError("No data returned")

        grid_imp_kwh = row[0] or 0.0
        grid_exp_kwh = row[1] or 0.0
        batt_chg_kwh = row[2] or 0.0
        batt_dis_kwh = row[3] or 0.0
        water_kwh = row[4] or 0.0
        pv_kwh = row[5] or 0.0
        load_kwh = row[6] or 0.0
        
        import_cost = row[7] or 0.0
        export_rev = row[8] or 0.0
        grid_charge_cost = row[9] or 0.0
        self_cons_savings = row[10] or 0.0
        
        net_cost = import_cost - export_rev
        
        return {
            "period": period,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "grid_import_kwh": round(grid_imp_kwh, 2),
            "grid_export_kwh": round(grid_exp_kwh, 2),
            "battery_charge_kwh": round(batt_chg_kwh, 2),
            "battery_discharge_kwh": round(batt_dis_kwh, 2),
            "water_heating_kwh": round(water_kwh, 2),
            "pv_production_kwh": round(pv_kwh, 2),
            "load_consumption_kwh": round(load_kwh, 2),
            "import_cost_sek": round(import_cost, 2),
            "export_revenue_sek": round(export_rev, 2),
            "grid_charge_cost_sek": round(grid_charge_cost, 2),
            "self_consumption_savings_sek": round(self_cons_savings, 2),
            "net_cost_sek": round(net_cost, 2),
            "slot_count": row[11] or 0
        }
    except Exception as e:
        # logger.warning(f"Failed to get historical energy data for {period}: {e}")
        # Fallback with zeros
        return {
            "period": period,
            "start_date": datetime.now().date().isoformat(),
            "end_date": datetime.now().date().isoformat(),
            "grid_import_kwh": 0.0,
            "grid_export_kwh": 0.0,
            "battery_charge_kwh": 0.0,
            "battery_discharge_kwh": 0.0,
            "water_heating_kwh": 0.0,
            "pv_production_kwh": 0.0,
            "load_consumption_kwh": 0.0,
            "import_cost_sek": 0.0,
            "export_revenue_sek": 0.0,
            "grid_charge_cost_sek": 0.0,
            "self_consumption_savings_sek": 0.0,
            "net_cost_sek": 0.0,
            "slot_count": 0,
            "error": str(e)
        }


# --- Additional Missing Endpoints ---

@router_ha.get("/services")
async def get_ha_services():
    """List available HA services."""
    config = load_home_assistant_config()
    url = config.get("url")
    token = config.get("token")
    if not url or not token: 
        return {"services": []}
    
    try:
        headers = _make_ha_headers(token)
        resp = requests.get(f"{url.rstrip('/')}/api/services", headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            # Flatten to list of "domain.service" strings
            services = []
            for domain_obj in data:
                domain = domain_obj.get("domain", "")
                for service_name in domain_obj.get("services", {}).keys():
                    services.append(f"{domain}.{service_name}")
            return {"services": sorted(services)}
    except Exception as e:
        print(f"Error fetching HA services: {e}")
    
    return {"services": []}


@router_ha.post("/test")
async def test_ha_connection():
    """Test connection to Home Assistant."""
    config = load_home_assistant_config()
    url = config.get("url")
    token = config.get("token")
    
    if not url or not token:
        return {"status": "error", "message": "HA not configured"}
    
    try:
        headers = _make_ha_headers(token)
        resp = requests.get(f"{url.rstrip('/')}/api/", headers=headers, timeout=5)
        if resp.status_code == 200:
            return {"status": "success", "message": "Connected to Home Assistant"}
        else:
            return {"status": "error", "message": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router_services.get("/api/ha-socket")
async def get_ha_socket_status():
    """Return status of the HA WebSocket connection."""
    try:
        from backend.ha_socket import get_socket_status
        return get_socket_status()
    except ImportError:
        return {"status": "unavailable", "message": "HA socket module not loaded"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router_services.get("/api/db/current_schedule")
async def get_db_current_schedule():
    """Get the current schedule from the database."""
    try:
        from db_writer import get_current_schedule_from_db
        schedule = get_current_schedule_from_db()
        return {"schedule": schedule}
    except ImportError:
        return {"schedule": None, "message": "DB module not available"}
    except Exception as e:
        return {"schedule": None, "error": str(e)}


@router_services.post("/api/db/push_current")
async def push_to_db():
    """Push current schedule to database."""
    try:
        from db_writer import write_schedule_to_db
        import json
        with open("schedule.json", "r") as f:
            schedule = json.load(f)
        write_schedule_to_db(schedule)
        return {"status": "success", "message": "Schedule pushed to DB"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router_services.post("/api/simulate")
async def run_simulation():
    """Run schedule simulation."""
    try:
        from planner.simulation import simulate_schedule
        import json
        with open("schedule.json", "r") as f:
            schedule = json.load(f)
        result = simulate_schedule(schedule)
        return {"status": "success", "result": result}
    except ImportError:
        return {"status": "error", "message": "Simulation module not available"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


