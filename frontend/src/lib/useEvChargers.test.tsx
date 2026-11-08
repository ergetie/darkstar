import { act, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useEvChargers } from './useEvChargers'
import type { EVChargerState } from './api'
import type { ConnectionState } from './socket'

let status: ConnectionState = 'connected'
const chargersMock = vi.fn()

vi.mock('./hooks', () => ({
    useSocket: vi.fn(),
    useSocketStatus: () => status,
}))

vi.mock('./api', () => ({
    Api: { ev: { chargers: (...args: unknown[]) => chargersMock(...args) } },
}))

function charger(soc: number): EVChargerState {
    return { id: 'ev1', name: 'Tesla', soc_percent: soc } as EVChargerState
}

function Probe({ enabled }: { enabled: boolean }) {
    const { chargers } = useEvChargers(enabled)
    return <div data-testid="soc">{chargers.map((c) => c.soc_percent).join(',')}</div>
}

beforeEach(() => {
    status = 'connected'
    chargersMock.mockReset()
    chargersMock.mockResolvedValue([charger(31)])
})

describe('useEvChargers reconnect refetch', () => {
    it('fetches exactly once on initial connect', async () => {
        const { rerender } = render(<Probe enabled />)
        await waitFor(() => expect(chargersMock).toHaveBeenCalledTimes(1))
        rerender(<Probe enabled />)
        await act(async () => {})
        expect(chargersMock).toHaveBeenCalledTimes(1)
    })

    it('refetches once after a drop and reconnect and shows the new data', async () => {
        const { rerender } = render(<Probe enabled />)
        await waitFor(() => expect(screen.getByTestId('soc').textContent).toBe('31'))

        status = 'offline'
        rerender(<Probe enabled />)
        await act(async () => {})
        expect(chargersMock).toHaveBeenCalledTimes(1)

        chargersMock.mockResolvedValue([charger(75)])
        status = 'connected'
        rerender(<Probe enabled />)
        await waitFor(() => expect(screen.getByTestId('soc').textContent).toBe('75'))
        expect(chargersMock).toHaveBeenCalledTimes(2)
    })

    it('does not fetch on reconnect while disabled', async () => {
        const { rerender } = render(<Probe enabled={false} />)
        status = 'connecting'
        rerender(<Probe enabled={false} />)
        status = 'connected'
        rerender(<Probe enabled={false} />)
        await act(async () => {})
        expect(chargersMock).not.toHaveBeenCalled()
    })
})
