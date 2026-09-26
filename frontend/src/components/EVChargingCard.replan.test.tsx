import { act, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import EVChargingCard from './EVChargingCard'
import type { EVChargerState } from '../lib/api'

const socketHandlers: Record<string, (data: unknown) => void> = {}

vi.mock('../lib/hooks', () => ({
    useSocket: (event: string, cb: (data: unknown) => void) => {
        socketHandlers[event] = cb
    },
}))

vi.mock('../lib/api', () => ({
    Api: { ev: { setSchedule: vi.fn(), manualCharge: { stop: vi.fn() } } },
}))

vi.mock('../lib/useToast', () => ({
    useToast: () => ({ toast: vi.fn() }),
}))

function charger(overrides: Partial<EVChargerState> = {}): EVChargerState {
    return {
        id: 'ev1',
        name: 'Tesla',
        plugged_in: true,
        soc_percent: 50,
        power_kw: 0,
        target_soc_percent: 90,
        ready_by: '07:00',
        repeat: 'daily',
        ready_by_date: null,
        deadline: null,
        required_kwh: 10,
        delivered_kwh: 2,
        remaining_kwh: 8,
        planned_by_day: [{ date: '2026-09-26', kwh: 8, basis: 'known' }],
        keep_on_after_target: false,
        ha_ready_by_entity: null,
        ha_target_soc_entity: null,
        type: 'current',
        n_days: null,
        status: 'on_track',
        source: 'api',
        externally_controlled: false,
        last_updated: '2026-09-25T20:00:00+00:00',
        last_planned_at: '2026-09-25T19:00:00+00:00',
        plan_pending: false,
        assumed_plugged: false,
        planned_start: null,
        ...overrides,
    }
}

function renderCard(c: EVChargerState) {
    return render(
        <MemoryRouter>
            <EVChargingCard charger={c} config={{}} loadBalancing={null} onRefresh={async () => {}} />
        </MemoryRouter>,
    )
}

function rerenderCard(rerender: (ui: React.ReactElement) => void, c: EVChargerState) {
    rerender(
        <MemoryRouter>
            <EVChargingCard charger={c} config={{}} loadBalancing={null} onRefresh={async () => {}} />
        </MemoryRouter>,
    )
}

beforeEach(() => {
    for (const key of Object.keys(socketHandlers)) delete socketHandlers[key]
})

describe('EVChargingCard re-planning feedback', () => {
    it('shows Re-planning and hides previous-plan numbers while pending', () => {
        renderCard(charger({ plan_pending: true }))
        expect(screen.getByTestId('ev-replanning')).toHaveTextContent('RE-PLANNING…')
        expect(screen.queryByText('ON TRACK')).not.toBeInTheDocument()
        expect(screen.queryByText('Remaining Need')).not.toBeInTheDocument()
        expect(screen.queryByText('Planned per day')).not.toBeInTheDocument()
        expect(screen.queryByTestId('ev-plan-values')).not.toBeInTheDocument()
        // Goal values stay visible.
        expect(screen.getByText('07:00')).toBeInTheDocument()
    })

    it('shows the new plan once pending clears', () => {
        const { rerender } = renderCard(charger({ plan_pending: true }))
        rerenderCard(rerender, charger({ plan_pending: false, last_planned_at: '2026-09-25T20:00:05+00:00' }))
        expect(screen.queryByTestId('ev-replanning')).not.toBeInTheDocument()
        expect(screen.getByText('ON TRACK')).toBeInTheDocument()
        expect(screen.getByText('Remaining Need')).toBeInTheDocument()
    })

    it('shows re-plan failed with stale values after a planner_error', () => {
        const pending = charger({ plan_pending: true })
        const { rerender } = renderCard(pending)
        act(() => socketHandlers['planner_error']?.({ error: 'boom' }))
        rerenderCard(rerender, { ...pending, plan_pending: false })

        expect(screen.getByTestId('ev-replan-failed')).toHaveTextContent('Re-plan failed — showing last plan')
        expect(screen.getByTestId('ev-plan-values').className).toContain('opacity-60')
        expect(screen.queryByTestId('ev-replanning')).not.toBeInTheDocument()
    })

    it('ignores planner_error when nothing was pending', () => {
        renderCard(charger())
        act(() => socketHandlers['planner_error']?.({ error: 'boom' }))
        expect(screen.queryByTestId('ev-replan-failed')).not.toBeInTheDocument()
    })

    it('clears the failure once the goal is edited again', () => {
        const pending = charger({ plan_pending: true })
        const { rerender } = renderCard(pending)
        act(() => socketHandlers['planner_error']?.({ error: 'boom' }))
        rerenderCard(rerender, { ...pending, plan_pending: false, last_updated: '2026-09-25T20:10:00+00:00' })
        expect(screen.queryByTestId('ev-replan-failed')).not.toBeInTheDocument()
    })
})

describe('EVChargingCard awaiting plug-in', () => {
    it('shows the planned start and a plug-in hint when assumed plugged', () => {
        const start = new Date(2026, 8, 25, 22, 0).toISOString()
        renderCard(charger({ plugged_in: false, status: 'idle', assumed_plugged: true, planned_start: start }))
        expect(screen.getByTestId('ev-awaiting-plug-in')).toHaveTextContent('Planned from 22:00 — plug in the car')
    })

    it('shows no hint when not assumed plugged', () => {
        renderCard(charger({ plugged_in: false, status: 'idle' }))
        expect(screen.queryByTestId('ev-awaiting-plug-in')).not.toBeInTheDocument()
    })
})
