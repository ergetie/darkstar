import { describe, expect, it } from 'vitest'
import { parseCostSeriesResponse } from './api'

const axis = {
    timezone: 'Europe/Stockholm',
    start: '2026-10-05T00:00:00+02:00',
    end: '2026-10-06T00:00:00+02:00',
}

function validResponse() {
    return {
        period: 'today',
        bucket: 'hour',
        points: [
            {
                start: '2026-10-05T00:00:00+02:00',
                import_cost_sek: 3,
                export_revenue_sek: 0.5,
                net_cost_sek: 2.5,
                cumulative_net_cost_sek: 2.5,
            },
        ],
        grid_only_comparison: {
            status: 'available',
            reason: 'complete_coverage',
            method_version: 'grid-only-bill-v1',
            coverage: { covered_slots: 4, total_slots: 4, excluded_slots: 0 },
            time_axis: { ...axis },
            through: '2026-10-05T01:00:00+02:00',
            grid_only_cost_sek: 5,
            grid_only_wear_cost_sek: 0,
            ds_electricity_cost_sek: 2.5,
            ds_wear_cost_sek: 0.5,
            ds_cost_sek: 3,
            saving_sek: 2,
            points: [
                {
                    start: '2026-10-05T00:00:00+02:00',
                    end: '2026-10-05T01:00:00+02:00',
                    import_cost_sek: 3,
                    export_revenue_sek: 0.5,
                    ds_electricity_cost_sek: 2.5,
                    ds_wear_cost_sek: 0.5,
                    grid_only_wear_cost_sek: 0,
                    ds_cost_sek: 3,
                    grid_only_cost_sek: 5,
                    cumulative_ds_cost_sek: 3,
                    cumulative_grid_only_cost_sek: 5,
                },
            ],
            segments: [
                {
                    start: '2026-10-05T00:00:00+02:00',
                    end: '2026-10-05T01:00:00+02:00',
                    points: [
                        {
                            at: '2026-10-05T00:00:00+02:00',
                            cumulative_ds_cost_sek: 0,
                            cumulative_grid_only_cost_sek: 0,
                        },
                        {
                            at: '2026-10-05T00:15:00+02:00',
                            cumulative_ds_cost_sek: 0.75,
                            cumulative_grid_only_cost_sek: 1.25,
                        },
                        {
                            at: '2026-10-05T00:30:00+02:00',
                            cumulative_ds_cost_sek: 1.5,
                            cumulative_grid_only_cost_sek: 2.5,
                        },
                        {
                            at: '2026-10-05T00:45:00+02:00',
                            cumulative_ds_cost_sek: 2.25,
                            cumulative_grid_only_cost_sek: 3.75,
                        },
                        {
                            at: '2026-10-05T01:00:00+02:00',
                            cumulative_ds_cost_sek: 3,
                            cumulative_grid_only_cost_sek: 5,
                        },
                    ],
                },
            ],
        },
    }
}

describe('parseCostSeriesResponse', () => {
    it('accepts and returns wear-inclusive amounts with explicit full-period timezone metadata', () => {
        const parsed = parseCostSeriesResponse(validResponse())
        const comparison = parsed.grid_only_comparison
        expect(comparison?.status).toBe('available')
        if (!comparison || (comparison.status !== 'available' && comparison.status !== 'partial')) {
            throw new Error('expected an amount-bearing response')
        }
        expect(comparison.ds_electricity_cost_sek + comparison.ds_wear_cost_sek).toBe(3)
        expect(comparison.grid_only_cost_sek - comparison.ds_cost_sek).toBe(2)
    })

    it.each([
        (value: ReturnType<typeof validResponse>) => {
            value.grid_only_comparison.saving_sek = 99
        },
        (value: ReturnType<typeof validResponse>) => {
            value.grid_only_comparison.points[0].ds_wear_cost_sek = Number.NaN
        },
        (value: ReturnType<typeof validResponse>) => {
            value.grid_only_comparison.points[0].cumulative_ds_cost_sek = 2
        },
        (value: ReturnType<typeof validResponse>) => {
            value.grid_only_comparison.segments[0].points.splice(2, 1)
        },
        (value: ReturnType<typeof validResponse>) => {
            value.grid_only_comparison.segments[0].points[2].at = '2026-10-05T00:31:00+02:00'
        },
        (value: ReturnType<typeof validResponse>) => {
            value.grid_only_comparison.time_axis.timezone = 'Not/A_Timezone'
        },
    ])('rejects malformed amounts, cumulative values, segments, and axis metadata', (corrupt) => {
        const value = validResponse()
        corrupt(value)
        expect(() => parseCostSeriesResponse(value)).toThrow('Invalid cost-series response')
    })

    it('rejects retired baseline and battery-comparison fields instead of falling back', () => {
        const value = validResponse() as ReturnType<typeof validResponse> & { battery_comparison?: unknown }
        value.battery_comparison = { saving_sek: 500 }
        expect(() => parseCostSeriesResponse(value)).toThrow('Invalid cost-series response')
    })

    it('accepts valid daily totals when independent three-decimal bucket rounding accumulates', () => {
        const comparison = validResponse().grid_only_comparison
        const dailyPoints = []
        const segments = []
        let dsElectricity = 0
        let dsWear = 0
        let dsCost = 0
        let gridOnlyCost = 0

        for (let index = 0; index < 30; index += 1) {
            const date = new Date(Date.UTC(2026, 8, 1 + index)).toISOString().slice(0, 10)
            const nextDate = new Date(Date.UTC(2026, 8, 2 + index)).toISOString().slice(0, 10)
            const start = `${date}T00:00:00+02:00`
            const bucketEnd = `${nextDate}T00:00:00+02:00`
            const slotEnd = `${date}T00:15:00+02:00`
            const previousDsCost = dsCost
            const previousGridCost = gridOnlyCost

            dsElectricity += 0.5004
            dsWear += 0.0003
            dsCost += 0.5007
            gridOnlyCost += 1.2344
            dailyPoints.push({
                start,
                end: bucketEnd,
                import_cost_sek: 0.5,
                export_revenue_sek: 0,
                ds_electricity_cost_sek: 0.5,
                ds_wear_cost_sek: 0,
                grid_only_wear_cost_sek: 0,
                ds_cost_sek: 0.501,
                grid_only_cost_sek: 1.234,
                cumulative_ds_cost_sek: Number(dsCost.toFixed(3)),
                cumulative_grid_only_cost_sek: Number(gridOnlyCost.toFixed(3)),
            })
            segments.push({
                start,
                end: slotEnd,
                points: [
                    {
                        at: start,
                        cumulative_ds_cost_sek: Number(previousDsCost.toFixed(3)),
                        cumulative_grid_only_cost_sek: Number(previousGridCost.toFixed(3)),
                    },
                    {
                        at: slotEnd,
                        cumulative_ds_cost_sek: Number(dsCost.toFixed(3)),
                        cumulative_grid_only_cost_sek: Number(gridOnlyCost.toFixed(3)),
                    },
                ],
            })
        }

        const value = {
            period: 'month',
            bucket: 'day',
            points: [],
            grid_only_comparison: {
                ...comparison,
                status: 'partial',
                reason: 'partial_coverage',
                coverage: { covered_slots: 30, total_slots: 2880, excluded_slots: 2850 },
                time_axis: {
                    timezone: 'Europe/Stockholm',
                    start: '2026-09-01T00:00:00+02:00',
                    end: '2026-10-01T00:00:00+02:00',
                },
                through: '2026-09-30T00:15:00+02:00',
                grid_only_cost_sek: Number(gridOnlyCost.toFixed(3)),
                grid_only_wear_cost_sek: 0,
                ds_electricity_cost_sek: Number(dsElectricity.toFixed(3)),
                ds_wear_cost_sek: Number(dsWear.toFixed(3)),
                ds_cost_sek: Number(dsCost.toFixed(3)),
                saving_sek: Number((gridOnlyCost - dsCost).toFixed(3)),
                points: dailyPoints,
                segments,
            },
        }

        expect(dailyPoints.reduce((sum, point) => sum + point.ds_electricity_cost_sek, 0)).toBe(15)
        expect(value.grid_only_comparison.ds_electricity_cost_sek).toBe(15.012)
        expect(() => parseCostSeriesResponse(value)).not.toThrow()

        const badBucketDelta = structuredClone(value)
        badBucketDelta.grid_only_comparison.points[10].cumulative_ds_cost_sek += 0.01
        expect(() => parseCostSeriesResponse(badBucketDelta)).toThrow('Invalid cost-series response')

        const badSummary = structuredClone(value)
        badSummary.grid_only_comparison.grid_only_cost_sek += 0.1
        badSummary.grid_only_comparison.saving_sek += 0.1
        expect(() => parseCostSeriesResponse(badSummary)).toThrow('Invalid cost-series response')

        const badPoint = structuredClone(value)
        badPoint.grid_only_comparison.points[10].ds_cost_sek += 0.01
        expect(() => parseCostSeriesResponse(badPoint)).toThrow('Invalid cost-series response')

        const badSegmentBucket = structuredClone(value)
        badSegmentBucket.grid_only_comparison.segments[10].points[1].cumulative_ds_cost_sek += 0.01
        badSegmentBucket.grid_only_comparison.segments[11].points[0].cumulative_ds_cost_sek += 0.01
        expect(() => parseCostSeriesResponse(badSegmentBucket)).toThrow('Invalid cost-series response')

        const outsideBucket = structuredClone(value)
        outsideBucket.grid_only_comparison.segments[10].start = '2026-09-10T23:30:00+02:00'
        outsideBucket.grid_only_comparison.segments[10].end = '2026-09-10T23:45:00+02:00'
        outsideBucket.grid_only_comparison.segments[10].points[0].at =
            outsideBucket.grid_only_comparison.segments[10].start
        outsideBucket.grid_only_comparison.segments[10].points[1].at =
            outsideBucket.grid_only_comparison.segments[10].end
        expect(() => parseCostSeriesResponse(outsideBucket)).toThrow('Invalid cost-series response')
    })

    it('accepts unavailable amounts only with coverage and time-axis metadata intact', () => {
        const value = {
            ...validResponse(),
            grid_only_comparison: {
                status: 'unavailable',
                reason: 'no_usable_observations',
                method_version: 'grid-only-bill-v1',
                coverage: { covered_slots: 0, total_slots: 4, excluded_slots: 4 },
                time_axis: { ...axis },
            },
        }
        const parsed = parseCostSeriesResponse(value)
        expect(parsed.grid_only_comparison?.status).toBe('unavailable')
        expect(() =>
            parseCostSeriesResponse({
                ...value,
                grid_only_comparison: { ...value.grid_only_comparison, saving_sek: 0 },
            }),
        ).toThrow('Invalid cost-series response')
    })
})
