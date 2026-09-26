import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CommandBar from './CommandBar'
import { Api, type EVChargerState } from '../lib/api'
import { useSocket } from '../lib/hooks'

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
        planned_by_day: [],
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
            onRefresh={onRefresh}
            {...props}
        />,
    )
    return { onRefresh, onEvRefresh }
}

beforeEach(() => {
    vi.clearAllMocks()
})

const openTopUp = () => fireEvent.click(screen.getByRole('button', { name: /^Top Up/ }))
const openEv = () => fireEvent.click(screen.getByRole('button', { name: /^EV/ }))

describe('CommandBar Top Up', () => {
    it('opens a popover and sends the chosen target', async () => {
        vi.mocked(Api.executor.quickAction.set).mockResolvedValue({ status: 'success' })
        renderBar()
        openTopUp()
        expect(screen.getByRole('dialog', { name: 'Battery Top Up' })).toBeInTheDocument()
        fireEvent.click(screen.getByRole('radio', { name: '80%' }))
        fireEvent.click(screen.getByRole('button', { name: 'Start Top Up to 80%' }))

        await waitFor(() =>
            expect(Api.executor.quickAction.set).toHaveBeenCalledWith('force_charge', 60, { target_soc: 80 }),
        )
        await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    })

    it('defaults to 60% and the stepper sets a custom target', async () => {
        vi.mocked(Api.executor.quickAction.set).mockResolvedValue({ status: 'success' })
        renderBar()
        expect(screen.getByRole('button', { name: /^Top Up 60%/ })).toBeInTheDocument()
        openTopUp()
        fireEvent.click(screen.getByLabelText('Increase Top Up target'))
        fireEvent.click(screen.getByRole('button', { name: 'Start Top Up to 75%' }))
        await waitFor(() =>
            expect(Api.executor.quickAction.set).toHaveBeenCalledWith('force_charge', 60, { target_soc: 75 }),
        )
    })

    it('clamps the target to the configured min SoC and hides lower presets', () => {
        renderBar({ batteryMinSoc: 50 })
        openTopUp()
        expect(screen.queryByRole('radio', { name: '40%' })).not.toBeInTheDocument()
        const decrease = screen.getByLabelText('Decrease Top Up target')
        for (let i = 0; i < 5; i++) fireEvent.click(decrease)
        expect(screen.getByRole('button', { name: /Top Up target: 50%/ })).toBeInTheDocument()
    })

    it('shows the API rejection message in the toast', async () => {
        vi.mocked(Api.executor.quickAction.set).mockRejectedValue(new Error('Target already reached'))
        renderBar()
        openTopUp()
        fireEvent.click(screen.getByRole('button', { name: /Start Top Up/ }))
        await waitFor(() => expect(toast).toHaveBeenCalledWith({ message: 'Target already reached', variant: 'error' }))
    })

    it('when active shows the target and offers Stop', async () => {
        vi.mocked(Api.executor.quickAction.clear).mockResolvedValue({})
        renderBar({
            executorStatus: {
                quick_action: {
                    type: 'force_charge',
                    expires_at: '',
                    remaining_minutes: 1,
                    reason: '',
                    params: { target_soc: 70 },
                },
            } as never,
        })
        expect(screen.getByRole('button', { name: /^Top Up → 70%/ })).toBeInTheDocument()
        openTopUp()
        expect(screen.queryByLabelText('Increase Top Up target')).not.toBeInTheDocument()
        fireEvent.click(screen.getByRole('button', { name: 'Stop Top Up' }))
        await waitFor(() => expect(Api.executor.quickAction.clear).toHaveBeenCalled())
    })

    it('closes on Escape', () => {
        renderBar()
        openTopUp()
        fireEvent.keyDown(document, { key: 'Escape' })
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
})

describe('CommandBar EV Charge', () => {
    it('is hidden when no controllable charger is plugged in', () => {
        renderBar({
            evChargers: [charger({ plugged_in: false }), charger({ id: 'ext', externally_controlled: true })],
        })
        expect(screen.queryByRole('button', { name: /^EV/ })).not.toBeInTheDocument()
    })

    it('single plugged charger: no selector, starts with the default target at charger max', async () => {
        vi.mocked(Api.ev.manualCharge.start).mockResolvedValue({ success: true } as never)
        const { onEvRefresh } = renderBar({ evChargers: [charger()] })

        openEv()
        expect(screen.queryByLabelText('EV charger')).not.toBeInTheDocument()
        fireEvent.click(screen.getByRole('button', { name: 'Start charging to 60%' }))

        await waitFor(() => expect(Api.ev.manualCharge.start).toHaveBeenCalledWith('ev1', { target_soc: 60 }))
        expect(onEvRefresh).toHaveBeenCalled()
    })

    it('multiple plugged chargers: selector picks the charger', async () => {
        vi.mocked(Api.ev.manualCharge.start).mockResolvedValue({ success: true } as never)
        renderBar({ evChargers: [charger(), charger({ id: 'ev2', name: 'Leaf', type: 'binary' })] })

        openEv()
        fireEvent.change(screen.getByLabelText('EV charger'), { target: { value: 'ev2' } })
        fireEvent.click(screen.getByRole('radio', { name: '80%' }))
        fireEvent.click(screen.getByRole('button', { name: 'Start charging to 80%' }))

        await waitFor(() => expect(Api.ev.manualCharge.start).toHaveBeenCalledWith('ev2', { target_soc: 80 }))
    })

    it('current-type charger offers charging current in the popover', async () => {
        vi.mocked(Api.ev.manualCharge.start).mockResolvedValue({ success: true } as never)
        renderBar({ evChargers: [charger()] })

        openEv()
        const amps = screen.getByLabelText('Charging current in amps') as HTMLSelectElement
        expect(amps.value).toBe('')
        fireEvent.change(amps, { target: { value: '10' } })
        fireEvent.click(screen.getByRole('button', { name: /Start charging/ }))

        await waitFor(() =>
            expect(Api.ev.manualCharge.start).toHaveBeenCalledWith('ev1', { target_soc: 60, current_a: 10 }),
        )
    })

    it('binary charger has no current option', () => {
        renderBar({ evChargers: [charger({ type: 'binary', min_current_a: null, max_current_a: null })] })
        openEv()
        expect(screen.queryByLabelText('Charging current in amps')).not.toBeInTheDocument()
    })

    it('active manual charge shows the target and stops it', async () => {
        vi.mocked(Api.ev.manualCharge.stop).mockResolvedValue({ success: true, was_active: true })
        renderBar({
            evChargers: [
                charger({ manual_charge: { target_soc: 80, current_a: null, started_at: '2026-09-24T10:00:00Z' } }),
            ],
        })
        expect(screen.getByRole('button', { name: /^EV → 80%/ })).toBeInTheDocument()
        openEv()
        expect(screen.queryByLabelText('Increase EV charge target')).not.toBeInTheDocument()
        fireEvent.click(screen.getByRole('button', { name: 'Stop EV Charge' }))
        await waitFor(() => expect(Api.ev.manualCharge.stop).toHaveBeenCalledWith('ev1'))
    })
})

describe('CommandBar Boost and Vacation', () => {
    it('boost defaults to 1h', async () => {
        vi.mocked(Api.waterBoost.start).mockResolvedValue({} as never)
        renderBar()
        fireEvent.click(screen.getByRole('button', { name: /^Boost 1h/ }))
        fireEvent.click(screen.getByRole('button', { name: 'Start Boost for 1h' }))
        await waitFor(() => expect(Api.waterBoost.start).toHaveBeenCalledWith(60))
    })

    it('vacation defaults to 3 days', () => {
        renderBar()
        fireEvent.click(screen.getByRole('button', { name: /^Vacay 3d/ }))
        expect(screen.getByRole('button', { name: 'Start Vacation (3 days)' })).toBeInTheDocument()
    })
})

describe('CommandBar planner feedback', () => {
    function handlers() {
        const map: Record<string, (data: unknown) => void> = {}
        for (const [event, cb] of vi.mocked(useSocket).mock.calls) map[event as string] = cb as (d: unknown) => void
        return map
    }

    it('server-started run spins the planner button via planner_progress', () => {
        renderBar()
        act(() => handlers()['planner_progress']({ phase: 'running_solver', elapsed_ms: 100 }))
        const button = screen.getByTitle('Run Planner')
        expect(button).toBeDisabled()
        expect(button.getAttribute('data-planner-phase')).toBe('running_solver')
    })

    it('planner_error shows the failed state and an error toast', () => {
        renderBar()
        act(() => handlers()['planner_error']({ error: 'Nordpool unavailable', duration_ms: 50 }))
        const button = screen.getByTitle('Planner failed')
        expect(button.getAttribute('data-planner-phase')).toBe('failed')
        expect(toast).toHaveBeenCalledWith({ message: 'Planner failed: Nordpool unavailable', variant: 'error' })
    })
})

describe('CommandBar level popovers', () => {
    it('risk popover applies the tapped level and closes', () => {
        const onSetRiskAppetite = vi.fn()
        renderBar({ onSetRiskAppetite })
        fireEvent.click(screen.getByRole('button', { name: /^Risk 3 · Neutral/ }))
        fireEvent.click(screen.getByRole('radio', { name: /Aggressive/ }))
        expect(onSetRiskAppetite).toHaveBeenCalledWith(4)
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })

    it('water popover applies the tapped level', () => {
        const onSetComfortLevel = vi.fn()
        renderBar({ onSetComfortLevel })
        fireEvent.click(screen.getByRole('button', { name: /^Water 3 · Neutral/ }))
        fireEvent.click(screen.getByRole('radio', { name: /Economy/ }))
        expect(onSetComfortLevel).toHaveBeenCalledWith(1)
    })

    it('vacation accepts a custom number of days', async () => {
        vi.mocked(Api.configSave).mockResolvedValue({} as never)
        renderBar()
        fireEvent.click(screen.getByRole('button', { name: /^Vacay/ }))
        fireEvent.click(screen.getByRole('button', { name: /Vacation length: 3d, tap to type/ }))
        const input = screen.getByRole('spinbutton', { name: 'Vacation length' })
        fireEvent.change(input, { target: { value: '10' } })
        fireEvent.keyDown(input, { key: 'Enter' })
        fireEvent.click(screen.getByRole('button', { name: 'Start Vacation (10 days)' }))
        await waitFor(() => expect(Api.configSave).toHaveBeenCalled())
    })
})

describe('CommandBar plan status', () => {
    const minutesAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString()

    it('shows the planned time with a check icon and no emoji', () => {
        renderBar({
            plannerMeta: { planned_at: minutesAgo(5) },
            automationConfig: { enable_scheduler: true, every_minutes: 15 },
        })
        const status = screen.getByTestId('plan-status')
        expect(status).toHaveTextContent(/^Last\s*\d/)
        expect(status).not.toHaveTextContent('✅')
        expect(status).not.toHaveAttribute('data-stale')
    })

    it('marks the plan outdated after three missed scheduler runs', () => {
        renderBar({
            plannerMeta: { planned_at: minutesAgo(50) },
            automationConfig: { enable_scheduler: true, every_minutes: 15 },
        })
        const status = screen.getByTestId('plan-status')
        expect(status).toHaveAttribute('data-stale', 'true')
        expect(status).toHaveTextContent('outdated')
    })

    it('tells the user when auto planning is off', () => {
        renderBar({
            plannerMeta: { planned_at: minutesAgo(5) },
            automationConfig: { enable_scheduler: false, every_minutes: 15 },
        })
        expect(screen.getByTestId('plan-status')).toHaveTextContent('Auto off')
    })

    it('shows "No plan yet" without planner metadata', () => {
        renderBar()
        expect(screen.getByTestId('plan-status')).toHaveTextContent('No plan yet')
    })
})

describe('CommandBar custom boost length', () => {
    it('typed minutes are rounded to 15-minute steps and sent', async () => {
        vi.mocked(Api.waterBoost.start).mockResolvedValue({} as never)
        renderBar()
        fireEvent.click(screen.getByRole('button', { name: /^Boost/ }))
        fireEvent.click(screen.getByRole('button', { name: /Boost duration: 60m, tap to type/ }))
        const input = screen.getByRole('spinbutton', { name: 'Boost duration' })
        fireEvent.change(input, { target: { value: '100' } })
        fireEvent.keyDown(input, { key: 'Enter' })
        fireEvent.click(screen.getByRole('button', { name: 'Start Boost for 1h 45m' }))
        await waitFor(() => expect(Api.waterBoost.start).toHaveBeenCalledWith(105))
    })

    it('stepper moves in 15-minute steps', () => {
        renderBar()
        fireEvent.click(screen.getByRole('button', { name: /^Boost/ }))
        fireEvent.click(screen.getByLabelText('Increase Boost duration'))
        expect(screen.getByRole('button', { name: 'Start Boost for 1h 15m' })).toBeInTheDocument()
    })
})
