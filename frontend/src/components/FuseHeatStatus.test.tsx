import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import FuseHeatStatus from './FuseHeatStatus'
import type { LoadBalancerStatusResponse } from '../lib/api'

const status: LoadBalancerStatusResponse = {
    enabled: true,
    state: 'throttling',
    reason: '',
    main_fuse_a: 20,
    phase_current_a: { 1: 24, 2: 18, 3: 20 },
    phase_headroom_a: {},
    phase_heat_percent: { 1: 82, 2: 61, 3: 53 },
    phase_heat_state: { 1: 'heating', 2: 'cooling', 3: 'holding' },
    fuse_safety_percent: 80,
    tick_interval_s: 15,
    ev: [],
    shed: [],
}
afterEach(() => vi.useRealTimers())
describe('estimated fuse heat', () => {
    it('shows independent phase trends, heat and configured threshold', () => {
        render(<FuseHeatStatus status={status} />)
        expect(screen.getByText(/↑ Heating up/)).toBeInTheDocument()
        expect(screen.getByText(/↓ Cooling down/)).toBeInTheDocument()
        expect(screen.getByText(/→ Heat holding/)).toBeInTheDocument()
        expect(screen.getByRole('meter', { name: 'L1 estimated fuse heat' })).toHaveAttribute('aria-valuenow', '82')
        expect(screen.getByRole('meter', { name: 'L2 estimated fuse heat' })).toHaveAttribute(
            'aria-valuetext',
            expect.stringContaining('intervention threshold 80%'),
        )
        expect(screen.getByText('About fuse protection').closest('details')).not.toHaveAttribute('open')
    })
    it('freezes stale phase display and keeps its last heat value', () => {
        render(<FuseHeatStatus status={{ ...status, phase_heat_state: { 1: 'stale', 2: 'cooling', 3: 'holding' } }} />)
        expect(screen.getByText(/Stale · frozen/)).toBeInTheDocument()
        expect(screen.getByRole('meter', { name: 'L1 estimated fuse heat' })).toHaveAttribute('aria-valuenow', '82')
        expect(screen.getByText(/Heat estimates are frozen/)).toBeInTheDocument()
    })
    it('marks old heat snapshots stale even if other live messages still arrive', () => {
        vi.useFakeTimers()
        vi.setSystemTime(new Date('2026-10-21T12:00:00Z'))
        render(<FuseHeatStatus status={{ ...status, heat_sampled_at: new Date().toISOString() }} />)
        act(() => {
            vi.advanceTimersByTime(46000)
        })
        expect(screen.getAllByText(/Stale · frozen/)).toHaveLength(3)
    })
    it('explains an actual heat hold without claiming all throttling is caused by heat', () => {
        render(
            <FuseHeatStatus
                status={{
                    ...status,
                    battery: {
                        phases: [1, 2, 3],
                        planned_w: 7000,
                        cap_w: 3000,
                        state: 'throttling',
                        reason: 'Battery: holding 3.0 kW — fuse heat must cool below 50%',
                    },
                }}
            />,
        )
        expect(screen.getByText(/increases and restores require heat below 50%/)).toBeInTheDocument()
    })
    it('keeps above-scale values readable and missing phases unavailable', () => {
        render(
            <FuseHeatStatus
                status={{ ...status, phase_heat_percent: { 1: 125 }, phase_heat_state: { 1: 'heating' } }}
            />,
        )
        expect(screen.getByText(/125%/)).toBeInTheDocument()
        expect(screen.getByRole('meter', { name: 'L1 estimated fuse heat' })).toHaveAttribute('aria-valuenow', '100')
        expect(screen.getAllByText(/· Unavailable/)).toHaveLength(2)
    })
    it('omits heat for old payloads instead of inventing cold readings', () => {
        const { container } = render(<FuseHeatStatus status={{ ...status, phase_heat_percent: undefined }} />)
        expect(container.querySelector('[role="meter"]')).toBeNull()
        expect(screen.getByText('24.0 / 20 A')).toBeInTheDocument()
    })
})
