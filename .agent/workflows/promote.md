---
description: Promotes Backlog item(s) to Plan
---

## **Step 1: Review Backlog**

1. Read docs/BACKLOG.md.  
2. List the high-priority items found there.  
3. **STOP** and ask the user: "Which tasks should I move to the active Plan? (Reply with numbers or 'Top 3')"

## **Step 2: Transfer to Plan**

1. Based on user input, extract the selected tasks from docs/BACKLOG.md.  
2. Read docs/PLAN.md.  
3. Append these tasks to the **BOTTOM** of docs/PLAN.md.  
   * Create a new "Phase" or "Rev" header if one doesn't exist for these tasks (ask user for a name if unsure, e.g., "Rev 5").

## **Step 3: Cleanup**

1. Remove the transferred tasks from docs/BACKLOG.md.  
2. Run git add docs/.  
3. Run git commit \-m "docs(plan): promote tasks from backlog".