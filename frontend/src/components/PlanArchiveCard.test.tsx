/* planner-run-archive: Debug page plan archive card */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from './ui/Toast'
import PlanArchiveCard from './PlanArchiveCard'
import type { PlanArchiveSummary } from '../lib/api'

type Deferred = { resolve: (r: Response) => void }

const FULL: PlanArchiveSummary = {
    enabled: true,
    retention_days: 60,
    count: 12,
    total_bytes: 2 * 1024 * 1024,
    oldest: '2026-11-01T10:00:00+00:00',
    newest: '2026-11-21T10:00:00+00:00',
}
const EMPTY: PlanArchiveSummary = { ...FULL, count: 0, total_bytes: 0, oldest: null, newest: null }

function json(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('PlanArchiveCard', () => {
    let summary: PlanArchiveSummary
    let calls: { url: string; method: string }[]
    let pendingDownload: Deferred | null
    let downloadResponse: (() => Response) | null
    let clicked: string[]

    beforeEach(() => {
        summary = FULL
        calls = []
        pendingDownload = null
        downloadResponse = null
        clicked = []
        vi.stubGlobal(
            'fetch',
            vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
                const url = String(input)
                const method = init?.method ?? 'GET'
                calls.push({ url, method })
                if (url.startsWith('api/debug/plan-archive/download')) {
                    if (downloadResponse) return downloadResponse()
                    return new Promise<Response>((resolve) => {
                        pendingDownload = { resolve }
                    })
                }
                if (url === 'api/debug/plan-archive' && method === 'DELETE') {
                    summary = EMPTY
                    return json({ deleted: 12 })
                }
                if (url === 'api/debug/plan-archive') return json(summary)
                return json({})
            }),
        )
        // jsdom has no scrollIntoView (used by the Select dropdown)
        Element.prototype.scrollIntoView = vi.fn()
        URL.createObjectURL = vi.fn(() => 'blob:test')
        URL.revokeObjectURL = vi.fn()
        vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
            clicked.push(this.download)
        })
    })

    afterEach(() => {
        vi.restoreAllMocks()
        vi.unstubAllGlobals()
    })

    const renderCard = () =>
        render(
            <ToastProvider>
                <PlanArchiveCard />
            </ToastProvider>,
        )

    const downloadCalls = () => calls.filter((c) => c.url.startsWith('api/debug/plan-archive/download'))

    it('renders count, size, date range and retention', async () => {
        renderCard()
        expect((await screen.findByTestId('plan-archive-count')).textContent).toBe('12')
        expect(screen.getByText('2.0 MB')).toBeTruthy()
        expect(screen.getByText('60 days')).toBeTruthy()
        expect(screen.getByText(new RegExp(new Date(FULL.oldest!).toLocaleDateString()))).toBeTruthy()
        expect(calls[0]).toEqual({ url: 'api/debug/plan-archive', method: 'GET' })
    })

    it('downloads everything without a days parameter', async () => {
        downloadResponse = () =>
            new Response(new Blob(['zip']), {
                headers: { 'Content-Disposition': 'attachment; filename="darkstar-plan-archive-1.zip"' },
            })
        renderCard()
        await screen.findByTestId('plan-archive-count')
        fireEvent.click(screen.getByRole('button', { name: /^Download$/ }))

        await waitFor(() => expect(clicked).toEqual(['darkstar-plan-archive-1.zip']))
        expect(downloadCalls().map((c) => c.url)).toEqual(['api/debug/plan-archive/download'])
    })

    it.each([
        ['Last 7 days', 'api/debug/plan-archive/download?days=7'],
        ['Last 24 hours', 'api/debug/plan-archive/download?days=1'],
    ])('downloads %s with a days parameter', async (label, url) => {
        downloadResponse = () => new Response(new Blob(['zip']))
        renderCard()
        await screen.findByTestId('plan-archive-count')
        fireEvent.click(screen.getByRole('button', { name: 'All' }))
        fireEvent.click(await screen.findByText(label))
        fireEvent.click(screen.getByRole('button', { name: /^Download$/ }))

        await waitFor(() => expect(downloadCalls().map((c) => c.url)).toEqual([url]))
    })

    it('shows a busy state and disables the button until the download finishes', async () => {
        renderCard()
        await screen.findByTestId('plan-archive-count')
        fireEvent.click(screen.getByRole('button', { name: /^Download$/ }))

        const busy = await screen.findByRole('button', { name: 'Preparing…' })
        expect((busy as HTMLButtonElement).disabled).toBe(true)
        expect(busy.querySelector('.animate-spin')).not.toBeNull()
        fireEvent.click(busy)
        expect(downloadCalls()).toHaveLength(1)

        await act(async () => {
            pendingDownload!.resolve(new Response(new Blob(['zip'])))
        })

        await waitFor(() => expect(screen.getByRole('button', { name: /^Download$/ })).toBeTruthy())
        expect((screen.getByRole('button', { name: /^Download$/ }) as HTMLButtonElement).disabled).toBe(false)
    })

    it('shows an error toast when the download fails', async () => {
        downloadResponse = () => json({ detail: 'The plan archive holds no records' }, 404)
        renderCard()
        await screen.findByTestId('plan-archive-count')
        fireEvent.click(screen.getByRole('button', { name: /^Download$/ }))

        expect(await screen.findByText('Plan archive download failed')).toBeTruthy()
        expect(screen.getByText('The plan archive holds no records')).toBeTruthy()
        expect((screen.getByRole('button', { name: /^Download$/ }) as HTMLButtonElement).disabled).toBe(false)
    })

    it('cancelling the clear confirmation deletes nothing', async () => {
        renderCard()
        await screen.findByTestId('plan-archive-count')
        fireEvent.click(screen.getByRole('button', { name: /^Clear archive$/ }))

        expect(await screen.findByRole('dialog')).toBeTruthy()
        fireEvent.click(screen.getByRole('button', { name: /^Cancel$/ }))

        await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
        expect(calls.filter((c) => c.method === 'DELETE')).toHaveLength(0)
        expect(screen.getByTestId('plan-archive-count').textContent).toBe('12')
    })

    it('confirming the clear deletes and shows zero records', async () => {
        renderCard()
        await screen.findByTestId('plan-archive-count')
        fireEvent.click(screen.getByRole('button', { name: /^Clear archive$/ }))
        fireEvent.click(await screen.findByRole('button', { name: /Yes, clear archive/ }))

        await waitFor(() => expect(screen.getByTestId('plan-archive-count').textContent).toBe('0'))
        expect(calls.filter((c) => c.method === 'DELETE').map((c) => c.url)).toEqual(['api/debug/plan-archive'])
        expect(screen.queryByRole('dialog')).toBeNull()
    })

    it('disables download and clear when the archive is empty', async () => {
        summary = EMPTY
        renderCard()
        await waitFor(() => expect(screen.getByTestId('plan-archive-count').textContent).toBe('0'))
        expect((screen.getByRole('button', { name: /^Download$/ }) as HTMLButtonElement).disabled).toBe(true)
        expect((screen.getByRole('button', { name: /^Clear archive$/ }) as HTMLButtonElement).disabled).toBe(true)
    })

    it('says so when archiving is disabled', async () => {
        summary = { ...EMPTY, enabled: false }
        renderCard()
        expect(await screen.findByText(/Archiving is disabled/)).toBeTruthy()
    })

    it('shows an error when the summary cannot be loaded', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn(async () => json({ detail: 'boom' }, 500)),
        )
        renderCard()
        expect(await screen.findByText(/Could not load the plan archive summary/)).toBeTruthy()
    })
})
