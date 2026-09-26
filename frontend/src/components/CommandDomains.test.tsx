import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { GridDomain, ResourcesDomain } from './CommandDomains'
import { Api } from '../lib/api'

vi.mock('../lib/api', () => ({
    Api: {
        energyRange: vi.fn(),
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
