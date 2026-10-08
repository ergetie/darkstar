import { fireEvent, render, screen } from '@testing-library/react'
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

const gridOnlyAxis = {
    timezone: 'Europe/Stockholm',
    start: '2026-10-05T00:00:00+02:00',
    end: '2026-10-06T00:00:00+02:00',
}

function gridOnlyComparison(overrides: Record<string, unknown> = {}) {
    return {
        status: 'available',
        reason: 'complete_coverage',
        method_version: 'grid-only-bill-v1',
        coverage: { covered_slots: 96, total_slots: 96, excluded_slots: 0 },
        time_axis: gridOnlyAxis,
        through: '2026-10-05T12:30:00+02:00',
        grid_only_cost_sek: 40,
        grid_only_wear_cost_sek: 0,
        ds_electricity_cost_sek: 28,
        ds_wear_cost_sek: 2,
        ds_cost_sek: 30,
        saving_sek: 10,
        points: [
            {
                start: '2026-10-05T12:00:00+02:00',
                end: '2026-10-05T13:00:00+02:00',
                import_cost_sek: 30,
                export_revenue_sek: 2,
                ds_electricity_cost_sek: 28,
                ds_wear_cost_sek: 2,
                grid_only_wear_cost_sek: 0,
                ds_cost_sek: 30,
                grid_only_cost_sek: 40,
                cumulative_ds_cost_sek: 30,
                cumulative_grid_only_cost_sek: 40,
            },
        ],
        segments: [
            {
                start: '2026-10-05T12:00:00+02:00',
                end: '2026-10-05T12:15:00+02:00',
                points: [
                    { at: '2026-10-05T12:00:00+02:00', cumulative_ds_cost_sek: 29, cumulative_grid_only_cost_sek: 39 },
                    { at: '2026-10-05T12:15:00+02:00', cumulative_ds_cost_sek: 30, cumulative_grid_only_cost_sek: 40 },
                ],
            },
        ],
        ...overrides,
    }
}

function seriesWith(comparison: unknown) {
    return {
        period: 'today',
        bucket: 'hour',
        points: [
            {
                start: '2026-10-05T12:00:00+02:00',
                import_cost_sek: 30,
                export_revenue_sek: 2,
                net_cost_sek: 28,
                cumulative_net_cost_sek: 28,
            },
        ],
        grid_only_comparison: comparison,
    } as never
}

describe('GridDomain grid-only comparison', () => {
    const openPanel = () => fireEvent.click(screen.getByRole('button', { name: 'Grid-only bill details' }))

    it('shows the signed savings including configured wear, with neutral zero styling', async () => {
        vi.mocked(Api.energyRange).mockResolvedValue(rangeResponse())
        vi.mocked(Api.energyCostSeries).mockResolvedValue(seriesWith(gridOnlyComparison()))
        const { rerender } = render(<GridDomain netCost={null} importKwh={null} exportKwh={null} />)

        expect(await screen.findByText('DS vs grid-only')).toBeInTheDocument()
        expect(screen.getByText('+10.00 kr')).toHaveClass('text-good')
        expect(screen.queryByText(/Estimate|Verified|Darkstar saved you/)).not.toBeInTheDocument()
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

        vi.mocked(Api.energyCostSeries).mockResolvedValue(
            seriesWith(
                gridOnlyComparison({
                    saving_sek: 0,
                    grid_only_cost_sek: 40,
                    ds_cost_sek: 40,
                    ds_electricity_cost_sek: 38,
                    ds_wear_cost_sek: 2,
                }),
            ),
        )
        rerender(<GridDomain key="zero" netCost={null} importKwh={null} exportKwh={null} />)
        expect(await screen.findByText('0.00 kr')).toHaveClass('text-muted')
    })

    it('shows a negative signed amount and exact whole-installation wear explanation', async () => {
        vi.mocked(Api.energyRange).mockResolvedValue(rangeResponse())
        vi.mocked(Api.energyCostSeries).mockResolvedValue(
            seriesWith(
                gridOnlyComparison({
                    saving_sek: -2.1,
                    grid_only_cost_sek: 30,
                    ds_cost_sek: 32.1,
                    ds_electricity_cost_sek: 30.1,
                }),
            ),
        )
        render(<GridDomain netCost={null} importKwh={null} exportKwh={null} />)
        expect(await screen.findByText('−2.10 kr')).toHaveClass('text-bad')
        openPanel()
        const panel = screen.getByRole('dialog')
        expect(panel).toHaveTextContent(
            "Same recorded consumption bought entirely from the grid at each slot's price, compared with actual import costs minus export income, including estimated battery wear.",
        )
        expect(panel).toHaveTextContent('Whole-installation comparison, including solar and exports.')
        expect(panel).toHaveTextContent('Grid-only electricity 30.00 kr')
        expect(panel).toHaveTextContent('Grid-only battery wear 0.00 kr')
        expect(panel).toHaveTextContent('DS electricity 30.10 kr')
        expect(panel).toHaveTextContent('DS battery wear 2.00 kr')
        expect(panel).toHaveTextContent('DS incl. battery wear 32.10 kr')
        expect(panel).toHaveTextContent('Completed through 2026-10-05 12:30')
    })

    it('closes the details panel on outside pointer and Escape', async () => {
        vi.mocked(Api.energyRange).mockResolvedValue(rangeResponse())
        vi.mocked(Api.energyCostSeries).mockResolvedValue(seriesWith(gridOnlyComparison()))
        render(<GridDomain netCost={null} importKwh={null} exportKwh={null} />)
        await screen.findByText('+10.00 kr')
        const button = screen.getByRole('button', { name: 'Grid-only bill details' })
        fireEvent.click(button)
        expect(screen.getByRole('dialog')).toBeInTheDocument()
        fireEvent.pointerDown(document.body)
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
        fireEvent.click(button)
        expect(screen.getByRole('dialog')).toBeInTheDocument()
        fireEvent.keyDown(document, { key: 'Escape' })
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })

    it('shows the floored partial coverage share', async () => {
        vi.mocked(Api.energyRange).mockResolvedValue(rangeResponse())
        vi.mocked(Api.energyCostSeries).mockResolvedValue(
            seriesWith(
                gridOnlyComparison({
                    status: 'partial',
                    reason: 'partial_coverage',
                    coverage: { covered_slots: 90, total_slots: 96, excluded_slots: 6 },
                }),
            ),
        )
        render(<GridDomain netCost={null} importKwh={null} exportKwh={null} />)
        expect(await screen.findByText('· 93% of the period')).toHaveClass('text-muted')
        openPanel()
        expect(screen.getByRole('dialog')).toHaveTextContent('90 of 96 slots (6 excluded)')
    })

    it('shows a plain unavailable reason without an amount or details panel', async () => {
        vi.mocked(Api.energyRange).mockResolvedValue(rangeResponse())
        vi.mocked(Api.energyCostSeries).mockResolvedValue(
            seriesWith({
                status: 'unavailable',
                reason: 'no_usable_observations',
                method_version: 'grid-only-bill-v1',
                coverage: { covered_slots: 0, total_slots: 96, excluded_slots: 96 },
                time_axis: gridOnlyAxis,
            }),
        )
        render(<GridDomain netCost={null} importKwh={null} exportKwh={null} />)
        expect(await screen.findByText('No usable recorded inputs are available for this period.')).toBeInTheDocument()
        expect(screen.queryByText(/DS vs grid-only/)).not.toBeInTheDocument()
        expect(screen.queryByRole('button', { name: 'Grid-only bill details' })).not.toBeInTheDocument()
    })

    it('keeps Battery Charge informational and removes the Self-Use Saved row and tooltip', async () => {
        vi.mocked(Api.energyRange).mockResolvedValue(rangeResponse({ grid_charge_cost_sek: 4 }))
        vi.mocked(Api.energyCostSeries).mockResolvedValue(seriesWith(gridOnlyComparison()))
        render(<GridDomain netCost={null} importKwh={null} exportKwh={null} />)
        const batteryCharge = await screen.findByText('Battery Charge')
        expect(batteryCharge).toHaveAttribute(
            'title',
            'Informational only. Battery charging costs are already included in Grid Import above and are not deducted again.',
        )
        expect(screen.queryByText('Self-Use Saved')).not.toBeInTheDocument()
        expect(screen.queryByText(/House use covered by solar\/battery/)).not.toBeInTheDocument()
        expect(screen.getByText('-4.0 kr')).toBeInTheDocument()
    })

    it('keeps actual electricity and its separate wear-inclusive figure visible', async () => {
        vi.mocked(Api.energyRange).mockResolvedValue(
            rangeResponse({ battery_wear_cost_sek: 2, net_cost_incl_wear_sek: 39 }),
        )
        vi.mocked(Api.energyCostSeries).mockResolvedValue(seriesWith(gridOnlyComparison()))
        render(<GridDomain netCost={null} importKwh={null} exportKwh={null} />)
        await screen.findByText('DS vs grid-only')
        expect(screen.getAllByText('-37.00').length).toBeGreaterThan(0)
        expect(screen.getAllByText('-39.00').length).toBeGreaterThan(0)
    })

    it('shows chart request failures distinctly while retaining the actual totals', async () => {
        vi.mocked(Api.energyRange).mockResolvedValue(
            rangeResponse({ net_cost_sek: 37.13, net_cost_incl_wear_sek: 38.23 }),
        )
        vi.mocked(Api.energyCostSeries).mockRejectedValue(new Error('Invalid cost-series response'))
        render(<GridDomain netCost={null} importKwh={null} exportKwh={null} />)

        expect(await screen.findByText('Actual electricity cost · Today')).toBeInTheDocument()
        expect(screen.getAllByText('-37.13').length).toBeGreaterThan(0)
        expect(screen.getAllByText('-38.23').length).toBeGreaterThan(0)
        expect(screen.getByTestId('cost-chart-error')).toHaveTextContent('Unable to load chart data for this period')
        expect(screen.queryByText('No recorded slots yet for this period')).not.toBeInTheDocument()
    })
})
