## Why

The frontend currently has two independent backend-status indicators that confuse users: a sidebar green dot (30s REST poll) and a Dashboard "● Live" badge (WebSocket state). They can disagree, the REST poll lags up to 30s, and the WebSocket is only initialized when the Dashboard mounts — so the sidebar dot is the only signal on other pages, and it's the weaker one. We should consolidate to a single, accurate, real-time indicator driven by the WebSocket, visible everywhere.

## What Changes

- Eagerly initialize the Socket.IO singleton at app startup (in `App.tsx` / `RootLayout`) so the connection state is meaningful on every route, not just the Dashboard.
- Extend the connection-state model from a boolean to a tri-state: `connecting` | `connected` | `offline`, where `offline` is escalated after the socket has been in `connecting` for more than 10 seconds (sustained failure).
- Replace the sidebar's 30s REST API polling (`Api.status()`) with a subscription to the WebSocket connection state. The sidebar dot becomes the single, always-visible indicator with three colors: grey (connecting), green (connected), red (offline). Tooltip-only, no text label.
- Remove the "● Live" / "● Reconnecting…" badge from the top of the Dashboard page, including its now-orphaned `Badge` import from `Banner.tsx`.
- Keep the Dashboard's `useSocketStatus()` subscription and refetch-on-reconnect logic intact — only the visible badge is removed; the refetch trigger condition is updated to check `=== 'connected'`.
- Keep the `App.tsx` 60s health poll and amber "Backend appears offline" banner unchanged — it serves a different purpose (a loud alarm for sustained outages, separate from the ambient dot).

## Capabilities

### New Capabilities

_(none — no new capability is introduced; the socket connection state is an internal mechanism, not a user-facing capability)_

### Modified Capabilities

- `dashboard-connection-resilience`: The "Dashboard shows connection liveness" requirement is replaced — the visible liveness indicator moves from the Dashboard to the Sidebar (app-wide), the socket is eagerly initialized at app boot, and the state model becomes tri-state (`connecting`/`connected`/`offline`) with a 10s sustained-failure escalation to `offline`.

## Impact

- **Frontend**:
  - `frontend/src/lib/socket.ts` — extend state model from boolean to tri-state union; add 10s escalation timer.
  - `frontend/src/lib/hooks.ts` — `useSocketStatus()` return type changes from `boolean` to `ConnectionState`.
  - `frontend/src/App.tsx` — eagerly call `getSocket()` on mount.
  - `frontend/src/components/Sidebar.tsx` — replace `Api.status()` polling with `useSocketStatus()`; update dot to tri-state color/title.
  - `frontend/src/pages/Dashboard.tsx` — remove the `<Badge>` liveness block and orphaned `Badge` import; update refetch condition to `=== 'connected'`.
  - `frontend/src/lib/hooks.test.ts` — update assertions for tri-state; add escalation test case.
- **Backend**: none.
- **Dependencies**: none.
- **APIs**: the sidebar no longer calls `Api.status()` every 30s (minor reduction in request volume); `Api.status()` remains in use by `App.tsx` health poll.
