import { act, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ScheduleSlot } from '../lib/types'

// Minimal Chart.js stand-in: jsdom has no canvas. Captures the instance so the
// test can drive the baked-in onClick handler and count data updates.
const { charts, FakeChart } = vi.hoisted(() => {
    type Options = { onClick: (event: unknown, elements: { index: number }[]) => void; plugins: unknown }
    const charts: InstanceType<typeof FakeChart>[] = []
    class FakeChart {
        static register() {}
        data: unknown
        options: Options
        $plugins = {}
        update = vi.fn()
        draw = vi.fn()
        destroy = vi.fn()
        resetZoom = vi.fn()
        zoomScale = vi.fn()
        constructor(_canvas: unknown, cfg: { data: unknown; options: Options }) {
            this.data = cfg.data
            this.options = cfg.options
            charts.push(this)
        }
    }
    return { charts, FakeChart }
})
type FakeChart = InstanceType<typeof FakeChart>
vi.mock('chart.js/auto', () => ({ Chart: FakeChart }))
vi.mock('chartjs-plugin-zoom', () => ({ default: {} }))
vi.mock('../lib/api', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../lib/api')>()
    return {
        ...actual,
        Api: {
            ...actual.Api,
            config: vi.fn(() => Promise.resolve({})),
            theme: vi.fn(() =>
                Promise.resolve({
                    current: 'test',
                    themes: [{ name: 'test', palette: ['#111111'], background: '#000000', foreground: '#ffffff' }],
                }),
            ),
        },
    }
})

import ChartCard from './ChartCard'

// jsdom's localStorage is shadowed by Node's disabled global one; stub it.
function makeMemoryStorage(): Storage {
    const store = new Map<string, string>()
    return {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => void store.set(key, value),
        removeItem: (key: string) => void store.delete(key),
        clear: () => store.clear(),
        key: (index: number) => Array.from(store.keys())[index] ?? null,
        get length() {
            return store.size
        },
    } as Storage
}

const DAY_START = Date.UTC(2026, 9, 4, 0, 0, 0)

function makeSlots(count: number, stepMinutes: number): ScheduleSlot[] {
    return Array.from({ length: count }, (_, i) => ({
        start_time: new Date(DAY_START + i * stepMinutes * 60 * 1000).toISOString(),
        import_price_sek_kwh: 1 + i / 100,
    }))
}

function chart(): FakeChart {
    const latest = charts[charts.length - 1]
    if (!latest) throw new Error('chart not created')
    return latest
}

function panel(container: HTMLElement): Element | null {
    // The info panel is always shown; it is pinned to a slot only while one is selected
    return container.querySelector('[data-slot-panel][data-pinned="true"]')
}

async function renderWithSelection(slots: ScheduleSlot[], index: number) {
    const view = render(<ChartCard slotsOverride={slots} />)
    await waitFor(() => expect(charts.length).toBeGreaterThan(0))
    await waitFor(() => expect(chart().update).toHaveBeenCalled())
    act(() => chart().options.onClick(null, [{ index }]))
    await waitFor(() => expect(panel(view.container)).not.toBeNull())
    return view
}

describe('ChartCard mobile slot selection', () => {
    beforeEach(() => {
        charts.length = 0
        vi.useFakeTimers({ toFake: ['Date'] })
        vi.setSystemTime(new Date(DAY_START + 10 * 60 * 60 * 1000))
        vi.stubGlobal('localStorage', makeMemoryStorage())
        vi.stubGlobal(
            'matchMedia',
            vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
        )
    })

    afterEach(() => {
        vi.useRealTimers()
        vi.unstubAllGlobals()
    })

    it('keeps the selection when the parent re-renders with the same schedule array', async () => {
        const slots = makeSlots(96, 15)
        const view = await renderWithSelection(slots, 40)
        const updates = chart().update.mock.calls.length

        view.rerender(<ChartCard slotsOverride={slots} />)
        view.rerender(<ChartCard slotsOverride={slots} />)

        expect(panel(view.container)).not.toBeNull()
        // Same array: the data effect does not re-run, so the chart is not rebuilt
        expect(chart().update.mock.calls.length).toBe(updates)
    })

    it('keeps a still-valid selection when the schedule data refreshes', async () => {
        const view = await renderWithSelection(makeSlots(96, 15), 40)
        const updates = chart().update.mock.calls.length

        view.rerender(<ChartCard slotsOverride={makeSlots(96, 15)} />)

        await waitFor(() => expect(chart().update.mock.calls.length).toBeGreaterThan(updates))
        expect(panel(view.container)).not.toBeNull()
    })

    it('clears the selection when the new data no longer contains the index', async () => {
        // 15-min slots give 192 buckets; hourly slots give 48, so index 100 is gone
        const view = await renderWithSelection(makeSlots(96, 15), 100)

        view.rerender(<ChartCard slotsOverride={makeSlots(24, 60)} />)

        await waitFor(() => expect(panel(view.container)).toBeNull())
    })
})
