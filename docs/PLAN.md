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

---





### REV // F12 — Scheduler Not Running First Cycle [TO INVESTIGATE]

**Problem:** Scheduler shows `last_run_at: null` even though enabled and running.
From debug endpoint:
```json
{
  "status": "running",
  "enabled": true,
  "runtime": {
    "last_run_at": null,
    "next_run_at": "2026-01-15T09:15:27",
    "last_run_status": null
  },
  "diagnostics": {
    "message": "🔄 Scheduler is enabled but hasn't run yet (waiting for first scheduled time)"
  }
}
```

**To Investigate:**
- [ ] Why scheduler waits until next boundary instead of running immediately on startup
- [ ] Check if `next_run_at` calculation is correct
- [ ] Consider adding "run immediately on startup if enabled" behavior

**Priority:** Medium (scheduler works, just delayed start)

---

### REV // F13 — Socket.IO Debug Cleanup [POST-BETA]

**Goal:** Remove verbose debug logging and runtime config after beta testers have confirmed stable Socket.IO connections across various environments.

**Context:** REV F11 added extensive instrumentation to debug the HA Ingress connection issue:
- `console.log` statements throughout `socket.ts`
- `?socket_path` and `?socket_transports` URL param overrides
- Packet-level logging (`packetCreate`, `packet` events)

This should remain in place during beta testing to allow users to self-diagnose issues.

**Cleanup Scope:**
- [ ] Remove or reduce `console.log` statements in `socket.ts`
- [ ] Consider keeping URL param overrides as a hidden "power user" feature
- [ ] Remove `eslint-disable` comments added for debug casting
- [ ] Update `docs/ARCHITECTURE.md` if runtime config is removed

**Trigger:** After 2+ weeks of stable beta feedback with no new Socket.IO issues reported.

**Priority:** Low (cleanup only, no functional change)

---



### [PLANNED] REV // F15 — Extend Conditional Visibility to Parameters Tab

**Goal:** Apply the same `showIf` conditional visibility pattern from F14 to the Parameters/Settings tabs (not just HA Entities).

**Context:** The System Profile toggles (`has_solar`, `has_battery`, `has_water_heater`) should control visibility of many settings across all tabs:
- Water Heating parameters (min_kwh, spacing, temps) — grey if `!has_water_heater`
- Battery Economics — grey if `!has_battery`
- S-Index settings — grey if `!has_battery`
- Solar array params — grey if `!has_solar`
- Future: EV Charger, Heat Pump, Pool Heater, multiple MPPT strings

**Scope:**
- Extend `showIf` to `parameterSections` in `types.ts`
- Apply same greyed overlay pattern in ParametersTab
- Support all System Profile toggles as conditions

**Priority:** Low (foundation is set in F14, this is expansion)

**Dependencies:** REV F14 must be complete first

---






