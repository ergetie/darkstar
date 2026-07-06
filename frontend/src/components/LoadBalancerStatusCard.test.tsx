import { act, render, screen, waitFor } from '@testing-library/react'
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

describe('LoadBalancerStatusCard freshness indicator (load-balancing-completion 8.3)', () => {
    function enabledStatus(): LoadBalancerStatusResponse {
        return {
            enabled: true,
            state: 'idle',
            reason: 'Within limits',
            main_fuse_a: 20,
            tick_interval_s: 5,
            phase_current_a: { '1': 0.237, '2': 0.1, '3': 0.05 },
            phase_headroom_a: { '1': 19.8, '2': 19.9, '3': 19.95 },
            ev: [],
            shed: [],
        } as LoadBalancerStatusResponse
    }

    it('shows "updated Xs ago" and keeps it ticking', async () => {
        vi.useFakeTimers()
        try {
            vi.mocked(Api.executor.loadBalancerStatus).mockResolvedValue(enabledStatus())
            renderCard()
            await act(async () => {
                await Promise.resolve()
            })
            expect(screen.getByTestId('lb-freshness')).toHaveTextContent('updated 0s ago')

            act(() => {
                vi.advanceTimersByTime(3000)
            })
            expect(screen.getByTestId('lb-freshness')).toHaveTextContent('updated 3s ago')
            expect(screen.getByTestId('lb-freshness')).not.toHaveTextContent(/stale/)
        } finally {
            vi.useRealTimers()
        }
    })

    it('flags staleness once the payload age materially exceeds the tick interval', async () => {
        vi.useFakeTimers()
        try {
            vi.mocked(Api.executor.loadBalancerStatus).mockResolvedValue(enabledStatus())
            renderCard()
            await act(async () => {
                await Promise.resolve()
            })
            // tick_interval_s = 5 -> stale threshold max(3*5, 15) = 15s
            act(() => {
                vi.advanceTimersByTime(20000)
            })
            expect(screen.getByTestId('lb-freshness')).toHaveTextContent(/stale — last update 20s ago/)
        } finally {
            vi.useRealTimers()
        }
    })

    it('shows the raw per-phase reading as secondary text so near-zero homes read as live', async () => {
        vi.mocked(Api.executor.loadBalancerStatus).mockResolvedValue(enabledStatus())
        renderCard()
        expect(await screen.findByTestId('lb-raw-l1')).toHaveTextContent('0.237A')
        expect(screen.getByTestId('lb-raw-l2')).toHaveTextContent('0.100A')
    })
})
