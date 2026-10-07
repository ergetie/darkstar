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

    describe('without-Darkstar line', () => {
        const hourly = (cums: number[]): CostSeriesResponse => ({
            period: 'today',
            bucket: 'hour',
            points: cums.map((c, i) => point(`2026-10-05T0${i}:00:00`, 1, 0, c)),
        })
        const cmp = (rows: [number, number, number][], status = 'available') =>
            ({
                status,
                reason: 'validated',
                points: rows.map(([h, darkstar, selfUse]) => ({
                    start: `2026-10-05T0${h}:00:00`,
                    darkstar_cumulative_comparison_cost_sek: darkstar,
                    self_use_cumulative_comparison_cost_sek: selfUse,
                })),
            }) as CostSeriesResponse['battery_comparison']

        it('is null when there are no comparison amounts', () => {
            const g = computeCostChartGeometry(hourly([4, 2]))
            expect(g.without).toBeNull()
            expect(g.withoutValues).toEqual([null, null])
        })

        it('is null when the comparison is unavailable, even if points are present', () => {
            const g = computeCostChartGeometry({
                ...hourly([4, 2]),
                battery_comparison: cmp([[0, 1, 2]], 'unavailable'),
            })
            expect(g.without).toBeNull()
        })

        it('ignores the legacy baseline field and leaves the actual line unchanged', () => {
            const plain = hourly([4, 2])
            const legacy = {
                ...plain,
                points: plain.points.map((p) => ({ ...p, baseline_cumulative_net_cost_sek: 99 })),
            }
            const a = computeCostChartGeometry(plain)
            const b = computeCostChartGeometry(legacy)
            expect(b.line).toEqual(a.line)
            expect(b.without).toBeNull()
        })

        it('is actual plus self-use minus Darkstar per matching bucket, on the shared scale', () => {
            const g = computeCostChartGeometry({
                ...hourly([4, 2]),
                battery_comparison: cmp([
                    [0, 1, 3],
                    [1, 2, 6],
                ]),
            })
            expect(g.withoutValues).toEqual([6, 6])
            // starts at the zero line, then one point per matched bucket
            expect(g.without).toHaveLength(3)
            expect(g.without?.[0].y).toBeCloseTo(g.zeroY)
            // without (6) is above actual (4) in cost, so it sits higher on the chart
            expect(g.without?.[1].y).toBeLessThan(g.line[1].y)
        })

        it('carries the last difference across a gap in the comparison', () => {
            const g = computeCostChartGeometry({
                ...hourly([4, 5, 6]),
                battery_comparison: cmp([
                    [0, 1, 3], // delta 2
                    [2, 1, 4], // delta 3
                ]),
            })
            expect(g.withoutValues).toEqual([6, 7, 9])
            expect(g.without?.map((p) => p.pointIndex)).toEqual([0, 0, 1, 2])
        })

        it('stops at the last comparison point', () => {
            const g = computeCostChartGeometry({
                ...hourly([4, 5, 6]),
                battery_comparison: cmp([[0, 1, 3]]),
            })
            expect(g.withoutValues).toEqual([6, null, null])
        })

        it('does not start before the first comparison point', () => {
            const g = computeCostChartGeometry({
                ...hourly([4, 5, 6]),
                battery_comparison: cmp([
                    [1, 1, 3],
                    [2, 1, 3],
                ]),
            })
            expect(g.withoutValues).toEqual([null, 7, 8])
            expect(g.without?.[0].pointIndex).toBe(1)
            expect(g.without).toHaveLength(2)
        })

        describe('saving shading', () => {
            it('is empty without a without line', () => {
                expect(computeCostChartGeometry(hourly([4, 2])).saving).toEqual([])
            })

            it('is good where without costs more than actual, spanning both lines', () => {
                const g = computeCostChartGeometry({
                    ...hourly([4, 2]),
                    battery_comparison: cmp([
                        [0, 1, 3],
                        [1, 2, 6],
                    ]),
                })
                // zero-start pair, then two buckets
                expect(g.saving.map((s) => s.tone)).toEqual(['good', 'good'])
                const seg = g.saving[1]
                expect(seg.points).toHaveLength(4)
                expect(seg.points[1].y).toBeCloseTo(g.line[2].y)
                expect(seg.points[2].y).toBeCloseTo(g.without![2].y)
                expect(seg.points[2].y).toBeLessThan(seg.points[1].y)
            })

            it('is bad where without costs less than actual', () => {
                const g = computeCostChartGeometry({
                    ...hourly([4, 5]),
                    battery_comparison: cmp([
                        [0, 3, 1],
                        [1, 3, 1],
                    ]),
                })
                expect(g.saving.map((s) => s.tone)).toEqual(['bad', 'bad'])
            })

            it('splits at the crossing with interpolation', () => {
                const g = computeCostChartGeometry({
                    ...hourly([4, 4]),
                    battery_comparison: cmp([
                        [0, 3, 1], // delta -2: without below actual
                        [1, 1, 3], // delta +2: without above actual
                    ]),
                })
                // zero-start -> bucket0 is bad, bucket0 -> bucket1 crosses halfway
                expect(g.saving.map((s) => s.tone)).toEqual(['bad', 'bad', 'good'])
                const [, bad, good] = g.saving
                expect(bad.points).toHaveLength(3)
                expect(good.points).toHaveLength(3)
                expect(bad.points[1].x).toBeCloseTo((g.line[1].x + g.line[2].x) / 2)
                expect(good.points[0]).toEqual(bad.points[1])
            })

            it('covers carried-forward stretches and stops with the line', () => {
                const g = computeCostChartGeometry({
                    ...hourly([4, 5, 6]),
                    battery_comparison: cmp([[0, 1, 3]]),
                })
                expect(g.saving).toHaveLength(1) // only zero-start -> bucket 0
            })
        })
    })
})
