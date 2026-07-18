import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import LoadBalancerCompactView from './LoadBalancerCompactView'
import type { LoadBalancerStatusResponse } from '../lib/api'

function baseStatus(overrides: Partial<LoadBalancerStatusResponse> = {}): LoadBalancerStatusResponse {
    return {
        enabled: true,
        state: 'idle',
        reason: '',
        main_fuse_a: 20,
        phase_current_a: { '1': 5, '2': 5, '3': 5 },
        phase_headroom_a: { '1': 15, '2': 15, '3': 15 },
        resume_margin_percent: 90,
        ev: [],
        shed: [],
        ...overrides,
    }
}

function renderView(status: LoadBalancerStatusResponse | null) {
    return render(
        <MemoryRouter>
            <LoadBalancerCompactView status={status} />
        </MemoryRouter>,
    )
}

describe('LoadBalancerCompactView', () => {
    it('shows a loading placeholder while status is null', () => {
        renderView(null)
        expect(screen.getByText(/Loading load balancer status/)).toBeInTheDocument()
    })

    it('renders the state label, reason, and a link to the Executor page', () => {
        renderView(baseStatus({ state: 'throttling', reason: 'Reduced 16A -> 10A (headroom -6.0A)' }))

        expect(screen.getByText('Throttling')).toBeInTheDocument()
        expect(screen.getByText('Reduced 16A -> 10A (headroom -6.0A)')).toBeInTheDocument()
        expect(screen.getByRole('link', { name: 'Details →' })).toHaveAttribute('href', '/executor')
    })

    it('renders live phase bars for L1/L2/L3 against the fuse rating, colored by margin', () => {
        const { container } = renderView(
            baseStatus({
                main_fuse_a: 20,
                phase_current_a: { '1': 26, '2': 5, '3': 19 },
            }),
        )

        expect(screen.getByText('26.0A / 20A')).toBeInTheDocument()
        expect(screen.getByText('5.0A / 20A')).toBeInTheDocument()
        expect(screen.getByText('19.0A / 20A')).toBeInTheDocument()

        // Only L1 (26A) is over the 20A fuse rating -> exactly one bar colored "bad"
        expect(container.querySelectorAll('.rounded-full.bg-bad')).toHaveLength(1)
    })

    it('omits idle EV chargers and shows active (non-idle) ones', () => {
        renderView(
            baseStatus({
                ev: [
                    {
                        charger_id: 'idle-charger',
                        charger_name: 'Idle Charger',
                        setpoint_a: null,
                        planned_target_a: null,
                        state: 'idle',
                        reason: '',
                    },
                    {
                        charger_id: 'throttled-charger',
                        charger_name: 'Garage EV',
                        setpoint_a: 10,
                        planned_target_a: null,
                        state: 'throttling',
                        reason: 'Reduced due to headroom',
                    },
                ],
            }),
        )

        expect(screen.queryByText('Idle Charger')).not.toBeInTheDocument()
        expect(screen.getByText('Garage EV')).toBeInTheDocument()
        expect(screen.getByText('Throttling')).toBeInTheDocument()
    })

    it('omits non-shed loads and shows only actively shed ones', () => {
        renderView(
            baseStatus({
                shed: [
                    { load_id: 'main_tank', device_type: 'water_heater', shed: false, reason: '' },
                    { load_id: 'pool_pump', device_type: 'other', shed: true, reason: 'Over limit' },
                ],
            }),
        )

        expect(screen.queryByText(/main_tank/)).not.toBeInTheDocument()
        expect(screen.getByText(/pool_pump/)).toBeInTheDocument()
    })
})
