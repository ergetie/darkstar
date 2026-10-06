/* diagnostics-export: Debug page download buttons */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../components/ui/Toast'
import { DebugContent } from './Debug'

type Deferred = { resolve: (r: Response) => void; reject: (e: Error) => void }

function blobResponse(name: string): Response {
    return new Response(new Blob(['data']), {
        status: 200,
        headers: { 'Content-Disposition': `attachment; filename="${name}"` },
    })
}

describe('Debug page download buttons', () => {
    const originalLocation = window.location
    let location: { href: string }
    let exportCalls: string[]
    let pending: Deferred | null
    let exportResponse: (() => Response) | null
    let clicked: { href: string; download: string }[]

    beforeEach(() => {
        location = { href: '' }
        exportCalls = []
        pending = null
        exportResponse = null
        clicked = []
        Object.defineProperty(window, 'location', { configurable: true, value: location })
        vi.stubGlobal(
            'fetch',
            vi.fn(async (input: RequestInfo | URL) => {
                const url = String(input)
                if (url.startsWith('api/system/db-snapshot') || url.startsWith('api/system/diagnostics')) {
                    exportCalls.push(url)
                    if (exportResponse) return exportResponse()
                    return new Promise<Response>((resolve, reject) => {
                        pending = { resolve, reject }
                    })
                }
                return { ok: true, status: 200, json: async () => ({ logs: [] }) } as Response
            }),
        )
        URL.createObjectURL = vi.fn(() => 'blob:test')
        URL.revokeObjectURL = vi.fn()
        vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
            clicked.push({ href: this.href, download: this.download })
        })
    })

    afterEach(() => {
        Object.defineProperty(window, 'location', { configurable: true, value: originalLocation })
        vi.restoreAllMocks()
        vi.unstubAllGlobals()
    })

    const renderPage = () =>
        render(
            <ToastProvider>
                <DebugContent />
            </ToastProvider>,
        )

    it('Config button points to a relative URL', () => {
        renderPage()
        fireEvent.click(screen.getByRole('button', { name: /^Config$/ }))
        expect(location.href).toBe('api/config/download')
    })

    it('renders the "Export bundle" button and no "Export diagnostics" button', () => {
        renderPage()
        expect(screen.getByRole('button', { name: /^Export bundle$/ })).toBeTruthy()
        expect(screen.queryByRole('button', { name: /Export diagnostics/ })).toBeNull()
    })

    it('toolbar wraps and buttons never wrap their text', () => {
        renderPage()
        const toolbar = screen.getByRole('button', { name: /^Config$/ }).parentElement as HTMLElement
        expect(toolbar.className).toContain('flex-wrap')
        for (const name of [/^Logs$/, /^Config$/, /^Database$/, /^Export bundle$/, /^Clear$/]) {
            expect(screen.getAllByRole('button', { name }).slice(-1)[0].className).toContain('whitespace-nowrap')
        }
    })

    it.each([
        ['Export bundle', 'Exporting…', 'api/system/diagnostics', 'darkstar-diagnostics-1.zip'],
        ['Database', 'Preparing…', 'api/system/db-snapshot', 'planner_learning-1.db'],
    ])('%s shows a busy state until the file is delivered', async (label, busyLabel, url, filename) => {
        renderPage()
        fireEvent.click(screen.getByRole('button', { name: new RegExp(`^${label}$`) }))

        const busyBtn = await screen.findByRole('button', { name: busyLabel })
        expect((busyBtn as HTMLButtonElement).disabled).toBe(true)
        expect(busyBtn.querySelector('.animate-spin')).not.toBeNull()
        expect(exportCalls).toEqual([url])
        // Other export button is disabled too, and a second click does nothing.
        const other = label === 'Database' ? /Export bundle|Exporting/ : /Database|Preparing/
        expect((screen.getByRole('button', { name: other }) as HTMLButtonElement).disabled).toBe(true)
        fireEvent.click(busyBtn)
        expect(exportCalls).toHaveLength(1)

        await act(async () => {
            pending!.resolve(blobResponse(filename))
        })

        await waitFor(() => expect(screen.getByRole('button', { name: new RegExp(`^${label}$`) })).toBeTruthy())
        expect((screen.getByRole('button', { name: new RegExp(`^${label}$`) }) as HTMLButtonElement).disabled).toBe(
            false,
        )
        expect(clicked).toHaveLength(1)
        expect(clicked[0].download).toBe(filename)
        expect(location.href).toBe('')
    })

    it('shows a readable message when a concurrent export is rejected (409)', async () => {
        exportResponse = () =>
            new Response(JSON.stringify({ detail: 'Another export is already in progress' }), { status: 409 })
        renderPage()
        fireEvent.click(screen.getByRole('button', { name: /^Export bundle$/ }))

        expect(await screen.findByText('Export failed')).toBeTruthy()
        expect(screen.getByText(/Another export is already running/)).toBeTruthy()
        expect((screen.getByRole('button', { name: /^Export bundle$/ }) as HTMLButtonElement).disabled).toBe(false)
        expect(clicked).toHaveLength(0)
    })

    it('shows the backend error detail on failure and re-enables the button', async () => {
        exportResponse = () =>
            new Response(JSON.stringify({ detail: 'Database snapshot failed: disk full' }), { status: 500 })
        renderPage()
        fireEvent.click(screen.getByRole('button', { name: /^Database$/ }))

        expect(await screen.findByText('Database download failed')).toBeTruthy()
        expect(screen.getByText('Database snapshot failed: disk full')).toBeTruthy()
        expect((screen.getByRole('button', { name: /^Database$/ }) as HTMLButtonElement).disabled).toBe(false)
    })

    it('shows an error when the network request fails', async () => {
        renderPage()
        fireEvent.click(screen.getByRole('button', { name: /^Export bundle$/ }))
        await screen.findByRole('button', { name: 'Exporting…' })
        await act(async () => {
            pending!.reject(new TypeError('network'))
        })
        expect(await screen.findByText(/Could not reach the server/)).toBeTruthy()
        expect((screen.getByRole('button', { name: /^Export bundle$/ }) as HTMLButtonElement).disabled).toBe(false)
    })
})
