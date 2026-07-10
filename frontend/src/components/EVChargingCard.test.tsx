import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import EVChargingCard from './EVChargingCard'
import type { EVChargerState } from '../lib/api'

vi.mock('../lib/api', () => ({
    Api: {
        ev: {
            setSchedule: vi.fn(),
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

describe('EVChargingCard balancer badge (7.6)', () => {
    it('shows Throttling (not throttled) when the balancer reports throttling', () => {
        renderCard(baseCharger())
        render(
            <MemoryRouter>
                <EVChargingCard
                    charger={baseCharger()}
                    config={{}}
                    loadBalancing={{ ev: [{ charger_id: 'ev1', state: 'throttling' }] }}
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
                    loadBalancing={{ ev: [{ charger_id: 'ev1', state: 'stale_fallback' }] }}
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
                    loadBalancing={{ ev: [{ charger_id: 'ev1', state: 'paused' }] }}
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
