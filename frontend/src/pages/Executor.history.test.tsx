/* load-balancing-completion 8.3: execution history explainer header */
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ExecutorPage from './Executor'

vi.mock('../lib/hooks', () => ({
    useSocket: vi.fn(),
}))

// The status card has its own tests; keep this one focused on the page.
vi.mock('../components/LoadBalancerStatusCard', () => ({
    default: () => null,
}))

const LAST_RUN_AT = '2026-07-06T12:34:56+02:00'

function mockFetch() {
    vi.stubGlobal(
        'fetch',
        vi.fn(async (input: RequestInfo | URL) => {
            const url = String(input)
            let body: unknown = {}
            if (url.includes('api/executor/status')) {
                body = {
                    enabled: true,
                    shadow_mode: false,
                    last_run_at: LAST_RUN_AT,
                    last_run_status: 'success',
                    last_action: 'Idle - within plan',
                    override_active: false,
                }
            } else if (url.includes('api/executor/history')) {
                body = { records: [], count: 0 }
            } else if (url.includes('api/executor/stats')) {
                body = {
                    period_days: 7,
                    total_executions: 0,
                    successful: 0,
                    failed: 0,
                    success_rate: 0,
                    override_count: 0,
                    override_rate: 0,
                    override_types: {},
                }
            }
            return {
                ok: true,
                status: 200,
                json: async () => body,
            } as Response
        }),
    )
}

describe('Execution history explainer header', () => {
    afterEach(() => {
        vi.unstubAllGlobals()
    })

    it('shows the last tick time and outcome plus the recording policy', async () => {
        mockFetch()
        render(
            <MemoryRouter>
                <ExecutorPage />
            </MemoryRouter>,
        )

        const explainer = await screen.findByTestId('history-explainer')
        expect(explainer).toHaveTextContent('Last executor tick')
        expect(explainer).toHaveTextContent('success')
        expect(explainer).toHaveTextContent('Idle - within plan')
        expect(explainer).toHaveTextContent('one heartbeat per 15-minute slot')
    })

    it('explains itself even before any tick has run', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn(async (input: RequestInfo | URL) => {
                const url = String(input)
                const body = url.includes('api/executor/history')
                    ? { records: [], count: 0 }
                    : url.includes('api/executor/status')
                      ? { enabled: false, shadow_mode: false, last_run_status: 'never', override_active: false }
                      : {}
                return { ok: true, status: 200, json: async () => body } as Response
            }),
        )
        render(
            <MemoryRouter>
                <ExecutorPage />
            </MemoryRouter>,
        )

        const explainer = await screen.findByTestId('history-explainer')
        expect(explainer).toHaveTextContent('No executor tick recorded yet')
        expect(explainer).toHaveTextContent('Only changes')
    })
})
