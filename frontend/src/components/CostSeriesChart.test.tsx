import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import CostSeriesChart from './CostSeriesChart'
import type { CostSeriesResponse } from '../lib/api'

const series = {
    period: 'today',
    start_date: '2026-10-04',
    end_date: '2026-10-04',
    bucket: 'hour',
    points: [
        {
            start: '2026-10-04T00:00:00',
            import_cost_sek: 2,
            export_revenue_sek: 0.5,
            net_cost_sek: 1.5,
            cumulative_net_cost_sek: 1.5,
        },
    ],
    baseline: null,
} as CostSeriesResponse

const comparisonOf = (overrides: Record<string, unknown> = {}) =>
    ({
        status: 'available',
        reason: 'validated',
        points: [
            {
                start: '2026-10-04T00:00:00',
                darkstar_cumulative_comparison_cost_sek: 1.5,
                self_use_cumulative_comparison_cost_sek: 2.5,
            },
        ],
        ...overrides,
    }) as CostSeriesResponse['battery_comparison']

const dottedPath = (container: HTMLElement) => container.querySelector('path[stroke-dasharray="1 3"]')
const hoverFirst = (container: HTMLElement) =>
    fireEvent.mouseEnter(container.querySelector('.absolute.inset-0.flex > div') as HTMLElement)

describe('CostSeriesChart', () => {
    it('renders one chart without any tabs, ignoring legacy baseline data', () => {
        const legacy = {
            ...series,
            points: [{ ...series.points[0], baseline_cumulative_net_cost_sek: 2.5 }],
        } as CostSeriesResponse
        const { container } = render(<CostSeriesChart series={legacy} loading={false} />)

        expect(screen.getByText('Actual cost so far')).toHaveClass('whitespace-nowrap')
        for (const label of ['import', 'export', 'Actual']) {
            expect(screen.getByText(label)).toHaveClass('whitespace-nowrap')
        }
        expect(screen.queryByRole('button')).not.toBeInTheDocument()
        expect(screen.queryByRole('tab')).not.toBeInTheDocument()
        expect(screen.queryByText('Without Darkstar')).not.toBeInTheDocument()
        expect(dottedPath(container)).toBeNull()
    })

    it('draws the dotted Without Darkstar line and legend entry when comparison amounts exist', () => {
        const { container } = render(
            <CostSeriesChart series={{ ...series, battery_comparison: comparisonOf() }} loading={false} />,
        )
        expect(dottedPath(container)).not.toBeNull()
        expect(screen.getByText('Without Darkstar')).toBeInTheDocument()
        expect(screen.queryByRole('button')).not.toBeInTheDocument()
    })

    it('shades the saving without adding text, only when the without line exists', () => {
        const { container, rerender } = render(<CostSeriesChart series={series} loading={false} />)
        expect(container.querySelectorAll('[data-testid="cost-chart-saving"]')).toHaveLength(0)

        rerender(<CostSeriesChart series={{ ...series, battery_comparison: comparisonOf() }} loading={false} />)
        const shading = container.querySelectorAll('[data-testid="cost-chart-saving"]')
        expect(shading.length).toBeGreaterThan(0)
        expect(shading[0]).toHaveClass('fill-good')
        expect(shading[0].textContent).toBe('')
        expect(screen.getAllByText('Without Darkstar')).toHaveLength(1)
    })

    it('draws the dotted line for estimated comparisons too', () => {
        const { container } = render(
            <CostSeriesChart
                series={{ ...series, battery_comparison: comparisonOf({ status: 'estimated' }) }}
                loading={false}
            />,
        )
        expect(dottedPath(container)).not.toBeNull()
    })

    it('omits the dotted line when the comparison is unavailable', () => {
        const { container } = render(
            <CostSeriesChart
                series={{ ...series, battery_comparison: comparisonOf({ status: 'unavailable', reason: 'x' }) }}
                loading={false}
            />,
        )
        expect(dottedPath(container)).toBeNull()
        expect(screen.queryByText('Without Darkstar')).not.toBeInTheDocument()
    })

    it('withholds non-finite comparison points', () => {
        const invalid = {
            ...series,
            battery_comparison: comparisonOf({
                status: 'estimated',
                points: [
                    {
                        start: series.points[0].start,
                        darkstar_cumulative_comparison_cost_sek: Number.NaN,
                        self_use_cumulative_comparison_cost_sek: 2,
                    },
                ],
            }),
        }
        const { container } = render(<CostSeriesChart series={invalid} loading={false} />)
        expect(dottedPath(container)).toBeNull()
        expect(screen.queryByText('Without Darkstar')).not.toBeInTheDocument()
        expect(screen.getByText('Actual cost so far')).toBeInTheDocument()
    })

    it('replaces the legend with the hover readout', () => {
        const { container } = render(<CostSeriesChart series={series} loading={false} />)
        hoverFirst(container)

        expect(screen.queryByText('import')).not.toBeInTheDocument()
        expect(screen.getByText(/total/)).toBeInTheDocument()
        expect(screen.queryByText(/without/)).not.toBeInTheDocument()
        expect(screen.getByText('Actual cost so far')).toHaveClass('whitespace-nowrap')
    })

    it('adds the without-Darkstar total to the hover readout with cost signs', () => {
        // actual 1.5 + self-use 2.5 - darkstar 1.5 = 2.5 cost
        const { container } = render(
            <CostSeriesChart series={{ ...series, battery_comparison: comparisonOf() }} loading={false} />,
        )
        hoverFirst(container)
        expect(screen.getByText(/total/)).toBeInTheDocument()
        expect(screen.getByText('-1.50 kr')).toBeInTheDocument()
        expect(screen.getByText('-2.50 kr')).toBeInTheDocument()
        expect(screen.getByText(/without/)).toBeInTheDocument()
    })

    it('does not render a separate comparison axis for the completed interval', () => {
        render(
            <CostSeriesChart
                series={{ ...series, battery_comparison: comparisonOf({ through: '2026-10-04T03:45:00' }) }}
                loading={false}
            />,
        )
        expect(screen.queryByText('03:45')).not.toBeInTheDocument()
        expect(screen.getByText('24')).toBeInTheDocument()
    })
})
