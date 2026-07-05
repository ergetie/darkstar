import { describe, expect, it, vi } from 'vitest'
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
    it('reflects connect/disconnect events from the socket', () => {
        const socket = getSocket()
        const { result } = renderHook(() => useSocketStatus())

        act(() => {
            socket.emit('connect')
        })
        expect(result.current).toBe(true)

        act(() => {
            socket.emit('disconnect', 'transport close')
        })
        expect(result.current).toBe(false)
    })
})
