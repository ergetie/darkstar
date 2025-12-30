# Darkstar Energy Manager: Active Plan

**Vision: From Calculator to Agent**
Darkstar is transitioning from a deterministic optimizer (v1) to an intelligent energy agent (v2). It does not just optimize based on static config; it observes context (Weather, Vacation, Prices), predicts outcomes (Aurora ML), and actively strategizes (Strategy Engine) to maximize efficiency and comfort.

---

## Revision Naming Conventions

| Prefix | Area | Examples |
|--------|------|----------|
| **K** | Kepler (MILP solver) | K1-K19 |
| **E** | Executor | E1 |
| **A** | Aurora (ML) | A25-A29 |
| **H** | History/DB | H1 |
| **O** | Onboarding | O1 |
| **UI** | User Interface | UI1, UI2 |
| **F** | Fixes/Bugfixes | F1 |

---

## 🤖 AI Instructions (Read First)

1.  **Structure:** This file is a **chronological stream**. Newest items are at the **bottom**.
    
2.  **No Reordering:** Never move items. Only update their status or append new items.
    
3.  **Status Protocol:**
    
    -   Update the status tag in the Header: `### [STATUS] Rev ID — Title`
        
    -   Allowed Statuses: `[DRAFT]`, `[PLANNED]`, `[IN PROGRESS]`, `[DONE]`, `[PAUSED]`, `[OBSOLETE]`.
        
4.  **New Revisions:** Always use the template below.
    
5.  **Cleanup:** When this file gets too long (>15 completed items), move the oldest `[DONE]` items to `CHANGELOG.md`.
    

### Revision Template


```

### [STATUS] Rev ID — Title

**Goal:** Short description of the objective.
**Plan:**

* [ ] Step 1
* [ ] Step 2

```

---

## 📜 Revision Stream

*All completed revisions have been moved to [CHANGELOG_PLAN.md](CHANGELOG_PLAN.md).*§

### [DONE] Rev UI3 — UX Polish Bundle

**Goal:** Improve frontend usability and safety with three key improvements.

**Plan:**
- [x] Add React ErrorBoundary to prevent black screen crashes
- [x] Replace entity dropdowns with searchable combobox
- [x] Add light/dark mode toggle with backend persistence
- [x] Migrate Executor entity config to Settings tab
- [x] Implement new TE-style color palette (see `frontend/color-palette.html`)

**Files:**
- `frontend/src/components/ErrorBoundary.tsx` [NEW]
- `frontend/src/components/EntitySelect.tsx` [NEW]
- `frontend/src/components/ThemeToggle.tsx` [NEW]
- `frontend/src/App.tsx` [MODIFIED]
- `frontend/src/index.css` [MODIFIED]
- `frontend/tailwind.config.cjs` [MODIFIED]
- `frontend/src/components/Sidebar.tsx` [MODIFIED]
- `frontend/src/pages/Settings.tsx` [MODIFIED]
- `frontend/index.html` [MODIFIED]
- `frontend/color-palette.html` [NEW] — Design reference
- `frontend/noise.png` [NEW] — Grain texture

**Color Palette Summary:**
- Light mode: TE/OP-1 style with `#DFDFDF` base
- Dark mode: Deep space with `#0f1216` canvas
- Flair colors: Same bold colors in both modes (`#FFCE59` gold, `#1FB256` green, `#A855F7` purple, `#4EA8DE` blue)
- FAT 12px left border on metric cards
- Button glow in dark mode only
- Sharp grain texture overlay (4% opacity)
- Mini bar graphs instead of sparklines

---

### [IN PROGRESS] Rev UI4 — Settings Page Audit & Cleanup

**Goal:** Ensure the Settings page is the complete source of truth for all configuration. User should never need to manually edit `config.yaml`.

---

#### Phase 1: Config Key Audit & Documentation ✅

Map every config key to its code usage and document purpose. Identify unused keys.

**Completed:**
- [x] Add explanatory comments to every key in `config.default.yaml`
- [x] Verify each key is actually used in code (grep search)
- [x] Remove 28 unused/orphaned config keys:
  - `smoothing` section (8) - replaced by Kepler ramping_cost
  - `decision_thresholds` (3) - legacy heuristics
  - `arbitrage` section (8) - replaced by Kepler MILP
  - `kepler.enabled/primary_planner/shadow_mode` (3) - vestigial
  - `manual_planning` unused keys (3) - never referenced
  - `schedule_future_only`, `sync_interval_minutes`, `carry_forward_tolerance_ratio`
- [x] Document `secrets.yaml` vs `config.yaml` separation
- [x] Add backlog items for unimplemented features (4 items)

**Remaining:**
- [ ] Create categorization proposal: Normal vs Advanced
- [ ] Discuss: vacation_mode dual-source (HA entity for ML vs config for anti-legionella)
- [ ] Discuss: grid.import_limit_kw vs system.grid.max_power_kw naming/purpose

---

#### Phase 2: Entity Consolidation Design ✅

Design how HA entity mappings should be organized in Settings UI.

**Key Design Decision: Dual HA Entity / Config Pattern**

Some settings exist in both HA (entities) and Darkstar (config). Users want:
- Darkstar works **without** HA entities (config-only mode)
- If HA entity exists, **bidirectional sync** with config
- Changes in HA → update Darkstar, changes in Darkstar → update HA

**Current dual-source keys identified:**
| Key | HA Entity | Config | Current Behavior |
|-----|-----------|--------|------------------|
| vacation_mode | `input_sensors.vacation_mode` | `water_heating.vacation_mode.enabled` | HA read for ML, config for anti-legionella (NOT synced) |
| automation_enabled | `executor.automation_toggle_entity` | `executor.enabled` | HA for toggle, config for initial state |

**Write-only keys (Darkstar → HA, no read-back):**
| Key | HA Entity | Purpose |
|-----|-----------|---------|
| soc_target | `executor.soc_target_entity` | Display/automation only, planner sets value |

**Tasks:**
- [x] Design bidirectional sync mechanism for dual-source keys
- [x] Decide which keys need HA entity vs config-only vs both
- [x] Propose new Settings tab structure (entities in dedicated section)
- [x] Design "Core Sensors" vs "Control Entities" groupings
- [x] Determine which entities are required vs optional
- [x] Design validation (entity exists in HA, correct domain)

**Missing Entities to Add (from audit):**
- [x] `input_sensors.today_*` (6 keys)
- [x] `executor.manual_override_entity`

---

#### Phase 3: Settings UI Implementation ✅

Add all missing config keys to Settings UI with proper categorization.

**Tasks:**
- [x] Restructure Settings tabs (System, Parameters, UI, Advanced)
- [x] Group Home Assistant entities at bottom of System tab
- [x] Add missing configuration fields (input_sensors, executor, notifications)
- [x] Implement "Danger Zone" in Advanced tab with reset confirmation
- [x] ~~Normal vs Advanced toggle~~ — Skipped (Advanced tab exists)
- [x] Add inline help/tooltips for every setting
  - [x] Create `scripts/extract-config-help.py` (parses YAML inline comments)
  - [x] Generate `config-help.json` (136 entries extracted)
  - [x] Create `Tooltip.tsx` component with hover UI
  - [x] Integrate tooltips across all Settings tabs
- [x] Update `config.default.yaml` comments to match tooltips

---

#### Phase 4: Verification ✅

- [x] Test all Settings fields save correctly to `config.yaml`
- [x] Verify config changes take effect (planner re-run, executor reload)
- [x] Confirm no config keys are missing from UI (89 keys covered, ~89%)
- [x] ~~Test Normal/Advanced mode toggle~~ — N/A (skipped)
- [x] Document intentionally hidden keys (see verification_report.md)

**Additional Fixes:**
- [x] Vacation mode banner: instant update when toggled in QuickActions
- [x] Vacation mode banner: corrected color to warning (#F59E0B) per design system

---

**Audit Reference:** See `config_audit.md` in artifacts for detailed key mapping.

---

### [PLANNED] Rev UI5 — Dashboard Polish & Financials

**Goal:** Transform the Dashboard from a live monitor into a polished financial tool with real-time energy visualization.

---

#### Phase 1: Bug Fixes

- [ ] **Fix "Now Line" Alignment:** Debug and fix the issue where the "Now line" does not align with the current time/slot (varies between 24h and 48h views).
- [ ] **Fix "Cost Reality" Widget:** Restore "Plan Cost" series in the Cost Reality comparison widget.

---

#### Phase 2: Energy Flow Chart

- [ ] **New Component:** Create an energy flow chart card for the Dashboard.
- [ ] Show real-time flow between: PV → Battery → House Load → Grid (import/export).
- [ ] Use animated traces and "hubs" like "github.com/flixlix/power-flow-card-plus".
- [ ] Follow the design system in `docs/design-system/AI_GUIDELINES.md`.

---

#### Phase 3: Chart Polish

- [ ] Render `soc_target` as a step-line (not interpolated).
- [ ] Implement mouse-wheel zoom for the main power chart.
- [ ] Add tooltips for Price series explaining "VAT + Fees" breakdown.

---

#### Phase 4: Financial Analytics

- [ ] Integrate `pricing.subscription_fee_sek_per_month` into the cost engine.
- [ ] Calculate and display monthly ROI / Break-even metrics on Dashboard.

---

### NEXT REV HERE