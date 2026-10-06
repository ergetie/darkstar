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
            baseline_cumulative_net_cost_sek: 2.5,
        },
    ],
    baseline: null,
} as CostSeriesResponse

describe('CostSeriesChart header', () => {
    it('keeps the actual heading on one line and ignores legacy baseline data', () => {
        render(<CostSeriesChart series={series} loading={false} />)

        const heading = screen.getByText('Actual cost so far')
        expect(heading).toHaveClass('whitespace-nowrap')
        for (const label of ['import', 'export', 'net']) {
            expect(screen.getByText(label)).toHaveClass('whitespace-nowrap')
        }
        expect(screen.queryByText('no Darkstar')).not.toBeInTheDocument()
    })

    it('offers a separate comparison view only when validated points are available', () => {
        const available = {
            ...series,
            battery_comparison: {
                status: 'available',
                reason: 'validated',
                saving_sek: 1,
                points: [
                    {
                        start: '2026-10-04T00:00:00+02:00',
                        darkstar_cumulative_comparison_cost_sek: 1.5,
                        self_use_cumulative_comparison_cost_sek: 2.5,
                    },
                ],
            },
        } as CostSeriesResponse
        render(<CostSeriesChart series={available} loading={false} />)
        fireEvent.click(screen.getByRole('button', { name: 'Comparison' }))

        expect(screen.getByText('Estimated comparison cost')).toBeInTheDocument()
        expect(screen.getByText('Darkstar')).toBeInTheDocument()
        expect(screen.getByText('Plain self-use')).toBeInTheDocument()
        expect(screen.queryByText('import')).not.toBeInTheDocument()
    })

    it('replaces the actual legend with the hover readout', () => {
        const { container } = render(<CostSeriesChart series={series} loading={false} />)
        const target = container.querySelector('.absolute.inset-0.flex > div') as HTMLElement
        fireEvent.mouseEnter(target)

        expect(screen.queryByText('import')).not.toBeInTheDocument()
        expect(screen.getByText(/total/)).toBeInTheDocument()
        expect(screen.getByText('Actual cost so far')).toHaveClass('whitespace-nowrap')
    })
})

describe('Comparison accounting readout', () => {
    it('uses summary cost signs and labels the actual completed interval', () => {
        const comparison = {
            status: 'available',
            reason: 'validated',
            through: '2026-10-04T03:45:00',
            points: [
                {
                    start: '2026-10-04T00:00:00',
                    darkstar_cumulative_comparison_cost_sek: 1.5,
                    self_use_cumulative_comparison_cost_sek: -2.5,
                },
            ],
        }
        const { container } = render(
            <CostSeriesChart
                series={{ ...series, battery_comparison: comparison } as CostSeriesResponse}
                loading={false}
            />,
        )
        fireEvent.click(screen.getByRole('button', { name: 'Comparison' }))
        expect(screen.getByText('03:45')).toBeInTheDocument()
        expect(screen.queryByText('24')).not.toBeInTheDocument()
        const target = container.querySelector('.absolute.inset-0.flex > div') as HTMLElement
        fireEvent.click(target)
        expect(screen.getByText('1.50 kr')).toBeInTheDocument()
        expect(screen.getByText('-2.50 kr')).toBeInTheDocument()
    })
})
