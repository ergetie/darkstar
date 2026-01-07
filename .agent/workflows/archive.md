---
description: Moves the last section of Plan to the top of Changelog.
---

## **Step 1: Analyze PLAN.md**

1. Read docs/PLAN.md.  
2. Identify the **Completed Revisions**. This is typically REV sections in the file that has all items checked off. (If a REV has all items checked off but the title is not marked "DONE" then mark it as done and proceed).
3. Extract this section completely (Header \+ Content). (Do not touch any unfinished REV's!)

## **Step 2: Invert and Transfer**

1. Read docs/CHANGELOG_PLAN.md.  
2. **CRITICAL:** Insert the extracted section at the **TOP** of CHANGELOG\_PLAN.md (immediately after the main title/header). (Make sure it fits the "ERA" otherwise create a new "ERA" section.)  
   * *Reasoning:* The Changelog is reverse-chronological (newest first).  
3. Save docs/CHANGELOG\_PLAN.md.

## **Step 3: Cleanup**

1. Remove the extracted section from docs/PLAN.md.  
2. Ensure docs/PLAN.md is clean (no extra newlines at the bottom).  
3. Save docs/PLAN.md.

## **Step 4: Commit**

1. Run git add docs/PLAN.md docs/CHANGELOG\_PLAN.md.  
2. Run git commit \-m "docs(plan): archive completed phase".