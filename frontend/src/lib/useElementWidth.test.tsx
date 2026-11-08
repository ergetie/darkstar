import { act, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useElementWidth } from './useElementWidth'

function Probe({ onRender }: { onRender: (width: number) => void }) {
    const [ref, width] = useElementWidth<HTMLDivElement>()
    onRender(width)
    return <div ref={ref} data-testid="probe" />
}

class FakeObserver {
    static instances: FakeObserver[] = []
    disconnect = vi.fn()
    observe = vi.fn()
    constructor(public callback: ResizeObserverCallback) {
        FakeObserver.instances.push(this)
    }
}

afterEach(() => {
    vi.unstubAllGlobals()
    FakeObserver.instances = []
})

describe('useElementWidth', () => {
    it('is 0 and does not throw where ResizeObserver does not exist', () => {
        vi.stubGlobal('ResizeObserver', undefined)
        const widths: number[] = []
        render(<Probe onRender={(w) => widths.push(w)} />)
        expect(widths.every((w) => w === 0)).toBe(true)
    })

    it('follows the observer, ignores repeated equal widths and disconnects on unmount', () => {
        vi.stubGlobal('ResizeObserver', FakeObserver)
        const widths: number[] = []
        const { unmount } = render(<Probe onRender={(w) => widths.push(w)} />)
        const observer = FakeObserver.instances[0]
        expect(observer.observe).toHaveBeenCalledTimes(1)

        const emit = (width: number) =>
            act(() =>
                observer.callback(
                    [{ contentRect: { width } } as ResizeObserverEntry],
                    observer as unknown as ResizeObserver,
                ),
            )
        emit(320)
        const rendersAfterFirst = widths.length
        emit(320)
        expect(widths.length).toBe(rendersAfterFirst)
        expect(widths[widths.length - 1]).toBe(320)

        unmount()
        expect(observer.disconnect).toHaveBeenCalled()
    })
})
