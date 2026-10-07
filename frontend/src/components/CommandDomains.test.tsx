import { act, fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { GridDomain, ResourcesDomain } from './CommandDomains'
import { Api } from '../lib/api'

vi.mock('../lib/api', () => ({
    Api: {
        energyRange: vi.fn(),
        energyCostSeries: vi.fn().mockResolvedValue({ period: 'today', bucket: 'hour', points: [] }),
        ev: {
            chargers: vi.fn(),
        },
        executor: {
            loadBalancerStatus: vi.fn(),
        },
    },
}))

vi.mock('../lib/hooks', () => ({
    useSocket: vi.fn(),
}))

const baseProps = {
    pvActual: 1,
    pvForecast: 2,
    loadActual: 1,
    loadAvg: 2,
    waterKwh: 0,
}

// jsdom's localStorage is unavailable under this Node version's built-in
// (disabled without a flag) global localStorage shadowing it — stub a
// simple in-memory implementation instead of relying on the real one.
function makeMemoryStorage(): Storage {
    const store = new Map<string, string>()
    return {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => void store.set(key, value),
        removeItem: (key: string) => void store.delete(key),
        clear: () => store.clear(),
        key: (index: number) => Array.from(store.keys())[index] ?? null,
        get length() {
            return store.size
        },
    } as Storage
}

beforeEach(() => {
    vi.stubGlobal('localStorage', makeMemoryStorage())
    vi.mocked(Api.ev.chargers).mockResolvedValue([])
    vi.mocked(Api.executor.loadBalancerStatus).mockResolvedValue({
        enabled: false,
        state: 'disabled',
        reason: '',
        main_fuse_a: null,
        phase_current_a: {},
        phase_headroom_a: {},
        ev: [],
        shed: [],
    } as never)
})

describe('ResourcesDomain EV-tab lockout (7.1)', () => {
    it('shows Metrics even when localStorage persisted "ev" and there is no EV charger', () => {
        localStorage.setItem('darkstar-resources-tab', 'ev')

        render(<ResourcesDomain {...baseProps} hasEvCharger={false} />)

        // Metrics content (House Load) is visible; the EV toggle/tab content is not.
        expect(screen.getByText('House Load')).toBeInTheDocument()
        expect(screen.queryByText(/Loading chargers/)).not.toBeInTheDocument()
    })

    it('respects the persisted "ev" tab when a charger is configured', async () => {
        localStorage.setItem('darkstar-resources-tab', 'ev')
        vi.mocked(Api.ev.chargers).mockResolvedValue([])

        render(<ResourcesDomain {...baseProps} hasEvCharger={true} />)

        expect(await screen.findByText(/No EV chargers enabled or configured/)).toBeInTheDocument()
    })
})

function rangeResponse(overrides: Record<string, unknown> = {}) {
    return {
        period: 'today',
        start_date: '2026-09-26',
        end_date: '2026-09-26',
        grid_import_kwh: 20,
        grid_export_kwh: 5,
        battery_charge_kwh: 0,
        battery_discharge_kwh: 0,
        water_heating_kwh: 0,
        pv_production_kwh: 10,
        load_consumption_kwh: 25,
        ev_charging_kwh: 12,
        ev_grid_kwh: 7.2,
        ev_solar_kwh: 4.8,
        ev_cost_sek: 18.4,
        ev_solar_share: 0.4,
        import_cost_sek: 40,
        export_revenue_sek: 3,
        grid_charge_cost_sek: 0,
        self_consumption_savings_sek: 0,
        net_cost_sek: 37,
        battery_wear_cost_sek: 0,
        net_cost_incl_wear_sek: 37,
        slot_count: 96,
        ...overrides,
    } as never
}

describe('GridDomain EV sub-row under Grid Import', () => {
    it('shows EV cost, kWh and solar share without changing the headline Net', async () => {
        vi.mocked(Api.energyRange).mockResolvedValue(rangeResponse())

        render(<GridDomain netCost={null} importKwh={null} exportKwh={null} />)

        expect(await screen.findByText('-18.4 kr')).toBeInTheDocument()
        expect(screen.getByText('12.0 kWh')).toBeInTheDocument()
        expect(screen.getByText('40% solar')).toBeInTheDocument()
        expect(screen.getAllByText('-37.00').length).toBeGreaterThan(0)
        expect(screen.getByText('-40.0 kr')).toBeInTheDocument()
    })

    const noEvEnergy = {
        ev_charging_kwh: 0,
        ev_grid_kwh: 0,
        ev_solar_kwh: 0,
        ev_cost_sek: 0,
        ev_solar_share: null,
    }

    it('shows 0 kr and 0 kWh without a solar share when a charger is configured but idle', async () => {
        vi.mocked(Api.energyRange).mockResolvedValue(rangeResponse(noEvEnergy))

        render(<GridDomain netCost={null} importKwh={null} exportKwh={null} hasEvCharger />)

        expect(await screen.findByText(/of which EV/)).toBeInTheDocument()
        expect(screen.getByText('0 kr')).toBeInTheDocument()
        expect(screen.getByText('0 kWh')).toBeInTheDocument()
        expect(screen.queryByText(/% solar/)).not.toBeInTheDocument()
    })

    it('explains that the EV figure is grid import cost only', async () => {
        vi.mocked(Api.energyRange).mockResolvedValue(rangeResponse())

        render(<GridDomain netCost={null} importKwh={null} exportKwh={null} hasEvCharger />)

        const label = await screen.findByText('↳ of which EV')
        const row = label.parentElement as HTMLElement
        expect(row).toHaveAttribute(
            'title',
            expect.stringMatching(/Grid import cost of EV charging.*Part of Grid Import/),
        )
        expect(row.getAttribute('title')).not.toMatch(/export/i)
        expect(screen.queryByText(/incl\. above/)).not.toBeInTheDocument()
    })

    it('explains the solar share in a tooltip', async () => {
        vi.mocked(Api.energyRange).mockResolvedValue(rangeResponse())

        render(<GridDomain netCost={null} importKwh={null} exportKwh={null} hasEvCharger />)

        const solar = await screen.findByText('40% solar')
        expect(solar).toHaveAttribute('title', expect.stringMatching(/came from solar.*information only/))
    })

    it('hides the EV row when no charger is configured and there is no EV energy', async () => {
        vi.mocked(Api.energyRange).mockResolvedValue(rangeResponse(noEvEnergy))

        render(<GridDomain netCost={null} importKwh={null} exportKwh={null} />)

        expect(await screen.findByText('Grid Import')).toBeInTheDocument()
        expect(screen.queryByText(/of which EV/)).not.toBeInTheDocument()
    })
})

describe('GridDomain validated battery comparison', () => {
    const darkstar = {
        grid_cost_sek: 30,
        wear_cost_sek: 1,
        stored_energy_change_kwh: 1,
        stored_energy_value_sek: 2,
        comparison_cost_sek: 29,
    }
    const selfUse = {
        grid_cost_sek: 38,
        wear_cost_sek: 1.5,
        stored_energy_change_kwh: 0,
        stored_energy_value_sek: 0,
        comparison_cost_sek: 39.5,
    }
    const seriesWith = (comparison: unknown) =>
        ({
            period: 'today',
            bucket: 'hour',
            points: [],
            baseline: { net_cost_sek: 0, saving_incl_wear_sek: 999 },
            battery_comparison: comparison,
        }) as never

    const openPanel = () => fireEvent.click(screen.getByRole('button', { name: 'How this is calculated' }))

    it('shows one compact saving line with the amount and a Verified chip, never legacy savings', async () => {
        vi.mocked(Api.energyRange).mockResolvedValue(rangeResponse())
        vi.mocked(Api.energyCostSeries).mockResolvedValue(
            seriesWith({
                status: 'available',
                reason: 'validated',
                basis: 'calibrated',
                darkstar,
                self_use: selfUse,
                saving_sek: 10.5,
                reference_price_sek_kwh: 2.1,
                through: '2026-10-05T12:30:00',
                points: [],
            }),
        )

        render(<GridDomain netCost={null} importKwh={null} exportKwh={null} />)

        expect(await screen.findByText('Darkstar saved you')).toBeInTheDocument()
        expect(screen.getByText('10.50 kr')).toHaveClass('text-good')
        expect(screen.getByRole('button', { name: 'How this is calculated' })).toHaveTextContent('Verified')
        // Details stay hidden until the info button is used.
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
        expect(screen.queryByText(/Darkstar comparison:/)).not.toBeInTheDocument()
        expect(screen.queryByText(/999/)).not.toBeInTheDocument()
        expect(screen.queryByRole('tab')).not.toBeInTheDocument()
        expect(screen.queryByRole('button', { name: 'Actual' })).not.toBeInTheDocument()
        expect(screen.queryByRole('button', { name: 'Comparison' })).not.toBeInTheDocument()
    })

    it('opens an opaque details panel with explanation, completed-through time and cost breakdown', async () => {
        vi.mocked(Api.energyRange).mockResolvedValue(rangeResponse())
        vi.mocked(Api.energyCostSeries).mockResolvedValue(
            seriesWith({
                status: 'available',
                reason: 'validated',
                basis: 'calibrated',
                darkstar,
                self_use: selfUse,
                saving_sek: 10.5,
                reference_price_sek_kwh: 2.1,
                through: '2026-10-05T12:30:00',
                points: [],
            }),
        )
        render(<GridDomain netCost={null} importKwh={null} exportKwh={null} />)
        await screen.findByText('Darkstar saved you')

        openPanel()

        const panel = screen.getByRole('dialog')
        expect(panel).toHaveClass('bg-surface')
        expect(panel).toHaveTextContent(/plain self-use inverter/)
        expect(panel).toHaveTextContent('Completed through 2026-10-05 12:30')
        expect(panel).toHaveTextContent('Verified: the model passed its accuracy checks.')
        expect(panel).toHaveTextContent('Cost adjustments and assumptions')
        expect(panel).toHaveTextContent('2.100 kr/kWh')
        expect(panel).toHaveTextContent('30.00 / 1.00 / 2.00 kr')
        expect(panel).toHaveTextContent('38.00 / 1.50 / 0.00 kr')
        expect(panel).not.toHaveTextContent(/of the period|Based on/)
    })

    it('toggles the panel with the info button, and closes it on outside click and Escape', async () => {
        vi.mocked(Api.energyRange).mockResolvedValue(rangeResponse())
        vi.mocked(Api.energyCostSeries).mockResolvedValue(
            seriesWith({
                status: 'available',
                reason: 'validated',
                basis: 'calibrated',
                darkstar,
                self_use: selfUse,
                saving_sek: 10.5,
                reference_price_sek_kwh: 2.1,
                through: '2026-10-05T12:30:00',
                points: [],
            }),
        )
        render(<GridDomain netCost={null} importKwh={null} exportKwh={null} />)
        await screen.findByText('Darkstar saved you')
        const button = screen.getByRole('button', { name: 'How this is calculated' })
        expect(button).toHaveAttribute('aria-expanded', 'false')

        fireEvent.click(button)
        expect(screen.getByRole('dialog')).toBeInTheDocument()
        expect(button).toHaveAttribute('aria-expanded', 'true')

        // Interacting inside the panel keeps it open.
        fireEvent.mouseDown(screen.getByRole('dialog'))
        fireEvent.pointerDown(screen.getByRole('dialog'))
        expect(screen.getByRole('dialog')).toBeInTheDocument()

        fireEvent.click(button)
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

        fireEvent.click(button)
        expect(screen.getByRole('dialog')).toBeInTheDocument()
        fireEvent.mouseDown(document.body)
        fireEvent.pointerDown(document.body)
        fireEvent.touchStart(document.body)
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

        fireEvent.click(button)
        expect(screen.getByRole('dialog')).toBeInTheDocument()
        fireEvent.keyDown(document, { key: 'Escape' })
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
        expect(button).toHaveAttribute('aria-expanded', 'false')
    })

    describe('coverage', () => {
        const partial = (covered: number, total: number) =>
            seriesWith({
                status: 'available',
                reason: 'validated',
                basis: 'calibrated',
                darkstar,
                self_use: selfUse,
                saving_sek: 10.5,
                points: [],
                coverage: { covered_slots: covered, total_slots: total, excluded_slots: total - covered },
            })

        it('adds a muted percent suffix and a coverage sentence in the panel when coverage is partial', async () => {
            vi.mocked(Api.energyRange).mockResolvedValue(rangeResponse())
            vi.mocked(Api.energyCostSeries).mockResolvedValue(partial(90, 96))
            render(<GridDomain netCost={null} importKwh={null} exportKwh={null} />)

            // 90 / 96 = 93.75 -> floored to 93
            const suffix = await screen.findByText('· 93% of the period')
            expect(suffix).toHaveClass('text-muted')
            expect(screen.queryByText(/Based on/)).not.toBeInTheDocument()

            openPanel()
            expect(screen.getByRole('dialog')).toHaveTextContent(
                'Based on 90 of 96 completed 15-minute slots (6 left out because they are missing or could not be compared reliably).',
            )
        })

        it('never rounds up to 100% while slots are excluded', async () => {
            vi.mocked(Api.energyRange).mockResolvedValue(rangeResponse())
            vi.mocked(Api.energyCostSeries).mockResolvedValue(partial(1999, 2000))
            render(<GridDomain netCost={null} importKwh={null} exportKwh={null} />)
            expect(await screen.findByText('· 99% of the period')).toBeInTheDocument()
        })

        it('shows no suffix or sentence when every slot is covered', async () => {
            vi.mocked(Api.energyRange).mockResolvedValue(rangeResponse())
            vi.mocked(Api.energyCostSeries).mockResolvedValue(partial(96, 96))
            render(<GridDomain netCost={null} importKwh={null} exportKwh={null} />)
            await screen.findByText('Darkstar saved you')

            expect(screen.queryByText(/of the period/)).not.toBeInTheDocument()
            openPanel()
            expect(screen.getByRole('dialog')).not.toHaveTextContent(/Based on/)
        })
    })

    it('labels configured-loss amounts with an Estimate chip and explains verification state in the panel', async () => {
        vi.mocked(Api.energyRange).mockResolvedValue(rangeResponse())
        vi.mocked(Api.energyCostSeries).mockResolvedValue(
            seriesWith({
                status: 'estimated',
                reason: 'configured_losses',
                basis: 'configured_losses',
                label: 'Estimate based on configured losses',
                calibration_status: 'insufficient_data',
                calibration_reason: 'unverified_history',
                darkstar,
                self_use: selfUse,
                saving_sek: 10.5,
            }),
        )

        render(<GridDomain netCost={null} importKwh={null} exportKwh={null} />)

        expect(await screen.findByText('Darkstar saved you')).toBeInTheDocument()
        const chip = screen.getByRole('button', { name: 'How this is calculated' })
        expect(chip).toHaveTextContent('Estimate')
        expect(chip).not.toHaveTextContent('Verified')
        openPanel()
        const panel = screen.getByRole('dialog')
        expect(panel).toHaveTextContent('Not enough reliable history to verify; configured battery losses are used.')
        expect(panel).not.toHaveTextContent('Verified: the model passed')
        expect(panel).not.toHaveTextContent(/unverified_history/)
    })

    it('withholds the previous estimate while a new period is loading', async () => {
        vi.mocked(Api.energyRange).mockResolvedValue(rangeResponse())
        vi.mocked(Api.energyCostSeries).mockResolvedValueOnce(
            seriesWith({
                status: 'available',
                reason: 'validated',
                darkstar,
                self_use: selfUse,
                saving_sek: 10.5,
                points: [],
            }),
        )
        render(<GridDomain netCost={null} importKwh={null} exportKwh={null} />)
        expect(await screen.findByText('10.50 kr')).toBeInTheDocument()
        let complete: (value: never) => void = () => undefined
        vi.mocked(Api.energyCostSeries).mockImplementationOnce(
            () =>
                new Promise((resolve) => {
                    complete = resolve
                }),
        )
        fireEvent.click(screen.getByRole('button', { name: 'Yesterday' }))
        expect(screen.queryByText('10.50 kr')).not.toBeInTheDocument()
        await act(async () => complete(seriesWith({ status: 'unreliable_model', reason: 'holdout_validation_failed' })))
        expect(
            await screen.findByText('The battery comparison estimate did not pass its accuracy checks.'),
        ).toBeInTheDocument()
        expect(screen.queryByText('10.50 kr')).not.toBeInTheDocument()
    })

    it('says Darkstar cost you extra when the saving is negative', async () => {
        vi.mocked(Api.energyRange).mockResolvedValue(rangeResponse())
        vi.mocked(Api.energyCostSeries).mockResolvedValue(
            seriesWith({
                status: 'available',
                reason: 'validated',
                darkstar,
                self_use: selfUse,
                saving_sek: -2.1,
                reference_price_sek_kwh: 0,
                points: [],
            }),
        )

        render(<GridDomain netCost={null} importKwh={null} exportKwh={null} />)

        const amount = await screen.findByText('2.10 kr')
        expect(screen.getByText('Darkstar cost you extra')).toBeInTheDocument()
        expect(screen.queryByText('Darkstar saved you')).not.toBeInTheDocument()
        expect(amount).toHaveClass('text-bad')
        expect(screen.getByRole('button', { name: 'How this is calculated' })).toHaveTextContent('Verified')
    })

    it('shows a plain-language unavailable state without legacy fallback', async () => {
        vi.mocked(Api.energyRange).mockResolvedValue(rangeResponse())
        vi.mocked(Api.energyCostSeries).mockResolvedValue(
            seriesWith({ status: 'unreliable_model', reason: 'holdout_validation_failed' }),
        )

        render(<GridDomain netCost={null} importKwh={null} exportKwh={null} />)

        expect(
            await screen.findByText('The battery comparison estimate did not pass its accuracy checks.'),
        ).toBeInTheDocument()
        // Only the single muted status line: no amount, chip, or details panel.
        expect(screen.getByRole('status')).toHaveTextContent(
            'The battery comparison estimate did not pass its accuracy checks.',
        )
        expect(screen.queryByText('Darkstar saved you')).not.toBeInTheDocument()
        expect(screen.queryByText('Darkstar cost you extra')).not.toBeInTheDocument()
        expect(screen.queryByRole('button', { name: 'How this is calculated' })).not.toBeInTheDocument()
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
        expect(screen.queryByText(/999/)).not.toBeInTheDocument()
    })

    it('explains collecting history and unsupported periods without amounts', async () => {
        vi.mocked(Api.energyRange).mockResolvedValue(rangeResponse())
        vi.mocked(Api.energyCostSeries).mockResolvedValue(
            seriesWith({ status: 'insufficient_data', reason: 'unverified_history', history: { eligible_count: 0 } }),
        )
        const { rerender } = render(<GridDomain netCost={null} importKwh={null} exportKwh={null} />)
        expect(
            await screen.findByText(
                'Battery comparison needs more reliable history to estimate battery losses, even when viewing today.',
            ),
        ).toBeInTheDocument()
        expect(screen.queryByText('Darkstar saved you')).not.toBeInTheDocument()
        expect(screen.queryByText(/999/)).not.toBeInTheDocument()

        vi.mocked(Api.energyCostSeries).mockResolvedValue(
            seriesWith({ status: 'incomplete_period', reason: 'unsupported_period_measurements' }),
        )
        rerender(<GridDomain key="unsupported-period" netCost={null} importKwh={null} exportKwh={null} />)
        expect(
            await screen.findByText('This period includes measurements that cannot be compared reliably.'),
        ).toBeInTheDocument()
        expect(screen.queryByText('Darkstar saved you')).not.toBeInTheDocument()
    })

    it.each([undefined, Number.NaN, Number.POSITIVE_INFINITY])(
        'withholds malformed saving %s without crashing',
        async (saving) => {
            vi.mocked(Api.energyRange).mockResolvedValue(rangeResponse())
            vi.mocked(Api.energyCostSeries).mockResolvedValue(
                seriesWith({
                    status: 'estimated',
                    basis: 'configured_losses',
                    darkstar,
                    self_use: selfUse,
                    saving_sek: saving,
                }),
            )
            render(<GridDomain netCost={null} importKwh={null} exportKwh={null} />)
            expect(await screen.findByText('Grid Import')).toBeInTheDocument()
            expect(screen.queryByText('Darkstar saved you')).not.toBeInTheDocument()
            expect(screen.queryByText(/NaN|Infinity|999/)).not.toBeInTheDocument()
        },
    )

    it.each([
        [0, 'Darkstar saved you', 'text-good'],
        [2.1, 'Darkstar saved you', 'text-good'],
        [-2.1, 'Darkstar cost you extra', 'text-bad'],
    ])('shows configured-estimate sign %s consistently', async (saving, wording, tone) => {
        vi.mocked(Api.energyRange).mockResolvedValue(rangeResponse())
        vi.mocked(Api.energyCostSeries).mockResolvedValue(
            seriesWith({
                status: 'estimated',
                basis: 'configured_losses',
                darkstar,
                self_use: selfUse,
                saving_sek: saving,
                calibration_status: 'unreliable_model',
                calibration_reason: 'holdout_validation_failed',
            }),
        )
        render(<GridDomain netCost={null} importKwh={null} exportKwh={null} />)
        expect(await screen.findByText(wording)).toBeInTheDocument()
        expect(screen.getByText(`${Math.abs(saving).toFixed(2)} kr`)).toHaveClass(tone)
        expect(screen.getByRole('button', { name: 'How this is calculated' })).toHaveTextContent('Estimate')
        openPanel()
        expect(screen.getByRole('dialog')).toHaveTextContent(
            'Calibration checks did not pass; configured battery losses are used.',
        )
        expect(screen.queryByText(/holdout_validation_failed|Verified battery savings/)).not.toBeInTheDocument()
    })

    it('hides comparison when no battery is configured', async () => {
        vi.mocked(Api.energyRange).mockResolvedValue(rangeResponse())
        vi.mocked(Api.energyCostSeries).mockResolvedValue(
            seriesWith({ status: 'no_battery', reason: 'battery_not_configured' }),
        )

        render(<GridDomain netCost={null} importKwh={null} exportKwh={null} />)

        expect(await screen.findByText('Grid Import')).toBeInTheDocument()
        expect(screen.queryByText('Darkstar saved you')).not.toBeInTheDocument()
        expect(screen.queryByRole('button', { name: 'How this is calculated' })).not.toBeInTheDocument()
    })
})
