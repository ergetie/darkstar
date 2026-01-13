# Manual Test Script: Darkstar UI Validation

**Status:** ACTION REQUIRED
**Date:** 2026-01-13
**Version:** v2.4.9-beta

Per the audit plan, the following items require manual user verification as they involve interactive UI states that cannot be verified via static code analysis.

## 🟢 Settings Persistence Tests

| ID | Test Case | Steps | Expected Result | Status |
|----|-----------|-------|=================|--------|
| **3.1** | System Tab Save | 1. Go to Settings > System<br>2. Toggle "Solar panels installed" OFF<br>3. Click Save<br>4. Refresh Page | Toggle remains OFF after refresh | [ ] |
| **3.2** | Parameters Tab Save | 1. Go to Settings > Charging<br>2. Change "Price smoothing" to `0.10`<br>3. Click Save<br>4. Refresh Page | Value `0.10` persists | [ ] |
| **3.3** | Advanced Tab Save | 1. Go to Settings > Advanced<br>2. Change "Min sample threshold" to `5`<br>3. Click Save<br>4. Refresh Page | Value `5` persists | [ ] |
| **3.4** | UI Tab Save | 1. Go to Settings > UI<br>2. Change theme to "Nordic Dark"<br>3. Click Save<br>4. Refresh Page | Theme remains "Nordic Dark" | [ ] |
| **3.9** | Concurrency | 1. Open Darkstar in two tabs<br>2. Change a setting in Tab A (don't save)<br>3. Change a different setting in Tab B and Save<br>4. return to Tab A and Save | Last write wins, no crash/error | [ ] |

## 🟢 Interactive Elements

| ID | Test Case | Steps | Expected Result | Status |
|----|-----------|-------|=================|--------|
| **3.10** | Toggle Persistence | 1. Toggle any boolean switch<br>2. Navigate away and back | Switch state is preserved | [ ] |
| **3.11** | Dropdown Persist | 1. Change "Nordpool Price Area" dropdown<br>2. Save and Refresh | Selection is preserved | [ ] |
| **3.12** | Dial Dragging | 1. Drag Azimuth dial pointer<br>2. Drag Tilt dial pointer | Values update smoothly and snap to increments | [ ] |

## 🟢 Dashboard & Charts

| ID | Test Case | Steps | Expected Result | Status |
|----|-----------|-------|=================|--------|
| **3.16** | Empty Chart | 1. Stop backend/planner<br>2. Load dashboard | Chart handles empty data gracefully (no white screen) | [ ] |
| **3.17** | Partial Data | 1. View dashboard mid-day | Chart shows mix of history and forecast clearly | [ ] |
| **3.20** | Banner Dismiss | 1. Click 'X' on any warning banner<br>2. Refresh page | Banner reappears (session only) OR stays gone (local storage) | [ ] |

## 🟢 Mobile Responsiveness (Phase 11)

| ID | Test Case | Steps | Expected Result | Status |
|----|-----------|-------|=================|--------|
| **11.6** | Touch Dropdowns | 1. Open Settings on request phone<br>2. Tap any dropdown | Options are easily tapable (min 44px) | [ ] |
| **11.8** | Sidebar Collapse | 1. Resize browser to <768px | Sidebar becomes hamburger menu | [ ] |

## 🟢 Error Handling (Phase 7)

| ID | Test Case | Steps | Expected Result | Status |
|----|-----------|-------|=================|--------|
| **7.3** | Network Timeout | 1. Disconnect Network<br>2. Try to Save Settings | "Network Error" or "Offline" toast appears | [ ] |
| **7.6** | Inline Errors | 1. Enter text in number field (if possible)<br>2. Save | Red border + "Must be a number" message | [ ] |
