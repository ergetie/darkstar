import { render, screen, fireEvent, act, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { SystemAlert, type HealthStatus, type HealthIssue } from './SystemAlert'
import { Api } from '../lib/api'

vi.mock('../lib/api', () => ({
    Api: { acknowledgeHealthIssue: vi.fn() },
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

beforeEach(() => {
    vi.stubGlobal('localStorage', makeMemoryStorage())
    vi.mocked(Api.acknowledgeHealthIssue).mockReset()
})

function issue(overrides: Partial<HealthIssue> = {}): HealthIssue {
    return {
        category: 'monitors',
        severity: 'warning',
        message: 'Something is off',
        guidance: 'Check it out',
        ...overrides,
    }
}

function status(issues: HealthIssue[]): HealthStatus {
    return {
        healthy: issues.length === 0,
        issues,
        checked_at: '2026-07-18T00:00:00Z',
        critical_count: issues.filter((i) => i.severity === 'critical').length,
        warning_count: issues.filter((i) => i.severity === 'warning').length,
    }
}

describe('SystemAlert snooze', () => {
    it('snoozing hides only the snoozed issue', () => {
        const a = issue({ code: 'INVARIANT_A', message: 'Issue A' })
        const b = issue({ code: 'INVARIANT_B', message: 'Issue B' })
        render(<SystemAlert health={status([a, b])} />)

        expect(screen.getByText('Issue A')).toBeInTheDocument()
        expect(screen.getByText('Issue B')).toBeInTheDocument()

        const snoozeButtons = screen.getAllByTitle('Snooze for 24 hours')
        fireEvent.click(snoozeButtons[0])

        expect(screen.queryByText('Issue A')).not.toBeInTheDocument()
        expect(screen.getByText('Issue B')).toBeInTheDocument()
    })

    it('expired snooze re-renders the banner', () => {
        const a = issue({ code: 'INVARIANT_A', message: 'Issue A' })

        vi.useFakeTimers()
        try {
            render(<SystemAlert health={status([a])} />)
            fireEvent.click(screen.getByTitle('Snooze for 24 hours'))
            expect(screen.queryByText('Issue A')).not.toBeInTheDocument()

            // the component refreshes its internal clock every 60s; advance
            // past the 24h snooze window so the expiry check re-evaluates
            act(() => {
                vi.advanceTimersByTime(24 * 60 * 60 * 1000 + 60_000)
            })

            expect(screen.getByText('Issue A')).toBeInTheDocument()
        } finally {
            vi.useRealTimers()
        }
    })

    it('message-number changes do not defeat the snooze', () => {
        const a = issue({ code: 'INVARIANT_A', message: 'tick success 98.64%' })
        const { rerender } = render(<SystemAlert health={status([a])} />)
        fireEvent.click(screen.getByTitle('Snooze for 24 hours'))
        expect(screen.queryByText('tick success 98.64%')).not.toBeInTheDocument()

        const aChanged = issue({ code: 'INVARIANT_A', message: 'tick success 98.71%' })
        rerender(<SystemAlert health={status([aChanged])} />)

        expect(screen.queryByText('tick success 98.71%')).not.toBeInTheDocument()
    })

    it('the snoozed chip restores banners', () => {
        const a = issue({ code: 'INVARIANT_A', message: 'Issue A' })
        const { rerender } = render(<SystemAlert health={status([a])} />)
        fireEvent.click(screen.getByTitle('Snooze for 24 hours'))
        expect(screen.queryByText('Issue A')).not.toBeInTheDocument()

        rerender(<SystemAlert health={status([a])} />)
        const chip = screen.getByText('1 snoozed')
        fireEvent.click(chip)

        rerender(<SystemAlert health={status([a])} />)
        expect(screen.getByText('Issue A')).toBeInTheDocument()
    })

    it('falls back to category when no code is present', () => {
        const a = issue({ category: 'forecast', code: undefined, message: 'No code here' })
        const { rerender } = render(<SystemAlert health={status([a])} />)
        fireEvent.click(screen.getByTitle('Snooze for 24 hours'))
        expect(screen.queryByText('No code here')).not.toBeInTheDocument()

        rerender(<SystemAlert health={status([a])} />)
        expect(screen.getByText('1 snoozed')).toBeInTheDocument()
    })

    it('critical issues can be snoozed too', () => {
        const c = issue({ severity: 'critical', code: 'CRIT_A', message: 'Critical issue' })
        render(<SystemAlert health={status([c])} />)
        fireEvent.click(screen.getByTitle('Snooze for 24 hours'))
        expect(screen.queryByText('Critical issue')).not.toBeInTheDocument()
    })
})

describe('SystemAlert acknowledgeable info notices', () => {
    const notice = () =>
        issue({
            category: 'forecast',
            severity: 'info',
            code: 'pv_site_ratio_low',
            acknowledge_id: 'pv_site_ratio_low',
            message: 'Your solar panels produce much less than forecast on clear days (about 40 % of forecast).',
            guidance: 'This can be shading.',
        })

    it('renders an info issue with acknowledge_id as an info banner', () => {
        const { container } = render(<SystemAlert health={status([notice()])} />)

        expect(screen.getByText(/much less than forecast on clear days/)).toBeInTheDocument()
        expect(screen.getByText(/This can be shading/)).toBeInTheDocument()
        expect(container.querySelector('.banner.banner-info')).not.toBeNull()
    })

    it('Got it acknowledges via the API and hides the notice', async () => {
        vi.mocked(Api.acknowledgeHealthIssue).mockResolvedValue({ id: 'pv_site_ratio_low' })
        render(<SystemAlert health={status([notice()])} />)

        fireEvent.click(screen.getByRole('button', { name: 'Got it' }))

        await waitFor(() => expect(screen.queryByText(/much less than forecast/)).not.toBeInTheDocument())
        expect(Api.acknowledgeHealthIssue).toHaveBeenCalledWith('pv_site_ratio_low')
    })

    it('keeps the notice visible when the API call fails', async () => {
        vi.mocked(Api.acknowledgeHealthIssue).mockRejectedValue(new Error('boom'))
        const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
        render(<SystemAlert health={status([notice()])} />)

        fireEvent.click(screen.getByRole('button', { name: 'Got it' }))

        await waitFor(() => expect(consoleError).toHaveBeenCalled())
        expect(screen.getByText(/much less than forecast/)).toBeInTheDocument()
        consoleError.mockRestore()
    })

    it('does not render an info issue without acknowledge_id', () => {
        const { container } = render(
            <SystemAlert health={status([issue({ severity: 'info', message: 'Plain info' })])} />,
        )

        expect(screen.queryByText('Plain info')).not.toBeInTheDocument()
        expect(container).toBeEmptyDOMElement()
    })
})
