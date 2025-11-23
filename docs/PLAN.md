# Darkstar Energy Manager: Master Plan

**Vision: From Calculator to Agent**
Darkstar is transitioning from a deterministic optimizer (v1) to an intelligent energy agent (v2). It does not just optimize based on static config; it observes context (Weather, Vacation, Prices), predicts outcomes (Aurora ML), and actively strategizes (Strategy Engine) to maximize efficiency and comfort.

---

## Active Revisions

### Rev 61 - The Aurora Tab (AI Agent Interface)
**Goal:** Transform the UI from a "Developer Console" into an "Intelligent Agent" interface. This new tab (`/aurora`) visualizes the system's "Brain," explaining *why* decisions are made, visualizing forecast corrections, and allowing high-level "Risk" adjustments.

#### 1. Backend: The Aurora API (`backend/api/aurora.py`)
*   **New Blueprint:** `aurora_bp` registered in `backend/webapp.py`.
*   **Endpoint:** `GET /api/aurora/dashboard`
    *   **Identity:** Compute "Graduation Level" (Infant < 14d, Statistician < 60d, Graduate > 60d) based on `learning_runs` count and data depth from `learning.db`.
    *   **State:**
        *   *Risk Profile:* Derive "Persona" from `config.s_index` (e.g., <1.0 = "Gambler", 1.0–1.2 = "Balanced", >1.2 = "Paranoid").
        *   *Weather Context:* Fetch Weather Volatility (0–1) from `ml.weather` for the next 48h.
    *   **Horizon Series:** Return an aligned 48h timeseries containing:
        *   `base` (The raw physics/avg model).
        *   `correction` (The ML adjustment).
        *   `final` (The value used by Planner).
    *   **History:** Last 14 days of "Total Correction Volume" (sum of abs(corrections)) to show agent activity.
*   **Endpoint:** `POST /api/aurora/briefing`
    *   **Logic:** Uses `backend.strategy.voice` (LLM) to generate a 2-sentence summary of the Dashboard state (e.g., "I am feeling paranoid due to storm variance...").

#### 2. Frontend: Core & Types (`frontend/src/`)
*   **Types:** Update `types.ts` with `AuroraDashboardResponse`, `AuroraState`, `AuroraIdentity`.
*   **API:** Update `api.ts` with `Api.aurora.dashboard()` and `Api.aurora.briefing()`.

#### 3. Frontend: The Aurora UI (`frontend/src/pages/Aurora.tsx`)
*   **Identity Header:**
    *   **Avatar:** Visual icon (Cap/Shield) representing Graduation and Risk state.
    *   **The Pulse:** An animated "heartbeat" line indicating system stability (Green = Stable, Amber = Volatile/Correcting, Red = Anomaly).
*   **Daily Briefing Card:** Text block displaying the LLM-generated summary.
*   **Decomposition Chart (`DecompositionChart.tsx`):**
    *   A custom `Chart.js` implementation.
    *   **Layer 1 (Line):** Base Forecast.
    *   **Layer 2 (Stacked Bar):** The Correction (Green for + / Red for -).
    *   **Layer 3 (Dashed Line):** Final Forecast.
    *   *Interaction:* Tooltip explains the correction reason (e.g., "Volatile Weather").
*   **The Risk Dial:**
    *   A slider component mapping to `s_index.base_factor`.
    *   Visual labels: "Gambler" (Low) ↔ "Prepper" (High).
    *   *Action:* Updates config via `/api/config/save`.

#### 4. Verification
*   **Database:** Ensure `learning.py` is correctly populating `pv_correction_kwh` in `slot_forecasts` (Rev 59/60 check).
*   **Performance:** Ensure `ml.weather.get_weather_volatility` is cached or fast enough for dashboard loads.

#### 5. Aurora UX Polish Roadmap (Rev 61 Phase 2)
*   **Layout & Storytelling**
    *   Align `/aurora` layout with Dashboard/Forecasting: shared hero row, 2-column content grid, clear top→middle→bottom narrative (Identity → Horizon → Impact).
    *   Keep consistent inner padding (`p-4 md:p-5`) and card spacing across all Aurora cards.
*   **Identity & Agent Presence**
    *   Replace emoji avatar with a dedicated "Aurora bot" badge (robot/eye glyph in a subtle accent frame).
    *   Add compact KPIs in the hero card: Graduation (label + days), current risk persona + factor, and today’s total correction volume.
    *   Introduce a small status capsule (e.g., "Calibrating", "Confident", "Cautious") derived from graduation, volatility, and correction volume.
*   **Heartbeat / Vitals**
    *   Replace wifi-style bars with a more organic "vital signal": ECG-style line, pulsing core, or animated energy flow bar.
    *   Color and amplitude of the signal should reflect volatility/risk, but remain subtle and theme-consistent.
    *   Place the vitals element adjacent to the Aurora badge in the hero card with a clear label (e.g., "Vitals" / "Signal").
*   **Risk Dial as Control Surface**
    *   Refine the Risk Dial card into a proper control module: clear title + description, slider row, tick row, and textual interpretation row.
    *   Segment the slider background into semantic regions (Gambler / Balanced / Paranoid) using gentle tints, not harsh gradients.
    *   Show live textual feedback while dragging (e.g., "More aggressive with cheap slots" vs "Preserving extra reserve for uncertainty").
    *   Add safe controls: "Apply" vs "Reset to Recommended" buttons for S-index changes.
*   **Decomposition Chart UX**
    *   Upgrade the load/PV toggle to a pill toggle with icons (e.g., bolt for load, sun for PV) and smooth crossfade between modes.
    *   Keep correction bars translucent and visually differentiate PV vs load corrections when both are shown.
    *   Add a small summary strip below the chart (e.g., "+X kWh added, −Y kWh shaved over 48h") and optionally highlight the most-corrected period.
*   **Intervention History / Impact**
    *   Redesign the 14-day correction history as a low-profile "Impact" strip under the chart, with clear trend indication (more/less active than last week).
    *   Consider two-tone bars per day to distinguish PV vs load corrections in the same visual footprint.
*   **Briefing as Console Output**
    *   Style the briefing card as a small system console: darker panel, "AURORA//LOG" label, prompt marker (e.g., ">") before text.
    *   Include structured context above the free text (Mode, Persona, Volatility, Horizon) and a "Last updated" timestamp.
*   **Microinteractions & Feedback**
    *   On risk changes, briefly animate the hero border or avatar glow and show a non-intrusive confirmation message (S-index updated).
    *   During briefing fetch, reflect loading state in both button and text (dim old text, fade in new).
*   **Copy & Naming**
    *   Standardise Aurora section names: "Aurora Status", "Aurora Briefing", "Forecast Decomposition", "Intervention History", "Risk Profile".
    *   Keep persona labels concise and consistent, with optional tooltips for deeper explanation.

*Implementation phases:*
*   **Phase 2.1:** Hero card cleanup (padding, KPIs), new vitals/heartbeat visual, and improved Risk Dial module.
*   **Phase 2.2:** Decomposition chart toggle polish and Impact strip redesign.
*   **Phase 2.3:** Briefing console styling, microinteractions, and copy tightening.

### Rev XX - PUT THE NEXT REVISION ABOVE THIS LINE!

---

## Backlog

### 🧠 Strategy & Aurora (AI)
*   **[Rev A25] Manual Plan Simulate Regression**: Verify if manual block additions in the Planning Tab still work correctly with the new `simulate` signature (Strategy engine injection).
*   **[Rev A27] Scheduled Retraining**: Automate `ml/train.py` execution (e.g., weekly) to keep Aurora models fresh without manual intervention. Similar to Rev 57!
*   **[Rev A28] The Analyst (Expansion)**: Add "Grid Peak Shaving" capability—detect monthly peaks and force-discharge battery to cap grid import fees.
*   **[Rev A29] Smart EV Integration**: Prioritize home battery vs. EV charging based on "Departure Time" (requires new inputs).

### 🖥️ UI & Dashboard
*   **[UI] Reset Learning**: Add "Reset Learning for Today" button to Settings/Debug to clear cached S-index/metrics without using CLI.
*   **[UI] Chart Polish**:
    *   Render `soc_target` as a step-line series.
    *   Add zoom support (wheel/controls).
    *   Offset tooltips to avoid covering data points.
    *   Ensure price series includes full 24h history even if schedule is partial.
*   **[UI] Mobile**: Improve mobile responsiveness for Planning Timeline and Settings.

### ⚙️ Planner & Core
*   **[Core] Dynamic Window Expansion (Smart Thresholds)**: *Note: Rev 20 in Aurora v2 Plan claimed this was done, but validating if fully merged/tested.* Logic: Allow charging in "expensive" slots if the "cheap" window is physically too short to reach Target SoC.
*   **[Core] Sensor Unification**: Refactor `inputs.py` / `learning.py` to read *all* sensor IDs from `config.yaml` (`input_sensors`), removing the need for `secrets.yaml` to hold entity IDs.

### 🛠️ Ops & Infrastructure
*   **[Ops] Deployment**: Document/Script the transfer of `planner_learning.db` and models to production servers.
*   **[Ops] Error Handling**: Audit all API calls for graceful failure states (no infinite spinners).

---

## Future Ideas (Darkstar 3.x+?)
*   **Multi-Model Aurora**: Separate ML models for Season or Weekday/Weekend.
*   **Admin Tools:** Force Retrain button, Clear Learning Cache button.
