import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { ResourcesDomain } from './CommandDomains'
import { Api } from '../lib/api'

vi.mock('../lib/api', () => ({
    Api: {
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
