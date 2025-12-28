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

#### Phase 1: Config Key Audit & Documentation

Map every config key to its code usage and document purpose. Identify unused keys.

**Tasks:**
- [ ] Add explanatory comments to every key in `config.default.yaml`
- [ ] Verify each key is actually used in code (grep search)
- [ ] Flag any unused/orphaned config keys for removal discussion
- [ ] Document which keys are in `secrets.yaml` vs `config.yaml` (secrets = API keys/tokens only)
- [ ] Create categorization proposal: Normal vs Advanced vs Internal

**Discussion Points (resolve before Phase 2):**
- [ ] Which keys should be hidden entirely or removed from config? (e.g., `kepler.enabled` has no alternative)
- [ ] Should `vacation_mode` be HA entity, config toggle, or both?
- [ ] How should we categorize ~70 missing config keys?

---

#### Phase 2: Entity Consolidation Design

Design how HA entity mappings should be organized in Settings UI.

**Tasks:**
- [ ] Propose new Settings tab structure (entities may need dedicated section)
- [ ] Design "Core Sensors" vs "Control Entities" groupings
- [ ] Determine which entities are required vs optional
- [ ] Decide if `input_sensors.*` and `executor.*_entity` should merge or stay separate
- [ ] Design validation (entity exists in HA, correct domain)

**Missing Entities to Add (from audit):**
- `input_sensors.vacation_mode`
- `input_sensors.alarm_state`
- `input_sensors.total_*` (6 keys)
- `input_sensors.today_*` (6 keys)
- `executor.automation_toggle_entity`
- `executor.manual_override_entity`

---

#### Phase 3: Settings UI Implementation

Add all missing config keys to Settings UI with proper categorization.

**Tasks:**
- [ ] Restructure Settings tabs (System, Entities, Parameters, UI, Advanced?)
- [ ] Implement "Normal" vs "Advanced" mode toggle
- [ ] Add missing `input_sensors.*` fields (15 keys)
- [ ] Add missing `executor.*` fields (2 keys)
- [ ] Add missing config sections:
  - [ ] `pricing.*` (VAT, fees, tax)
  - [ ] `battery_economics.*`
  - [ ] `decision_thresholds.*`
  - [ ] `strategic_charging.*`
  - [ ] `smoothing.*`
  - [ ] `kepler.*` (if not removed)
  - [ ] `automation.schedule.*`
  - [ ] `automation.ml_training.*`
  - [ ] `executor.controller.*`
  - [ ] `forecasting.*`
  - [ ] `grid.*`
  - [ ] `appliances.*`
- [ ] Add inline help/tooltips for every setting
- [ ] Update `config.default.yaml` comments to match tooltips

---

#### Phase 4: Verification

- [ ] Test all Settings fields save correctly to `config.yaml`
- [ ] Verify config changes take effect (planner re-run, executor reload)
- [ ] Confirm no config keys are missing from UI
- [ ] Test Normal/Advanced mode toggle behavior
- [ ] Document any intentionally hidden keys

---

**Audit Reference:** See `config_audit.md` in artifacts for detailed key mapping.

---

### NEXT REV HERE