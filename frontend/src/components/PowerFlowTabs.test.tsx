import { act, render, screen } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import PowerFlowTabs from './PowerFlowTabs'
import { Api, type LoadBalancerStatusResponse } from '../lib/api'
import { useSocket } from '../lib/hooks'
import type { PowerFlowData } from './PowerFlowRegistry'

vi.mock('../lib/api', () => ({
    Api: {
        executor: {
            loadBalancerStatus: vi.fn(),
        },
    },
}))

vi.mock('../lib/hooks', () => ({
    useSocket: vi.fn(),
}))

vi.mock('./PowerFlowCard', () => ({
    default: () => <div data-testid="flow-view">flow</div>,
}))

vi.mock('./LoadBalancerCompactView', () => ({
    default: () => <div data-testid="lb-view">lb</div>,
}))

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

const flowData: PowerFlowData = {
    solar: { kw: 0 },
    battery: { kw: 0, soc: 50 },
    grid: { kw: 0 },
    house: { kw: 0 },
    water: { kw: 0 },
    ev: { kw: 0 },
}

function baseStatus(overrides: Partial<LoadBalancerStatusResponse> = {}): LoadBalancerStatusResponse {
    return {
        enabled: true,
        state: 'idle',
        reason: '',
        main_fuse_a: 20,
        phase_current_a: { '1': 5, '2': 5, '3': 5 },
        phase_headroom_a: { '1': 15, '2': 15, '3': 15 },
        ev: [],
        shed: [],
        ...overrides,
    }
}

function emitLiveMetrics(status: LoadBalancerStatusResponse) {
    const calls = vi.mocked(useSocket).mock.calls.filter((c) => c[0] === 'live_metrics')
    const [, callback] = calls[calls.length - 1]
    act(() => {
        ;(callback as (data: unknown) => void)({ load_balancing: status })
    })
}

beforeEach(() => {
    vi.stubGlobal('localStorage', makeMemoryStorage())
    vi.mocked(useSocket).mockClear()
})

describe('PowerFlowTabs visibility', () => {
    it('shows no tab strip and only the flow view when load balancing is disabled', async () => {
        vi.mocked(Api.executor.loadBalancerStatus).mockResolvedValue(baseStatus({ enabled: false, state: 'disabled' }))

        render(<PowerFlowTabs data={flowData} />)

        expect(await screen.findByTestId('flow-view')).toBeInTheDocument()
        expect(screen.queryByText('Load Balancer')).not.toBeInTheDocument()
        expect(screen.queryByTestId('lb-view')).not.toBeInTheDocument()
    })

    it('shows the tab strip once load balancing reports enabled', async () => {
        vi.mocked(Api.executor.loadBalancerStatus).mockResolvedValue(baseStatus())

        render(<PowerFlowTabs data={flowData} />)

        expect(await screen.findByText('Load Balancer')).toBeInTheDocument()
        expect(screen.getByTestId('flow-view')).toBeInTheDocument()
    })
})

describe('PowerFlowTabs persisted-tab fallback', () => {
    it('falls back to the flow view when the persisted tab is unavailable', async () => {
        localStorage.setItem('darkstar-powerflow-tab', 'lb')
        vi.mocked(Api.executor.loadBalancerStatus).mockResolvedValue(baseStatus({ enabled: false, state: 'disabled' }))

        render(<PowerFlowTabs data={flowData} />)

        expect(await screen.findByTestId('flow-view')).toBeInTheDocument()
        expect(screen.queryByTestId('lb-view')).not.toBeInTheDocument()
        expect(screen.queryByText('Load Balancer')).not.toBeInTheDocument()
    })

    it('restores the persisted Load Balancer tab once enabled', async () => {
        localStorage.setItem('darkstar-powerflow-tab', 'lb')
        vi.mocked(Api.executor.loadBalancerStatus).mockResolvedValue(baseStatus())

        render(<PowerFlowTabs data={flowData} />)

        expect(await screen.findByTestId('lb-view')).toBeInTheDocument()
    })
})

describe('PowerFlowTabs auto-switch-once-per-episode', () => {
    it('switches to the Load Balancer tab on a non-intervening -> intervening transition', async () => {
        vi.mocked(Api.executor.loadBalancerStatus).mockResolvedValue(baseStatus({ state: 'idle' }))

        render(<PowerFlowTabs data={flowData} />)
        expect(await screen.findByTestId('flow-view')).toBeInTheDocument()

        emitLiveMetrics(baseStatus({ state: 'shedding' }))

        expect(await screen.findByTestId('lb-view')).toBeInTheDocument()
    })

    it('does not re-trigger switching between intervening states, and stays on flow after the user switches back mid-episode', async () => {
        vi.mocked(Api.executor.loadBalancerStatus).mockResolvedValue(baseStatus({ state: 'idle' }))

        render(<PowerFlowTabs data={flowData} />)
        await screen.findByTestId('flow-view')

        emitLiveMetrics(baseStatus({ state: 'shedding' }))
        expect(await screen.findByTestId('lb-view')).toBeInTheDocument()

        // user manually switches back to Flow
        screen.getByText('Flow').click()
        expect(await screen.findByTestId('flow-view')).toBeInTheDocument()

        // intervening -> intervening transition must not force the tab again
        emitLiveMetrics(baseStatus({ state: 'throttling' }))
        expect(screen.getByTestId('flow-view')).toBeInTheDocument()
        expect(screen.queryByTestId('lb-view')).not.toBeInTheDocument()
    })

    it('auto-switches again once a new episode begins after recovery', async () => {
        vi.mocked(Api.executor.loadBalancerStatus).mockResolvedValue(baseStatus({ state: 'idle' }))

        render(<PowerFlowTabs data={flowData} />)
        await screen.findByTestId('flow-view')

        emitLiveMetrics(baseStatus({ state: 'shedding' }))
        expect(await screen.findByTestId('lb-view')).toBeInTheDocument()

        screen.getByText('Flow').click()
        expect(await screen.findByTestId('flow-view')).toBeInTheDocument()

        // balancer recovers to idle, still on Flow (no forced switch on recovery)
        emitLiveMetrics(baseStatus({ state: 'idle' }))
        expect(screen.getByTestId('flow-view')).toBeInTheDocument()

        // new episode starts -> auto-switch fires again
        emitLiveMetrics(baseStatus({ state: 'throttling' }))
        expect(await screen.findByTestId('lb-view')).toBeInTheDocument()
    })
})

describe('PowerFlowTabs warning dot', () => {
    it('shows a warning dot on the Load Balancer tab label while intervening and unseen', async () => {
        vi.mocked(Api.executor.loadBalancerStatus).mockResolvedValue(baseStatus({ state: 'idle' }))

        render(<PowerFlowTabs data={flowData} />)
        await screen.findByTestId('flow-view')

        emitLiveMetrics(baseStatus({ state: 'shedding' }))
        await screen.findByTestId('lb-view')

        // switch back to Flow while shedding is still active -> dot should show
        screen.getByText('Flow').click()
        await screen.findByTestId('flow-view')

        const tabButton = screen.getByText('Load Balancer').closest('button')
        expect(tabButton?.querySelector('span.bg-bad')).toBeTruthy()
    })

    it('shows no warning dot while idle', async () => {
        vi.mocked(Api.executor.loadBalancerStatus).mockResolvedValue(baseStatus({ state: 'idle' }))

        render(<PowerFlowTabs data={flowData} />)
        await screen.findByTestId('flow-view')

        const tabButton = screen.getByText('Load Balancer').closest('button')
        expect(tabButton?.querySelector('span.bg-bad')).toBeFalsy()
    })
})
