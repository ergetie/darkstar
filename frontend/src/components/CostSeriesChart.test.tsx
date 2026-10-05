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
    it('keeps the heading on one line with the legend on its own row below', () => {
        render(<CostSeriesChart series={series} loading={false} />)

        const heading = screen.getByText('Cost so far')
        expect(heading).toHaveClass('whitespace-nowrap')

        const legend = screen.getByText('no Darkstar').parentElement as HTMLElement
        expect(legend).toHaveClass('flex-wrap')
        // Heading and legend are siblings in the header, so the legend sits on a row of its own
        expect(legend.parentElement).toBe(heading.parentElement)
        for (const label of ['import', 'export', 'net', 'no Darkstar']) {
            expect(screen.getByText(label)).toHaveClass('whitespace-nowrap')
        }
    })

    it('replaces the legend with the hover readout, heading unchanged', () => {
        const { container } = render(<CostSeriesChart series={series} loading={false} />)
        const target = container.querySelector('.absolute.inset-0.flex > div') as HTMLElement
        fireEvent.mouseEnter(target)

        expect(screen.queryByText('import')).not.toBeInTheDocument()
        expect(screen.getByText(/no Darkstar/)).toBeInTheDocument()
        expect(screen.getByText('Cost so far')).toHaveClass('whitespace-nowrap')
    })
})
