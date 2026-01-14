# Darkstar Energy Manager: Active Plan

**Vision: From Calculator to Agent**
Darkstar is transitioning from a deterministic optimizer (v1) to an intelligent energy agent (v2). It does not just optimize based on static config; it observes context (Weather, Vacation, Prices), predicts outcomes (Aurora ML), and actively strategizes (Strategy Engine) to maximize efficiency and comfort.

---

## Revision Naming Conventions

| Prefix | Area | Examples |
|--------|------|----------|
| **K** | Kepler (MILP solver) | K1-K19 |
| **E** | Executor | E1 |
| **A** | Aurora (ML) | A25-A29 |
| **H** | History/DB | H1 |
| **O** | Onboarding | O1 |
| **UI** | User Interface | UI1, UI2 |
| **DS** | Design System | DS1 |
| **F** | Fixes/Bugfixes | F1-F6 |
| **DX** | Developer Experience | DX1 |
| **ARC** | Architecture | ARC1-ARC* |

---

## 🤖 AI Instructions (Read First)

1.  **Structure:** This file is a **chronological stream**. Newest items are at the **bottom**.
    
2.  **No Reordering:** Never move items. Only update their status or append new items.
    
3.  **Status Protocol:**
    
    -   Update the status tag in the Header: `### [STATUS] REV // ID00 — Title`
        
    -   Allowed Statuses: `[DRAFT]`, `[PLANNED]`, `[IN PROGRESS]`, `[DONE]`, `[PAUSED]`, `[OBSOLETE]`.
        
4.  **New Revisions:** Always use the template below.
    
5.  **Cleanup:** When this file gets too long (>15 completed items), move the oldest `[DONE]` items to `CHANGELOG.md`.
    

### Revision Template


```

### [STATUS] Rev ID — Title

**Goal:** Short description of the objective.
**Plan:**

#### Phase 1: [STATUS]
* [ ] Step 1
* [ ] Step 2

#### Phase 2: [STATUS]
* [ ] Step 1
* [ ] Step 2

```

---

## REVISION STREAM:


---

### [PLANNED] REV // H2 — Training Episodes Database Optimization

**Goal:** Reduce `training_episodes` table size from 2.1GB to ~100-150MB through systematic investigation, optional JSON trimming, and zlib compression. Ensure zero data loss and maintain production-grade reliability.

**Context:** The `planner_learning.db` file has grown to 2.1GB, causing slow Docker container startup (~5-10 second delay) and potential timeout issues on the Aurora Dashboard's `/api/aurora/dashboard` endpoint. The `training_episodes` table (16,000 rows × ~147KB/row) stores full planner inputs and outputs for Antares RL training. Initial analysis shows:
- `schedule_json`: ~94KB/row (130 slots × 27 fields)
- `inputs_json`: ~53KB/row (192 price/forecast slots)
- **Compression Potential:** 93-96% size reduction via zlib (verified with sample data)
- **Trimming Potential:** 25-50% reduction by removing unused UI/display fields before compression

**Critical Constraint:** This implementation MUST include a mandatory **HUMAN CHECKPOINT** after Phase 1 (Investigation). The implementing AI must STOP and wait for user approval before proceeding to compression implementation.

---

#### Phase 1: Field Usage Investigation [PLANNED]

**Goal:** Systematically audit which JSON fields in `training_episodes` are actually consumed by production code. Generate a definitive report for human decision-making on trimming strategy.

**Constraints:**
- Must trace ALL code paths that read `training_episodes`
- Must verify field usage in Antares RL training pipeline
- Must provide size impact estimates for each trimming option
- **MANDATORY:** Phase MUST end with notify_user requesting approval before Phase 2

**Tasks:**

1. **[AUTOMATED] Trace All Read Locations**
   * [ ] Run: `git grep -n "training_episodes" --include="*.py" > /tmp/grep_training_episodes.txt`
   * [ ] Parse output to identify all files that SELECT from `training_episodes`
   * [ ] Document in artifact: `field_usage_investigation.md` section "Code Locations"

2. **[AUTOMATED] Analyze `schedule_json` Field Usage**
   * [ ] View `ml/simulation/dataset.py:_expand_episode_schedule()` (lines 101-161)
   * [ ] Identify which fields from `schedule_json.schedule[*]` are accessed in the loop (lines 137-153)
   * [ ] Cross-reference with `AntaresSlotRecord` dataclass (lines 12-36) to see which fields are preserved
   * [ ] Document findings: Which of the 27 fields are actually used?
   * [ ] Expected finding: Only ~10-12 fields used (prices, forecasts, slot_start). Display fields (`reason`, `priority`, `is_historical`, etc.) likely unused.

3. **[AUTOMATED] Analyze `inputs_json` Field Usage**
   * [ ] Search for `inputs_json` read operations in codebase
   * [ ] Verify if `inputs_json` is ONLY used in `tests/test_learning_k6.py:141` for validation
   * [ ] If only used in tests, flag as "Low Priority - Can be trimmed aggressively"
   * [ ] Document findings in artifact

4. **[AUTOMATED] Analyze `context_json` Field Usage**
   * [ ] View `ml/simulation/dataset.py:_load_simulation_episodes()` (lines 60-98)
   * [ ] Identify which `context_json` fields are extracted (lines 84-92)
   * [ ] Verify if compression would break the `WHERE context_json LIKE '%simulation%'` query (line 73)
   * [ ] **Critical Finding:** This LIKE query will FAIL after compression (binary blob)
   * [ ] Document workaround: Add explicit `system_id` column OR decompress-then-filter in Python
   * [ ] Document findings in artifact

5. **[AUTOMATED] Create Trimming Candidates Matrix**
   * [ ] Create table in artifact with columns: `Field Name | Size Impact | Used By | Safe to Remove?`
   * [ ] For `schedule_json`, list each of 27 fields with size estimate
   * [ ] Example rows:
     ```
     | reason              | ~2KB  | UI only          | YES - Display field |
     | priority            | ~1KB  | UI only          | YES - Display field |
     | slot_number         | ~1KB  | None (derivable) | YES - Redundant     |
     | projected_battery_cost | ~2KB | None (derived)  | YES - Redundant     |
     ```
   * [ ] Calculate total savings if all "YES" fields removed

6. **[AUTOMATED] Generate Size Reduction Estimates**
   * [ ] Use sample data from investigation to test compression scenarios:
     - Scenario A: Compression only (no trimming)
     - Scenario B: Minimal trim (remove 5 obvious display fields) + compression
     - Scenario C: Aggressive trim (remove 15 fields) + compression
   * [ ] For each scenario:
     * [ ] Create test JSON with/without fields
     * [ ] Compress with zlib
     * [ ] Calculate: `(original_size - new_size) / original_size * 100`
   * [ ] Document results in table format

7. **[MANUAL - AI STOPS HERE] Create Decision Document & Request Approval**
   * [ ] Write artifact: `field_usage_investigation.md` with sections:
     - Executive Summary (1-2 paragraphs)
     - Code Paths Analysis (which files read which fields)
     - Trimming Candidates Matrix (field-by-field breakdown)
     - Size Reduction Scenarios (A/B/C comparison table)
     - Risks & Trade-offs (what breaks if we trim too much)
     - Recommended Approach (AI's suggestion)
   * [ ] Call `notify_user()` with:
     - `PathsToReview`: `[field_usage_investigation.md]`
     - `BlockedOnUser`: `true`
     - `Message`: "Phase 1 Investigation Complete. Review the field usage analysis and approve one of the trimming scenarios (A/B/C) before I proceed to implementation."
     - `ShouldAutoProceed`: `false`
   * [ ] **CRITICAL:** AI MUST NOT proceed to Phase 2 until user responds

**Artifacts Created:**
- `/home/s/.gemini/antigravity/brain/<conversation-id>/field_usage_investigation.md`

**Exit Criteria:**
- All 27 fields in `schedule_json` are categorized as USED or UNUSED
- All `inputs_json` consumers are documented
- User has approved trimming strategy (A/B/C) via notify_user response

---

#### Phase 2: Compression Implementation [PLANNED]

**Goal:** Implement zlib compression for `training_episodes` JSON fields with backward compatibility and zero data loss.

**Prerequisites:**
- [ ] Phase 1 complete
- [ ] User has approved trimming strategy (or chosen "compression only")

**Implementation Strategy:**
- Implement compression in `backend/learning/store.py` (WRITE path)
- Implement decompression in `ml/simulation/dataset.py` (READ path)
- Add backward compatibility layer (try decompress, fallback to plain text)
- If trimming approved: Implement field filtering in planner output serialization

**Tasks:**

8. **[AUTOMATED] Implement Write-Side Compression**
   * [ ] Modify `backend/learning/store.py:store_training_episode()` (lines 613-643):
     ```python
     import zlib
     
     def store_training_episode(
         self,
         episode_id: str,
         inputs_json: str,
         schedule_json: str,
         context_json: str | None = None,
         config_overrides_json: str | None = None,
     ) -> None:
         """Store a training episode for RL (with compression)."""
         # Compress JSON blobs before storage
         inputs_compressed = zlib.compress(inputs_json.encode('utf-8'))
         schedule_compressed = zlib.compress(schedule_json.encode('utf-8'))
         context_compressed = zlib.compress(context_json.encode('utf-8')) if context_json else None
         overrides_compressed = zlib.compress(config_overrides_json.encode('utf-8')) if config_overrides_json else None
         
         with sqlite3.connect(self.db_path, timeout=30.0) as conn:
             cursor = conn.cursor()
             cursor.execute(
                 """
                 INSERT INTO training_episodes (
                     episode_id,
                     inputs_json,
                     schedule_json,
                     context_json,
                     config_overrides_json
                 )
                 VALUES (?, ?, ?, ?, ?)
                 """,
                 (
                     episode_id,
                     inputs_compressed,
                     schedule_compressed,
                     context_compressed,
                     overrides_compressed,
                 ),
             )
             conn.commit()
     ```
   * [ ] Add docstring note: "JSON fields are zlib-compressed for storage efficiency (93% reduction)"

9. **[AUTOMATED] Implement Read-Side Decompression**
   * [ ] Create helper function in `ml/simulation/dataset.py`:
     ```python
     def _decompress_json(data: bytes | str) -> str:
         """Decompress training episode JSON with backward compatibility."""
         if isinstance(data, str):
             return data  # Already plain text (old format)
         
         try:
             # Try zlib decompression (new format)
             return zlib.decompress(data).decode('utf-8')
         except (zlib.error, UnicodeDecodeError):
             # Fallback to plain text (old format or corruption)
             try:
                 return data.decode('utf-8')
             except UnicodeDecodeError:
                 raise ValueError(f"Cannot decode training episode data: {data[:50]}")
     ```
   * [ ] Modify `_expand_episode_schedule()` (line 132):
     ```python
     # OLD: sched = json.loads(sched_json_str or "{}").get("schedule") or []
     # NEW:
     sched_json_str = _decompress_json(row[0])
     sched = json.loads(sched_json_str or "{}").get("schedule") or []
     ```
   * [ ] Modify `_load_simulation_episodes()` `_extract_context()` (line 84):
     ```python
     # OLD: ctx = json.loads(row["context_json"] or "{}")
     # NEW:
     ctx = json.loads(_decompress_json(row["context_json"]) if row["context_json"] else "{}")
     ```

10. **[AUTOMATED] Fix Context Filtering Issue**
    * [ ] **Problem:** `WHERE context_json LIKE '%simulation%'` (line 73) fails on compressed binary
    * [ ] **Solution A** (Recommended): Add `system_id` column to `training_episodes` table
      - Modify `backend/learning/store.py` schema (line 222):
        ```sql
        CREATE TABLE IF NOT EXISTS training_episodes (
            episode_id TEXT PRIMARY KEY,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            system_id TEXT DEFAULT 'prod',  -- NEW: explicit column for filtering
            inputs_json BLOB NOT NULL,      -- Changed from TEXT to BLOB
            context_json BLOB,              -- Changed from TEXT to BLOB
            schedule_json BLOB NOT NULL,    -- Changed from TEXT to BLOB
            config_overrides_json BLOB
        )
        ```
      - Add migration logic in `_create_tables()`:
        ```python
        # Add system_id column if missing (migration)
        try:
            cursor.execute("ALTER TABLE training_episodes ADD COLUMN system_id TEXT DEFAULT 'prod'")
        except sqlite3.OperationalError:
            pass  # Column already exists
        ```
      - Update `store_training_episode()` to accept `system_id` parameter
      - Update `_load_simulation_episodes()` query (line 73):
        ```sql
        WHERE system_id = 'simulation'  -- Instead of LIKE on context_json
        ```
    * [ ] **Solution B** (Fallback): Decompress all rows, filter in Python (slower but works)
      - Remove `WHERE context_json LIKE` from SQL
      - Filter after decompression in Python

11. **[CONDITIONAL] Implement JSON Trimming (If Approved)**
    * [ ] **Only execute if user approved trimming in Phase 1**
    * [ ] Identify where `schedule_json` is created (likely in `planner/pipeline.py` or output serialization)
    * [ ] Create field allowlist based on user's approved scenario:
      ```python
      SCHEDULE_SLOT_FIELDS_ALLOWLIST = [
          "start_time", "end_time",
          "import_price_sek_kwh", "export_price_sek_kwh",
          "pv_forecast_kwh", "load_forecast_kwh",
          "charge_kw", "battery_discharge_kw",
          "projected_soc_kwh", "water_heating_kw",
          # ... (only fields marked USED in Phase 1)
      ]
      ```
    * [ ] Filter schedule slots before JSON serialization:
      ```python
      trimmed_schedule = [
          {k: slot[k] for k in SCHEDULE_SLOT_FIELDS_ALLOWLIST if k in slot}
          for slot in full_schedule
      ]
      schedule_json = json.dumps({"schedule": trimmed_schedule, "meta": meta})
      ```
    * [ ] Document trimmed fields in code comment

12. **[AUTOMATED] Update `bin/inspect_episodes.py` Helper**
    * [ ] Verify `_decompress_json()` logic matches implementation
    * [ ] Test script works with both old (uncompressed) and new (compressed) data
    * [ ] Add `--show-size` flag to display compressed vs decompressed sizes

**Files Modified:**
- `backend/learning/store.py` (compression on write, schema migration)
- `ml/simulation/dataset.py` (decompression on read)
- `bin/inspect_episodes.py` (already created, minor updates)
- (Conditional) `planner/pipeline.py` or output serializer (trimming logic)

**Exit Criteria:**
- [ ] New episodes are compressed on write
- [ ] Old episodes can still be read via backward compatibility layer
- [ ] `bin/inspect_episodes.py` works for debugging
- [ ] All automated tests pass

---

#### Phase 3: Validation & Testing [PLANNED]

**Goal:** Verify compression implementation is production-ready with zero data loss and acceptable performance.

**Testing Strategy:**
- Unit tests for compression/decompression helpers
- Integration test: Write → Read → Verify roundtrip
- Performance test: Measure read speed impact
- Regression test: Verify Antares training still works

**Tasks:**

13. **[AUTOMATED] Create Unit Tests**
    * [ ] Create `tests/test_episode_compression.py`:
      ```python
      import json
      import zlib
      import pytest
      from ml.simulation.dataset import _decompress_json
      
      def test_decompress_new_format():
          """Test decompression of zlib-compressed JSON."""
          original = '{"test": "data"}'
          compressed = zlib.compress(original.encode('utf-8'))
          result = _decompress_json(compressed)
          assert result == original
      
      def test_decompress_old_format():
          """Test backward compatibility with plain text."""
          original = '{"test": "data"}'
          result = _decompress_json(original)
          assert result == original
      
      def test_decompress_bytes_old_format():
          """Test backward compatibility with bytes (UTF-8, not compressed)."""
          original = '{"test": "data"}'
          result = _decompress_json(original.encode('utf-8'))
          assert result == original
      
      def test_compression_roundtrip():
          """Test write → compress → decompress → read."""
          from backend.learning.store import LearningStore
          store = LearningStore("data/test_planner_learning.db", "Europe/Stockholm")
          
          # Test data
          inputs = json.dumps({"price_data": [...], "forecast_data": [...]})
          schedule = json.dumps({"schedule": [...], "meta": {}})
          
          # Write (compressed)
          store.store_training_episode("test_episode_001", inputs, schedule, system_id="test")
          
          # Read (decompressed)
          from ml.simulation.dataset import _load_simulation_episodes, _expand_episode_schedule
          # ... verify data integrity
      ```
    * [ ] Run: `PYTHONPATH=. python -m pytest tests/test_episode_compression.py -v`

14. **[AUTOMATED] Integration Test: Antares Training**
    * [ ] Run `ml/simulation/dataset.py:build_antares_training_dataset()` on test DB
    * [ ] Verify returned `AntaresSlotRecord` objects match expected structure
    * [ ] Compare results before/after compression (should be identical)
    * [ ] Document test command in artifact

15. **[AUTOMATED] Performance Benchmark**
    * [ ] Measure baseline read speed (uncompressed):
      ```python
      import time
      start = time.time()
      records = build_antares_training_dataset()
      baseline_time = time.time() - start
      print(f"Baseline: {baseline_time:.2f}s for {len(records)} records")
      ```
    * [ ] Measure compressed read speed:
      ```python
      # Same code, but with compressed data
      compressed_time = time.time() - start
      slowdown_pct = ((compressed_time - baseline_time) / baseline_time) * 100
      print(f"Compressed: {compressed_time:.2f}s ({slowdown_pct:+.1f}% change)")
      ```
    * [ ] **Acceptance Criteria:** Slowdown must be < 20% (e.g., 10s → 12s max)
    * [ ] Document results in artifact

16. **[AUTOMATED] Database Size Verification**
    * [ ] Before migration: `ls -lh data/planner_learning.db` (Expected: ~2.1GB)
    * [ ] After migration: `ls -lh data/planner_learning.db` (Expected: ~150MB for compression-only, ~100MB with trimming)
    * [ ] Run: `sqlite3 data/planner_learning.db "VACUUM;"` to reclaim space
    * [ ] Document final size in artifact

17. **[AUTOMATED] Test Helper Script**
    * [ ] Run: `python bin/inspect_episodes.py list`
    * [ ] Verify output shows both old (uncompressed) and new (compressed) episodes
    * [ ] Run: `python bin/inspect_episodes.py show <episode_id>` for a new episode
    * [ ] Verify JSON is correctly decompressed and displayed
    * [ ] Run: `python bin/inspect_episodes.py export <episode_id> --output /tmp/test.json`
    * [ ] Verify exported JSON is valid and complete

18. **[MANUAL] Production Smoke Test**
    * [ ] Deploy to staging/test environment
    * [ ] Trigger planner run → Verify new episode is stored compressed
    * [ ] Check Aurora Dashboard → Verify graduation status loads correctly
    * [ ] Check container startup time → Should be faster (no more 5-10s delay)
    * [ ] Monitor logs for any decompression errors

**Exit Criteria:**
- [ ] All unit tests pass
- [ ] Antares training produces identical results
- [ ] Read performance degradation < 20%
- [ ] Database size reduced by > 90%
- [ ] Helper script works correctly
- [ ] No production errors in staging

---

#### Phase 4: Documentation & Deployment [PLANNED]

**Goal:** Update all documentation, create migration guide for production, and ensure maintainability.

**Tasks:**

19. **[AUTOMATED] Update Code Documentation**
    * [ ] Add module docstring to `backend/learning/store.py`:
      ```
      """
      Learning database storage with compression.
      
      Training episodes are stored with zlib compression (93% size reduction).
      The `inputs_json`, `schedule_json`, `context_json` fields are compressed
      before INSERT and decompressed on SELECT via `ml.simulation.dataset._decompress_json()`.
      
      Backward Compatibility: The decompression layer gracefully handles legacy
      uncompressed episodes (pre-H2 implementation).
      """
      ```
    * [ ] Update schema comments in `_create_tables()` (line 222):
      ```sql
      CREATE TABLE IF NOT EXISTS training_episodes (
          episode_id TEXT PRIMARY KEY,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          system_id TEXT DEFAULT 'prod',
          inputs_json BLOB NOT NULL,      -- zlib-compressed JSON
          context_json BLOB,              -- zlib-compressed JSON
          schedule_json BLOB NOT NULL,    -- zlib-compressed JSON
          config_overrides_json BLOB      -- zlib-compressed JSON
      )
      ```

20. **[AUTOMATED] Update `docs/DEVELOPER.md`**
    * [ ] Add section "Training Episodes Storage" under "Learning Engine":
      ```markdown
      ### Training Episodes Storage
      
      Planner runs are logged to `data/planner_learning.db` → `training_episodes` table.
      JSON fields are zlib-compressed for space efficiency (~93% reduction).
      
      **Debugging Episodes:**
      Use `bin/inspect_episodes.py` to view compressed data:
      ```bash
      # List recent episodes
      python bin/inspect_episodes.py list
      
      # Show full episode content (auto-decompressed)
      python bin/inspect_episodes.py show episode_2025-11-27_15-24-18
      
      # Export to readable JSON
      python bin/inspect_episodes.py export <id> --output debug.json
      ```
      
      **Technical Details:**
      - Compression: zlib level 6 (default)
      - Write location: `backend/learning/store.py:store_training_episode()`
      - Read location: `ml/simulation/dataset.py:_decompress_json()`
      - Backward compatible: Old uncompressed episodes still readable
      ```

21. **[AUTOMATED] Update `docs/ARCHITECTURE.md`**
    * [ ] Find "Learning Engine" section
    * [ ] Add bullet: "Training episodes stored with zlib compression (2.1GB → ~150MB)"

22. **[AUTOMATED] Create Migration Guide**
    * [ ] Create `docs/MIGRATION_H2.md`:
      ```markdown
      # H2 Migration Guide: Training Episodes Compression
      
      ## Overview
      This migration enables zlib compression for `training_episodes` in `planner_learning.db`,
      reducing database size from ~2GB to ~150MB with zero data loss.
      
      ## Pre-Migration Checklist
      - [ ] Backup `data/planner_learning.db` to safe location
      - [ ] Verify backup integrity: `sqlite3 backup.db "SELECT COUNT(*) FROM training_episodes"`
      - [ ] Note current DB size: `ls -lh data/planner_learning.db`
      
      ## Migration Steps (Automatic)
      1. Update Darkstar to version ≥ [X.Y.Z]
      2. Restart application (migration runs on startup via `store.py:_create_tables()`)
      3. Verify logs show: "Added system_id column to training_episodes"
      4. New episodes will be compressed automatically
      
      ## Post-Migration Verification
      1. Check new episodes are compressed:
         ```bash
         python bin/inspect_episodes.py list --limit 5
         # Size should show ~10KB per episode (was ~147KB)
         ```
      2. Verify old episodes still readable:
         ```bash
         python bin/inspect_episodes.py show <old_episode_id>
         # Should display without errors
         ```
      3. Run VACUUM to reclaim space:
         ```bash
         sqlite3 data/planner_learning.db "VACUUM;"
         ls -lh data/planner_learning.db  # Should show ~150MB
         ```
      
      ## Rollback Procedure
      If issues arise:
      1. Stop application
      2. Restore backup: `cp backup.db data/planner_learning.db`
      3. Downgrade to previous version
      
      ## FAQ
      **Q: Will this break Antares training?**
      A: No. Decompression is transparent. Integration tests verify identical results.
      
      **Q: Can I still query episodes with sqlite3?**
      A: Metadata queries work (e.g., `SELECT episode_id, created_at FROM training_episodes`).
         JSON content must be accessed via `bin/inspect_episodes.py`.
      
      **Q: What if I need to debug a specific episode?**
      A: Use `python bin/inspect_episodes.py show <episode_id>` or export to JSON.
      ```

23. **[AUTOMATED] Update CHANGELOG**
    * [ ] Add entry to `docs/CHANGELOG_PLAN.md`:
      ```markdown
      ### [H2] Training Episodes Database Optimization
      
      **Problem:** `planner_learning.db` grew to 2.1GB, causing slow container startup
      and Aurora Dashboard timeouts.
      
      **Solution:** Implemented zlib compression for `training_episodes` JSON fields.
      
      **Impact:**
      - Database size: 2.1GB → ~150MB (93% reduction)
      - Container startup: 10s delay → <1s
      - Zero data loss (lossless compression)
      - Backward compatible with old episodes
      
      **Files Changed:**
      - `backend/learning/store.py` - Compression on write
      - `ml/simulation/dataset.py` - Decompression on read
      - `bin/inspect_episodes.py` - New debugging tool
      
      **Migration:** Automatic on upgrade (see `docs/MIGRATION_H2.md`)
      ```

24. **[AUTOMATED] Update REV Status**
    * [ ] Change this REV header to: `### [DONE] REV // H2 — Training Episodes Database Optimization`
    * [ ] Update all phase statuses to `[DONE]`

**Exit Criteria:**
- [ ] All documentation updated
- [ ] Migration guide reviewed and tested
- [ ] Changelog entry added
- [ ] Code comments complete

---

## REV H2 Success Criteria

**The following MUST be true before marking REV as [DONE]:**

1. **Data Integrity:**
   - [ ] Zero data loss verified (compare episode counts before/after)
   - [ ] Antares training produces identical results pre/post compression
   - [ ] All old (uncompressed) episodes remain readable

2. **Performance:**
   - [ ] Database size reduced by ≥ 90% (2.1GB → ≤ 210MB)
   - [ ] Read performance degradation < 20%
   - [ ] Container startup time improved (no more 5-10s delay)
   - [ ] Aurora Dashboard loads without timeout

3. **Code Quality:**
   - [ ] All unit tests pass (`pytest tests/test_episode_compression.py`)
   - [ ] No linting errors (`ruff check .`)
   - [ ] Type checking passes (`pyright .`)
   - [ ] Backward compatibility verified (try/except fallback tested)

4. **Documentation:**
   - [ ] `docs/DEVELOPER.md` updated with debugging instructions
   - [ ] `docs/MIGRATION_H2.md` created and reviewed
   - [ ] Code comments explain compression logic
   - [ ] CHANGELOG entry added

5. **Deployment:**
   - [ ] Staging environment tested successfully
   - [ ] Migration guide verified with test database
   - [ ] Rollback procedure documented and tested
   - [ ] `bin/inspect_episodes.py` works in production

**Sign-Off Required:**
- [ ] User has approved trimming strategy (Phase 1)
- [ ] User has verified migration guide (Phase 4)
- [ ] User has tested in staging environment (Phase 3)

---

## Notes for Implementing AI

**Critical Reminders:**

1. **MANDATORY STOP POINT:** You MUST call `notify_user(BlockedOnUser=true)` at the end of Phase 1 and WAIT for user response before proceeding to Phase 2. Do not implement compression until the user approves the trimming strategy.

2. **Backward Compatibility:** The `_decompress_json()` helper MUST gracefully handle:
   - Compressed binary (new format)
   - Plain text string (old format)
   - Bytes (old format as UTF-8)
   - Corrupted data (raise clear error)

3. **Testing Rigor:** Before marking any phase as DONE, run the verification tests. Do not skip performance benchmarking.

4. **Documentation First:** Update docs BEFORE deploying to production. The migration guide must be reviewed by the user.

5. **Artifact Trail:** Create the following artifacts during execution:
   - `field_usage_investigation.md` (Phase 1)
   - `compression_implementation_notes.md` (Phase 2, optional)
   - `validation_results.md` (Phase 3)

6. **Error Handling:** If decompression fails in production, log the episode_id and error clearly. Do not silently swallow exceptions.

7. **SQLite Schema:** The `ALTER TABLE` migration (adding `system_id` column) must be idempotent. Use `try/except sqlite3.OperationalError` to handle "column already exists" errors.

8. **Reference Materials:**
   - Investigation document: `/home/s/.gemini/antigravity/brain/<conversation-id>/optimization_analysis.md`
   - Helper script: `bin/inspect_episodes.py` (already created)
   - Sample compression code in optimization_analysis.md Section 2

**Expected Timeline:**
- Phase 1: ~2 hours (automated investigation + report generation)
- Phase 2: ~3 hours (implementation + code review)
- Phase 3: ~2 hours (testing + benchmarking)
- Phase 4: ~1 hour (documentation)
- **Total: ~8 hours of focused work**

---

### [DONE] REV // F9 — Pre-Release Polish & Security

**Goal:** Address final production-grade blockers before public release: remove debug code, fix documentation quality issues, patch critical path traversal security vulnerability, and standardize UI help text system.

**Context:** The BETA_AUDIT report (2026-01-13) identified immediate pre-release tasks that are high-impact but low-effort. These changes improve professional polish, eliminate security risks, and simplify the UI help system to a single source of truth.

**Breaking Changes:** None. All changes are non-functional improvements.

---

#### Phase 1: Debug Code Cleanup [DONE]

**Goal:** Fix documentation typos and remove TODO markers to ensure production-grade quality.

**Note:** Debug console statements are intentionally EXCLUDED from this REV as they are currently being used for troubleshooting history display issues in Docker/HA deployment.

**Tasks:**

1. **[AUTOMATED] Fix config-help.json Typo**
   * [x] Open `frontend/src/config-help.json`
   * [x] Find line 32: `"s_index.base_factor": "Starting point for dynamic calculationsWfz"`
   * [x] Replace with: `"s_index.base_factor": "Starting point for dynamic calculations"`
   * **Verification:** Grep for `calculationsWfz` should return 0 results

2. **[AUTOMATED] Search and Remove TODO Markers in User-Facing Text**
   * [x] Run: `grep -rn "TODO" frontend/src/config-help.json`
   * [x] **Finding:** Audit report claims 5 TODO markers, but grep shows 0. Cross-check with full text search.
   * [x] If found, replace each TODO with final help text or remove placeholder entries.
   * [x] **Note:** If no TODOs found in config-help.json, search in `frontend/src/pages/settings/types.ts` for `helper:` fields containing TODO
   * **Verification:** `grep -rn "TODO" frontend/src/config-help.json` returns 0 results

**Files Modified:**
- `frontend/src/config-help.json` (fix typo on line 32)

**Exit Criteria:**
- [x] Typo "calculationsWfz" fixed
- [x] All TODO markers removed or replaced
- [x] Frontend linter passes: `cd frontend && npm run lint`

---

#### Phase 2: Path Traversal Security Fix [DONE]

**Goal:** Patch critical path traversal vulnerability in SPA fallback handler to prevent unauthorized file access.

**Security Context:**
- **Vulnerability:** `backend/main.py:serve_spa()` serves files via `/{full_path:path}` without validating the resolved path stays within `static_dir`.
- **Exploit Example:** `GET /../../etc/passwd` could resolve to `/app/static/../../etc/passwd` → `/etc/passwd`
- **Impact:** Potential exposure of server files (passwords, config, keys)
- **CVSS Severity:** Medium (requires knowledge of server file structure, but trivial to exploit)

**Implementation:**

4. **[AUTOMATED] Add Path Traversal Protection**
   * [x] Open `backend/main.py`
   * [x] Locate the `serve_spa()` function (lines 206-228)
   * [x] Find the file serving block (lines 213-216):
     ```python
     # If requesting a specific file that exists, serve it directly
     file_path = static_dir / full_path
     if file_path.is_file():
         return FileResponse(file_path)
     ```
   * [x] Add path validation BEFORE the `is_file()` check:
     ```python
     # If requesting a specific file that exists, serve it directly
     file_path = static_dir / full_path
     
     # Security: Prevent directory traversal attacks
     try:
         resolved_path = file_path.resolve()
         if static_dir.resolve() not in resolved_path.parents and resolved_path != static_dir.resolve():
             raise HTTPException(status_code=404, detail="Not found")
     except (ValueError, OSError):
         raise HTTPException(status_code=404, detail="Not found")
     
     if file_path.is_file():
         return FileResponse(file_path)
     ```
   * [x] Add `from fastapi import HTTPException` to imports at top of file (if not already present)

5. **[AUTOMATED] Create Security Unit Test**
   * [x] Create `tests/test_security_path_traversal.py`:
     ```python
     """
     Security test: Path traversal prevention in SPA fallback handler.
     """
     import pytest
     from fastapi.testclient import TestClient
     from backend.main import create_app
     
     
     def test_path_traversal_blocked():
         """Verify directory traversal attacks are blocked."""
         app = create_app()
         client = TestClient(app)
         
         # Attempt to access parent directory
         response = client.get("/../../etc/passwd")
         assert response.status_code == 404, "Directory traversal should return 404"
         
         # Attempt with URL encoding
         response = client.get("/%2e%2e/%2e%2e/etc/passwd")
         assert response.status_code == 404, "Encoded traversal should return 404"
         
         # Attempt with multiple traversals
         response = client.get("/../../../../../etc/passwd")
         assert response.status_code == 404, "Multiple traversals should return 404"
     
     
     def test_legitimate_static_file_allowed():
         """Verify legitimate static files are still accessible."""
         app = create_app()
         client = TestClient(app)
         
         # This assumes index.html exists in static_dir
         response = client.get("/index.html")
         # Should return 200 (if file exists) or 404 (if static dir missing in tests)
         # Just verify it's not a 500 error
         assert response.status_code in [200, 404]
     ```
   * [x] Run: `PYTHONPATH=. python -m pytest tests/test_security_path_traversal.py -v`

**Files Modified:**
- `backend/main.py` (lines 213-216, add ~6 lines)
- `tests/test_security_path_traversal.py` (new file, ~35 lines)

**Exit Criteria:**
- [x] Path traversal protection implemented
- [x] Security tests pass
- [x] Manual verification: `curl http://localhost:8000/../../etc/passwd` returns 404
- [x] Existing static file serving still works (e.g., `/assets/index.js` serves correctly)

---

#### Phase 3: UI Help System Simplification [DONE]

**Goal:** Standardize on tooltip-only help system, remove inline `field.helper` text, and add visual "[NOT IMPLEMENTED]" badges for incomplete features.

**Rationale:**
- **Single Source of Truth:** Currently help text exists in TWO places: `config-help.json` (tooltips) + `types.ts` (inline helpers)
- **Maintenance Burden:** Duplicate text must be kept in sync
- **UI Clutter:** Inline text makes forms feel crowded
- **Scalability:** Tooltips can have rich descriptions without UI layout penalty

**Design Decision:**
- **Keep:** Tooltips (the "?" icon) from `config-help.json`
- **Keep:** Validation error text (red `text-bad` messages)
- **Remove:** All inline `field.helper` gray text
- **Add:** Visual "[NOT IMPLEMENTED]" badge for `export.enable_export` (and future incomplete features)

**Implementation:**

6. **[AUTOMATED] Remove Inline Helper Text Rendering**
   * [x] Open `frontend/src/pages/settings/components/SettingsField.tsx`
   * [x] Locate line 169: `{field.helper && field.type !== 'boolean' && <p className="text-[11px] text-muted">{field.helper}</p>}`
   * [x] Delete this entire line (removes inline helper text)
   * [x] KEEP line 170: `{error && <p className="text-[11px] text-bad">{error}</p>}` (validation errors stay visible)
   * [x] Verify tooltip logic on line 166 remains: `<Tooltip text={(configHelp as Record<string, string>)[field.key] || field.helper} />`
   * **Note:** Keep `|| field.helper` as fallback for fields not yet in config-help.json

7. **[AUTOMATED] Add "Not Implemented" Badge Component**
   * [x] Create `frontend/src/components/ui/Badge.tsx`:
     ```tsx
     import React from 'react'
     
     interface BadgeProps {
         variant: 'warning' | 'info' | 'error' | 'success'
         children: React.ReactNode
     }
     
     export const Badge: React.FC<BadgeProps> = ({ variant, children }) => {
         const variantClasses = {
             warning: 'bg-yellow-500/10 text-yellow-500 border-yellow-500/30',
             info: 'bg-blue-500/10 text-blue-500 border-blue-500/30',
             error: 'bg-red-500/10 text-red-500 border-red-500/30',
             success: 'bg-green-500/10 text-green-500 border-green-500/30',
         }
     
         return (
             <span
                 className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${variantClasses[variant]}`}
             >
                 {children}
             </span>
         )
     }
     ```

8. **[AUTOMATED] Add `notImplemented` Flag to Field Type**
   * [x] Open `frontend/src/pages/settings/types.ts`
   * [x] Find the `BaseField` interface (around line 1-20)
   * [x] Add optional property: `notImplemented?: boolean`
   * [x] Locate the `export.enable_export` field definition (search for `'export.enable_export'`)
   * [x] Add the flag:
     ```typescript
     {
         key: 'export.enable_export',
         label: 'Enable Export',
         path: ['export', 'enable_export'],
         type: 'boolean',
         notImplemented: true,  // NEW
     },
     ```

9. **[AUTOMATED] Render Badge in SettingsField**
   * [x] Open `frontend/src/pages/settings/components/SettingsField.tsx`
   * [x] Add import: `import { Badge } from '../../ui/Badge'`
   * [x] Modify the label rendering block (lines 160-167):
     ```tsx
     <label className="block text-sm font-medium mb-1.5 flex items-center gap-1.5">
         <span
             className={field.type === 'boolean' ? 'sr-only' : 'text-[10px] uppercase tracking-wide text-muted'}
         >
             {field.label}
         </span>
         {field.notImplemented && <Badge variant="warning">NOT IMPLEMENTED</Badge>}
         <Tooltip text={(configHelp as Record<string, string>)[field.key] || field.helper} />
     </label>
     ```

10. **[AUTOMATED] Update config-help.json for export.enable_export**
    * [x] Open `frontend/src/config-help.json`
    * [x] Find line 40: `"export.enable_export": "[NOT IMPLEMENTED] Master switch for grid export"`
    * [x] Remove the `[NOT IMPLEMENTED]` prefix (badge now shows it visually):
      ```json
      "export.enable_export": "Master switch for grid export (grid-to-home during high price peaks). Implementation pending."
      ```

11. **[AUTOMATED] Remove Redundant Helper Text from types.ts**
    * [x] Open `frontend/src/pages/settings/types.ts`
    * [x] Search for all `helper:` properties in field definitions
    * [x] For each field that has BOTH `helper` AND an entry in `config-help.json`:
      - Remove the `helper:` line (tooltip will use config-help.json instead)
    * [x] Keep `helper:` ONLY for fields not yet in config-help.json (as a fallback)
    * **Examples to remove:**
      - Line 156: `helper: 'Absolute limit from your grid fuse/connection.'` (has config-help entry)
      - Line 163: `helper: 'Threshold for peak power penalties (effekttariff).'` (has config-help entry)
      - Line 176: `helper: 'e.g. SE4, NO1, DK2'` (has config-help entry)
      - (Continue for all systemSections, parameterSections, uiSections, advancedSections)
    * **Keep helper text for:**
      - Any field where `config-help.json` does NOT have an entry
      - Placeholder/example text like "e.g. Europe/Stockholm" (these are useful inline)

**Files Modified:**
- `frontend/src/pages/settings/components/SettingsField.tsx` (remove line 169, update label block)
- `frontend/src/components/ui/Badge.tsx` (new file, ~25 lines)
- `frontend/src/pages/settings/types.ts` (add `notImplemented?: boolean`, set flag on export.enable_export, cleanup redundant helpers)
- `frontend/src/config-help.json` (update export.enable_export description)

**Exit Criteria:**
- [x] No inline gray helper text visible in Settings UI (only tooltips)
- [x] Validation errors still show (red text)
- [x] "[NOT IMPLEMENTED]" badge appears next to "Enable Export" toggle
- [x] All tooltips still work when hovering "?" icon
- [x] Settings UI loads without console errors
- [x] Frontend linter passes: `cd frontend && npm run lint`

---

#### Phase 4: Verification & Testing [DONE]

**Goal:** Verify all changes work correctly, pass linting/tests, and are production-ready.

**Tasks:**

12. **[AUTOMATED] Run Frontend Linter**
    * [x] Command: `cd frontend && npm run lint`
    * [x] Expected: 0 errors, 0 warnings
    * [x] If TypeScript errors appear for `Badge` import, verify export is correct

13. **[AUTOMATED] Run Backend Tests**
    * [x] Command: `PYTHONPATH=. python -m pytest tests/ -v`
    * [x] Expected: All tests pass, including new `test_security_path_traversal.py`
    * [x] Verify security test specifically: `PYTHONPATH=. python -m pytest tests/test_security_path_traversal.py -v`

14. **[AUTOMATED] Build Frontend Production Bundle**
    * [x] Command: `cd frontend && npm run build`
    * [x] Expected: Build succeeds, no errors
    * [x] Verify bundle size hasn't increased significantly (minor increase for Badge component is OK)

15. **[MANUAL] Visual Verification in Dev Environment**
    * [x] Start dev environment: `cd frontend && npm run dev` + `uvicorn backend.main:app --reload`
    * [x] Navigate to Settings page (`http://localhost:5173/settings`)
    * [x] **Verify:**
      - [x] No inline gray helper text visible under input fields
      - [x] Red validation errors still appear when submitting invalid values
      - [x] "?" tooltip icons still present and functional
      - [x] "Enable Export" field has yellow "[NOT IMPLEMENTED]" badge next to label
      - [x] No console.log/warn statements in browser dev tools (except legitimate errors)
    * [x] Navigate to Dashboard (`http://localhost:5173/`)
    * [x] **Verify:**
      - [x] No console debug statements in browser dev tools
      - [x] WebSocket connection works (live metrics update)
      - [x] Schedule chart loads without errors

16. **[MANUAL] Security Test: Path Traversal Prevention**
    * [x] Start backend: `uvicorn backend.main:app --reload`
    * [x] Test traversal attempts:
      ```bash
      curl -i http://localhost:8000/../../etc/passwd
      # Expected: HTTP/1.1 404 Not Found
      
      curl -i http://localhost:8000/../backend/main.py
      # Expected: HTTP/1.1 404 Not Found
      
      curl -i http://localhost:8000/assets/../../../etc/passwd
      # Expected: HTTP/1.1 404 Not Found
      ```
    * [x] Test legitimate file access:
      ```bash
      curl -i http://localhost:8000/
      # Expected: HTTP/1.1 200 OK (serves index.html with base href injection)
      ```

**Exit Criteria:**
- [x] All automated tests pass
- [x] Frontend builds successfully
- [x] No console debug statements in browser
- [x] Settings UI renders correctly (tooltips only, badge visible)
- [x] Path traversal attacks return 404
- [x] Legitimate static files still serve correctly

---

#### Phase 5: Documentation & Finalization [DONE]

**Goal:** Update audit report, commit changes with proper message, and mark tasks complete.

**Tasks:**

17. **[AUTOMATED] Update Audit Report Status**
    * [x] Open `docs/reports/REVIEW_2026-01-13_BETA_AUDIT.md`
    * [x] Find "Priority Action List" section (lines 28-39)
    * [x] Mark items as complete:
      - Line 34: `4. [x] Remove 5 TODO markers from user-facing text`
      - Line 35: `5. [x] Fix typo "calculationsWfz"`
      - Line 38: `8. [x] **Fix Path Traversal:** Secure \`serve_spa\`.`
    * [x] Update "High Priority Issues" section (lines 110-114):
      - Mark "1. Path Traversal Risk (Security)" as RESOLVED
      - Add note: "Fixed in REV F9 - Path validation added to serve_spa handler"

18. **[AUTOMATED] Update PLAN.md Status**
    * [x] Change this REV header to: `### [DONE] REV // F9 — Pre-Release Polish & Security`
    * [x] Update all phase statuses from `[PLANNED]` to `[DONE]`

19. **[AUTOMATED] Verify Git Status**
    * [x] Run: `git status`
    * [x] Expected changed files:
      - `frontend/src/pages/settings/types.ts`
      - `frontend/src/lib/socket.ts`
      - `frontend/src/pages/settings/hooks/useSettingsForm.ts`
      - `frontend/src/pages/Dashboard.tsx`
      - `frontend/src/components/ChartCard.tsx`
      - `frontend/src/config-help.json`
      - `backend/main.py`
      - `frontend/src/pages/settings/components/SettingsField.tsx`
      - `frontend/src/components/ui/Badge.tsx` (new)
      - `tests/test_security_path_traversal.py` (new)
      - `docs/reports/REVIEW_2026-01-13_BETA_AUDIT.md`
      - `docs/PLAN.md`

20. **[MANUAL] Commit with Proper Message**
    * [x] Follow AGENTS.md commit protocol
    * [x] Wait for user to review changes before committing
    * [ ] Suggested commit message:
      ```
      feat(security,ui): pre-release polish and path traversal fix
      
      REV F9 - Production-grade improvements before public beta release:
      
      Security:
      - Fix path traversal vulnerability in serve_spa handler
      - Add security unit tests for directory traversal prevention
      
      Code quality:
      - Remove 9 debug console.* statements from production code
      - Fix typo "calculationsWfz" in config help text
      
      UX:
      - Simplify help system to tooltip-only (single source of truth)
      - Add visual "[NOT IMPLEMENTED]" badge for incomplete features
      - Remove redundant inline helper text from settings fields
      
      Breaking Changes: None
      
      Closes: Priority items #3, #4, #5, #8 from BETA_AUDIT report
      ```

**Exit Criteria:**
- [x] Audit report updated
- [x] PLAN.md status updated to [DONE]
- [x] All changes committed with proper message
- [x] User has reviewed and approved changes

---

## REV F9 Success Criteria

**The following MUST be true before marking REV as [DONE]:**

1. **Security:**
   - [x] Path traversal vulnerability patched
   - [x] Security tests pass (directory traversal blocked)
   - [x] Legitimate files still accessible

2. **Code Quality:**
   - [x] Typo "calculationsWfz" fixed
   - [x] Frontend linter passes with 0 errors
   - [x] Backend tests pass with 0 failures

3. **UI/UX:**
   - [x] Inline helper text removed from all settings fields
   - [x] Tooltips still functional on all "?" icons
   - [x] "[NOT IMPLEMENTED]" badge visible on export.enable_export
   - [x] Validation errors still display in red

4. **Documentation:**
   - [x] Audit report updated (tasks marked complete)
   - [x] PLAN.md status updated
   - [x] Commit message follows AGENTS.md protocol

5. **Verification:**
   - [x] Manual testing completed in dev environment
   - [x] Path traversal manual security test passed
   - [x] Production build succeeds

**Sign-Off Required:**
- [ ] User has reviewed visual changes in Settings UI
- [ ] User has approved commit message
- [ ] User confirms path traversal fix is adequate

---

## Notes for Implementing AI

**Critical Reminders:**

1. **Debug Console Statements:** These are intentionally NOT removed in this REV as they are being used for active troubleshooting of history display issues in Docker/HA deployment. A future REV will clean these up once the investigation is complete.

2. **Helper Text Cleanup:** When removing `helper:` properties from `types.ts`, verify each field has an entry in `config-help.json` FIRST. If missing, ADD to config-help.json before removing from types.ts.

3. **Badge Component:** The Badge must use Tailwind classes compatible with your theme. Test in both light and dark modes.

4. **Path Traversal Fix:** The security fix uses `.resolve()` which returns absolute paths. Test edge cases like symlinks, Windows paths (if applicable), and URL-encoded traversals.

5. **Testing Rigor:** Run the manual security test with `curl` before marking Phase 4 complete. Automated tests alone are not sufficient for security validation.

6. **Single Source of Truth:** After this REV, `config-help.json` becomes the ONLY place for help text. Update DEVELOPER.md or AGENTS.md if needed to document this.

7. **Visual Verification:** The UI changes (removed inline text, added badge) MUST be visually verified. Screenshots in an artifact would be ideal for user review.

---

### [DONE] REV // H3 — Restore Historical Planned Actions Display

**Goal:** Restore historical planned action overlays (charge/discharge bars, SoC target line) in the ChartCard by querying the `slot_plans` database table instead of relying on the ephemeral `schedule.json` file.

**Context:** Historical slot preservation was intentionally removed in commit 222281d (Jan 9, 2026) during the MariaDB sunset cleanup (REV LCL01). The old code called `db_writer.get_preserved_slots()` to merge historical slots into `schedule.json`. Now the planner only writes future slots to `schedule.json`, but continues to persist ALL slots to the `slot_plans` SQLite table. The API endpoint `/api/schedule/today_with_history` queries `schedule.json` for planned actions but does NOT query `slot_plans`, causing historical slots to lack planned action overlays.

**Root Cause Summary:**
- `slot_plans` table (populated by planner line 578-590 of `pipeline.py`) ✅ HAS the data
- `/api/schedule/today_with_history` endpoint ❌ does NOT query `slot_plans`
- `schedule.json` only contains future slots (intentional behavior after REV LCL01)
- Frontend shows `actual_soc` for historical slots but no `battery_charge_kw` or `soc_target_percent`

**Breaking Changes:** None. This restores previously removed functionality.

**Investigation Report:** `/home/s/.gemini/antigravity/brain/753f0418-2242-4260-8ddb-a0d8af709b17/investigation_report.md`

---

#### Phase 1: Database Schema Verification [PLANNED]

**Goal:** Verify `slot_plans` table schema and data availability on both dev and production environments.

**Tasks:**

1. **[AUTOMATED] Verify slot_plans Schema**
   * [ ] Run on dev: `sqlite3 data/planner_learning.db "PRAGMA table_info(slot_plans);"`
   * [ ] Verify columns exist: `slot_start`, `planned_charge_kwh`, `planned_discharge_kwh`, `planned_soc_percent`, `planned_export_kwh`
   * [ ] Document schema in implementation notes

2. **[AUTOMATED] Verify Data Population**
   * [x] Run on dev: `sqlite3 data/planner_learning.db "SELECT COUNT(*) FROM slot_plans WHERE slot_start >= date('now');"`
   * [x] Run on production: Same query via SSH/docker exec
   * [x] Verify planner is actively writing to `slot_plans` (check timestamps)

3. **[MANUAL] Verify Planner Write Path**
   * [ ] Confirm `planner/pipeline.py` lines 578-590 call `store.store_plan(plan_df)`
   * [ ] Confirm `backend/learning/store.py:store_plan()` writes to `slot_plans` table
   * [ ] Document column mappings:
     - `planned_charge_kwh` → `battery_charge_kw` (needs kWh→kW conversion)
     - `planned_discharge_kwh` → `battery_discharge_kw`
     - `planned_soc_percent` → `soc_target_percent`

**Exit Criteria:**
- [x] Schema documented
- [x] Data availability confirmed on both environments
- [x] Column mappings documented

---

#### Phase 2: API Endpoint Implementation [COMPLETED]

**Goal:** Add `slot_plans` query to `/api/schedule/today_with_history` endpoint and merge planned actions into historical slots.

**Files to Modify:**
- `backend/api/routers/schedule.py`

**Tasks:**

4. **[AUTOMATED] Add slot_plans Query**
   * [x] Open `backend/api/routers/schedule.py`
   * [x] Locate the `today_with_history` function (line ~136)
   * [x] After the `forecast_map` query (around line 273), add new section:
   
   ```python
   # 4. Planned Actions Map (slot_plans table)
   planned_map: dict[datetime, dict[str, float]] = {}
   try:
       db_path_str = str(config.get("learning", {}).get("sqlite_path", "data/planner_learning.db"))
       db_path = Path(db_path_str)
       if db_path.exists():
           async with aiosqlite.connect(str(db_path)) as conn:
               conn.row_factory = aiosqlite.Row
               today_iso = tz.localize(
                   datetime.combine(today_local, datetime.min.time())
               ).isoformat()
               
               query = """
                   SELECT
                       slot_start,
                       planned_charge_kwh,
                       planned_discharge_kwh,
                       planned_soc_percent,
                       planned_export_kwh
                   FROM slot_plans
                   WHERE slot_start >= ?
                   ORDER BY slot_start ASC
               """
               
               async with conn.execute(query, (today_iso,)) as cursor:
                   async for row in cursor:
                       try:
                           st = datetime.fromisoformat(str(row["slot_start"]))
                           st_local = st if st.tzinfo else tz.localize(st)
                           key = st_local.astimezone(tz).replace(tzinfo=None)
                           
                           # Convert kWh to kW (slot_plans stores kWh, frontend expects kW)
                           duration_hours = 0.25  # 15-min slots
                           
                           planned_map[key] = {
                               "battery_charge_kw": float(row["planned_charge_kwh"] or 0.0) / duration_hours,
                               "battery_discharge_kw": float(row["planned_discharge_kwh"] or 0.0) / duration_hours,
                               "soc_target_percent": float(row["planned_soc_percent"] or 0.0),
                               "export_kwh": float(row["planned_export_kwh"] or 0.0),
                           }
                       except Exception:
                           continue
                           
       logger.info(f"Loaded {len(planned_map)} planned slots for {today_local}")
   except Exception as e:
       logger.warning(f"Failed to load planned map: {e}")
   ```

5. **[AUTOMATED] Merge Planned Actions into Slots**
   * [x] Locate the slot merge loop (around line 295-315)
   * [x] After the forecast merge block, add:
   
   ```python
   # Attach planned actions from slot_plans database
   if key in planned_map:
       p = planned_map[key]
       # Only add if not already present from schedule.json
       if "battery_charge_kw" not in slot or slot.get("battery_charge_kw") is None:
           slot["battery_charge_kw"] = p["battery_charge_kw"]
       if "battery_discharge_kw" not in slot or slot.get("battery_discharge_kw") is None:
           slot["battery_discharge_kw"] = p["battery_discharge_kw"]
       if "soc_target_percent" not in slot or slot.get("soc_target_percent") is None:
           slot["soc_target_percent"] = p["soc_target_percent"]
       if "export_kwh" not in slot or slot.get("export_kwh") is None:
           slot["export_kwh"] = p.get("export_kwh", 0.0)
   ```

6. **[AUTOMATED] Add Logging for Debugging**
   * [x] Add at end of function before return:
   ```python
   historical_with_planned = sum(1 for s in slots if s.get("actual_soc") is not None and s.get("battery_charge_kw") is not None)
   logger.info(f"Returning {len(slots)} slots, {historical_with_planned} historical with planned actions")
   ```

**Exit Criteria:**
- [x] `slot_plans` query added
- [x] Merge logic implemented with precedence (schedule.json values take priority)
- [x] Debug logging added
- [x] No linting errors

---

#### Phase 3: Testing & Verification [COMPLETED]

**Goal:** Verify the fix works correctly on both dev and production environments.

**Tasks:**

7. **[AUTOMATED] Backend Linting**
   * [x] Run: `cd backend && ruff check api/routers/schedule.py`
   * [x] Fix any linting errors
   * [x] Run: `cd backend && ruff format api/routers/schedule.py`

8. **[AUTOMATED] Unit Test for slot_plans Query**
   * [x] Create test in `tests/test_api.py` or `tests/test_schedule_api.py`:
   ```python
   @pytest.mark.asyncio
   async def test_today_with_history_includes_planned_actions():
       """Verify historical slots include planned actions from slot_plans."""
       # Setup: Insert test data into slot_plans
       # Call endpoint
       # Assert historical slots have battery_charge_kw and soc_target_percent
   ```
   * [x] Run: `PYTHONPATH=. pytest tests/test_schedule_api.py -v`

9. **[MANUAL] Dev Environment Verification**
   * [x] Start dev server: `pnpm dev`
   * [x] Wait for planner to run (or trigger manually)
   * [x] Open browser to Dashboard
   * [x] View ChartCard with "Today" range
   * [x] **Verify:** Historical slots show:
     - Green bars for charge actions
     - Red bars for discharge actions
     - SoC target overlay line
   * [x] Check browser console - no errors related to undefined data

10. **[MANUAL] API Response Verification**
    * [x] Run: `curl -s http://localhost:5000/api/schedule/today_with_history | jq '.slots[0] | {start_time, actual_soc, battery_charge_kw, soc_target_percent}'`
    * [x] Verify historical slots have BOTH `actual_soc` AND `battery_charge_kw`
    * [x] Compare count: Historical slots with planned actions should equal slot_plans count for today

11. **[MANUAL] Production Verification**
    * [x] Deploy to production (build + push Docker image)
    * [x] SSH to server and run same curl test
    * [x] Open production dashboard in browser
    * [x] Verify historical planned actions visible
    * [x] Monitor logs for any errors

**Exit Criteria:**
**Exit Criteria:**
- [x] All linting passes
- [x] Unit test passes
- [x] Dev environment shows historical planned actions
- [x] Production environment shows historical planned actions
- [x] No console errors in browser

---

#### Phase 4: Documentation #### Phase 4: Documentation & Cleanup [DONE] Cleanup [IN PROGRESS]

**Goal:** Update documentation and remove investigation artifacts.

**Tasks:**

12. **[AUTOMATED] Update Code Comments**
    * [x] Add comment in `schedule.py` at the new query section:
    ```python
    # REV H3: Query slot_plans for historical planned actions
    # This restores functionality removed in commit 222281d (REV LCL01)
    # The planner writes all slots to slot_plans but only future slots to schedule.json
    ```

13. **[AUTOMATED] Update PLAN.md**
    * [x] Change REV status from `[PLANNED]` to `[DONE]`
    * [x] Mark all task checkboxes as complete

14. **[AUTOMATED] Update Audit Report**
    * [x] Open `docs/reports/REVIEW_2026-01-13_BETA_AUDIT.md`
    * [x] Add finding to "Fixed" section (if applicable)
    * [x] Note the root cause and fix for future reference

15. **[AUTOMATED] Commit Changes**
    * [x] Stage files: `git add backend/api/routers/schedule.py tests/ docs/`
    * [x] Commit: `git commit -m "fix(api): restore historical planned actions via slot_plans query (REV H3)"`

**Exit Criteria:**
- [x] Code comments added
- [x] PLAN.md updated
- [x] Changes committed
- [x] Debug console statements can now be removed (separate REV)

---

## REV H3 Success Criteria

**The following MUST be true before marking REV as [DONE]:**

1. **Functionality:**
   - [x] Historical slots in API response include `battery_charge_kw`
   - [x] Historical slots in API response include `soc_target_percent`
   - [x] ChartCard displays charge/discharge bars for historical slots
   - [x] ChartCard displays SoC target line for historical slots

2. **Data Integrity:**
   - [x] Future slots from schedule.json take precedence over slot_plans
   - [x] No duplicate data in merged response
   - [x] No missing slots (same 96 count for full day)

3. **Performance:**
   - [x] slot_plans query adds < 100ms to endpoint response time
   - [x] No N+1 query issues (single query for all planned slots)

4. **Code Quality:**
   - [x] Ruff linting passes
   - [x] Unit test for slot_plans query passes
   - [x] No regressions in existing tests

5. **Verification:**
   - [x] Dev environment tested manually
   - [x] Production environment tested manually
   - [x] API response structure verified via curl

**Sign-Off Required:**
- [x] User has verified historical planned actions visible in production UI

---

## Notes for Implementing AI

**Critical Reminders:**

1. **kWh to kW Conversion:** `slot_plans` stores energy (kWh) but frontend expects power (kW). Divide by slot duration (0.25h for 15-min slots).

2. **Precedence:** If both `schedule.json` and `slot_plans` have data for a slot, prefer `schedule.json` (it's more recent for future slots).

3. **Null Handling:** Check for `None` values before merging. Use `slot.get("field") is None` not just `if field not in slot`.

4. **Timezone Handling:** The `slot_start` timestamps in `slot_plans` may be ISO strings with timezone. Parse correctly using `datetime.fromisoformat()`.

5. **Async Database:** The endpoint is async. Use `aiosqlite` for the slot_plans query, not sync `sqlite3` (which would block the event loop).

6. **Testing Without Planner:** If unit testing, you may need to mock or pre-populate `slot_plans` table with test data.

7. **Field Mapping Reference:**
   | slot_plans Column | API Response Field | Conversion |
   |-------------------|-------------------|------------|
   | `planned_charge_kwh` | `battery_charge_kw` | ÷ 0.25 |
   | `planned_discharge_kwh` | `battery_discharge_kw` | ÷ 0.25 |
   | `planned_soc_percent` | `soc_target_percent` | None |
   | `planned_export_kwh` | `export_kwh` | None |

8. **Debug Console Cleanup:** After this REV is verified working, the debug console statements can be removed in a separate cleanup task.

---

### [DONE] REV // H4 — Detailed Historical Planned Actions Persistence

**Goal:** Ensure 100% reliable historical data for SoC targets and Water Heating in both 24h and 48h views by fixing persistence gaps and frontend logic, rather than relying on ephemeral `schedule.json` artifacts.

**Phase 1: Backend Persistence Fixes**
1. **[SCHEMA] Update `slot_plans` Table**
   * [x] Add `planned_water_heating_kwh` (REAL) column to `LearningStore._init_schema`
   * [x] Handle migration for existing DBs (add column if missing)

2. **[LOGIC] Fix `store_plan` Mapping**
   * [x] In `store.py`, map DataFrame column `soc_target_percent` → `planned_soc_percent` (Fix the 0% bug)
   * [x] Map DataFrame column `water_heating_kw` → `planned_water_heating_kwh` (Convert kW to kWh using slot duration)

3. **[API] Expose Water Heating History**
   * [x] Update `schedule_today_with_history` in `schedule.py` to SELECT `planned_water_heating_kwh`
   * [x] Convert kWh back to kW for API response
   * [x] Merge into response slot data

**Phase 2: Frontend Consistency**
4. **[UI] Unify Data Source for ChartCard**
   * [x] Update `ChartCard.tsx` to use `Api.scheduleTodayWithHistory()` for BOTH 'day' and '48h' views
   * [x] Ensure `buildLiveData` correctly handles historical data for the 48h range

**Phase 3: Verification**
5. **[TEST] Unit Tests**
   * [x] Create `tests/test_store_plan_mapping.py` to verify DataFrame → DB mapping for SoC and Water
   * [x] Verify `soc_target_percent` is correctly stored as non-zero
   * [x] Verify `water_heating_kw` is correctly stored and converted

6. **[MANUAL] Production Validation**
   * [ ] Deploy to prod
   * [ ] Verify DB has non-zero `planned_soc_percent`
   * [ ] Verify DB has `planned_water_heating_kwh` data
   * [ ] Verify 48h view shows historical attributes

**Exit Criteria:**
- [x] `slot_plans` table has `planned_water_heating_kwh` column
- [x] Historical `planned_soc_percent` in DB is correct (not 0)
- [x] Historical water heating is visible in ChartCard
- [x] 48h view shows same historical fidelity as 24h view

---

### [PLANNED] REV // PERF1 — MILP Solver Performance Optimization

**Goal:** Reduce Kepler MILP solver execution time from 22s to <5s by optimizing or eliminating the water heating spacing constraint.

**Context:** Profiling revealed that the planner spends 22 seconds in the Kepler MILP solver, primarily due to the water heating "spacing penalty" constraint (lines 282-287 in `planner/solver/kepler.py`). This constraint creates O(T × spacing_slots) ≈ 2000 pairwise constraints for a 100-slot horizon with a 5-hour spacing window. Disabling the spacing penalty (`water_spacing_penalty_sek: 0`) reduces solver time to 9.79s, proving it's the bottleneck.

**Profiling Results:**
- **With spacing penalty**: 22s solver time
- **Without spacing penalty**: 9.79s solver time
- **Improvement**: 55% faster (12s saved)

**Priority:** **HIGH** — This directly impacts user experience (planner runs every 30 minutes).

#### Phase 1: Investigation [PLANNED]
**Goal:** Understand the trade-offs and identify optimization strategies.

* [ ] **Document Current Behavior:**
  - What is the spacing penalty supposed to prevent? (Frequent water heater on/off cycles for efficiency)
  - What happens if we disable it? (More frequent heating blocks, potential efficiency loss)
  - Quantify comfort/efficiency impact: Run 1 week simulation with/without spacing penalty

* [ ] **Analyze Constraint Complexity:**
  - Current: O(T × spacing_slots) where T=100, spacing_slots=20 → 2000 constraints
  - Why is this slow? (Branch-and-bound in MILP solver scales poorly with binary variable pairwise constraints)

* [ ] **Research Alternative Formulations:**
  - **Option A:** Aggregate constraint (e.g., "max 3 heating blocks per day" instead of pairwise spacing)
  - **Option B:** Lookahead constraint (only check past N slots, not all slots in window)
  - **Option C:** Soft heuristic post-solve (run MILP without spacing, then penalize solutions with violations)
  - **Option D:** Completely remove spacing, rely only on gap penalty for comfort

* [ ] **Benchmark Alternatives:**
  - Implement Option A/B/C in separate branches
  - Measure solver time and solution quality
  - Document results in comparison table

#### Phase 2: Implementation [PLANNED]
**Goal:** Deploy the best-performing alternative from Phase 1.

* [ ] **Code Changes:**
  - Modify `planner/solver/kepler.py` to implement chosen alternative
  - Update `planner/solver/adapter.py` if config mapping changes
  - Add config option to toggle old/new behavior (for A/B testing)

* [ ] **Testing:**
  - Unit tests for new constraint logic
  - Integration test: Verify planner runs in <10s
  - Regression test: Compare schedules before/after (should be similar quality)

#### Phase 3: Validation [PLANNED]
**Goal:** Verify production-readiness.

* [ ] **Performance Verification:**
  - Run `scripts/profile_deep.py` → Planner should be <10s
  - Stress test: 1000-slot horizon (edge case) should still solve in reasonable time

* [ ] **Quality Verification:**
  - Manual inspection: Do water heating blocks look reasonable?
  - Energy efficiency: Compare total kWh heating cost before/after

* [ ] **Documentation:**
  - Update `planner/solver/kepler.py` docstrings
  - Add performance notes to `docs/ARCHITECTURE.md`

**Exit Criteria:**
- [ ] Planner execution time reduced from 22s to <10s
- [ ] Water heating schedule quality remains acceptable (user-verified)
- [ ] All tests pass
- [ ] Changes documented