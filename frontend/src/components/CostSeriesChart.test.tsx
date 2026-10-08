import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import CostSeriesChart from './CostSeriesChart'
import type { CostSeriesResponse, GridOnlyComparison } from '../lib/api'

const axis = {
    timezone: 'Europe/Stockholm',
    start: '2026-10-05T00:00:00+02:00',
    end: '2026-10-06T00:00:00+02:00',
}

const actualPoint = {
    start: '2026-10-05T12:00:00+02:00',
    import_cost_sek: 3,
    export_revenue_sek: 1,
    net_cost_sek: 2,
    cumulative_net_cost_sek: 2,
}

function comparison(status: 'available' | 'partial' | 'unavailable' = 'available'): GridOnlyComparison {
    if (status === 'unavailable') {
        return {
            status,
            reason: 'no_usable_observations',
            method_version: 'grid-only-bill-v1',
            coverage: { covered_slots: 0, total_slots: 96, excluded_slots: 96 },
            time_axis: axis,
        }
    }
    const partial = status === 'partial'
    return {
        status,
        reason: partial ? 'partial_coverage' : 'complete_coverage',
        method_version: 'grid-only-bill-v1',
        coverage: partial
            ? { covered_slots: 3, total_slots: 4, excluded_slots: 1 }
            : { covered_slots: 4, total_slots: 4, excluded_slots: 0 },
        time_axis: axis,
        through: '2026-10-05T13:00:00+02:00',
        grid_only_cost_sek: 10,
        grid_only_wear_cost_sek: 0,
        ds_electricity_cost_sek: 7,
        ds_wear_cost_sek: 1,
        ds_cost_sek: 8,
        saving_sek: 2,
        points: [
            {
                start: '2026-10-05T12:00:00+02:00',
                end: '2026-10-05T13:00:00+02:00',
                import_cost_sek: 3,
                export_revenue_sek: 1,
                ds_electricity_cost_sek: 7,
                ds_wear_cost_sek: 1,
                grid_only_wear_cost_sek: 0,
                ds_cost_sek: 8,
                grid_only_cost_sek: 10,
                cumulative_ds_cost_sek: 8,
                cumulative_grid_only_cost_sek: 10,
            },
        ],
        segments: [
            {
                start: '2026-10-05T12:00:00+02:00',
                end: '2026-10-05T12:15:00+02:00',
                points: [
                    { at: '2026-10-05T12:00:00+02:00', cumulative_ds_cost_sek: 0, cumulative_grid_only_cost_sek: 0 },
                    { at: '2026-10-05T12:15:00+02:00', cumulative_ds_cost_sek: 2, cumulative_grid_only_cost_sek: 2.5 },
                ],
            },
            {
                start: '2026-10-05T12:30:00+02:00',
                end: '2026-10-05T13:00:00+02:00',
                points: [
                    { at: '2026-10-05T12:30:00+02:00', cumulative_ds_cost_sek: 2, cumulative_grid_only_cost_sek: 2.5 },
                    { at: '2026-10-05T12:45:00+02:00', cumulative_ds_cost_sek: 5, cumulative_grid_only_cost_sek: 6.25 },
                    { at: '2026-10-05T13:00:00+02:00', cumulative_ds_cost_sek: 8, cumulative_grid_only_cost_sek: 10 },
                ],
            },
        ],
    }
}

const series = (gridOnly?: GridOnlyComparison): CostSeriesResponse => ({
    period: 'today',
    bucket: 'hour',
    points: [actualPoint],
    grid_only_comparison: gridOnly,
})

const dottedPath = (container: HTMLElement) => container.querySelector('path[stroke-dasharray="1 3"]')

describe('CostSeriesChart', () => {
    it('draws the solid DS and dotted Grid-only lines with no comparison switch', () => {
        const { container } = render(<CostSeriesChart series={series(comparison())} loading={false} />)
        expect(dottedPath(container)).not.toBeNull()
        expect(screen.getByText('DS')).toBeInTheDocument()
        expect(screen.getByText('Grid-only')).toBeInTheDocument()
        expect(screen.queryByText('Without Darkstar')).not.toBeInTheDocument()
        expect(screen.queryByRole('tab')).not.toBeInTheDocument()
        expect(screen.queryByRole('button', { name: /comparison/i })).not.toBeInTheDocument()
    })

    it('shades only between matching covered segments and breaks at the excluded slot', () => {
        const { container } = render(<CostSeriesChart series={series(comparison('partial'))} loading={false} />)
        expect(container.querySelectorAll('[data-testid="grid-only-line"]')).toHaveLength(2)
        expect(container.querySelectorAll('[data-testid="ds-line"]')).toHaveLength(2)
        expect(container.querySelectorAll('[data-testid="cost-chart-saving"]').length).toBeGreaterThan(0)
    })

    it('falls back to Actual and omits comparison lines when no amount is available', () => {
        const { container } = render(<CostSeriesChart series={series(comparison('unavailable'))} loading={false} />)
        expect(container.querySelector('[data-testid="actual-line"]')).not.toBeNull()
        expect(dottedPath(container)).toBeNull()
        expect(screen.getByText('Actual')).toBeInTheDocument()
        expect(screen.queryByText('Grid-only')).not.toBeInTheDocument()
    })

    it('shows a local bucket readout for keyboard focus and pointer hover', () => {
        render(<CostSeriesChart series={series(comparison())} loading={false} />)
        const bucket = screen.getByRole('button', { name: 'Hour 12:00 cost details' })
        fireEvent.focus(bucket)
        expect(screen.getByTestId('cost-chart-readout')).toHaveTextContent('12:00')
        expect(screen.getByTestId('cost-chart-readout')).toHaveTextContent('DS')
        expect(screen.getByTestId('cost-chart-readout')).toHaveTextContent('Grid-only')
        fireEvent.blur(bucket)
        expect(screen.queryByTestId('cost-chart-readout')).not.toBeInTheDocument()
    })

    it('retains the empty state and loading skeleton', () => {
        const { rerender, container } = render(<CostSeriesChart series={null} loading />)
        expect(container.querySelector('[aria-busy="true"]')).not.toBeNull()
        rerender(<CostSeriesChart series={null} loading={false} seriesError />)
        expect(screen.getByTestId('cost-chart-error')).toHaveTextContent('Unable to load chart data for this period')
        expect(screen.queryByText('No recorded slots yet for this period')).not.toBeInTheDocument()
        rerender(<CostSeriesChart series={series()} loading={false} />)
        expect(screen.getByText('Actual cost so far')).toBeInTheDocument()
        rerender(<CostSeriesChart series={{ period: 'today', bucket: 'hour', points: [] }} loading={false} />)
        expect(screen.getByText('No recorded slots yet for this period')).toBeInTheDocument()
    })

    it('identifies a repeated-hour bucket by offset even when the other occurrence has no data', () => {
        const gridOnly = comparison('unavailable')
        gridOnly.time_axis = {
            timezone: 'Europe/Stockholm',
            start: '2026-10-25T00:00:00+02:00',
            end: '2026-10-26T00:00:00+01:00',
        }
        const value = series(gridOnly)
        value.points = [{ ...actualPoint, start: '2026-10-25T02:00:00+01:00' }]
        render(<CostSeriesChart series={value} loading={false} />)
        fireEvent.focus(screen.getByRole('button', { name: 'Hour 02:00 +01:00 cost details' }))
        expect(screen.getByTestId('cost-chart-readout')).toHaveTextContent('02:00 +01:00')
    })
})
