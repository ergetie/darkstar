# Investigation Report: v2.4.10-beta Issues

## 1. Executor Error: "Failed to get state of : 404"

### Symptom
The user logs show:
```
10:15:00ERRORexecutor.actions... Failed to get state of : 404 Client Error: Not Found for url: http://supervisor/core/api/states/
```
The error message format `Failed to get state of :` indicates that the `entity_id` variable was an empty string `""` at the time of the call.

### Root Cause
In `backend/executor/actions.py`, several methods call `self.ha.get_state_value(entity)` without first verifying if `entity` is a valid string.
Specifically, `_set_work_mode` does not check if `self.config.inverter.work_mode_entity` is set.

```python
    def _set_work_mode(self, target_mode: str) -> ActionResult:
        """Set inverter work mode if different from current."""
        start = time.time()
        entity = self.config.inverter.work_mode_entity  # <--- If this is "", it crashes
        
        # Get current state
        current = self.ha.get_state_value(entity)
```

The home assistant client constructs the URL as `.../api/states/` (with empty ID), which returns a 404.

### Remediation
Update `backend/executor/actions.py` to add guard clauses for empty entity IDs in:
- `_set_work_mode`
- `_set_grid_charging`
- `_set_soc_target`
- `set_water_temp`

(Note: `_set_max_export_power` already has this check).

---

## 2. Config Overwrite on Restart

### Symptom
User reports that `config.yaml` values (e.g., `price_area` "SE3") revert to previous values ("SE4") on restart.

### Root Cause
This is caused by the startup synchronization logic in `darkstar/run.sh` (the Home Assistant Add-on entrypoint).
The script captures environment variables from the Add-on Configuration (`options.json`) and enforces them on `config.yaml` during startup.

```python
# darkstar/run.sh
price_area = os.environ.get('PRICE_AREA', '$PRICE_AREA')
# ...
if price_area:
    if 'nordpool' not in config:
        config['nordpool'] = {}
    if config['nordpool'].get('price_area') != price_area:
        config['nordpool']['price_area'] = price_area  # <--- Overwrites config.yaml
        modified = True
```

If the user changes the setting in the **Darkstar UI** (saving to `config.yaml`), but leaves the **Add-on Configuration** unchanged (e.g., "SE4"), the next restart will detect a mismatch and overwrite `config.yaml` with the Add-on's value ("SE4").

### Remediation
**Immediate Workaround:**
Users running the HA Add-on must update settings in the **Add-on Configuration** tab, not the Darkstar UI, for the following fields:
- Timezone
- Price Area
- Sensor Entities (Battery, PV, Load)
- System Toggles (Solar, Battery, Water Heater)

**Code Fix:**
1.  **Documentation Update:** Clearly mark these fields as "Managed by Supervisor" in the UI when running in Add-on mode.
2.  **Logic Update:** Verify if `run.sh` logic can be relaxed to only set values if they are missing, or potentially check if the UI can update the Supervisor config (requires Ingress API token).

Additionally, `run.sh` uses `yaml.dump` (PyYAML), which does not preserve comments. This explains the "rewritten" appearance of the file. Switching to `ruamel.yaml` in the startup script would preserve the file structure.
