import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { act, renderHook } from '@testing-library/react'

// socket.ts drives a real socket.io Manager on import; replace it with a
// minimal fake emitter so tests can fire connect/disconnect without a network.
vi.mock('socket.io-client', () => {
    class FakeEmitter {
        private listeners: Record<string, Array<(...args: unknown[]) => void>> = {}
        on(event: string, cb: (...args: unknown[]) => void) {
            ;(this.listeners[event] ??= []).push(cb)
            return this
        }
        off() {
            return this
        }
        onAny() {
            return this
        }
        connect() {
            return this
        }
        emit(event: string, ...args: unknown[]) {
            ;(this.listeners[event] || []).forEach((cb) => cb(...args))
        }
    }
    class FakeManager extends FakeEmitter {
        engine = { on: () => {} }
        socket() {
            return new FakeEmitter()
        }
        open(cb?: (err?: Error) => void) {
            cb?.()
        }
    }
    return { Manager: FakeManager }
})

import { getSocket } from './socket'
import { useSocketStatus } from './hooks'

describe('useSocketStatus', () => {
    beforeEach(() => {
        vi.useFakeTimers()
    })

    afterEach(() => {
        vi.useRealTimers()
    })

    it('reflects connect/disconnect events from the socket', () => {
        const socket = getSocket()
        const { result } = renderHook(() => useSocketStatus())

        act(() => {
            socket.emit('connect')
        })
        expect(result.current).toBe('connected')

        act(() => {
            socket.emit('disconnect', 'transport close')
        })
        expect(result.current).toBe('connecting')
    })

    it('escalates to offline after 10 seconds in connecting', () => {
        const socket = getSocket()
        const { result } = renderHook(() => useSocketStatus())

        act(() => {
            socket.emit('connect')
        })
        expect(result.current).toBe('connected')

        act(() => {
            socket.emit('disconnect', 'transport close')
        })
        expect(result.current).toBe('connecting')

        act(() => {
            vi.advanceTimersByTime(10_001)
        })
        expect(result.current).toBe('offline')
    })

    it('does not escalate when reconnect happens within 10 seconds', () => {
        const socket = getSocket()
        const { result } = renderHook(() => useSocketStatus())

        act(() => {
            socket.emit('connect')
        })
        act(() => {
            socket.emit('disconnect', 'transport close')
        })
        expect(result.current).toBe('connecting')

        act(() => {
            vi.advanceTimersByTime(5_000)
            socket.emit('connect')
        })
        expect(result.current).toBe('connected')

        act(() => {
            vi.advanceTimersByTime(10_000)
        })
        expect(result.current).toBe('connected')
    })

    it('clears the escalation timer on connect so no stale offline transition fires', () => {
        const socket = getSocket()
        const { result } = renderHook(() => useSocketStatus())

        act(() => {
            socket.emit('connect')
        })
        act(() => {
            socket.emit('disconnect', 'transport close')
        })

        act(() => {
            vi.advanceTimersByTime(5_000)
            socket.emit('connect')
        })
        expect(result.current).toBe('connected')

        act(() => {
            vi.advanceTimersByTime(10_000)
        })
        expect(result.current).toBe('connected')
    })
})
