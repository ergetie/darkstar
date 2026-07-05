import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import MonitorStatusCard from './MonitorStatusCard'
import { Api } from '../lib/api'

vi.mock('../lib/api', () => ({
    Api: {
        monitors: vi.fn(),
    },
}))

describe('MonitorStatusCard', () => {
    it('renders each invariant and active violations when monitors are healthy-ish', async () => {
        vi.mocked(Api.monitors).mockResolvedValue({
            running: true,
            healthy: false,
            last_cycle_at: '2026-07-05T10:00:00Z',
            last_error: null,
            invariants: {
                slot_continuity: {
                    name: 'slot_continuity',
                    status: 'pass',
                    detail: 'ok',
                    evaluated_at: '2026-07-05T10:00:00Z',
                },
                soc_bounds: {
                    name: 'soc_bounds',
                    status: 'violation',
                    detail: 'SoC out of bounds',
                    evaluated_at: '2026-07-05T10:00:00Z',
                },
            },
            active_violations: [
                {
                    invariant: 'soc_bounds',
                    first_detected_at: '2026-07-05T09:00:00Z',
                    detail: 'SoC out of bounds',
                },
            ],
        })

        render(<MonitorStatusCard />)

        expect(await screen.findByText('slot_continuity')).toBeInTheDocument()
        expect(screen.getByText('soc_bounds')).toBeInTheDocument()
        expect(screen.getByText('Active Violations (1)')).toBeInTheDocument()
    })

    it('shows an error state instead of crashing when the endpoint is unreachable', async () => {
        vi.mocked(Api.monitors).mockRejectedValue(new Error('network error'))

        render(<MonitorStatusCard />)

        await waitFor(() => {
            expect(screen.getByText(/Unable to reach/)).toBeInTheDocument()
        })
    })
})
