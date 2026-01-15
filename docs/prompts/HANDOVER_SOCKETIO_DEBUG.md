# Handover: Socket.IO Live Metrics Not Working in HA Add-on

## Problem Statement
The PowerFlow card in the HA Add-on deployment shows NO live metrics data. The backend is successfully emitting `live_metrics` events via Socket.IO, but the frontend never receives them.

**This issue ONLY affects HA Add-on deployments** — local development works fine.

## Current Status (2026-01-15)
- REV F11 in `docs/PLAN.md` tracks this issue
- Multiple fix attempts made, none successful yet
- Comprehensive debugging added in commit `d6bf260`

## Architecture Overview

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Browser   │ ──▶ │  HA Core Ingress │ ──▶ │ Darkstar Add-on │
│             │     │  (Reverse Proxy) │     │   (Port 5000)   │
└─────────────┘     └──────────────────┘     └─────────────────┘
                           │
                    Adds X-Ingress-Path
                    Strips /api/hassio_ingress/xxx/ prefix?
```

### Key Components
1. **Frontend Socket.IO Client**: `frontend/src/lib/socket.ts`
2. **Backend Socket.IO Server**: `backend/core/websockets.py`
3. **ASGI Wrapper**: `backend/main.py` (line 293: `socketio.ASGIApp`)
4. **HA Add-on Config**: `darkstar/config.yaml` (`ingress_stream: true`)

## What We Know

### Backend IS Working
```
INFO: darkstar.ha_socket - DIAG: Emitting live_metrics for load_kw raw=3612 val=3.612
INFO: darkstar.ha_socket - DIAG: Emitting live_metrics for pv_kw raw=791 val=0.791
```

### Frontend IS Trying to Connect
```
🔌 WebSocket initializing: origin=https://home.wxl.se, path=/api/hassio_ingress/xxx/socket.io/
```

### But Getting 404 or Silent Failures
Previous console showed:
```
GET https://home.wxl.se/socket.io/?EIO=4&transport=polling [404]
🔌 WebSocket connection error: xhr poll error
```

## Root Cause Theories

### Theory 1: Path Mismatch (MOST LIKELY)
- Frontend sends: `path=/api/hassio_ingress/xxx/socket.io/`
- Socket.IO client makes request to: `origin + path`
- HA Ingress receives: `/api/hassio_ingress/xxx/socket.io/`
- HA Ingress proxies to add-on and MAY strip prefix
- Backend Socket.IO listens on: `/socket.io` (default)

**The Question**: Does HA Ingress strip the `/api/hassio_ingress/xxx/` prefix when proxying?

### Theory 2: WebSocket Upgrade Not Passing Through
- HA Ingress has `ingress_stream: true` which SHOULD enable WebSocket
- But upgrade headers may not be passed correctly

### Theory 3: The Client Path Should Be `/socket.io/`
If HA Ingress does strip the prefix, then the frontend should use:
```typescript
socket = io(baseUrl.origin, { path: '/socket.io/' })
```
Not the full ingress path.

## Debug Endpoints Available

After deploying the latest code:

| Endpoint | Purpose |
|:---------|:--------|
| `GET /api/ha-socket` | HA WebSocket client (backend→HA) status |
| `GET /api/socketio-debug` | Socket.IO server status + connected clients |
| `GET /api/scheduler-debug` | Scheduler status (separate issue) |
| `GET /api/executor-debug` | Executor status |

## Files Modified

### `frontend/src/lib/socket.ts`
- Extensive connection diagnosis logging
- Transport open/close events
- Reconnect tracking
- Hint messages for common errors

### `backend/core/websockets.py`
- `logger=True, engineio_logger=True` — verbose Socket.IO logging
- Connect/disconnect event handlers that log:
  - `PATH_INFO` (what path the server received)
  - `X-Ingress-Path` header
  - `QUERY_STRING`

### `backend/api/routers/debug.py`
- Added `/api/socketio-debug` endpoint

## What the Next Agent Should Do

### Step 1: Deploy and Collect Diagnostics
1. Build and deploy to HA Add-on
2. Open browser console, navigate to Darkstar
3. Copy FULL console output (don't filter)
4. Copy Add-on logs (should show Socket.IO verbose output)
5. Visit `/api/socketio-debug` and copy output

### Step 2: Analyze the Logs

**Look for in Browser Console:**
- What path is shown in "Socket Path:"?
- Is there a `🔌 Socket.IO Transport OPENED` message?
- What error appears in `❌ Socket.IO connect_error`?

**Look for in Add-on Logs:**
- Is there a `🔌 Socket.IO client CONNECTED` message?
- What `PATH_INFO` does the server receive?
- Any Engine.IO errors?

### Step 3: Fix Based on Findings

**If server never receives connection:**
- HA Ingress is not forwarding Socket.IO requests correctly
- May need nginx config in HA, or different path strategy

**If server receives connection but wrong path:**
- Mismatch between client path and server path
- Try changing frontend to use `/socket.io/` instead of full ingress path

**If server receives and connects but no events:**
- Event emission or subscription issue
- Check `socket.onAny()` for any events at all

## Related Documentation
- `docs/PLAN.md` — REV F11: Socket.IO Live Metrics Not Working
- `docs/ARCHITECTURE.md` — System architecture
- `.agent/memory.md` — Contains note about HA Ingress SPA Support

## Commit History (Recent)
```
d6bf260 debug(socket.io): comprehensive debugging for HA Ingress issue
4866eb6 debug(socket.io): add extensive logging + ensure trailing slash
50bed82 fix(socket.io): path must include ingress prefix
b16a30d fix(ha-ingress): Socket.IO path calculation + add debug endpoints
```

## Quick Test Commands

```bash
# Build frontend
cd frontend && pnpm build

# Check linting
cd frontend && pnpm lint
ruff check backend/

# View Socket.IO client code
cat frontend/src/lib/socket.ts

# View Socket.IO server code
cat backend/core/websockets.py
```
