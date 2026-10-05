import { describe, expect, it } from 'vitest'
import { computeCostChartGeometry } from './CostSeriesChart'
import type { CostSeriesResponse } from '../lib/api'

const point = (start: string, imp: number, exp: number, cum: number) => ({
    start,
    import_cost_sek: imp,
    export_revenue_sek: exp,
    net_cost_sek: imp - exp,
    cumulative_net_cost_sek: cum,
})

describe('computeCostChartGeometry', () => {
    it('places hourly buckets on a fixed 24-slot day and starts the line at zero', () => {
        const series: CostSeriesResponse = {
            period: 'today',
            bucket: 'hour',
            points: [point('2026-10-05T00:00:00', 4, 0, 4), point('2026-10-05T01:00:00', 0, 2, 2)],
        }
        const g = computeCostChartGeometry(series)
        expect(g.slots).toBe(24)
        expect(g.bars.map((b) => b.index)).toEqual([0, 1])
        expect(g.line[0].y).toBeCloseTo(g.zeroY)
        expect(g.line).toHaveLength(3)
        expect(g.bars[0].importH).toBeCloseTo(35)
        expect(g.bars[1].exportH).toBeCloseTo(17.5)
    })

    it('uses one slot per day for longer periods', () => {
        const series: CostSeriesResponse = {
            period: 'week',
            bucket: 'day',
            start_date: '2026-09-29',
            end_date: '2026-10-05',
            points: [point('2026-10-05T00:00:00', 1, 0, 1)],
        }
        const g = computeCostChartGeometry(series)
        expect(g.slots).toBe(7)
        expect(g.bars[0].index).toBe(6)
    })

    describe('without-Darkstar baseline', () => {
        const withBaseline = (cum: number[]): CostSeriesResponse => ({
            period: 'today',
            bucket: 'hour',
            points: [
                { ...point('2026-10-05T00:00:00', 4, 0, 4), baseline_cumulative_net_cost_sek: cum[0] },
                { ...point('2026-10-05T01:00:00', 0, 2, 2), baseline_cumulative_net_cost_sek: cum[1] },
            ],
        })

        it('has no baseline line when the points carry no baseline', () => {
            const g = computeCostChartGeometry({
                period: 'today',
                bucket: 'hour',
                points: [point('2026-10-05T00:00:00', 4, 0, 4)],
            })
            expect(g.baseline).toBeNull()
        })

        it('uses the net line x positions and starts at zero', () => {
            const g = computeCostChartGeometry(withBaseline([5, 6]))
            expect(g.baseline).toHaveLength(g.line.length)
            expect(g.baseline?.map((p) => p.x)).toEqual(g.line.map((p) => p.x))
            expect(g.baseline?.[0].y).toBeCloseTo(g.zeroY)
        })

        it('extends the vertical range to the baseline maximum', () => {
            const g = computeCostChartGeometry(withBaseline([10, 12]))
            // The highest baseline value sits at the top padding, above the net line.
            expect(g.baseline?.[2].y).toBeCloseTo(8)
            expect(g.line[1].y).toBeGreaterThan(8)
        })

        it('leaves the net line unchanged when the baseline stays inside its range', () => {
            const plain = computeCostChartGeometry({
                period: 'today',
                bucket: 'hour',
                points: [point('2026-10-05T00:00:00', 4, 0, 4), point('2026-10-05T01:00:00', 0, 2, 2)],
            })
            const g = computeCostChartGeometry(withBaseline([3, 1]))
            expect(g.line).toEqual(plain.line)
            expect(g.zeroY).toBeCloseTo(plain.zeroY)
        })
    })
})
