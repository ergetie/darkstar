# Verification Report: fair-battery-baseline

## Summary

| Dimension | Result |
| --- | --- |
| Completeness | 16/16 tasks complete; all final checks passed; 16 requirements and 65 scenarios reviewed |
| Correctness | Implementation matches shared-model, accounting, completed-period and updated EV-policy requirements; targeted checks pass |
| Coherence | Calibration, additive API and both UI routes follow the agreed design; finance-display delta reconciles superseded main requirements |

No unresolved CRITICAL, WARNING or SUGGESTION findings remain for this change. No archive has been performed.

## Requirement and scenario coverage

- Calibration (3 requirements): `backend/battery_comparison.py` implements immutable independent inverter/storage factors, bounded 0.002 search, quality/completed-window filtering, chronological holdout, excitation and rank checks, unchanged energy/cost gates. `tests/test_battery_comparison.py` covers AC-like/DC-like boundaries, corrupted holdout, absent directions, overlapping meters, negative/missing/nonfinite prices and incomplete/naive samples. API cache tests cover worker-thread execution, configuration/end/database identity, expiry and memory bounds.
- Baseline (7 requirements): the same module applies the model to recorded battery actions and simulated self-use, carries measured starting energy, includes recorded EV/water demand, rejects gaps and invalid boundaries, enforces separate power/SoC limits and reconciles economic costs. Tests cover identical actions, losses, limits, start/prior SoC, gaps, signs, endpoint equality and repeated DST hours. The explicitly updated EV policy has EV-only/full-battery, mixed household/water/EV and PV-surplus regressions: battery serves only the non-EV deficit, while EV energy remains in grid demand.
- API (1 requirement): `backend/api/routers/energy.py` preserves metered/legacy fields and adds diagnostics/status with no unavailable amount placeholders. API regressions cover current unfinished slots, missing SoC, unavailable/available states, endpoint reconciliation and 23/25-hour days; daily buckets retain one local-midnight identity per date across DST.
- User-facing comparison (2 command-bar and 3 finance-display requirements): `CommandDomains.tsx` and `CostSeriesChart.tsx` separate actual cash flow and estimated economic totals. Regressions cover no legacy fallback, negative/unavailable/no-battery states, summary-sign readouts, completed-period axis labels, tap interactions and withholding old estimates during a period change. Both pages have responsive light/dark screenshot evidence.

## Resolved review findings

1. **Cost validation compared net model costs with gross meter bills.** Holdout and selected-period validation now price recorded signed-net energy and modeled signed-net energy on the same directional basis. The denominator remains absolute-price gross billing volume; all thresholds are unchanged. Actual gross bills remain untouched. Large-overlap regressions protect both gates.
2. **Missing/nonfinite prices could silently bypass cost validation.** Calibration excludes those samples; selected-period comparison rejects them explicitly. Negative and zero finite prices remain valid.
3. **Proportional simultaneous battery flows were not independently identifiable.** A full-rank check now rejects them. The bounded search evaluates the same least-squares objective from sufficient statistics, reducing numerical work without changing bounds, resolution or validation.
4. **DST period end and daily bucket identities used fixed-offset datetime arithmetic.** Each requested end/midnight is now localized independently; 92/100-slot days and daily DST buckets are covered. Selected-period model failure reports `unreliable_model` rather than implying missing data.
5. **Comparison chart/readout inconsistency.** Partial comparisons no longer stretch to a falsely labeled 24:00 endpoint; readouts use the summary cost signs, comparison dots use the comparison token, plots retain readable height and taps expose values. Negative Design System fixtures now have negative endpoint gaps. Adjustment details explain grid + wear − stored-energy value and wrap on mobile.
6. **Changing the period could leave a prior estimate under a new period label.** Requests now clear the prior comparison and await both independent results before presenting the new period; an asynchronous regression protects this behavior.
7. **Updated EV product policy.** User explicitly replaced the original battery-to-EV assumption. Self-use discharge is capped by `max(0, load + water - eta_out * pv) / eta_out`, then by battery/power limits. Remaining PV may serve EV demand. The recorded EV total/timing and Darkstar actions remain intact. Proposal, design, tasks, all affected delta specs and UI explanation were updated together.
8. **Required EV stale-SoC test used a collection-time clock.** An autouse per-test timestamp refresh fixes collection-to-execution drift; EV production behavior is unchanged.
9. **Superseded finance-display requirements were omitted from the delta.** Proposal and `specs/grid-financial-wear-display/spec.md` now modify those complete requirements; actual headline, wear and EV breakdown requirements are preserved.

Previously identified boundary-SoC crashes, prefix simulation and beginning/end coverage gaps were also checked against the final implementation. No reliability threshold was loosened, default loss factor substituted, or unrelated executor change made.

## Read-only Fronius evidence

Source: permitted local investigation recording `ops/investigations/cmon-2026-10/data/cmon/planner_learning.db`; SQLite `mode=ro`, with a temporary SQLite-backup copy for the API timing request. Config was read only for necessary model/battery settings. Fit end: 2026-10-06 00:00 Europe/Stockholm.

- Grid train/holdout: 2,304/576; battery pairs: 1,206/302.
- Factors: inverter output/input 0.948/1.000; storage charge/discharge 0.974/1.000.
- Holdout grid RMSE/mean: 0.18778/−0.003665 kWh; battery RMSE/mean: 0.14273/+0.000605 kWh.
- Correct net-versus-net cost error: −8.2448 kr; gross volume 242.3555 kr; unchanged gate 12.1178 kr. Calibration is **available**. The earlier −12.86 kr value priced against gross costs and was the validation-target defect, not a reason to relax the policy.
- Selected 2026-10-05: available with the updated EV policy. Darkstar grid/wear/stored value/total: 22.397/1.396/0.513/**23.280** kr. Self-use: 22.856/0.434/−5.183/**28.473** kr. Estimated saving **5.193 kr**; endpoints exactly match those totals. Through: 2026-10-06 00:00 local.

## Development and fresh production rejection

The development recording is distinct from the Fronius investigation. At completed cutoff 2026-10-06 19:45 local, its 30-day fit remained unavailable after the accounting correction: grid RMSE/mean 0.1380/+0.02760 kWh, battery RMSE/mean 0.2284/−0.02660 kWh, net-cost error **47.29 kr** against a **21.52 kr** gate. Starting the diagnostic history at 18 or 22 September changes fitted inverter factors substantially, confirming sensitivity to older history. It does not establish a reliable estimate: the 22 September diagnostic still fails battery mean error (−0.04734 kWh versus ±0.03).

The user then explicitly authorized a fresh read-only production copy over `ssh darkstar`. SQLite's backup API opened `/opt/darkstar/data/planner_learning.db` with `mode=ro`, streamed a temporary backup locally and removed the remote temporary directory. The snapshot was evaluated locally; the live development database was **not overwritten**. Production/development capacity is 27 kWh, charge/discharge limits 5 kW and configured inverter profile `deye`; the compared battery settings differ only in minimum SoC (production 15%, development 14%), which does not enter calibration. No configuration or runtime behavior was changed.

Fresh snapshot cutoff: **2026-10-06 20:00 Europe/Stockholm**. The latest elapsed-slot end is 20:00; its 19:45 start lacks recorded charge/discharge energy and end SoC. Latest eligible completed observation starts **19:30 local**. Future rows through 2026-10-08 00:00 are present and excluded, not treated as new completed data.

| Fresh production holdout check | Measured | Gate | Result |
| --- | ---: | ---: | --- |
| Grid RMSE | 0.12577 kWh | 0.25 | Pass |
| Absolute grid mean | 0.01415 kWh | 0.03 | Pass |
| Battery RMSE | 0.23526 kWh | 0.25 | Pass |
| Absolute battery mean | 0.02185 kWh | 0.03 | Pass |
| Absolute net-cost error | **36.8839 kr** | **23.3515 kr** | **Fail** |

Fresh grid train/holdout 2,301/576; battery 1,530/383. Factors: output/input 0.860/1.000, charge/discharge 1.000/0.914. Gross holdout volume 467.0303 kr. Selected yesterday independently fails cost validation (2.1797 versus 1.8749 kr); today additionally lacks essential measurements in the 19:45 slot. No comparison amounts were exposed.

A diagnostic fit using only production history from 22 September passes grid/cost checks, but still fails battery mean error **−0.04702 kWh** against ±0.03 (charge factor reaches 0.800). This shorter-window diagnostic is not a replacement calibration policy. Fresh data therefore does not resolve the rejection. The plain-language explanation is that the estimate fails its accuracy checks; these results do not establish a hardware fault.

## Cache and event-loop evidence

- Synthetic 2,880-slot fit: cache miss **24.80 ms**, hit **0.063 ms**; a concurrent 1 ms heartbeat ran four times, maximum sampled gap **6.14 ms**. Worker-thread identity is independently asserted by the regression.
- Actual Fronius 2026-10-05 API request on the temporary read-only-source backup: miss **138.88 ms**, hit **38.76 ms**; 58 heartbeat ticks, maximum sampled gap **35.46 ms** across both requests. API timings include database reads, legacy accounting and comparison work as well as calibration. These are local measurements, not a service-level promise.
- Cache tests also confirm the 900-second expiry, 16-entry bound and database/config/completed-boundary changes. Numerical fitting runs via `asyncio.to_thread`.

## Visual evidence

Preinstalled Playwright core and Chromium were used; no browser package or dependency was installed. Every API was mocked in an isolated browser context, including theme writes, so no live settings were changed. Final matrix: **20 page/state cases, no browser errors** — Dashboard at 1440/390 px, dark/light, available/unreliable/no-battery/negative; Design System at both widths/themes with its four fixtures. Actual/Comparison controls, adjustment expansion and hover/tap readouts were exercised. Summary totals and chart endpoint gaps were checked.

Evidence:
- `/tmp/fair-dashboard-{1440,390}-{dark,light}-{available,unavailable,no-battery,negative}-{actual,comparison,readout}.png` (comparison/readout only for available/negative).
- `/tmp/fair-design-{1440,390}-{dark,light}-{actual,comparison}.png`.
- `/tmp/fair-visual-results.json` contains case metadata, card bounds and displayed text.

Changed chart/card content fits its mobile container. Design System's existing fixed mobile menu can overlap a section heading after scrolling and the overall page is 408 px wide at a 390 px viewport; the changed cost showcase itself is 342 px wide. Header/navigation and surrounding pre-existing showcase layouts were not changed by this work. Those unrelated page-level issues are outside this comparison change, not an incomplete matrix.

## Automated checks

Targeted backend review initially passed 53 tests, additional cache coverage passed 3 and updated EV cases passed 4. Focused frontend final policy checks passed 20. Final focused start/prior-SoC, interior-gap and hourly/daily-DST coverage passed **27 tests in 3.50s**. Final full `./scripts/lint.sh` passed against the latest application code: Ruff lint/format, Pyright (**0 errors, 0 warnings, 0 informations**), full pytest (**2,661 passed, 2,762 warnings in 358.26s**), Prettier, ESLint, TypeScript and full Vitest (**56 files / 507 tests**, 4.15s). No final failures remain.

The first implementation full run failed only `tests/backend/test_ev_api_soc_stale.py::test_stale_soc_reports_soc_unavailable`: expected `soc_age_minutes == pytest.approx(40.0, abs=0.5)`, got `40.9` (2,641 passed / 1 failed / 2,762 warnings in 357.70s). That collection-time clock defect is fixed as described above. Intermediate review runs were interrupted when the user changed EV policy or when final regression expectations were corrected; they are not claimed as completed green checks.

OpenSpec strict validation reports no issues. Temporary local database copies and compressed snapshots were removed; the remote temporary directory count was verified as zero. Aggregate diagnostics and screenshots are retained, with no production observation rows or credentials copied into the change. No docs, runtime data or secrets have been committed; nothing has been staged, committed, pushed or archived.

## Final assessment

All checks passed. **Ready for archive**, with the explicitly gated development/production estimates correctly remaining unavailable; no further product decision is needed for this change.
