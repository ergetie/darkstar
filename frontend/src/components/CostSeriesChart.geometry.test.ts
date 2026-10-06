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

    describe('legacy baseline compatibility fields', () => {
        const withBaseline = (cum: number[]): CostSeriesResponse => ({
            period: 'today',
            bucket: 'hour',
            points: [
                { ...point('2026-10-05T00:00:00', 4, 0, 4), baseline_cumulative_net_cost_sek: cum[0] },
                { ...point('2026-10-05T01:00:00', 0, 2, 2), baseline_cumulative_net_cost_sek: cum[1] },
            ],
        })

        it('never draws or scales the actual chart from the legacy baseline', () => {
            const g = computeCostChartGeometry({
                period: 'today',
                bucket: 'hour',
                points: [point('2026-10-05T00:00:00', 4, 0, 4)],
            })
            expect(g.baseline).toBeNull()
        })

        it('leaves the actual net line unchanged regardless of legacy values', () => {
            const plain = computeCostChartGeometry({
                period: 'today',
                bucket: 'hour',
                points: [point('2026-10-05T00:00:00', 4, 0, 4), point('2026-10-05T01:00:00', 0, 2, 2)],
            })
            const g = computeCostChartGeometry(withBaseline([3, 1]))
            expect(g.line).toEqual(plain.line)
            expect(g.zeroY).toBeCloseTo(plain.zeroY)
            expect(g.baseline).toBeNull()
        })
    })
})
