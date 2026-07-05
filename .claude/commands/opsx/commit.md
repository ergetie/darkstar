---
description: Commit a completed OpenSpec change
---

Commit all files related to a completed change.

**Input**: The argument after `/commit` is the change name (kebab-case), AND/OR a plain description of what to commit. If omitted, infer from context or ask.

**Steps**

1. **Determine what to commit**

   Run `git status` to see all modified and untracked files.

   **If a change name was provided:**
   - Include all files under `openspec/changes/<name>/` and `openspec/changes/archive/*<name>*/` (if already archived)
   - Include all other modified files shown in `git status` — these are the implementation files changed as part of the work
   - Do NOT silently exclude files that look related. Stage everything that belongs to this change.

   **If a description was provided instead:**
   - Use judgement to select only the files relevant to that description
   - If it's unclear which files to include, ask the user before staging

   **If nothing was provided and context is ambiguous:**
   - Use the **AskUserQuestion tool** to clarify

2. **Build the commit message**

   - Title line: `<type>(<scope>): <short summary>` — include the change name as the scope if applicable (e.g. `feat(inverter-power-limits): add min/max clamping`)
   - Keep the title under 72 characters
   - Optionally add a blank line and a short body if the change needs explanation
   - **Do NOT include any "Co-Authored-By" lines**

3. **Stage the files**

   Stage the selected files using specific file paths — do not use `git add -A` or `git add .` as these may pick up unrelated or sensitive files.

   ```bash
   git add <file1> <file2> ...
   ```

   Confirm staged files with `git diff --cached --name-only` before committing.

4. **Attempt the commit**

   ```bash
   git commit -m "<message>"
   ```

   **Do not use `--no-verify`**. Pre-commit hooks must run.

5. **Handle the outcome**

   **If the commit succeeds:** Proceed to step 6.

   **If the commit fails due to auto-formatting** (hooks reformatted files but did not fix an error):
   - Check `git diff` — if previously staged files now have new changes, this is an auto-format
   - Re-stage the formatted files: `git add <same files>`
   - Run the commit again with the **same message** — do NOT amend

   **If the commit fails for any other reason** (lint errors, test failures, etc.):
   - Stop immediately
   - Show the hook output to the user
   - Do not retry, do not amend, do not proceed
   - Wait for the user to resolve the issue

6. **Verify success**

   Run `git log -1 --oneline` to confirm the commit was created.

   Do NOT assume the commit succeeded just because no error was printed — always verify with `git log`.

**Output On Success**

```
## Committed

**Message:** feat(add-auth): add JWT-based authentication
**Files staged:** 6 files
**Commit:** abc1234 feat(add-auth): add JWT-based authentication
```

**Output On Hook Failure (Auto-format)**

```
## Auto-format detected — re-committing

Pre-commit hook reformatted 2 files. Re-staging and committing again.

**Commit:** abc1234 feat(add-auth): add JWT-based authentication
```

**Output On Hook Failure (Blocking)**

```
## Commit Failed

Pre-commit hook failed with the following output:

<hook output>

The commit was not created. Fix the issue above and run `/commit` again.
```

**Guardrails**
- Never use `--no-verify` or skip hooks
- Never amend a commit — always create a new one
- Never assume a commit passed without verifying via `git log`
- Never include Co-Authored-By lines in the message
- Only re-commit automatically when the failure is clearly an auto-format (new diffs on previously staged files, no error message from the hook)
- Stage specific files by path — avoid `git add -A` or `git add .`
- If unsure which files belong, ask before staging
