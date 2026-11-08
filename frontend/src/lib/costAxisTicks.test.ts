import { describe, expect, it } from 'vitest'
import { computeCostChartGeometry } from '../components/CostSeriesChart'
import type { CostSeriesResponse } from './api'
import { compactAxisLabel, estimateLabelWidth, layoutAxisTicks, type AxisTick } from './costAxisTicks'

const GAP_MIN = 4

function geometryFor(start: string, end: string) {
    const series = {
        period: 'today',
        bucket: 'hour',
        points: [
            {
                start,
                import_cost_sek: 1,
                export_revenue_sek: 0,
                net_cost_sek: 1,
                cumulative_net_cost_sek: 1,
            },
        ],
        grid_only_comparison: {
            status: 'unavailable',
            reason: 'no_usable_observations',
            method_version: 'grid-only-bill-v1',
            coverage: {
                covered_slots: 0,
                total_slots: 1,
                excluded_slots: 1,
                water_unmeasured_slots: 0,
                water_unmeasured_hours: 0,
            },
            time_axis: { timezone: 'Europe/Stockholm', start, end },
        },
    } as unknown as CostSeriesResponse
    return computeCostChartGeometry(series)
}

function intervals(ticks: AxisTick[], widthPx: number) {
    return ticks.map((tick) => {
        const width = estimateLabelWidth(tick.label)
        const x = (tick.x / 100) * widthPx
        const left = tick.align === 'start' ? x : tick.align === 'end' ? x - width : x - width / 2
        return { tick, left, right: left + width }
    })
}

function overlaps(ticks: AxisTick[], widthPx: number): number {
    const placed = intervals(ticks, widthPx)
    let count = 0
    for (let a = 0; a < placed.length; a += 1) {
        for (let b = a + 1; b < placed.length; b += 1) {
            if (placed[a].tick.row !== placed[b].tick.row) continue
            if (placed[a].left < placed[b].right + GAP_MIN && placed[b].left < placed[a].right + GAP_MIN) count += 1
        }
    }
    return count
}

describe('layoutAxisTicks', () => {
    const fallBack = geometryFor('2026-10-25T00:00:00+02:00', '2026-10-26T00:00:00+01:00').ticks
    const normal = geometryFor('2026-10-05T00:00:00+02:00', '2026-10-06T00:00:00+02:00').ticks
    const springForward = geometryFor('2026-03-29T00:00:00+01:00', '2026-03-30T00:00:00+02:00').ticks

    it('compacts a repeated-hour label', () => {
        expect(compactAxisLabel('02:00 +01:00')).toBe('02+1')
        expect(compactAxisLabel('02:00 +05:30')).toBe('02+5:30')
        expect(compactAxisLabel('05:00')).toBe('05:00')
    })

    it('reproduces the collision of the raw fall-back layout on a narrow chart', () => {
        expect(overlaps(fallBack, 290)).toBeGreaterThan(0)
    })

    it('leaves the ticks untouched while the width is unknown', () => {
        expect(layoutAxisTicks(fallBack, 0)).toEqual(fallBack)
    })

    it.each([120, 200, 250, 290, 340, 390, 480, 640, 1024, 1600])(
        'never overlaps two labels on a fall-back day at %i px',
        (width) => {
            const laid = layoutAxisTicks(fallBack, width)
            expect(overlaps(laid, width)).toBe(0)
            for (const tick of laid) expect([0, 1]).toContain(tick.row)
        },
    )

    it.each([120, 200, 290, 390, 640])('never overlaps on a normal and a spring-forward day at %i px', (width) => {
        expect(overlaps(layoutAxisTicks(normal, width), width)).toBe(0)
        expect(overlaps(layoutAxisTicks(springForward, width), width)).toBe(0)
    })

    it('keeps the axis ends and both repeated-hour labels from 290 px up', () => {
        for (const width of [290, 340, 390, 640]) {
            const labels = layoutAxisTicks(fallBack, width).map((tick) => compactAxisLabel(tick.label))
            expect(labels).toEqual(expect.arrayContaining(['00:00', '02+2', '02+1', '25']))
        }
    })

    it('keeps the axis ends first on a narrower chart, omitting what cannot fit clear of them', () => {
        const labels = layoutAxisTicks(fallBack, 250).map((tick) => compactAxisLabel(tick.label))
        expect(labels).toEqual(expect.arrayContaining(['00:00', '02+2', '25']))
        expect(labels).not.toContain('02+1')
    })

    it('moves a colliding label to the other row before dropping it', () => {
        const laid = layoutAxisTicks(fallBack, 290)
        const five = laid.find((tick) => tick.label === '05:00')
        expect(five).toBeDefined()
        expect(five?.row).toBe(0)
    })

    it('keeps every label of a normal day on a wide chart, in its original row', () => {
        expect(layoutAxisTicks(normal, 1024)).toEqual(normal)
        expect(layoutAxisTicks(fallBack, 1600)).toEqual(fallBack)
    })

    it('drops lowest-priority labels first and never the axis ends on a very narrow chart', () => {
        const laid = layoutAxisTicks(fallBack, 80)
        const labels = laid.map((tick) => tick.label)
        expect(labels).toContain('00:00')
        expect(labels.length).toBeLessThan(fallBack.length)
    })
})
