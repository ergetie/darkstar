/* load-balancing-completion 8.3: execution history explainer header */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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

function mockFetch(historyRecords: unknown[] = []) {
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
                body = { records: historyRecords, count: historyRecords.length }
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

const EV_FAILURE_RECORD = {
    id: 7,
    executed_at: '2026-09-23T18:00:05+02:00',
    slot_start: '2026-09-23T18:00:05+02:00',
    success: 0,
    override_active: 0,
    commanded_work_mode: 'ev_charge_current',
    source: 'ev_charger',
    error_message: 'HTTP 500: min 6',
    action_results: [
        {
            type: 'ev_charge_current',
            success: false,
            message: 'Failed to set number.goe_current to 6A: HTTP 500',
            entity_id: 'number.goe_current',
            charger_id: 'goe',
            new_value: 6,
            skipped: false,
            error_details: 'HTTP 500: min 6',
        },
    ],
}

describe('Execution history source filter', () => {
    afterEach(() => {
        vi.unstubAllGlobals()
    })

    it('requests only EV records when the EV filter is selected', async () => {
        mockFetch()
        render(
            <MemoryRouter>
                <ExecutorPage />
            </MemoryRouter>,
        )

        fireEvent.click(await screen.findByRole('button', { name: 'EV' }))

        await waitFor(() => {
            const urls = vi.mocked(fetch).mock.calls.map((c) => String(c[0]))
            expect(urls.some((u) => u.includes('api/executor/history') && u.includes('source=ev_charger'))).toBe(true)
        })
        expect(screen.getByRole('button', { name: 'EV' })).toHaveAttribute('aria-pressed', 'true')
    })

    it('renders an EV badge for EV action records', async () => {
        mockFetch([EV_FAILURE_RECORD])
        render(
            <MemoryRouter>
                <ExecutorPage />
            </MemoryRouter>,
        )

        const badge = await screen.findByText(/EV current/)
        fireEvent.click(badge)

        expect(await screen.findByText('Charger: goe')).toBeInTheDocument()
        expect(screen.getAllByText(/Failed to set number.goe_current to 6A/).length).toBeGreaterThan(0)
        expect(screen.getAllByText('HTTP 500: min 6').length).toBeGreaterThan(0)
    })
})
