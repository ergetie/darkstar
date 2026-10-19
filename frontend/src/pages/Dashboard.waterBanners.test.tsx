import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

const { bundle } = vi.hoisted(() => ({ bundle: { current: {} as Record<string, unknown> } }))

vi.mock('../lib/api', () => ({
    Api: new Proxy(
        { dashboardBundle: () => Promise.resolve(bundle.current) },
        {
            get: (target, prop: string) =>
                prop in target
                    ? (target as Record<string, unknown>)[prop]
                    : new Proxy(() => Promise.reject(new Error('not mocked')), {
                          get: () => () => Promise.reject(new Error('not mocked')),
                      }),
        },
    ),
}))
vi.mock('../lib/hooks', () => ({ useSocket: () => undefined, useSocketStatus: () => 'connected' }))
vi.mock('../lib/useEvChargers', () => ({ useEvChargers: () => ({ chargers: [], refresh: vi.fn() }) }))
vi.mock('../lib/useToast', () => ({ useToast: () => ({ toast: vi.fn() }) }))
vi.mock('../components/ChartCard', () => ({ default: () => null }))
vi.mock('../components/PowerFlowTabs', () => ({ default: () => null }))
vi.mock('../components/PowerFlowHouse', () => ({ computeHouseKw: () => 0 }))
vi.mock('../components/CommandBar', () => ({ default: () => null }))
vi.mock('../components/BatteryStrategyCard', () => ({ default: () => null }))
vi.mock('../components/CommandDomains', () => ({ GridDomain: () => null, ResourcesDomain: () => null }))

import Dashboard from './Dashboard'

function setBundle(hasWaterHeater: boolean) {
    bundle.current = {
        config: {
            system: { has_water_heater: hasWaterHeater },
            water_heating: { vacation_mode: { enabled: true } },
            water_heaters: [],
        },
        water_boost: { boost: true, expires_at: null, heaters: {} },
    }
}

describe('Dashboard water banners', () => {
    beforeEach(() => {
        vi.spyOn(console, 'error').mockImplementation(() => undefined)
        vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    })

    it('shows the vacation and boost banners when a water heater is configured', async () => {
        setBundle(true)
        render(<Dashboard />)
        expect(await screen.findByText('Vacation Mode Active')).toBeTruthy()
        expect(screen.getByText('Water Heater Boost Active')).toBeTruthy()
    })

    it('hides both banners when has_water_heater is false', async () => {
        setBundle(false)
        render(<Dashboard />)
        // Wait until the bundle has been applied, then assert absence.
        await waitFor(() => expect(bundle.current).toBeTruthy())
        await new Promise((resolve) => setTimeout(resolve, 50))
        expect(screen.queryByText('Vacation Mode Active')).toBeNull()
        expect(screen.queryByText('Water Heater Boost Active')).toBeNull()
    })
})
