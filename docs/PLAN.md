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