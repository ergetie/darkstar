import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { UpdateCard } from './UpdateCard'
import { UpdateBanner } from './UpdateBanner'
import { Api, ApiError, type UpdaterStatus } from '../lib/api'
import { useUpdater, type UseUpdater } from '../lib/useUpdater'
import { renderHook, waitFor } from '@testing-library/react'

vi.mock('../lib/api', async (importOriginal) => {
    const original = await importOriginal<typeof import('../lib/api')>()
    return {
        ...original,
        Api: {
            version: vi.fn(),
            updater: {
                status: vi.fn(),
                check: vi.fn(),
                setChannel: vi.fn(),
                apply: vi.fn(),
                log: vi.fn(),
            },
        },
    }
})

// Node's built-in localStorage shadows jsdom's here; use an in-memory stand-in.
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

function status(overrides: Partial<UpdaterStatus> = {}): UpdaterStatus {
    return {
        reachable: true,
        channel: 'dev',
        current: { version: 'dev-1', commit: 'a' },
        target: { version: 'dev-2', commit: 'b', ref: 'origin/main' },
        update_available: true,
        commits: ['feat: something'],
        blocked: null,
        dirty_files: [],
        last_check: { ok: true, at: '2026-01-01T00:00:00Z' },
        last_success_at: '2026-01-01T00:00:00Z',
        apply: { state: 'idle' },
        ...overrides,
    }
}

function fakeUpdater(overrides: Partial<UseUpdater> = {}): UseUpdater {
    return {
        available: true,
        status: status(),
        error: null,
        busy: false,
        refresh: vi.fn(async () => status()),
        check: vi.fn(async () => undefined),
        setChannel: vi.fn(async () => undefined),
        apply: vi.fn(async () => true),
        ...overrides,
    }
}

beforeEach(() => {
    vi.stubGlobal('localStorage', makeMemoryStorage())
    vi.mocked(Api.updater.log).mockResolvedValue({ text: '', offset: 0 })
})

afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.clearAllMocks()
})

describe('UpdateCard', () => {
    it('shows versions, commits and applies only after confirm', async () => {
        const updater = fakeUpdater()
        render(<UpdateCard updater={updater} onClose={() => undefined} />)
        expect(screen.getByText('dev-1')).toBeTruthy()
        expect(screen.getByText('dev-2')).toBeTruthy()
        expect(screen.getByText('feat: something')).toBeTruthy()

        fireEvent.click(screen.getByRole('button', { name: 'Update' }))
        expect(updater.apply).not.toHaveBeenCalled()
        fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
        expect(updater.apply).not.toHaveBeenCalled()

        fireEvent.click(screen.getByRole('button', { name: 'Update' }))
        await act(async () => {
            fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
        })
        expect(updater.apply).toHaveBeenCalledTimes(1)
        expect(screen.getByText('Building...')).toBeTruthy()
    })

    it('disables Update and explains when blocked', () => {
        render(
            <UpdateCard
                updater={fakeUpdater({
                    status: status({ blocked: "Stable doesn't include your database version yet" }),
                })}
                onClose={() => undefined}
            />,
        )
        expect(screen.getByText("Stable doesn't include your database version yet")).toBeTruthy()
        expect((screen.getByRole('button', { name: 'Update' }) as HTMLButtonElement).disabled).toBe(true)
    })

    it('lists dirty files and disables Update', () => {
        render(
            <UpdateCard
                updater={fakeUpdater({ status: status({ dirty_files: ['VERSION'] }) })}
                onClose={() => undefined}
            />,
        )
        expect(screen.getByText('VERSION')).toBeTruthy()
        expect((screen.getByRole('button', { name: 'Update' }) as HTMLButtonElement).disabled).toBe(true)
    })

    it('explains an unreachable updater', () => {
        render(
            <UpdateCard
                updater={fakeUpdater({ status: { reachable: false, error: 'connection refused' } })}
                onClose={() => undefined}
            />,
        )
        expect(screen.getByText('Updater unavailable')).toBeTruthy()
        expect(screen.getByText('docker compose up -d updater')).toBeTruthy()
    })

    it('switches channel and checks on request', () => {
        const updater = fakeUpdater()
        render(<UpdateCard updater={updater} onClose={() => undefined} />)
        fireEvent.change(screen.getByRole('combobox'), { target: { value: 'stable' } })
        expect(updater.setChannel).toHaveBeenCalledWith('stable')
        fireEvent.click(screen.getByRole('button', { name: 'Check now' }))
        expect(updater.check).toHaveBeenCalled()
    })

    it('shows the failure and log tail of a failed update', () => {
        render(
            <UpdateCard
                updater={fakeUpdater({
                    status: status({
                        apply: { state: 'failed', message: 'Build failed', log_tail: ['step 3 error'] },
                    }),
                })}
                onClose={() => undefined}
            />,
        )
        expect(screen.getByText('Build failed')).toBeTruthy()
        expect(screen.getByText('step 3 error')).toBeTruthy()
    })

    it('polls through the restart and reloads once the target version is reported', async () => {
        vi.useFakeTimers()
        const reload = vi.fn()
        vi.stubGlobal('location', { ...window.location, reload })
        const refresh = vi
            .fn()
            .mockResolvedValueOnce(status({ apply: { state: 'restarting', target_version: 'dev-2' } }))
            .mockResolvedValueOnce(null) // backend down while restarting
            .mockResolvedValue(null)
        vi.mocked(Api.version).mockRejectedValueOnce(new Error('down')).mockResolvedValue({ version: 'dev-2' })
        vi.mocked(Api.updater.log).mockResolvedValueOnce({ text: 'building layer\n', offset: 15 })

        render(
            <UpdateCard
                updater={fakeUpdater({
                    refresh,
                    status: status({ apply: { state: 'building', target_version: 'dev-2' } }),
                })}
                onClose={() => undefined}
            />,
        )
        await act(async () => {
            await vi.advanceTimersByTimeAsync(2100)
        })
        expect(screen.getByText('building layer')).toBeTruthy()
        expect(reload).not.toHaveBeenCalled()
        await act(async () => {
            await vi.advanceTimersByTimeAsync(2000)
        })
        expect(screen.getByText('Restarting...')).toBeTruthy()
        await act(async () => {
            await vi.advanceTimersByTimeAsync(2000)
        })
        expect(reload).toHaveBeenCalled()
    })
})

describe('UpdateBanner', () => {
    it('is hidden when no update is ready or the feature is unavailable', () => {
        const { container, rerender } = render(
            <UpdateBanner updater={fakeUpdater({ available: false })} onOpen={vi.fn()} />,
        )
        expect(container.firstChild).toBeNull()
        rerender(<UpdateBanner updater={fakeUpdater({ status: status({ blocked: 'nope' }) })} onOpen={vi.fn()} />)
        expect(container.firstChild).toBeNull()
    })

    it('dismisses per target version and returns for a newer target', () => {
        const onOpen = vi.fn()
        const { rerender } = render(<UpdateBanner updater={fakeUpdater()} onOpen={onOpen} />)
        fireEvent.click(screen.getByRole('button', { name: 'View update' }))
        expect(onOpen).toHaveBeenCalled()
        fireEvent.click(screen.getByRole('button', { name: 'Dismiss update banner' }))
        expect(screen.queryByRole('status')).toBeNull()

        rerender(<UpdateBanner updater={fakeUpdater()} onOpen={onOpen} />)
        expect(screen.queryByRole('status')).toBeNull() // persisted

        rerender(
            <UpdateBanner
                updater={fakeUpdater({
                    status: status({ target: { version: 'dev-3', commit: 'c', ref: 'origin/main' } }),
                })}
                onOpen={onOpen}
            />,
        )
        expect(screen.getByText('Darkstar dev-3 is available.')).toBeTruthy()
    })
})

describe('useUpdater', () => {
    it('reports unavailable on 404 and available with status otherwise', async () => {
        vi.mocked(Api.updater.status).mockRejectedValueOnce(new ApiError('nope', 404))
        const hidden = renderHook(() => useUpdater())
        await waitFor(() => expect(Api.updater.status).toHaveBeenCalled())
        expect(hidden.result.current.available).toBe(false)

        vi.mocked(Api.updater.status).mockResolvedValueOnce(status())
        const shown = renderHook(() => useUpdater())
        await waitFor(() => expect(shown.result.current.available).toBe(true))
        expect(shown.result.current.status?.target?.version).toBe('dev-2')
    })

    it('surfaces an apply refusal with the file list', async () => {
        vi.mocked(Api.updater.status).mockResolvedValue(status())
        vi.mocked(Api.updater.apply).mockRejectedValueOnce(
            new ApiError('x', 409, { error: 'Local changes', files: ['VERSION'] }),
        )
        const { result } = renderHook(() => useUpdater())
        await waitFor(() => expect(result.current.available).toBe(true))
        let ok = true
        await act(async () => {
            ok = await result.current.apply()
        })
        expect(ok).toBe(false)
        expect(result.current.error).toBe('Local changes: VERSION')
    })
})
