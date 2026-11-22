/* learned-battery-inverter-parameters 10.3: learned parameter notification toggle */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ExecutorPage from './Executor'

vi.mock('../lib/hooks', () => ({
    useSocket: vi.fn(),
}))

vi.mock('../components/LoadBalancerStatusCard', () => ({
    default: () => null,
}))

function mockFetch(posts: { url: string; body: unknown }[]) {
    vi.stubGlobal(
        'fetch',
        vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
            const url = String(input)
            let body: unknown = {}
            if (url.includes('api/executor/notifications')) {
                if (init?.method === 'POST') {
                    posts.push({ url, body: JSON.parse(String(init.body)) })
                    body = { status: 'success' }
                } else {
                    body = {
                        service: 'notify.mobile_app',
                        on_charge_start: true,
                        on_charge_stop: false,
                        on_export_start: true,
                        on_export_stop: true,
                        on_water_heat_start: true,
                        on_water_heat_stop: false,
                        on_soc_target_change: false,
                        on_override_activated: true,
                        on_error: true,
                        on_learned_parameter_change: true,
                    }
                }
            } else if (url.includes('api/executor/status')) {
                body = { enabled: true, shadow_mode: false, last_run_status: 'success', override_active: false }
            } else if (url.includes('api/executor/history')) {
                body = { records: [], count: 0 }
            }
            return { ok: true, status: 200, json: async () => body } as Response
        }),
    )
}

describe('Executor notification toggles', () => {
    afterEach(() => {
        vi.unstubAllGlobals()
    })

    it('lists the learned parameter toggle and saves its key', async () => {
        const posts: { url: string; body: unknown }[] = []
        mockFetch(posts)
        render(
            <MemoryRouter>
                <ExecutorPage />
            </MemoryRouter>,
        )

        fireEvent.click(await screen.findByRole('button', { name: /Notifications/ }))
        const label = await screen.findByText('Learned Parameter Changed')
        const row = label.closest('div.flex.items-center') as HTMLElement
        const toggle = within(row).getByRole('switch')
        expect(toggle).toHaveAttribute('aria-checked', 'true')

        fireEvent.click(toggle)

        await waitFor(() => expect(posts).toHaveLength(1))
        expect(posts[0].url).toContain('api/executor/notifications')
        expect(posts[0].body).toEqual({ on_learned_parameter_change: false })
        await waitFor(() => expect(toggle).toHaveAttribute('aria-checked', 'false'))
    })
})
