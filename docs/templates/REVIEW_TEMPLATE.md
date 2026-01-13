# Project Audit Report Template

**Target:** [Project Name/Version]
**Date:** YYYY-MM-DD
**Auditor:** [Agent Name/Model]
**Status:** In Progress / Complete

---

## Executive Summary

[Brief high-level summary of the codebase health, critical risks, and readiness state.]

| Category | Status | Key Findings |
| :--- | :--- | :--- |
| **Docs** | ⚪ | ... |
| **Security** | ⚪ | ... |
| **Perf** | ⚪ | ... |
| **A11y** | ⚪ | ... |
| **Mobile** | ⚪ | ... |

### Top 3 Critical Action Items
1.  **[Area]:** [Action]
2.  **[Area]:** [Action]
3.  **[Area]:** [Action]

---

## Priority Action List (Bridge to Task.md)

### Immediate (Blocks Release)
1. [ ] [Action Item]
2. [ ] [Action Item]

### Short-Term (next Sprint)
3. [ ] [Action Item]

### Backlog
4. [ ] [Action Item]

---

## 🔴 Critical Issues (P0)

### 1. [Issue Name]
- **Location:** `path/to/file`
- **Impact:** [Why this matters]
- **Evidence:** [Code snippet or grep result]
- **Recommendation:** [Fix]

---

## 🟡 High Priority (P1)

### [Issue Name]
- ...

---

## 🟢 Medium Priority (P2)

### [Issue Name]
- ...

---

## ✅ Verified Good
- [List things that were checked and found correct]

---

## 💡 Brainstorming & Improvements

### [Improvement Area]
- **Idea:** [Description]
- **Benefit:** [Why do this?]
- **Effort:** Low / Medium / High

---

## Audit Checklist

### Phase 1: Configuration & Environment
- [ ] 1.1 Audit config structure for duplication
- [ ] 1.2 Verify default values are sane
- [ ] 1.3 Identify sensitive keys (secrets)
- [ ] 1.4 Check for dead/unimplemented config keys

### Phase 2: Codebase Hygiene
- [ ] 2.1 Search for TODOs/FIXMEs
- [ ] 2.2 Identify dead code / unused files
- [ ] 2.3 Check for unused imports
- [ ] 2.4 Verify no hardcoded credentials

### Phase 3: Functionality & Bugs
- [ ] 3.1 Verify core critical paths
- [ ] 3.2 Check for production debug logging
- [ ] 3.3 Test valid/invalid input ranges
- [ ] 3.4 Verify state persistence

### Phase 4: UX & Usability
- [ ] 4.1 First-run / Onboarding experience
- [ ] 4.2 Error states and feedback (Toasts/Banners)
- [ ] 4.3 Empty states
- [ ] 4.4 Loading states

### Phase 5: Copy & Content
- [ ] 5.1 Spell check user-facing text
- [ ] 5.2 Verify technical terminology consistency
- [ ] 5.3 Check for placeholder text

### Phase 6: Visual Design System
- [ ] 6.1 Verify usage of design tokens (No hardcoded hex)
- [ ] 6.2 Check spacing/padding consistency
- [ ] 6.3 Verify responsiveness
- [ ] 6.4 Check dark/light mode compatibility

### Phase 7: Error Handling
- [ ] 7.1 API error handling (4xx/5xx)
- [ ] 7.2 Network timeout/offline handling
- [ ] 7.3 Form validation feedback
- [ ] 7.4 Global error boundaries

### Phase 8: Component Logic Edge Cases
- [ ] 8.1 Zero/Null/Undefined states
- [ ] 8.2 Max/Min boundary testing
- [ ] 8.3 Typographical edge cases (long strings)

### Phase 9: Performance
- [ ] 9.1 Bundle size analysis
- [ ] 9.2 Rendering performance (React)
- [ ] 9.3 Database query efficiency (N+1, Blocking I/O)
- [ ] 9.4 Asset optimization

### Phase 10: Accessibility (a11y)
- [ ] 10.1 Semantic HTML usage
- [ ] 10.2 Keyboard navigation
- [ ] 10.3 ARIA labels and live regions
- [ ] 10.4 Contrast ratios
- [ ] 10.5 Screen reader flow

### Phase 11: Mobile & Responsive
- [ ] 11.1 Touch target sizes (>44px)
- [ ] 11.2 Layout stacking on small screens
- [ ] 11.3 Gestures / Interaction modes

### Phase 12: Documentation
- [ ] 12.1 Readme accuracy
- [ ] 12.2 Setup guide verification
- [ ] 12.3 API documentation completeness

### Phase 13: Security
- [ ] 13.1 Injection risks (SQL, XSS)
- [ ] 13.2 Auth/Permission checks
- [ ] 13.3 Data leakage (logs, headers)
- [ ] 13.4 Dependency vulnerabilities

### Phase 14: API & Architecture
- [ ] 14.1 REST/RPC consistency
- [ ] 14.2 Type safety (Pydantic/TS)
- [ ] 14.3 Circular dependencies

### Phase 15: Testing & QA
- [ ] 15.1 Unit test coverage gaps
- [ ] 15.2 Integration test gaps
- [ ] 15.3 E2E test gaps
