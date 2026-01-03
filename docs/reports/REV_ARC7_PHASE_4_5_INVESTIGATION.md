# Investigation Report: Rev ARC7 Phase 4 & 5

**Date:** 2026-01-04
**Subject:** Necessity of Rev ARC7 Phase 4 (Dashboard Bundle) & Phase 5 (HA Optimization)
**Status:** **RECOMMENDED FOR IMPLEMENTATION**

## 1. Executive Summary

While the current systems (Phase 1-3) have successfully reduced Dashboard load times significantly via caching, a deep-dive investigation into the codebase reveals fundamental architectural inefficiencies that threaten "Production Ready" status on constrained hardware (Raspberry Pi) and high-latency networks. 

**Conclusion:** To achieve the "State of the Art" and "100% Production Ready" goals, **Phase 5 is CRITICAL** and **Phase 4 is HIGHLY RECOMMENDED**.

## 2. Findings & Analysis

### Phase 5: HA Integration Optimization (CRITICAL)

The current implementation of `api/energy/today` and `api/ha/average` contains a severe performance anti-pattern.

*   **Issue:** `backend/inputs.py` uses `requests.get()` in a blocking manner without a persistent session.
*   **Impact:** The `get_energy_today` endpoint triggers **6 sequential HTTP requests** to Home Assistant.
    *   Each request involves: SSL Handshake → Request → Response → Connection Close.
    *   On a Raspberry Pi or if HA is busy, this introduces **600ms - 2000ms of avoidable latency**.
    *   If the 60s cache expires, the user hits this full latency wall.
*   **Recommendation:**
    *   **Must Implement:** Batching (Task 5.2). Using a single `/api/states` call reduces overhead by ~83%.
    *   **Stretch:** WebSocket integration (Task 5.3) would eliminate polling entirely, but batching is the minimum viable fix for "Production Ready".

### Phase 4: Dashboard Bundle API (HIGHLY RECOMMENDED)

The Dashboard currently makes **11 parallel API calls** (5 critical, 6 deferred) on load.

*   **Issue:** Browsers (Chrome/Firefox) typically limit concurrent connections per domain to **6**.
*   **Impact:**
    *   The 5 critical calls + 6 deferred calls saturate the browser's connection pool.
    *   "Head-of-line blocking" occurs: deferred low-priority requests might block critical ones if the network is jittery.
    *   On high-latency networks (e.g., accessing via mobile remotely), the RTT (Round Trip Time) penalty is paid 11 times.
*   **Recommendation:**
    *   Implement `/api/dashboard/bundle` to merge the 5 critical calls into 1.
    *   This ensures the dashboard renders immediately with a single RTT, leaving the connection pool open for the lazy-loaded charts and history.

## 3. Pros / Cons

| Phase | Pros | Cons | Verdict |
| :--- | :--- | :--- | :--- |
| **Phase 4 (Bundle)** | • Atomic state (no UI tearing)<br>• Single RTT (great for mobile/remote)<br>• Unblocks browser connection pool | • Moderate refactor complexity<br>• Large JSON payload (compression needed) | **Keep** |
| **Phase 5 (HA Opt)** | • **Fixes 6x sequential API calls**<br>• Reduces load on Home Assistant<br>• Critical for RPi/HA Add-on stability | • Refactoring `inputs.py` required<br>• New dependency on HA Batch/WS API | **MANDATORY** |

## 4. Implementation Plan Update

I recommend marking both phases as **[IN PROGRESS]** or **[NEXT]** and proceeding with implementation.

### Immediate Next Steps
1.  **Refactor `inputs.py`** to use `httpx.AsyncClient` with a persistent session (Phase 5).
2.  **Implement `get_ha_states_batch`** to fetch all energy sensors in one go (Phase 5).
3.  **Implement `/api/dashboard/bundle`** to aggregate critical data (Phase 4).
