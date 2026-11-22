/* planner-run-archive: the Debug page shows the plan archive card on the Logs tab */
import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../components/ui/Toast'
import { DebugContent } from './Debug'

describe('Debug page plan archive card', () => {
    beforeEach(() => {
        vi.stubGlobal(
            'fetch',
            vi.fn(async (input: RequestInfo | URL) => {
                const body =
                    String(input) === 'api/debug/plan-archive'
                        ? {
                              enabled: true,
                              retention_days: 60,
                              count: 3,
                              total_bytes: 4096,
                              oldest: '2026-11-20T10:00:00+00:00',
                              newest: '2026-11-21T10:00:00+00:00',
                          }
                        : { logs: [] }
                return new Response(JSON.stringify(body), { status: 200 })
            }),
        )
    })

    afterEach(() => {
        vi.restoreAllMocks()
        vi.unstubAllGlobals()
    })

    it('renders the card with the loaded summary below Recent events', async () => {
        render(
            <ToastProvider>
                <DebugContent />
            </ToastProvider>,
        )

        expect((await screen.findByTestId('plan-archive-count')).textContent).toBe('3')
        expect(screen.getByText('Plan archive')).toBeTruthy()
        const recent = screen.getByText('Recent events')
        const archive = screen.getByText('Plan archive')
        expect(recent.compareDocumentPosition(archive) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    })
})
