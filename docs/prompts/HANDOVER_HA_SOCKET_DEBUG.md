# HANDOVER: Debugging HA WebSocket Silent Failure

## 🔴 Critical Context
We are debugging a **"Black Box" failure** in the Home Assistant Add-on deployment. 
- **Symptom**: The PowerFlow card is blank (no live data).
- **Status**: The WebSocket connects and authenticates, but **no data flow** was visible in logs.
- **Current Version**: `v2.4.16-beta` (Installed by user).

## 🛠️ The New Diagnostic Tool
We just released `v2.4.16-beta` which adds a **Diagnostics API** to bypass log scraping.
The user will provide the JSON output from: `GET /api/ha-socket`

## 🧠 Diagnostic Analysis Protocol
Match the user's JSON output to one of these scenarios to determine the root cause:

### SCENARIO A: The "Poison Pill" (Parsing/Sanitization Failure)
**Signature:**
- `messages_received` > 0 (counting up)
- `metrics_emitted` == 0 (flatline)
- `stats.errors` contains entries (e.g., `ValueError`, `Sanitized invalid float`)

**Root Cause:**
HA is sending data `ha_socket.py` cannot parse (e.g., `NaN`, `unavailable`, `1,200` with comma), or data that crashes the JSON transport.
**Action:** Fix the parsing logic in `backend/ha_socket.py` to handle this specific edge case.

---

### SCENARIO B: The "Ghost" (Configuration Mismatch)
**Signature:**
- `messages_received` == 0
- `monitored_entities` is populated
- `status` == "running"

**Root Cause:**
The `monitored_entities` configured in `config.yaml` **do not match** the actual entity IDs in Home Assistant. HA accepts the subscription but sends no events because the IDs are wrong.
**Action:** Ask user to check valid entity IDs in HA Developer Tools vs their Darkstar config.

---

### SCENARIO C: The "Frontend Blindness" (Backend Healthy)
**Signature:**
- `messages_received` > 0
- `metrics_emitted` > 0
- `stats.errors` used to be empty or low

**Root Cause:**
The Backend is successfully broadcasting `live_metrics` via Socket.IO. The issue is in the **Frontend (React)** not receiving or rendering them.
**Action:** Debug `frontend/src/services/socket.ts` or `PowerFlowCard.tsx`.

## 📂 Key Files
- `backend/ha_socket.py`: WebSocket client logic (parsing, filtering).
- `backend/core/websockets.py`: Socket.IO transport.
- `docs/RELEASE_NOTES.md`: Changelog for context.
