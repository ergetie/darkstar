# Tasks

Working rules (design.md D6/D7): one phase per session — read `design.md`, read `findings.md`, run the phase, append findings, tick tasks, stop. All server access read-only (`mode=ro`). Diagnose-only: phases 0–4 change no code; fixes become separate changes. Each task notes the failure modes (FM1–FM8) it defends.

## 1. Setup & Baseline

- [x] 1.1 Create `findings.md` in this change dir: severity rubric (S1–S4 per design D2), FM catalog reference, append-only rules, and a "Baselines" section
- [x] 1.2 Run the full local test suite (`uv run python -m pytest`) and `scripts/ci_local.sh`; record pass/fail counts and versions in Baselines (any failure = immediate finding)
- [x] 1.3 Copy a snapshot of the production DB to the local scratchpad (`scp` from `darkstar:/opt/darkstar/data/planner_learning.db`) for heavy queries; record snapshot timestamp in Baselines
- [x] 1.4 Resolve OQ3: determine whether `slot_plans` or `schedule_planned` (92k rows, 4 cols) is the authoritative plan record — read the writing code, document the answer in findings.md; flag legacy table as a finding if dead

## 2. Evidence Mining — Executor & Control Loop (FM1, FM4)

- [x] 2.1 Compute `execution_log` tick success rate over full history; bucket all distinct `error_message` values by count and date-range; every recurring failure class becomes a finding or an explained-benign entry
- [x] 2.2 Check plan-vs-command consistency: sample slots where `commanded_*` diverges from `planned_*` without `override_active`; classify each divergence (bug / intended logic / data artifact)
- [x] 2.3 Detect stale-plan execution: reconstruct schedule age at each tick (schedule generation time vs `executed_at`); list episodes exceeding planner cadence and verify the freshness safeguard fired
- [x] 2.4 Mine logs + `execution_log` for HA-disconnect episodes (incl. the 2026-07-01 21:37 incident): verify reconnection completed, no commands were dropped mid-sequence, and recovery needed no restart
- [x] 2.5 Analyze `duration_ms` distribution over time for tick-duration degradation or timeout clustering
- [x] 2.6 Verify override behavior in history: for every `override_active` episode, confirm no automated command contradicted the override

## 3. Evidence Mining — Data Integrity (FM5)

- [x] 3.1 Slot continuity over full 8 months: find every gap, duplicate, and misaligned `slot_start` in `slot_observations` (special attention to DST days and app-restart times); classify each
- [x] 3.2 Energy-balance audit: compute per-slot balance residual (PV + import + discharge − load − export − charge) across history; characterize the residual distribution and investigate the tail outliers
- [x] 3.3 SoC continuity: check `soc_end` vs next slot's `soc_start` across history; investigate jumps beyond sensor-noise tolerance
- [x] 3.4 Dual-writer audit: confirm by code read + data check that recorder and executor never write the same `slot_observations` columns, and look for rows showing torn/partial writes
- [x] 3.5 Review all 149 `data_quality_daily` rows: for each non-clean day, verify the flagged issue was real and correctly scoped; verify clean days spot-check clean
- [x] 3.6 Spot-check recorded kWh against HA cumulative sensor history for 3 sampled days (one recent, one winter, one with known incident) to validate the recorder's disaggregation

## 4. Evidence Mining — Economics & Forecasts (FM2, FM3, FM6)

- [x] 4.1 Plan-vs-actual divergence: per day, compare planned charge/discharge/export (authoritative plan table from 1.4) against realized `slot_observations`; rank the worst 10 days and explain each
- [x] 4.2 Money audit: reconstruct realized cost per day from observations + prices; find episodes of export below economic value or charge at avoidable cost (battery wear per config included); each unexplained episode is a finding
- [x] 4.3 EV readiness: for every plugged-in night in history, determine whether the EV reached its target by the 07:00 departure; every miss is classified (bug / user action / infeasible)
- [x] 4.4 Water-comfort audit: check the max-heating-gap (8 h) and daily-energy targets against `slot_observations.water_kwh` history; list violations
- [x] 4.5 Forecast drift: compute PV, load, and price forecast error (from `slot_forecasts` vs observations) by week over 8 months; flag trends, step changes (e.g. around the June fix changes), and cold-start artifacts
- [x] 4.6 PV ceiling check: scan stored PV forecasts for values above the physical system ceiling (7.11 kWp arrays); any exceedance is a finding against the pv-open-meteo-baseline safeguards

## 5. Adversarial Code Review — Targeted (steered by phases 2–4 evidence)

- [x] 5.1 `planner/solver/kepler.py` objective: verify every price/cost term's sign, unit, and interaction (wear cost, export revenue, curtailment, ramping) against a worked numeric example (FM2)
- [x] 5.2 `executor/engine.py` + `actions.py` command paths: trace every code path that can issue an HA command; verify each is plan-driven, override-respecting, idempotent, and fails safe on partial errors (FM1)
- [x] 5.3 Unit/timezone boundary audit across planner↔executor↔recorder: kW vs kWh vs 15-min slots, local time vs UTC, DST handling in slot math (FM1, FM5)
- [x] 5.4 Dual-engine SQLite review: `backend/learning/store.py` (async) vs `executor/history.py` (sync StaticPool) — locking, busy-timeout, transaction scope, WAL assumptions (FM5)
- [x] 5.5 `backend/config_migration.py` + config save path: atomicity, failure-mid-write, version stamping, silent default injection (FM7)
- [x] 5.6 Frontend truthfulness pass: verify the numbers on Dashboard/ChartCard against their API sources (axis scaling, unit conversion, timezone bucketing, stale-socket state after reconnect) — read `ChartCard.tsx`, `Dashboard.tsx`, `lib/api.ts` (FM8)
- [x] 5.7 Consolidate phases 2–5 into findings.md; mark every finding CONFIRMED/UNVERIFIED; verify every FM1–FM8 now has either evidence of a defense or a finding

## 6. Fault-Injection Test Suite (spec: fault-injection-testing) — first code phase

- [x] 6.1 Build the shared fault-injection fixtures on the existing hermetic conftest pattern (fake HA client with scriptable failures, price-source stub, sensor-sequence injector); no network, no live system
- [x] 6.2 Implement HA-unavailability scenarios (connection refused, timeout, 404 mid-restart, 5xx) for executor tick and recorder cycle per spec
- [x] 6.3 Implement price-degradation scenarios (no tomorrow prices, partial slots, total fetch failure) per spec
- [x] 6.4 Implement sensor-anomaly scenarios (spike, negative cumulative delta, stuck value, unit outlier) per spec
- [x] 6.5 Implement restart-mid-slot and stale-schedule scenarios per spec
- [x] 6.6 Implement DST spring-forward and fall-back scenarios for planner, recorder, executor per spec
- [x] 6.7 Run the full suite + `scripts/ci_local.sh`; every fault-injection failure that reveals unsafe degradation is appended to findings.md (the test may then be marked xfail referencing the finding, so the suite stays green while the fix change is pending)

## 7. Runtime Invariant Monitors (spec: runtime-invariant-monitors) — second code phase

- [x] 7.1 Derive concrete thresholds for the 7 catalog invariants from phase 2–4 measured distributions; document each threshold + rationale in the module
- [x] 7.2 Implement the monitors module: scheduled read-only evaluation loop, per-invariant results, fail-open isolation (exception → unhealthy status, never propagates)
- [x] 7.3 Implement alert integration on the existing `SystemAlert` surface with per-episode dedup and recovery-clearing per spec; decide OQ1 (banner-only default) with the operator
- [x] 7.4 Expose per-invariant status + monitor health via the existing health/status API per spec
- [x] 7.5 Write monitor tests: each invariant's pass/violation/skip path, dedup behavior, isolation (injected evaluator crash leaves loops untouched), API exposure
- [ ] 7.6 Run full suite + lint + pyright strict; deploy to production (operator performs/approves the deploy per repo rules) and verify one green evaluation cycle on the live system

## 8. Synthesis & Exit

- [x] 8.1 Completeness audit of findings.md: every finding has severity, FM mapping, evidence, CONFIRMED/UNVERIFIED status; every anomaly from phases 2–4 is either a finding or explained-benign
- [x] 8.2 Group S1–S3 findings into proposed follow-up fix changes with sequencing and conflict notes (recommendations only — do not create them here)
- [x] 8.3 Write the exit statement: which FMs are defended and how, what is explicitly NOT covered, monitor status, and the soak criterion (OQ2, default 14 consecutive green days) with its start date
- [ ] 8.4 Confirm with the operator: review findings summary, agree follow-up priorities, and record the soak-window decision before this change is considered apply-complete
