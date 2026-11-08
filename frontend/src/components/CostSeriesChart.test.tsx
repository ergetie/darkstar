import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
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
            coverage: {
                covered_slots: 0,
                total_slots: 96,
                excluded_slots: 96,
                water_unmeasured_slots: 0,
                water_unmeasured_hours: 0,
            },
            time_axis: axis,
        }
    }
    const partial = status === 'partial'
    return {
        status,
        reason: partial ? 'partial_coverage' : 'complete_coverage',
        method_version: 'grid-only-bill-v1',
        coverage: partial
            ? {
                  covered_slots: 3,
                  total_slots: 4,
                  excluded_slots: 1,
                  water_unmeasured_slots: 0,
                  water_unmeasured_hours: 0,
              }
            : {
                  covered_slots: 4,
                  total_slots: 4,
                  excluded_slots: 0,
                  water_unmeasured_slots: 0,
                  water_unmeasured_hours: 0,
              },
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

    describe('bucket readout interaction', () => {
        const twoHours = () => {
            const gridOnly = comparison()
            gridOnly.points = [
                ...gridOnly.points!,
                {
                    ...gridOnly.points![0],
                    start: '2026-10-05T13:00:00+02:00',
                    end: '2026-10-05T14:00:00+02:00',
                },
            ]
            const value = series(gridOnly)
            value.points = [actualPoint, { ...actualPoint, start: '2026-10-05T13:00:00+02:00' }]
            return value
        }
        const hour12 = () => screen.getByRole('button', { name: 'Hour 12:00 cost details' })
        const hour13 = () => screen.getByRole('button', { name: 'Hour 13:00 cost details' })
        const readout = () => screen.queryByTestId('cost-chart-readout')

        // Sequence a touch browser fires for one tap (compat mouse events included).
        const tap = (el: HTMLElement) => {
            fireEvent.pointerEnter(el, { pointerType: 'touch' })
            fireEvent.pointerDown(el, { pointerType: 'touch' })
            fireEvent.mouseEnter(el)
            fireEvent.focus(el)
            fireEvent.pointerUp(el, { pointerType: 'touch' })
            fireEvent.click(el)
        }

        it('opens the readout on the first touch tap and closes it on the second', () => {
            render(<CostSeriesChart series={twoHours()} loading={false} />)
            tap(hour12())
            expect(readout()).toHaveTextContent('12:00')
            tap(hour12())
            expect(readout()).not.toBeInTheDocument()
        })

        it('switches to another bucket when it is tapped', () => {
            render(<CostSeriesChart series={twoHours()} loading={false} />)
            tap(hour12())
            fireEvent.blur(hour12())
            tap(hour13())
            expect(readout()).toHaveTextContent('13:00')
            expect(readout()).not.toHaveTextContent('12:00')
        })

        it('shows the readout on mouse hover, keeps it on click and clears it on leave', () => {
            render(<CostSeriesChart series={twoHours()} loading={false} />)
            fireEvent.pointerEnter(hour12(), { pointerType: 'mouse' })
            expect(readout()).toHaveTextContent('12:00')
            fireEvent.pointerDown(hour12(), { pointerType: 'mouse' })
            fireEvent.focus(hour12())
            fireEvent.pointerUp(hour12(), { pointerType: 'mouse' })
            fireEvent.click(hour12())
            expect(readout()).toHaveTextContent('12:00')
            fireEvent.mouseLeave(hour12().parentElement!.parentElement!)
            expect(readout()).not.toBeInTheDocument()
        })

        it('does not open on a touch pointerenter alone', () => {
            render(<CostSeriesChart series={twoHours()} loading={false} />)
            fireEvent.pointerEnter(hour12(), { pointerType: 'touch' })
            expect(readout()).not.toBeInTheDocument()
        })

        it('keyboard focus opens, Enter/Space keep it open, blur closes', () => {
            render(<CostSeriesChart series={twoHours()} loading={false} />)
            fireEvent.focus(hour12())
            expect(readout()).toHaveTextContent('12:00')
            fireEvent.click(hour12()) // Enter or Space: click with no pointer events
            expect(readout()).toHaveTextContent('12:00')
            fireEvent.click(hour12())
            expect(readout()).toHaveTextContent('12:00')
            fireEvent.blur(hour12())
            expect(readout()).not.toBeInTheDocument()
        })
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
    describe('axis labels on a repeated-hour day', () => {
        const fallBack = () => {
            const gridOnly = comparison('unavailable')
            gridOnly.time_axis = {
                timezone: 'Europe/Stockholm',
                start: '2026-10-25T00:00:00+02:00',
                end: '2026-10-26T00:00:00+01:00',
            }
            const value = series(gridOnly)
            value.points = [{ ...actualPoint, start: '2026-10-25T02:00:00+01:00' }]
            return value
        }
        const axisLabels = (container: HTMLElement) =>
            [...container.querySelectorAll<HTMLElement>('.relative.h-8 > span')].map((node) => ({
                text: node.textContent,
                left: Number.parseFloat(node.style.left),
                row: Number.parseInt(node.style.top, 10) / 16,
            }))

        afterEach(() => vi.restoreAllMocks())

        it('shows every label while the width is unknown', () => {
            const { container } = render(<CostSeriesChart series={fallBack()} loading={false} />)
            expect(axisLabels(container).map((label) => label.text)).toContain('05:00')
        })

        it('keeps the repeated-hour labels and the axis start and drops or moves what would overlap at 290 px', () => {
            vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 290 } as DOMRect)
            const { container } = render(<CostSeriesChart series={fallBack()} loading={false} />)
            const labels = axisLabels(container)
            const texts = labels.map((label) => label.text)
            expect(texts).toEqual(expect.arrayContaining(['00:00', '02+2', '02+1']))
            const sameRow = (row: number) => labels.filter((label) => label.row === row)
            for (const row of [0, 1]) {
                const lefts = sameRow(row).map((label) => label.left)
                expect(lefts).toEqual([...lefts].sort((a, b) => a - b))
            }
            // Raw layout puts 02+1 (row 1, start-aligned at 12 %) on top of 05:00 (row 1, centred at 24 %).
            expect(labels.filter((l) => l.row === 1 && (l.text === '02+1' || l.text === '05:00'))).toHaveLength(1)
        })
    })

    describe('excluded spans', () => {
        const span = {
            start: '2026-10-05T12:15:00+02:00',
            end: '2026-10-05T12:30:00+02:00',
            slots: 1,
            reason: 'unknown_component',
            component: 'ev',
        }

        it('draws one muted band per span under the lines', () => {
            const value = comparison('partial')
            value.excluded_spans = [
                span,
                { ...span, start: '2026-10-05T12:00:00+02:00', end: '2026-10-05T12:15:00+02:00' },
            ]
            const { container } = render(<CostSeriesChart series={series(value)} loading={false} />)
            const bands = container.querySelectorAll('[data-testid="cost-excluded-span"]')
            expect(bands).toHaveLength(2)
            expect(bands[0]).toHaveClass('cost-chart-excluded')
            expect(bands[0]).toHaveAttribute('aria-hidden', 'true')
            const svg = container.querySelector('svg')
            expect(bands[0].compareDocumentPosition(svg as Element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
        })

        it('renders no band for an empty or absent list', () => {
            const empty = comparison('partial')
            empty.excluded_spans = []
            const { container, rerender } = render(<CostSeriesChart series={series(empty)} loading={false} />)
            expect(container.querySelector('[data-testid="cost-excluded-span"]')).toBeNull()
            rerender(<CostSeriesChart series={series(comparison('partial'))} loading={false} />)
            expect(container.querySelector('[data-testid="cost-excluded-span"]')).toBeNull()
            expect(container.querySelectorAll('[data-testid="ds-line"]')).toHaveLength(2)
        })

        it('keeps the DS and Grid-only paths identical with and without spans', () => {
            const paths = (container: HTMLElement) =>
                [...container.querySelectorAll('[data-testid="ds-line"], [data-testid="grid-only-line"]')].map((node) =>
                    node.getAttribute('d'),
                )
            const plain = render(<CostSeriesChart series={series(comparison('partial'))} loading={false} />)
            const before = paths(plain.container)
            plain.unmount()
            const value = comparison('partial')
            value.excluded_spans = [span]
            const spanned = render(<CostSeriesChart series={series(value)} loading={false} />)
            expect(paths(spanned.container)).toEqual(before)
            expect(before).toHaveLength(4)
        })

        it('names the reason and time range when a bucket over a span is focused', () => {
            const value = comparison('partial')
            value.excluded_spans = [span]
            render(<CostSeriesChart series={series(value)} loading={false} />)
            fireEvent.focus(screen.getByRole('button', { name: 'Hour 12:00 cost details' }))
            expect(screen.getByTestId('cost-chart-excluded-readout')).toHaveTextContent(
                'Not compared: EV charger not measured (12:15–12:30)',
            )
            expect(screen.getByTestId('cost-chart-excluded-readout')).not.toHaveTextContent('unknown_component')
        })

        it('adds no reason line to a bucket that does not overlap a span', () => {
            const value = comparison('partial')
            value.excluded_spans = [{ ...span, start: '2026-10-05T08:00:00+02:00', end: '2026-10-05T09:00:00+02:00' }]
            render(<CostSeriesChart series={series(value)} loading={false} />)
            fireEvent.focus(screen.getByRole('button', { name: 'Hour 12:00 cost details' }))
            expect(screen.queryByTestId('cost-chart-excluded-readout')).not.toBeInTheDocument()
        })
    })
})
