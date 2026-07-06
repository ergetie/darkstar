## 1. Connection state model (socket.ts)

- [x] 1.1 Replace the module-level `connected` boolean with a `ConnectionState` type (`'connecting' | 'connected' | 'offline'`), initialized to `'connecting'`.
- [x] 1.2 Update `setConnected` to `setState` (or similar) that updates the internal state and notifies all `connectionListeners` with the new value.
- [x] 1.3 Update `getConnectionState()` to return `ConnectionState` instead of `boolean`.
- [x] 1.4 On the `connect` event: clear any pending escalation timer, set state to `'connected'`.
- [x] 1.5 On the `disconnect` event: set state to `'connecting'` and start a 10-second escalation timer that, if not cleared, sets state to `'offline'`.
- [x] 1.6 Ensure the escalation timer is cleared on `connect` and re-created on each `disconnect` (no stale timers).

## 2. Hook update (hooks.ts)

- [x] 2.1 Change `useSocketStatus()` return type from `boolean` to `ConnectionState`.
- [x] 2.2 Update the `useState` initializer to use `getConnectionState()` (already does, but type changes).

## 3. Eager socket init (App.tsx)

- [x] 3.1 Add `useEffect(() => { getSocket() }, [])` to `RootLayout` so the Socket.IO singleton is created on app mount, independent of which route is active.
- [x] 3.2 Import `getSocket` from `./lib/socket` in `App.tsx`.

## 4. Sidebar dot (Sidebar.tsx)

- [x] 4.1 Remove the `Api.status()` polling `useEffect` (lines 53–65) and the local `connected` state initialized from it.
- [x] 4.2 Replace with `const connected = useSocketStatus()` (import from `../lib/hooks`).
- [x] 4.3 Update the dot's conditional classes: `connected === 'connecting'` → grey (`bg-slate-700`), `connected === 'connected'` → green (`bg-good` + glow), `connected === 'offline'` → red (`bg-bad`).
- [x] 4.4 Update the `title` attribute: connecting → "Connecting…", connected → "System Online", offline → "System Offline — reconnecting".

## 5. Dashboard cleanup (Dashboard.tsx)

- [x] 5.1 Remove the "● Live" badge `<div>` block (lines 547–552) from the JSX.
- [x] 5.2 Remove the now-orphaned `import { Badge } from '../components/ui/Banner'` (line 16).
- [x] 5.3 Update the refetch-on-reconnect condition from `if (socketConnected)` to `if (socketConnected === 'connected')` (around line 449).

## 6. Tests (hooks.test.ts)

- [x] 6.1 Update the existing assertions: `expect(result.current).toBe(true)` → `toBe('connected')`, and `toBe(false)` → `toBe('connecting')` (disconnect goes to connecting, not offline).
- [x] 6.2 Add a test case for the 10s escalation: after `disconnect`, advance fake timers past 10s, assert state is `'offline'`.
- [x] 6.3 Add a test case for timer reset: disconnect → connect within 10s → assert state is `'connected'` and no escalation occurs.
- [x] 6.4 Add a test case for escalation timer cleared on connect: disconnect → advance 5s → connect → advance 10s → assert state is still `'connected'` (timer was cleared).

## 7. Verification

- [x] 7.1 Run `./scripts/lint.sh` and fix any failures.
- [x] 7.2 Run `pnpm run dev` and manually verify: sidebar dot is grey briefly on boot, turns green; navigate to `/settings` — dot persists and reflects state.
- [x] 7.3 Stop the backend and verify the sidebar dot escalates to red after ~10s (not 30s as before).
