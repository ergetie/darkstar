---
description: Breaks a vague request into a 100% Production-Grade checklist.
---

## **Phase 1: Requirements Gathering**

1. Read docs/architecture.md (if exists) and docs/PLAN.md.  
2. Analyze \[feature\_request\].  
3. **Constraint Check:** Ensure the feature aligns with the Monorepo structure (React/FastAPI).

## **Phase 2: The Blueprint**

Create a detailed technical specification. DO NOT write code yet.

1. **Data Models:** Define exact Pydantic models / SQL schemas.  
2. **API Contract:** Define endpoints (GET/POST) and expected JSON.  
3. **UI Components:** List React components and state management (Zustand/Context).  
4. **Edge Cases:** List at least 3 potential failure modes (e.g., "Network offline", "Invalid ID").

## **Phase 3: The Task List**

1. Generate a checklist of **Atomic Tasks**.  
   * *Example:* \[ \] Backend: Create Pydantic schema for User  
   * *Example:* \[ \] Tests: Write pytest for invalid login  
2. **Action:** Prepend this new checklist to the **Active Phase** section of docs/PLAN.md.  
3. **Report:** "Plan created. Type /promote to start working on the first task."