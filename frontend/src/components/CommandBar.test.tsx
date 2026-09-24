import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CommandBar from './CommandBar'
import { Api, type EVChargerState } from '../lib/api'

const toast = vi.fn()

vi.mock('../lib/api', () => ({
    Api: {
        executor: {
            quickAction: { set: vi.fn(), clear: vi.fn() },
            pause: vi.fn(),
            resume: vi.fn(),
            run: vi.fn(),
        },
        ev: { manualCharge: { start: vi.fn(), stop: vi.fn() } },
        waterBoost: { start: vi.fn(), startFor: vi.fn(), cancel: vi.fn() },
        runPlanner: vi.fn(),
        configSave: vi.fn(),
    },
}))

vi.mock('../lib/hooks', () => ({ useSocket: vi.fn() }))
vi.mock('../lib/useToast', () => ({ useToast: () => ({ toast }) }))

function charger(overrides: Partial<EVChargerState> = {}): EVChargerState {
    return {
        id: 'ev1',
        name: 'Tesla',
        plugged_in: true,
        soc_percent: 49,
        power_kw: 0,
        target_soc_percent: null,
        ready_by: null,
        repeat: null,
        ready_by_date: null,
        deadline: null,
        required_kwh: null,
        delivered_kwh: null,
        remaining_kwh: null,
        daily_quota_kwh: null,
        quota_schedule: null,
        keep_on_after_target: false,
        ha_ready_by_entity: null,
        ha_target_soc_entity: null,
        type: 'current',
        min_current_a: 6,
        max_current_a: 16,
        n_days: null,
        status: 'idle',
        source: null,
        externally_controlled: false,
        last_updated: null,
        last_planned_at: null,
        manual_charge: null,
        ...overrides,
    }
}

function renderBar(props: Partial<React.ComponentProps<typeof CommandBar>> = {}) {
    const onRefresh = vi.fn()
    const onEvRefresh = vi.fn()
    render(
        <CommandBar
            riskAppetite={3}
            comfortLevel={3}
            executorStatus={null}
            automationConfig={null}
            automationSaving={false}
            schedulerStatus={null}
            vacationMode={false}
            vacationModeHA={false}
            waterBoostActive={null}
            waterHeaters={[]}
            soc={40}
            batteryMinSoc={12}
            evChargers={[]}
            onEvRefresh={onEvRefresh}
            plannerMeta={null}
            onSetRiskAppetite={vi.fn()}
            onSetComfortLevel={vi.fn()}
            onToggleScheduler={vi.fn()}
            onRefresh={onRefresh}
            {...props}
        />,
    )
    return { onRefresh, onEvRefresh }
}

beforeEach(() => {
    vi.clearAllMocks()
})

describe('CommandBar Top Up', () => {
    it('uses the SoC stepper and sends the chosen target', async () => {
        vi.mocked(Api.executor.quickAction.set).mockResolvedValue({ status: 'success' })
        renderBar()
        fireEvent.click(screen.getByLabelText('Increase Top Up target'))
        fireEvent.click(screen.getByRole('button', { name: 'Top Up' }))

        await waitFor(() =>
            expect(Api.executor.quickAction.set).toHaveBeenCalledWith('force_charge', 60, { target_soc: 65 }),
        )
    })

    it('clamps the target to the configured min SoC', () => {
        renderBar({ batteryMinSoc: 12 })
        const decrease = screen.getByLabelText('Decrease Top Up target')
        for (let i = 0; i < 5; i++) fireEvent.click(decrease)
        expect(screen.getByRole('button', { name: /Top Up target: 12%/ })).toBeInTheDocument()
    })

    it('shows the API rejection message in the toast', async () => {
        vi.mocked(Api.executor.quickAction.set).mockRejectedValue(new Error('Target already reached'))
        renderBar()
        fireEvent.click(screen.getByRole('button', { name: 'Top Up' }))
        await waitFor(() => expect(toast).toHaveBeenCalledWith({ message: 'Target already reached', variant: 'error' }))
    })

    it('hides the stepper and shows STOP when active', () => {
        renderBar({
            executorStatus: {
                quick_action: { type: 'force_charge', expires_at: '', remaining_minutes: 1, reason: '', params: {} },
            } as never,
        })
        expect(screen.queryByLabelText('Increase Top Up target')).not.toBeInTheDocument()
        expect(screen.getAllByText('STOP').length).toBeGreaterThan(0)
    })
})

describe('CommandBar EV Charge', () => {
    it('is hidden when no controllable charger is plugged in', () => {
        renderBar({
            evChargers: [charger({ plugged_in: false }), charger({ id: 'ext', externally_controlled: true })],
        })
        expect(screen.queryByRole('button', { name: /EV Charge/ })).not.toBeInTheDocument()
    })

    it('single plugged charger: no selector, starts with the default target', async () => {
        vi.mocked(Api.ev.manualCharge.start).mockResolvedValue({ success: true } as never)
        const { onEvRefresh } = renderBar({ evChargers: [charger()] })

        expect(screen.queryByLabelText('EV charger')).not.toBeInTheDocument()
        fireEvent.click(screen.getByRole('button', { name: /EV Charge/ }))

        await waitFor(() => expect(Api.ev.manualCharge.start).toHaveBeenCalledWith('ev1', { target_soc: 80 }))
        expect(onEvRefresh).toHaveBeenCalled()
    })

    it('multiple plugged chargers: selector picks the charger', async () => {
        vi.mocked(Api.ev.manualCharge.start).mockResolvedValue({ success: true } as never)
        renderBar({ evChargers: [charger(), charger({ id: 'ev2', name: 'Leaf', type: 'binary' })] })

        fireEvent.change(screen.getByLabelText('EV charger'), { target: { value: 'ev2' } })
        fireEvent.click(screen.getByRole('button', { name: /EV Charge/ }))

        await waitFor(() => expect(Api.ev.manualCharge.start).toHaveBeenCalledWith('ev2', { target_soc: 80 }))
    })

    it('current-type charger offers amps behind a collapsed toggle', async () => {
        vi.mocked(Api.ev.manualCharge.start).mockResolvedValue({ success: true } as never)
        renderBar({ evChargers: [charger()] })

        expect(screen.queryByLabelText('Charging current in amps')).not.toBeInTheDocument()
        fireEvent.click(screen.getByLabelText('Charging current'))
        const amps = screen.getByLabelText('Charging current in amps') as HTMLSelectElement
        expect(amps.value).toBe('16')
        fireEvent.change(amps, { target: { value: '10' } })
        fireEvent.click(screen.getByRole('button', { name: /EV Charge/ }))

        await waitFor(() =>
            expect(Api.ev.manualCharge.start).toHaveBeenCalledWith('ev1', { target_soc: 80, current_a: 10 }),
        )
    })

    it('binary charger has no current option', () => {
        renderBar({ evChargers: [charger({ type: 'binary', min_current_a: null, max_current_a: null })] })
        expect(screen.queryByLabelText('Charging current')).not.toBeInTheDocument()
    })

    it('active manual charge shows STOP and stops it', async () => {
        vi.mocked(Api.ev.manualCharge.stop).mockResolvedValue({ success: true, was_active: true })
        renderBar({
            evChargers: [
                charger({ manual_charge: { target_soc: 80, current_a: null, started_at: '2026-09-24T10:00:00Z' } }),
            ],
        })
        expect(screen.queryByLabelText('Increase EV charge target')).not.toBeInTheDocument()
        fireEvent.click(screen.getByRole('button', { name: /STOP.*80%/ }))
        await waitFor(() => expect(Api.ev.manualCharge.stop).toHaveBeenCalledWith('ev1'))
    })
})
