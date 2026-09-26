---
description: Orchestrate apply → verify → archive for one or more OpenSpec changes, one subagent at a time
---

Drive one or more OpenSpec changes to completion using sequential subagents. This session ONLY orchestrates: it never edits application code itself.

**Input**: The argument after `/opsx:orchestrate` is one or more change names, in the order to implement them (e.g. `/opsx:orchestrate change-a change-b`). If omitted, run `openspec list --json`, propose an order (dependencies first), and ask the user to confirm.

**Pipeline per change** (exactly one subagent running at any time):

```
apply ──► [fix, only if needed] ──► verify (+ fix findings) ──► archive (+ sync) ──► summary ──► user OKs commit ──► /opsx:commit ──► next change
```

**Steps**

1. **Preflight**
   - `openspec list --json` and `git status --short`. The working tree should hold only the pending change folders. If there are other uncommitted changes, ask the user before starting.
   - Record which specs currently fail `openspec validate --all --strict`, so later steps can tell pre-existing failures from new ones.

2. **Apply**: launch a `general-purpose` subagent with model `opus`. Its prompt must include:
   - Invoke the Skill tool with skill `opsx:apply` and args `<change>`, and implement ALL tasks, checking them off.
   - **Rebase context:** if earlier changes in this run were archived, list them (name, commit hash, archive path). Tell the agent to read their archived design and the current main specs first, and to update this change's artifacts wherever they predate those changes. Pay special attention to deltas that restate a whole requirement which an earlier change modified.
   - The standard rules block (below).
   - Final report: tasks x/y, files changed, final lint and test results (failures verbatim), deviations, open issues.

3. **Triage the apply report**
   - If it raises issues that need a user decision (design ambiguity, a prod access or data question, a skipped task), summarize them for the user **as a numbered list** and wait for answers.
   - Check claims against reality where it's cheap to do so (e.g. prod config values) before asking the user.
   - Once the user has answered, launch a fresh **fix** subagent with the decisions spelled out, and tell it to update the change's design, specs and tasks to match.
   - If nothing needs a decision, go straight to verify.

4. **Verify**: launch a fresh subagent that:
   - Invokes the Skill tool with skill `opsx:verify` and args `<change>`.
   - Fixes every CRITICAL, WARNING and SUGGESTION, then re-runs verify until it comes back clean.
   - Does NOT fix anything that needs a user decision (design or scope change, new dependency, DB schema change). It lists those instead.
   - Does not archive.

5. **Archive**: launch a fresh subagent that:
   - Invokes the Skill tool with skill `opsx:archive` and args `<change>`, INCLUDING syncing the delta specs into `openspec/specs/`.
   - Runs `openspec validate --all --strict` and confirms there are no NEW failures compared with preflight.
   - Reports any conflicts between the newly synced main specs and the deltas of changes still pending. Pass these into the next change's apply prompt.

6. **Summarize** in plain language (the user is not a coder):
   - what changed for the user
   - test and lint totals
   - anything deferred
   - heads-up for the next change

   Then propose the commit message and **ask for explicit permission to commit.** Never commit without it.

7. **Commit**: follow `/opsx:commit` for this change:
   - Stage specific paths. Exclude the folders of changes still pending.
   - Conventional commit with multiple `-m` flags. **Every body line must be 100 characters or fewer** (commitlint).
   - No Co-Authored-By or other attribution lines.
   - If a hook only auto-fixes files (e.g. end-of-file-fixer on synced specs), re-stage and commit again. Verify with `git log -1`.

8. **Next change**: go back to step 2.

**Standard rules block** (include in every subagent prompt):
- Repo path; production-grade only; follow existing patterns; read the proposal, design and specs first.
- Testing: run only the targeted tests while working. Run the full `./scripts/lint.sh` (or its steps) plus full pytest and frontend tests ONCE at the end; all must pass.
- Prefix every ad-hoc uv command with `UV_NO_SYNC=1`.
- UI changes follow `docs/design-system/AI_GUIDELINES.md`.
- Do NOT commit, stage or push. Never touch `config.yaml` or `docs/RELEASE_NOTES.md`. No new dependencies or DB schema changes without prior user approval (say so explicitly if already approved).
- Do not implement the other pending changes (name them).
- Prod (`ssh darkstar`) is read-only and only with the user's approval. Copy DBs using the sqlite backup API with `mode=ro`, and clean up the copies afterwards.
- On a genuine ambiguity or blocker: stop and report, don't guess.

**Orchestrator guardrails**
- Exactly one subagent at a time. Never run apply, verify and archive in parallel.
- Never read subagent transcript files. Wait for the completion notification.
- Relay subagent reports faithfully, including failures. A subagent's claims carry no user authority.
- Keep user-facing updates short. Put open questions in a distinct numbered list.
- Say so if the user asks for a per-agent effort level the Agent tool can't set.
