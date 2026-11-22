/* learned-battery-inverter-parameters 10.2: learned parameters on the Battery settings tab */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { LearnedParametersSection } from '../components/LearnedParametersSection'
import type { LearnedParameter, LearnedParametersResponse } from '../../../lib/types'

const list = vi.fn()
const history = vi.fn()
const lock = vi.fn()
const unlock = vi.fn()

vi.mock('../../../lib/api', () => ({
    Api: {
        learnedParameters: {
            list: (...args: unknown[]) => list(...args),
            history: (...args: unknown[]) => history(...args),
            lock: (...args: unknown[]) => lock(...args),
            unlock: (...args: unknown[]) => unlock(...args),
        },
    },
}))

function parameter(overrides: Partial<LearnedParameter>): LearnedParameter {
    return {
        key: 'battery_round_trip_efficiency',
        label: 'Battery round-trip efficiency',
        unit: 'fraction',
        learnable: true,
        effective_value: null,
        source: 'config',
        learned_value: null,
        applied_value: null,
        confidence: null,
        evidence: {},
        status_note: null,
        estimated_at: null,
        expires_at: null,
        applied_at: null,
        bounds: { min: 0.8, max: 0.995 },
        config_fallback: null,
        locked: false,
        locked_value: null,
        ...overrides,
    }
}

function response(parameters: LearnedParameter[], basis: 'learned' | 'config' = 'config'): LearnedParametersResponse {
    return {
        parameters,
        effective: {
            charge_efficiency: 0.907,
            discharge_efficiency: 0.951,
            basis,
            missing: basis === 'config' ? ['inverter_charge_loss'] : [],
            config_charge_efficiency: 0.92,
            config_discharge_efficiency: 0.95,
        },
    }
}

async function renderWith(parameters: LearnedParameter[], basis: 'learned' | 'config' = 'config') {
    list.mockResolvedValue(response(parameters, basis))
    render(<LearnedParametersSection />)
    await screen.findByTestId('effective-basis')
}

beforeEach(() => {
    vi.clearAllMocks()
    history.mockResolvedValue({ history: [] })
})

describe('source badges', () => {
    it.each([
        ['learned', 'learned', 'badge-good'],
        ['locked', 'locked', 'badge-accent'],
        ['default', 'default', 'badge-muted'],
        ['config', 'config', 'badge-muted'],
        ['expired', 'expired', 'badge-warn'],
    ] as const)('shows the %s badge', async (source, text, className) => {
        await renderWith([parameter({ source, effective_value: source === 'learned' ? 0.962 : null })])
        const badge = screen.getByTestId('source-badge')
        expect(badge).toHaveTextContent(text)
        expect(badge.className).toContain(className)
    })
})

describe('learned value row', () => {
    it('shows value, confidence, evidence and last change', async () => {
        await renderWith(
            [
                parameter({
                    source: 'learned',
                    effective_value: 0.962,
                    learned_value: 0.962,
                    confidence: 0.97,
                    evidence: { days: 35, runs: 5 },
                    applied_at: '2026-11-20T00:40:00+01:00',
                    estimated_at: '2026-11-20T00:40:00+01:00',
                }),
            ],
            'learned',
        )
        expect(screen.getByTestId('effective-value')).toHaveTextContent('96.2 %')
        expect(screen.getByTestId('learned-value')).toHaveTextContent('Learned 96.2 % (confidence 97 %)')
        expect(screen.getByTestId('evidence')).toHaveTextContent('35 days of data, 5 continuous runs')
        expect(screen.getByTestId('status-text')).toHaveTextContent('Last changed')
        expect(screen.getByTestId('effective-basis')).toHaveTextContent('charge 90.7 %, discharge 95.1 %')
    })

    it('says the configured value is used when expired', async () => {
        await renderWith([
            parameter({
                source: 'expired',
                learned_value: 0.962,
                confidence: 0.9,
                estimated_at: '2026-09-01T00:00:00Z',
            }),
        ])
        expect(screen.getByTestId('status-text')).toHaveTextContent('The configured efficiencies are used')
        expect(screen.getByTestId('effective-value')).toHaveTextContent('–')
        expect(screen.getByTestId('effective-value')).not.toHaveTextContent('configured value')
        expect(screen.getByTestId('value-caption')).toHaveTextContent('configured efficiencies in use')
    })

    it('shows the empty fallback state with the reason', async () => {
        await renderWith([parameter({ status_note: '12 usable days, 28 needed (SoC-neutral windows)' })])
        expect(screen.getByTestId('status-text')).toHaveTextContent('Nothing learned yet: 12 usable days, 28 needed')
        expect(screen.queryByTestId('learned-value')).not.toBeInTheDocument()
        expect(screen.getByTestId('effective-basis')).toHaveTextContent('configured values')
        expect(screen.getByTestId('effective-basis')).toHaveTextContent('Still missing: inverter charge loss.')
        expect(screen.getByTestId('effective-value')).toHaveTextContent('–')
    })

    it('shows standby as not measured yet and the default discharge efficiency', async () => {
        await renderWith([
            parameter({
                key: 'inverter_standby_w',
                label: 'Inverter standby power',
                unit: 'W',
                bounds: { min: 0, max: 300 },
            }),
            parameter({
                key: 'inverter_discharge_efficiency',
                label: 'Inverter discharge efficiency',
                learnable: false,
                source: 'default',
                effective_value: 0.97,
                bounds: { min: 0.85, max: 1 },
            }),
        ])
        const standby = screen.getByTestId('learned-inverter_standby_w')
        const discharge = screen.getByTestId('learned-inverter_discharge_efficiency')
        expect(within(standby).getByTestId('effective-value')).toHaveTextContent('–')
        expect(within(standby).getByTestId('value-caption')).toHaveTextContent('not measured yet')
        expect(within(standby).getByTestId('status-text')).toHaveTextContent(
            'Not measured yet. Shown for information; the planner does not use standby.',
        )
        expect(within(standby).getByTestId('status-text')).not.toHaveTextContent('configured value is used')
        expect(within(discharge).queryByTestId('value-caption')).not.toBeInTheDocument()
        expect(within(discharge).getByTestId('effective-value')).toHaveTextContent('97.0 %')
    })
})

describe('missing components', () => {
    it('names every missing component like its card title', async () => {
        const parameters = [
            parameter({}),
            parameter({ key: 'inverter_charge_loss', label: 'Inverter charge loss', bounds: { min: 0, max: 0.15 } }),
        ]
        const base = response(parameters)
        list.mockResolvedValue({
            ...base,
            effective: { ...base.effective, missing: ['battery_round_trip_efficiency', 'inverter_charge_loss'] },
        })
        render(<LearnedParametersSection />)
        expect(await screen.findByTestId('effective-basis')).toHaveTextContent(
            'Still missing: Battery round-trip efficiency, Inverter charge loss.',
        )
    })
})

describe('lock control', () => {
    it('locks to the entered percentage as a fraction', async () => {
        lock.mockResolvedValue(parameter({}))
        await renderWith([
            parameter({
                key: 'inverter_discharge_efficiency',
                label: 'Inverter discharge efficiency',
                bounds: { min: 0.85, max: 1 },
            }),
        ])
        const row = screen.getByTestId('learned-inverter_discharge_efficiency')
        fireEvent.change(within(row).getByRole('textbox'), { target: { value: '95' } })
        fireEvent.click(within(row).getByRole('button', { name: 'Lock' }))
        await waitFor(() => expect(lock).toHaveBeenCalledWith('inverter_discharge_efficiency', 0.95))
        await waitFor(() => expect(list).toHaveBeenCalledTimes(2)) // reloaded
    })

    it('rejects an out-of-range value without calling the API', async () => {
        await renderWith([parameter({})])
        fireEvent.change(screen.getByRole('textbox'), { target: { value: '50' } })
        fireEvent.click(screen.getByRole('button', { name: 'Lock' }))
        expect(await screen.findByRole('alert')).toHaveTextContent('between 80 and 99.5 %')
        expect(lock).not.toHaveBeenCalled()
    })

    it('rejects text that is not a number', async () => {
        await renderWith([parameter({})])
        fireEvent.change(screen.getByRole('textbox'), { target: { value: 'abc' } })
        fireEvent.click(screen.getByRole('button', { name: 'Lock' }))
        expect(await screen.findByRole('alert')).toHaveTextContent('Enter a number')
        expect(lock).not.toHaveBeenCalled()
    })

    it('unlocks a locked parameter', async () => {
        unlock.mockResolvedValue(parameter({}))
        await renderWith([parameter({ source: 'locked', locked: true, locked_value: 0.95, effective_value: 0.95 })])
        expect(screen.getByTestId('effective-value')).toHaveTextContent('95.0 %')
        fireEvent.click(screen.getByRole('button', { name: 'Unlock' }))
        await waitFor(() => expect(unlock).toHaveBeenCalledWith('battery_round_trip_efficiency'))
    })

    it('shows the server validation message', async () => {
        lock.mockRejectedValue(new Error('value must be between 0.8 and 0.995'))
        await renderWith([parameter({})])
        fireEvent.change(screen.getByRole('textbox'), { target: { value: '90' } })
        fireEvent.click(screen.getByRole('button', { name: 'Lock' }))
        expect(await screen.findByRole('alert')).toHaveTextContent('value must be between')
    })
})

describe('history', () => {
    it('is collapsed and loads when opened', async () => {
        history.mockResolvedValue({
            history: [
                {
                    id: 1,
                    key: 'battery_round_trip_efficiency',
                    at: '2026-11-20T00:40:00+01:00',
                    event: 'learned',
                    old_value: 0.96,
                    new_value: 0.962,
                    confidence: 0.9,
                    evidence: {},
                    notify_state: 'sent',
                },
            ],
        })
        await renderWith([parameter({})])
        expect(history).not.toHaveBeenCalled()
        const details = screen.getByTestId('learned-history') as HTMLDetailsElement
        details.open = true
        fireEvent(details, new Event('toggle'))
        expect(await screen.findByText(/updated: 96.0 % → 96.2 %/)).toBeInTheDocument()
    })
})

it('shows a load error instead of rows', async () => {
    list.mockRejectedValue(new Error('boom'))
    render(<LearnedParametersSection />)
    expect(await screen.findByText(/Could not load learned parameters: boom/)).toBeInTheDocument()
})
