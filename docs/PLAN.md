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
| **DS** | Design System | DS1 |
| **F** | Fixes/Bugfixes | F1 |
| **DX** | Developer Experience | DX1 |

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


### [DONE] Rev UI5 — Dashboard Polish & Financials

**Goal:** Transform the Dashboard from a live monitor into a polished financial tool with real-time energy visualization.

---

#### Phase 1: Bug Fixes [DONE]

- [x] **Fix "Now Line" Alignment:** Debug and fix the issue where the "Now line" does not align with the current time/slot (varies between 24h and 48h views).
- [x] **Fix "Cost Reality" Widget:** Restore "Plan Cost" series in the Cost Reality comparison widget.

---

#### Phase 2: Energy Flow Chart [DONE]

- [x] **New Component:** Create an energy flow chart card for the Dashboard.
- [x] Show real-time flow between: PV → Battery → House Load → Grid (import/export).
- [x] Use animated traces and "hubs" like "github.com/flixlix/power-flow-card-plus".
- [x] Follow the design system in `docs/design-system/AI_GUIDELINES.md`.
- [x] **Infrastructure**: Stabilized WebSocket server with `eventlet` in `scripts/dev-backend.sh`.

---

#### Phase 3: Chart Polish [DONE]

- [x] Render `soc_target` as a step-line (not interpolated).
- [x] Refactor "Now Line" to Chart.js Plugin (for Zoom compatibility).
- [x] Implement mouse-wheel zoom for the main power chart.
- [x] Add tooltips for Price series explaining "VAT + Fees" breakdown.
- [ ] Visual Polish (Gradients, Annotations, Thresholds) - **Moved to Rev UI6**.

---

#### Phase 4: Financial Analytics - **Moved to Rev UI6**

---

### [PLANNED] Rev UI6 — Chart Makeover & Financials

**Goal:** Achieve a "Teenage Engineering" aesthetic and complete the financial analytics.

**Brainstorming: Chart Aesthetics**

> [!NOTE]
> Options maximizing "Teenage Engineering" + "OLED" vibes.

*   **Option A: "The Field" (V2)**
    *   *Vibe:* OP-1 Field / TX-6. Smooth, tactile, high-fidelity.
    *   *Grid:* **Fixed**: Real CSS Dot Grid (1px dots, 24px spacing).
    *   *Lines:* Soft 3px stroke with bloom/shadow.
    *   *Fill:* Vertical gradient (Color -> Transparent).

*   **Option B: "The OLED" (New)**
    *   *Vibe:* High-end Audio Gear / Cyber.
    *   *Grid:* Faint, dark grey lines.
    *   *Lines:* Extremely thin (2px), Neon Cyan/Pink.
    *   *Fill:* NONE. Pure vector look.
    *   *Background:* Pure Black (#000000).

*   **Option C: "The Swiss" (New)**
    *   *Vibe:* Braun / Brutalist Print.
    *   *Grid:* None.
    *   *Lines:* Thick (4px), Solid Black or Red.
    *   *Fill:* Solid low-opacity blocks (no gradients).
    *   *Font:* Bold, contrasting.

**Plan:**

* [/] **Chart Makeover**: Implement selected aesthetic (**Option A: The Field V2**).
    *   [x] Refactor `DecompositionChart` to support variants.
    *   [x] Implement Dot Grid via **Chart.js Plugin** (production-grade, pans/zooms with chart).
    *   [x] Disable old Chart.js grid lines in `ChartCard`.
    *   [x] Add Glow effect plugin to `ChartCard`.
    *   [ ] Refactor `EnergyFlow` to match Design System.
    *   [ ] Add "Now" line with pulsing "Live" dot.
* [ ] **Financials**: Implement detailed cost and savings breakdown.
* [ ] **Bug Fix**: Fix Dashboard settings persistence.