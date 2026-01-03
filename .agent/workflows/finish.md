---
description: The "Manager" script. Trigger this with /finish to force the AI to validate, document, and commit your work automatically.
---

## **Phase 1: Validation**

1. **Backend Check:**  
   * Run ruff check. \--fix.  
   * Run PYTHONPATH=. python \-m pytest \-q.  
   * If fail: Fix errors and retry (Max 3 attempts).  
2. **Frontend Check:**  
   * Run cd frontend && pnpm lint \--fix.  
   * Run cd frontend && pnpm test \--run.  
   * If fail: Fix errors and retry.

## **Phase 2: Documentation**

1. Read docs/PLAN.md.  
2. Check off the items completed in this session.  
3. If new tasks were discovered, add them to docs/BACKLOG.md.

## **Phase 3: Semantic Commit**

1. Generate a commit message based on git diff.  
2. **Constraint:** Use strict Conventional Commits format: type(scope): description.  
3. Execute: git commit \-am "message"  
4. Report: "Task successfully verified, documented, and committed."