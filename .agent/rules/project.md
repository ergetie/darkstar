---
trigger: always_on
---

## **1\. Monorepo Structure**

* **Root:** Core logic (planner.py, inputs.py), ml/, configs.  
* **Frontend:** frontend/ (React+Vite).  
* **Backend:** backend/ (FastAPI).  
* **Docs:** docs/PLAN.md (Active), docs/BACKLOG.md (Future), docs/CHANGELOG_PLAN.md (Archived revs from PLAN.md).

## **2\. Command Protocol**

You must execute commands in the correct directory.

* **Frontend:** ALWAYS cd frontend before running pnpm.  
  * Lint: pnpm lint (Zero tolerance)  
  * Test: pnpm test  
* **Backend:**  
  * Lint: ruff check. or ./lint.sh  
  * Test: python \-m pytest or PYTHONPATH=. python \-m pytest \-q.

## **3\. Git Standards**

**CRITICAL:** You must use **Strict Conventional Commits**.

* **Format:** type(scope): description  
* **Allowed Types:** feat, fix, docs, style, refactor, test, chore, perf.  
* **Scope:** The module or feature being changed (e.g., auth, ui, api).  
* **Examples:**  
  * ✅ feat(auth): add google login provider  
  * ✅ fix(ui): resolve overlap in sidebar  
  * ❌ update login (Reject this)

## **4\. The "Definition of Done"**

You are NOT done with a task until:

1. docs/PLAN.md is updated with progress.  
2. Linting passes (Frontend \+ Backend).  
3. Tests pass.  
4. Changes are committed.

## **5\. Documentation Lifecycle Rules**

* **PLAN.md:** Newest items are at the **BOTTOM**.  
* **CHANGELOG\_PLAN.md:** Newest items are at the **TOP**.  
* **Moving Data:** When archiving, you MUST respect this inversion.