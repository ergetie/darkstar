## Context

The frontend has a singleton Socket.IO client (`frontend/src/lib/socket.ts`) created lazily on first `getSocket()` call. Today only the Dashboard (and Executor, CommandBar, ModelTrainingCard) trigger that call by subscribing to socket events via `useSocket()`. The connection state is a module-level boolean updated by `connect`/`disconnect` listeners and exposed through `subscribeConnection()` / `useSocketStatus()`.

Three overlapping backend-status mechanisms exist today:

1. **App.tsx** (lines 68–99) — 60s REST poll of `Api.status()` + `Api.health()`, shows an amber full-width banner after 3 consecutive failures (~3 min). **Stays as-is** — serves as a loud alarm for sustained outages.
2. **Sidebar.tsx** (lines 50–65) — 30s REST poll of `Api.status()`, drives a tri-state dot (`null`/`true`/`false`). **Replaced** by WebSocket state.
3. **Dashboard.tsx** (lines 547–552) — WebSocket-driven "● Live" badge. **Removed**.

The socket is configured with `reconnection: true`, `reconnectionAttempts: Infinity`, backoff 1s→5s capped.

## Goals / Non-Goals

**Goals:**
- Single, accurate, real-time connection indicator visible on every route.
- Indicator reflects WebSocket transport state (not a laggy REST poll).
- Tri-state model distinguishes transient connecting from sustained offline.
- Eager socket initialization so the indicator is meaningful app-wide from first paint.

**Non-Goals:**
- Touching the App.tsx amber "Backend appears offline" banner or its 60s health poll.
- Changing the socket's reconnection policy (indefinite, 1s–5s backoff stays).
- Adding text labels to the sidebar dot (tooltip-only, per user decision).
- Backend changes.

## Decisions

### Decision 1: Eager socket init in `RootLayout`, not `App.tsx`

The socket is booted with a `useEffect(() => { getSocket() }, [])` inside the `RootLayout` component (not the top-level `App` function component). `RootLayout` is where `Sidebar` and the routed `<Outlet>` already mount, so the socket initializes at the same point in the tree where its state is consumed.

**Alternative considered**: Booting in `App.tsx` (the outermost component). Rejected because `RootLayout` is the natural boundary — it's the layout that renders the sidebar and the page outlet. `App.tsx` is concerned with router/error-boundary/toast setup.

### Decision 2: Tri-state model with 10s time-based escalation

The connection state type changes from `boolean` to:

```ts
type ConnectionState = 'connecting' | 'connected' | 'offline'
```

State transitions:

```
              connect event
  connecting ───────────────▶ connected
      │                           │
      │ >10s in 'connecting'      │ disconnect event
      ▼                           ▼
   offline ◀────────────── connecting
      │                           ▲
      │ connect event             │
      └──────────────▶ connected ─┘
```

The 10s escalation timer starts when the state enters `connecting` (either on initial boot or after a `disconnect`). If the timer fires before a `connect` event, state becomes `offline`. Any `connect` event clears the timer and sets `connected`. Any `disconnect` event sets `connecting` and starts a fresh timer.

**Alternative considered**: Attempt-count escalation (`reconnect_attempt` #4+ → offline). Rejected because the backoff schedule (1s→5s) makes attempt-count roughly equivalent to a timer, but the timer is simpler to reason about and test (no need to hook into `reconnect_attempt` events).

### Decision 3: Sidebar dot maps tri-state to existing color scheme

| State | Color | Tooltip |
|-------|-------|---------|
| `connecting` | grey (`bg-slate-700`) | "Connecting…" |
| `connected` | green (`bg-good` + glow) | "System Online" |
| `offline` | red (`bg-bad`) | "System Offline — reconnecting" |

The existing sidebar dot already had grey/green/red classes; this change only swaps the data source from REST-poll state to socket state and ensures all three states are reachable.

### Decision 4: Dashboard refetch condition uses `'connected'`

The existing refetch-on-reconnect logic (Dashboard.tsx lines 447–457) checks `if (socketConnected)`. With the type change, this becomes `if (socketConnected === 'connected')`. The `wasConnectedBefore` ref logic stays unchanged — it only fires a refetch when transitioning from disconnected→connected after the initial mount.

## Risks / Trade-offs

- **[Socket never reaches a terminal "offline" in some edge cases]** → With `reconnectionAttempts: Infinity`, the socket perpetually retries. The 10s timer is the heuristic that surfaces "this isn't a transient blip." If the backend is down for 30s, the dot goes red after 10s and stays red (timer is cleared on `connect`, restarted on each `disconnect`). This is the desired behavior.

- **[Sidebar dot shows "offline" on very first boot if backend is slow to accept the WebSocket]** → The socket connects on `RootLayout` mount. If the backend takes >10s to accept the WS upgrade (e.g. cold start), the dot will briefly flash red. Acceptable trade-off — 10s is generous for a WS handshake, and a red dot during a genuine cold start is not misleading.

- **[Test complexity increases]** → The escalation timer requires fake timers (`vi.useFakeTimers()`) in the test. The existing `hooks.test.ts` fake socket emitter doesn't emit `reconnect_attempt`, so the timer approach is the only viable one. Mitigation: keep the test focused on state transitions, not real timing.

- **[Orphaned `Badge` import if missed]** → Dashboard.tsx line 16 imports `Badge` from `Banner.tsx` solely for the liveness badge. Forgetting to remove it causes a lint error (unused import). The lint step catches this — no silent failure.
