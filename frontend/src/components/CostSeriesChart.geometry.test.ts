import { describe, expect, it } from 'vitest'
import { computeCostChartGeometry } from './CostSeriesChart'
import type { BatteryBenchmarkDay, BatteryBenchmarkResponse, CostSeriesResponse, GridOnlyComparison } from '../lib/api'

const normalAxis = {
    timezone: 'Europe/Stockholm',
    start: '2026-10-05T00:00:00+02:00',
    end: '2026-10-06T00:00:00+02:00',
}

const actualPoint = (start: string, importCost: number, exportRevenue: number, cumulative: number) => ({
    start,
    import_cost_sek: importCost,
    export_revenue_sek: exportRevenue,
    net_cost_sek: importCost - exportRevenue,
    cumulative_net_cost_sek: cumulative,
})

function comparison(overrides: Partial<GridOnlyComparison> = {}): GridOnlyComparison {
    return {
        status: 'available',
        reason: 'complete_coverage',
        method_version: 'grid-only-bill-v1',
        coverage: { covered_slots: 4, total_slots: 4, excluded_slots: 0 },
        time_axis: normalAxis,
        through: '2026-10-05T01:00:00+02:00',
        grid_only_cost_sek: 10,
        grid_only_wear_cost_sek: 0,
        ds_electricity_cost_sek: 8,
        ds_wear_cost_sek: 1,
        ds_cost_sek: 9,
        saving_sek: 1,
        points: [
            {
                start: '2026-10-05T00:00:00+02:00',
                end: '2026-10-05T01:00:00+02:00',
                import_cost_sek: 8,
                export_revenue_sek: 1,
                ds_electricity_cost_sek: 7,
                ds_wear_cost_sek: 1,
                grid_only_wear_cost_sek: 0,
                ds_cost_sek: 8,
                grid_only_cost_sek: 10,
                cumulative_ds_cost_sek: 9,
                cumulative_grid_only_cost_sek: 10,
            },
        ],
        segments: [
            {
                start: '2026-10-05T00:00:00+02:00',
                end: '2026-10-05T01:00:00+02:00',
                points: [
                    { at: '2026-10-05T00:00:00+02:00', cumulative_ds_cost_sek: 0, cumulative_grid_only_cost_sek: 0 },
                    {
                        at: '2026-10-05T00:15:00+02:00',
                        cumulative_ds_cost_sek: 2.25,
                        cumulative_grid_only_cost_sek: 2.5,
                    },
                    { at: '2026-10-05T00:30:00+02:00', cumulative_ds_cost_sek: 4.5, cumulative_grid_only_cost_sek: 5 },
                    {
                        at: '2026-10-05T00:45:00+02:00',
                        cumulative_ds_cost_sek: 6.75,
                        cumulative_grid_only_cost_sek: 7.5,
                    },
                    { at: '2026-10-05T01:00:00+02:00', cumulative_ds_cost_sek: 9, cumulative_grid_only_cost_sek: 10 },
                ],
            },
        ],
        ...overrides,
    } as GridOnlyComparison
}

const series = (
    gridOnly: GridOnlyComparison,
    actualPoints = [actualPoint('2026-10-05T00:00:00+02:00', 8, 1, 7)],
    bucket: 'hour' | 'day' = 'hour',
): CostSeriesResponse => ({ period: 'today', bucket, points: actualPoints, grid_only_comparison: gridOnly })

const unavailable = (axis = normalAxis): GridOnlyComparison => ({
    status: 'unavailable',
    reason: 'no_usable_observations',
    method_version: 'grid-only-bill-v1',
    coverage: { covered_slots: 0, total_slots: 96, excluded_slots: 96 },
    time_axis: axis,
})

describe('computeCostChartGeometry', () => {
    it('draws direct wear-inclusive DS and dotted grid-only values on a zero-inclusive scale', () => {
        const geometry = computeCostChartGeometry(series(comparison()))
        expect(geometry.hasComparison).toBe(true)
        expect(geometry.slots).toBe(24)
        expect(geometry.dsSegments[0].points.map((point) => point.value)).toEqual([0, 2.25, 4.5, 6.75, 9])
        expect(geometry.gridSegments[0].map((point) => point.value)).toEqual([0, 2.5, 5, 7.5, 10])
        expect(geometry.zeroY).toBeGreaterThan(8)
        expect(geometry.bars[0].dsRunning).toBe(9)
        expect(geometry.bars[0].gridRunning).toBe(10)
    })

    it('breaks both line and saving geometry at an excluded slot within a bucket', () => {
        const partial = comparison({
            status: 'partial',
            reason: 'partial_coverage',
            coverage: { covered_slots: 3, total_slots: 4, excluded_slots: 1 },
            grid_only_cost_sek: 5,
            ds_electricity_cost_sek: 3,
            ds_wear_cost_sek: 1,
            ds_cost_sek: 4,
            saving_sek: 1,
            points: [
                {
                    start: '2026-10-05T00:00:00+02:00',
                    end: '2026-10-05T01:00:00+02:00',
                    import_cost_sek: 4,
                    export_revenue_sek: 1,
                    ds_electricity_cost_sek: 3,
                    ds_wear_cost_sek: 1,
                    grid_only_wear_cost_sek: 0,
                    ds_cost_sek: 4,
                    grid_only_cost_sek: 5,
                    cumulative_ds_cost_sek: 4,
                    cumulative_grid_only_cost_sek: 5,
                },
            ],
            segments: [
                {
                    start: '2026-10-05T00:00:00+02:00',
                    end: '2026-10-05T00:15:00+02:00',
                    points: [
                        {
                            at: '2026-10-05T00:00:00+02:00',
                            cumulative_ds_cost_sek: 0,
                            cumulative_grid_only_cost_sek: 0,
                        },
                        {
                            at: '2026-10-05T00:15:00+02:00',
                            cumulative_ds_cost_sek: 1,
                            cumulative_grid_only_cost_sek: 2,
                        },
                    ],
                },
                {
                    start: '2026-10-05T00:30:00+02:00',
                    end: '2026-10-05T01:00:00+02:00',
                    points: [
                        {
                            at: '2026-10-05T00:30:00+02:00',
                            cumulative_ds_cost_sek: 1,
                            cumulative_grid_only_cost_sek: 2,
                        },
                        {
                            at: '2026-10-05T00:45:00+02:00',
                            cumulative_ds_cost_sek: 2.5,
                            cumulative_grid_only_cost_sek: 3.5,
                        },
                        {
                            at: '2026-10-05T01:00:00+02:00',
                            cumulative_ds_cost_sek: 4,
                            cumulative_grid_only_cost_sek: 5,
                        },
                    ],
                },
            ],
        })
        const geometry = computeCostChartGeometry(series(partial))
        expect(geometry.dsSegments).toHaveLength(2)
        expect(geometry.gridSegments).toHaveLength(2)
        expect(geometry.dsSegments[1].points[0].value).toBe(1)
        expect(geometry.gridSegments[1][0].value).toBe(2)
        expect(geometry.dsSegments[0].points[geometry.dsSegments[0].points.length - 1]?.x).toBeLessThan(
            geometry.dsSegments[1].points[0].x,
        )
        expect(geometry.saving).toHaveLength(3)
        expect(geometry.bars[0].dsRunning).toBe(4)
        expect(geometry.bars[0].gridRunning).toBe(5)
    })

    it('splits shading at a covered crossing without joining separate segments', () => {
        const crossing = comparison({
            ds_cost_sek: 8,
            saving_sek: 2,
            grid_only_cost_sek: 10,
            segments: [
                {
                    start: '2026-10-05T00:00:00+02:00',
                    end: '2026-10-05T00:30:00+02:00',
                    points: [
                        {
                            at: '2026-10-05T00:00:00+02:00',
                            cumulative_ds_cost_sek: 0,
                            cumulative_grid_only_cost_sek: 2,
                        },
                        {
                            at: '2026-10-05T00:15:00+02:00',
                            cumulative_ds_cost_sek: 3,
                            cumulative_grid_only_cost_sek: 2,
                        },
                        {
                            at: '2026-10-05T00:30:00+02:00',
                            cumulative_ds_cost_sek: 8,
                            cumulative_grid_only_cost_sek: 10,
                        },
                    ],
                },
            ],
        })
        const geometry = computeCostChartGeometry(series(crossing))
        expect(geometry.saving.map((shape) => shape.tone)).toEqual(['good', 'bad', 'bad', 'good'])
        expect(geometry.dsSegments).toHaveLength(1)
    })

    it('positions fall-back repeated hours by elapsed UTC and labels both offsets', () => {
        const axis = {
            timezone: 'Europe/Stockholm',
            start: '2026-10-25T00:00:00+02:00',
            end: '2026-10-26T00:00:00+01:00',
        }
        const geometry = computeCostChartGeometry(series(unavailable(axis)))
        expect(geometry.slots).toBe(25)
        expect(geometry.ticks.map((tick) => tick.label)).toContain('02:00 +02:00')
        expect(geometry.ticks.map((tick) => tick.label)).toContain('02:00 +01:00')
        const repeated = geometry.ticks.filter((tick) => tick.label.startsWith('02:00'))
        expect(repeated[0].x).toBeLessThan(repeated[1].x)
    })

    it('uses a 23-hour spring-forward axis without fabricating the missing hour', () => {
        const axis = {
            timezone: 'Europe/Stockholm',
            start: '2026-03-29T00:00:00+01:00',
            end: '2026-03-30T00:00:00+02:00',
        }
        const geometry = computeCostChartGeometry(series(unavailable(axis)))
        expect(geometry.slots).toBe(23)
        expect(geometry.ticks.map((tick) => tick.label)).not.toContain('02:00')
    })

    it('uses the supplied installation axis for Actual-only fallback geometry', () => {
        const points = [
            actualPoint('2026-10-05T00:00:00+02:00', 4, 0, 4),
            actualPoint('2026-10-05T01:00:00+02:00', 0, 2, 2),
        ]
        const geometry = computeCostChartGeometry(series(unavailable(), points))
        expect(geometry.hasComparison).toBe(false)
        expect(geometry.actualSegments[0]).toHaveLength(3)
        expect(geometry.actualSegments[0][0].x).toBe(0)
        expect(geometry.actualSegments[0][geometry.actualSegments[0].length - 1]?.x).toBeLessThan(100)
        expect(geometry.bars.map((bar) => bar.index)).toEqual([0, 1])
    })

    it('uses actual installation-local midnight bounds for daily bucket positions', () => {
        const axis = {
            timezone: 'Europe/Stockholm',
            start: '2026-03-28T00:00:00+01:00',
            end: '2026-03-30T00:00:00+02:00',
        }
        const geometry = computeCostChartGeometry(series(unavailable(axis), [], 'day'))
        expect(geometry.ticks).toHaveLength(2)
        expect(geometry.ticks.map((tick) => tick.x)).toEqual([0, 100])
    })

    it('ends Actual-only daily buckets at midnight in a half-hour installation timezone', () => {
        const axis = {
            timezone: 'Asia/Kolkata',
            start: '2026-10-05T00:00:00+05:30',
            end: '2026-10-07T00:00:00+05:30',
        }
        const points = [actualPoint(axis.start, 4, 0, 4)]
        const geometry = computeCostChartGeometry(series(unavailable(axis), points, 'day'))
        expect(geometry.bars[0].width).toBe(50)
        expect(Date.parse(geometry.bars[0].end)).toBe(Date.parse('2026-10-06T00:00:00+05:30'))
        expect(geometry.actualSegments[0][1].x).toBe(50)
    })

    describe('hindsight line', () => {
        const days = ['2026-10-05', '2026-10-06', '2026-10-07']
        const dayAxis = {
            timezone: 'Europe/Stockholm',
            start: '2026-10-05T00:00:00+02:00',
            end: '2026-10-08T00:00:00+02:00',
        }
        const dayBucket = (date: string, dsCost: number, cumulative: number) => {
            const start = `${date}T00:00:00+02:00`
            const next = new Date(Date.parse(start) + 86_400_000).toISOString()
            return {
                start,
                end: next,
                import_cost_sek: dsCost,
                export_revenue_sek: 0,
                ds_electricity_cost_sek: dsCost,
                ds_wear_cost_sek: 0,
                grid_only_wear_cost_sek: 0,
                ds_cost_sek: dsCost,
                grid_only_cost_sek: dsCost + 5,
                cumulative_ds_cost_sek: cumulative,
                cumulative_grid_only_cost_sek: cumulative + 5,
            }
        }
        const daily = comparison({
            time_axis: dayAxis,
            points: [dayBucket(days[0], 10, 10), dayBucket(days[1], 10, 20), dayBucket(days[2], 10, 30)],
            segments: [
                {
                    start: dayAxis.start,
                    end: dayAxis.end,
                    points: [
                        { at: dayAxis.start, cumulative_ds_cost_sek: 0, cumulative_grid_only_cost_sek: 0 },
                        { at: dayAxis.end, cumulative_ds_cost_sek: 30, cumulative_grid_only_cost_sek: 45 },
                    ],
                },
            ],
        })
        const day = (date: string, status: BatteryBenchmarkDay['status'], missed: number | null) =>
            ({
                date,
                status,
                missed_sek: missed,
                reason: status === 'scored' ? null : 'not_clean_recording',
            }) as BatteryBenchmarkDay
        const bench = (records: BatteryBenchmarkDay[]): BatteryBenchmarkResponse =>
            ({ start_date: days[0], end_date: days[2], days: records, totals: {} }) as BatteryBenchmarkResponse

        it('sits below DS by the cumulative missed value at each day end', () => {
            const geometry = computeCostChartGeometry(
                series(daily, [], 'day'),
                bench([day(days[0], 'scored', 2), day(days[1], 'scored', 3), day(days[2], 'scored', 1)]),
            )
            expect(geometry.hindsightSegments).toHaveLength(1)
            expect(geometry.hindsightSegments[0].map((point) => point.value)).toEqual([0, 8, 15, 24])
            expect(geometry.hindsightArea.length).toBeGreaterThan(0)
            expect(geometry.hindsightExcluded).toEqual([])
            expect(geometry.gridSegments[0].map((point) => point.value)).toEqual([0, 45])
        })

        it('leaves a marked gap on excluded days and adds nothing for them', () => {
            const geometry = computeCostChartGeometry(
                series(daily, [], 'day'),
                bench([day(days[0], 'scored', 2), day(days[1], 'excluded', null), day(days[2], 'scored', 1)]),
            )
            expect(geometry.hindsightSegments.map((segment) => segment.map((point) => point.value))).toEqual([
                [0, 8],
                [18, 27],
            ])
            expect(geometry.hindsightExcluded).toHaveLength(1)
            expect(geometry.hindsightExcluded[0].left).toBeCloseTo(100 / 3)
        })

        it('is not drawn in hourly views', () => {
            const geometry = computeCostChartGeometry(series(comparison()), bench([day('2026-10-05', 'scored', 2)]))
            expect(geometry.hindsightSegments).toEqual([])
            expect(geometry.hindsightArea).toEqual([])
        })
    })
})
