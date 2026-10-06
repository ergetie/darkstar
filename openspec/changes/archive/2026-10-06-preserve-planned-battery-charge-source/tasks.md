## 1. Evidence and design review

- [x] 1.1 Trace planner total/grid charging fields through schedule formatting, executor parsing, controller mode selection, and Fronius/Deye profile mappings.
- [x] 1.2 Reproduce the previous and candidate controller modes using the October 4 recorded zero-import battery-charging plan; document that this proves a command discrepancy, not financial loss.
- [x] 1.3 Create the retrospective proposal, design, executor delta requirements, and implementation checklist, explicitly identifying the candidate as local and unapproved.
- [x] 1.4 Review mode-selection semantics and legacy fallback; retain existing charge-power commands and existing `Auto` behavior, and document mixed-source power semantics as a separate investigation.

## 2. Existing candidate implementation

- [x] 2.1 Add optional grid-charging intent to `SlotPlan`, keeping explicit zero distinct from unknown.
- [x] 2.2 Parse explicit schedule intent before grid-import fallbacks while retaining total battery charging separately.
- [x] 2.3 Select solar/self-consumption mode for explicit zero grid charging; preserve positive grid charging, battery-export precedence, and runtime override behavior.
- [x] 2.4 Preserve grid-charging intent when EV source isolation rebuilds the slot.

## 3. Software verification

- [x] 3.1 Add regression tests for solar charging with and without export, positive grid charging, parser precedence/fallbacks, and EV-isolation preservation.
- [x] 3.2 Run executor tests and changed-file Ruff checks plus executor type checks; record the 794-test result and the emitted mock-coroutine warning.
- [x] 3.3 Add planner-adapter-to-formatter-to-executor regression coverage for zero-import/zero-export solar charging.
- [x] 3.4 Add actual Fronius and Deye profile action coverage for explicit solar-only plans and positive grid-charging plans.
- [x] 3.5 Add explicit null-source fallback and source-less solar-export scenarios, plus explicit-source override/export-precedence coverage.
- [x] 3.6 Triage the executor-suite mock-coroutine warning and complete outstanding verification after any reviewed implementation changes: 810 executor tests passed with no warnings; lint, formatting, and executor type checks passed.

## 4. Acceptance evidence

- [x] 4.1 Record the user's scope correction: no financial savings acceptance criterion; another agent reported no financial improvement.
- [x] 4.2 Record the user's acceptance of existing `Auto` mode behavior; physical revalidation and profile redesign are outside this correctness change.
- [x] 4.3 Complete design review and record the software/profile acceptance assessment before considering archive or release; production deployment remains a separate action.
