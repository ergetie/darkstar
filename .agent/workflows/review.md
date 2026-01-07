---
description: Code Reviewer
---

## **Phase 1: Analysis**

1. **Gather Context:**  
   * Run git diff \--staged (if empty, run git diff).  
   * Identify modified files.  
2. **Strict Audit:** Analyze the diff against these specific criteria:  
   * **Security:** Are there hardcoded secrets? Unsanitized inputs?  
   * **Performance:** Are there N+1 queries? Unnecessary re-renders?  
   * **Robustness:** Is there error handling? (try/catch, Error Boundaries).  
   * **Vibe:** Does the UI match the "Production Grade" standard?

## **Phase 2: Report**

* If **Critical Issues** found:  
  * 🛑 **STOP.** List the specific lines and the risk.  
  * Ask: "Should I fix these automatically?"  
* If **Minor Suggestions** found:  
  * List them as bullet points.  
  * Ask: "Proceed to commit, or refine?"

## **Phase 3: Auto-Fix (Optional)**

* If user says "Fix":  
  * Apply fixes for the critical issues.  
  * Re-run the linter.  
  * Re-run /review to verify.