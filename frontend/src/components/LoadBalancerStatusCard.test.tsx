import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import LoadBalancerStatusCard from './LoadBalancerStatusCard'
import { Api, type LoadBalancerStatusResponse } from '../lib/api'

vi.mock('../lib/api', () => ({
    Api: {
        executor: {
            loadBalancerStatus: vi.fn(),
        },
    },
}))

vi.mock('../lib/hooks', () => ({
    useSocket: vi.fn(),
}))

function renderCard() {
    return render(
        <MemoryRouter>
            <LoadBalancerStatusCard />
        </MemoryRouter>,
    )
}

describe('LoadBalancerStatusCard', () => {
    it('explains the feature is off and links to settings when disabled', async () => {
        vi.mocked(Api.executor.loadBalancerStatus).mockResolvedValue({
            enabled: false,
            state: 'disabled',
            reason: 'Load balancing disabled or unconfigured',
            main_fuse_a: null,
            phase_current_a: {},
            phase_headroom_a: {},
            ev: [],
            shed: [],
        } as LoadBalancerStatusResponse)

        renderCard()

        expect(await screen.findByText('Load Balancing is disabled')).toBeInTheDocument()
        expect(screen.getByRole('link', { name: 'Go to Settings' })).toHaveAttribute(
            'href',
            '/settings?tab=load-balancing',
        )
    })

    it('renders per-phase bars and the limitation reason while throttling', async () => {
        vi.mocked(Api.executor.loadBalancerStatus).mockResolvedValue({
            enabled: true,
            state: 'throttling',
            reason: 'Reduced 16A -> 10A (headroom -6.0A)',
            main_fuse_a: 20,
            phase_current_a: { '1': 26, '2': 5, '3': 5 },
            phase_headroom_a: { '1': -6, '2': 15, '3': 15 },
            ev: [
                {
                    charger_id: 'goe',
                    charger_name: 'Garage EV',
                    setpoint_a: 10,
                    planned_target_a: 16,
                    state: 'throttling',
                    reason: 'Reduced 16A -> 10A (headroom -6.0A)',
                },
            ],
            shed: [],
        } as LoadBalancerStatusResponse)

        renderCard()

        expect((await screen.findAllByText('Throttling')).length).toBeGreaterThan(0)
        expect(screen.getByText('Garage EV')).toBeInTheDocument()
        expect(screen.getByText('10A (planned 16A)')).toBeInTheDocument()
        expect(screen.getByText('Reduced 16A -> 10A (headroom -6.0A)')).toBeInTheDocument()
        expect(screen.getByText('26.0A / 20A')).toBeInTheDocument()
    })

    it('renders a distinct row per dynamically-throttled charger', async () => {
        vi.mocked(Api.executor.loadBalancerStatus).mockResolvedValue({
            enabled: true,
            state: 'throttling',
            reason: 'Reduced 16A -> 10A (headroom -6.0A)',
            main_fuse_a: 20,
            phase_current_a: { '1': 20, '2': 5, '3': 5 },
            phase_headroom_a: { '1': 0, '2': 15, '3': 15 },
            ev: [
                {
                    charger_id: 'goe',
                    charger_name: 'Garage EV',
                    setpoint_a: 10,
                    planned_target_a: 16,
                    state: 'throttling',
                    reason: 'Reduced 16A -> 10A (headroom -6.0A)',
                },
                {
                    charger_id: 'main_ev',
                    charger_name: 'Driveway EV',
                    setpoint_a: 16,
                    planned_target_a: 16,
                    state: 'idle',
                    reason: '',
                },
            ],
            shed: [],
        } as LoadBalancerStatusResponse)

        renderCard()

        expect(await screen.findByText('Garage EV')).toBeInTheDocument()
        expect(screen.getByText('Driveway EV')).toBeInTheDocument()
        expect(screen.getByText('16A')).toBeInTheDocument()
    })

    it('shows shed loads when the balancer is shedding', async () => {
        vi.mocked(Api.executor.loadBalancerStatus).mockResolvedValue({
            enabled: true,
            state: 'shedding',
            reason: 'phase overloaded',
            main_fuse_a: 20,
            phase_current_a: { '1': 5, '2': 25, '3': 5 },
            phase_headroom_a: { '1': 15, '2': -5, '3': 15 },
            ev: [],
            shed: [{ load_id: 'main_tank', device_type: 'water_heater', shed: true, reason: 'phase overloaded' }],
        } as LoadBalancerStatusResponse)

        renderCard()

        await waitFor(() => {
            expect(screen.getByText(/Shed: main_tank/)).toBeInTheDocument()
        })
    })
})
