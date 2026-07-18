# Tasks: s-index-history-persistence

## 1. Schema

- [x] 1.1 Add `SIndexHistory` ORM model to `backend/learning/models.py`: table `s_index_history` with `id` (Integer PK autoincrement), `created_at` (String, ISO-8601 UTC), `payload` (Text, JSON)
- [x] 1.2 Create Alembic migration adding the `s_index_history` table and an index on `created_at`; verify `alembic upgrade head` and `alembic downgrade -1` both run cleanly on a copy of a dev DB

## 2. Write path

- [x] 2.1 Add `record_s_index_history(s_index_debug: dict, ...)` to `planner/observability/logging.py`, following the `record_debug_payload` pattern (async session via `get_learning_engine().store`, warn-and-continue on any exception, silent skip when engine/store is unavailable) but NOT gated on `learning_config["enable"]`
- [x] 2.2 In the same function, after the insert, delete rows with `created_at` older than 365 days (cutoff computed in UTC)
- [x] 2.3 Call `record_s_index_history` from the schedule output path in `planner/output/schedule.py` where `s_index_debug` is in hand, once per successful schedule generation; skip when the debug dict is empty

## 3. Tests

- [x] 3.1 Test: a successful planner output write inserts exactly one `s_index_history` row whose payload round-trips to the input dict and whose `created_at` parses as UTC ISO-8601
- [x] 3.2 Test: rows older than 365 days are deleted on write, rows inside the window survive
- [x] 3.3 Test: an exception raised during insert is swallowed with a warning log and does not propagate
- [x] 3.4 Test: write happens with learning `enable: false`; write is skipped without error when the learning store is unavailable

## 4. Verification

- [x] 4.1 Run the full test suite and linters (`pnpm`/`pytest` per repo convention) — all green
- [x] 4.2 Run the dev backend against a real planner run and confirm a row appears in the local `data/planner_learning.db` `s_index_history` table with the expected payload
