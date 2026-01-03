# Technical Debt & Roadmap

## Async Migration (Blocking Calls)

The following locations use blocking I/O within `async def` route handlers. These should be migrated to non-blocking alternatives or run in threadpools.

### 1. External HTTP Requests (replace with `httpx` or `aiohttp`) - **[RESOLVED]**
- [x] `backend/api/routers/services.py`: Migrated to `httpx`.
- [x] `backend/health.py`: Migrated `HealthChecker` to async and `httpx`.

### 2. Database Operations (replace with `aiosqlite`) - **[RESOLVED]**
- [x] `backend/api/routers/forecast.py`: Migrated to `aiosqlite`.
- [x] `backend/api/routers/learning.py`: Migrated to `aiosqlite`.
- [x] `backend/api/routers/debug.py`: Migrated to `aiosqlite`.
- [x] `ml/api.py`: Added `get_forecast_slots_async` support.
