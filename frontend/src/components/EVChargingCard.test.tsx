import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import EVChargingCard from './EVChargingCard'
import { Api } from '../lib/api'
import type { EVChargerState, LoadBalancerEvStatus, LoadBalancerStatusResponse } from '../lib/api'

vi.mock('../lib/api', () => ({
    Api: {
        ev: {
            setSchedule: vi.fn(),
            manualCharge: { stop: vi.fn().mockResolvedValue({ success: true, was_active: true }) },
        },
    },
}))

vi.mock('../lib/useToast', () => ({
    useToast: () => ({ toast: vi.fn() }),
}))

function baseCharger(overrides: Partial<EVChargerState> = {}): EVChargerState {
    return {
        id: 'ev1',
        name: 'Tesla',
        plugged_in: true,
        soc_percent: 50,
        power_kw: 0,
        target_soc_percent: 80,
        ready_by: '07:00',
        repeat: 'daily',
        ready_by_date: null,
        deadline: null,
        required_kwh: 10,
        delivered_kwh: 2,
        remaining_kwh: 8,
        daily_quota_kwh: null,
        quota_schedule: null,
        keep_on_after_target: false,
        ha_ready_by_entity: null,
        ha_target_soc_entity: null,
        type: 'current',
        n_days: null,
        status: 'on_track',
        source: 'api',
        externally_controlled: false,
        last_updated: null,
        last_planned_at: null,
        ...overrides,
    }
}

function baseEvStatus(overrides: Partial<LoadBalancerEvStatus> = {}): LoadBalancerEvStatus {
    return {
        charger_id: 'ev1',
        charger_name: 'Tesla',
        setpoint_a: null,
        planned_target_a: null,
        state: 'idle',
        reason: '',
        ...overrides,
    }
}

function baseLoadBalancing(ev: LoadBalancerEvStatus[]): LoadBalancerStatusResponse {
    return {
        enabled: true,
        state: 'idle',
        reason: '',
        main_fuse_a: null,
        phase_current_a: {},
        phase_headroom_a: {},
        ev,
        shed: [],
    }
}

function renderCard(charger: EVChargerState) {
    return render(
        <MemoryRouter>
            <EVChargingCard charger={charger} config={{}} loadBalancing={null} onRefresh={async () => {}} />
        </MemoryRouter>,
    )
}

describe('EVChargingCard mode derivation (7.3)', () => {
    it('shows the viewing state when the charger has a goal', () => {
        renderCard(baseCharger())
        expect(screen.getByText('Configure Goal')).toBeInTheDocument()
        expect(screen.queryByText('Save Goal')).not.toBeInTheDocument()
    })

    it('shows the create-goal form (never a phantom goal) when target_soc_percent is null', () => {
        renderCard(baseCharger({ target_soc_percent: null, ready_by: null }))
        expect(screen.getByText('Save Goal')).toBeInTheDocument()
        expect(screen.queryByText('Configure Goal')).not.toBeInTheDocument()
        // No phantom 80%/07:00 goal values should appear in a viewing state.
        expect(screen.queryByText(/On track/)).not.toBeInTheDocument()
    })
})

describe('EVChargingCard unreachable charger', () => {
    it('shows "Charger unreachable" instead of Plugged/Away', () => {
        renderCard(baseCharger({ unreachable: true }))
        expect(screen.getByText(/Charger unreachable/)).toBeInTheDocument()
        expect(screen.queryByText(/Plugged/)).not.toBeInTheDocument()
    })

    it('shows Plugged when reachable', () => {
        renderCard(baseCharger({ unreachable: false }))
        expect(screen.getByText(/Plugged/)).toBeInTheDocument()
        expect(screen.queryByText(/Charger unreachable/)).not.toBeInTheDocument()
    })
})

describe('EVChargingCard balancer badge (7.6)', () => {
    it('shows Throttling (not throttled) when the balancer reports throttling', () => {
        renderCard(baseCharger())
        render(
            <MemoryRouter>
                <EVChargingCard
                    charger={baseCharger()}
                    config={{}}
                    loadBalancing={baseLoadBalancing([baseEvStatus({ state: 'throttling' })])}
                    onRefresh={async () => {}}
                />
            </MemoryRouter>,
        )
        expect(screen.getAllByText(/THROTTLING BY LOAD BALANCER/i).length).toBeGreaterThan(0)
    })

    it('shows the stale_fallback fail-safe badge, never "ON TRACK"', () => {
        render(
            <MemoryRouter>
                <EVChargingCard
                    charger={baseCharger()}
                    config={{}}
                    loadBalancing={baseLoadBalancing([baseEvStatus({ state: 'stale_fallback' })])}
                    onRefresh={async () => {}}
                />
            </MemoryRouter>,
        )
        expect(screen.getByText(/LOAD BALANCER FAIL-SAFE/i)).toBeInTheDocument()
        expect(screen.queryByText(/^ON TRACK$/i)).not.toBeInTheDocument()
    })

    it('shows the paused badge distinctly', () => {
        render(
            <MemoryRouter>
                <EVChargingCard
                    charger={baseCharger()}
                    config={{}}
                    loadBalancing={baseLoadBalancing([baseEvStatus({ state: 'paused' })])}
                    onRefresh={async () => {}}
                />
            </MemoryRouter>,
        )
        expect(screen.getByText(/PAUSED BY LOAD BALANCER/i)).toBeInTheDocument()
    })
})

describe('EVChargingCard settings link (7.7)', () => {
    it('uses a React Router Link to the load-balancing tab, not a raw <a> to advanced', () => {
        renderCard(baseCharger({ type: 'current' }))
        const link = screen.getByRole('link', { name: /add this charger to Excess PV priority/i })
        expect(link).toHaveAttribute('href', '/settings?tab=load-balancing')
    })
})

describe('EVChargingCard at-risk goal (fix-ev-current-charger-control 5.3)', () => {
    it('shows AT RISK with the undelivered kWh, ready-by time and reason', () => {
        const deadline = new Date(2026, 8, 23, 18, 30).toISOString()
        renderCard(
            baseCharger({
                status: 'at_risk',
                deadline,
                shortfall_kwh: 0.6,
                shortfall_reason: 'grid_limit',
                max_import_kw: 8,
            }),
        )
        expect(screen.getByText('AT RISK')).toBeInTheDocument()
        expect(screen.queryByText('ON TRACK')).not.toBeInTheDocument()
        expect(screen.getByTestId('ev-shortfall')).toHaveTextContent(
            "0.6 kWh won't be delivered by 18:30 — grid limit (8 kW) leaves no room",
        )
    })

    it('explains a too-close ready-by and a cost trade-off', () => {
        const { unmount } = renderCard(
            baseCharger({ status: 'at_risk', shortfall_kwh: 1.2, shortfall_reason: 'deadline_too_close' }),
        )
        expect(screen.getByTestId('ev-shortfall')).toHaveTextContent('ready-by too close')
        unmount()
        renderCard(baseCharger({ status: 'at_risk', shortfall_kwh: 1.2, shortfall_reason: 'cost_tradeoff' }))
        expect(screen.getByTestId('ev-shortfall')).toHaveTextContent('cheaper to miss than to charge')
    })

    it('shows no shortfall line while on track', () => {
        renderCard(baseCharger())
        expect(screen.getByText('ON TRACK')).toBeInTheDocument()
        expect(screen.queryByTestId('ev-shortfall')).not.toBeInTheDocument()
    })
})

describe('EVChargingCard manual charge line', () => {
    it('shows "Manual charge → X%" with Stop when active', async () => {
        const onRefresh = vi.fn().mockResolvedValue(undefined)
        render(
            <MemoryRouter>
                <EVChargingCard
                    charger={baseCharger({
                        manual_charge: { target_soc: 80, current_a: null, started_at: '2026-09-24T10:00:00+02:00' },
                    })}
                    config={{}}
                    loadBalancing={null}
                    onRefresh={onRefresh}
                />
            </MemoryRouter>,
        )
        expect(screen.getByTestId('ev-manual-charge')).toHaveTextContent('Manual charge → 80%')

        fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
        await waitFor(() => expect(onRefresh).toHaveBeenCalled())
        expect(Api.ev.manualCharge.stop).toHaveBeenCalledWith('ev1')
    })

    it('shows no manual charge line when inactive', () => {
        renderCard(baseCharger({ manual_charge: null }))
        expect(screen.queryByTestId('ev-manual-charge')).not.toBeInTheDocument()
    })
})
