/* load-balancing-completion 6.6: slow-tick warning visibility in the tab */
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { LoadBalancingTab } from '../LoadBalancingTab'
import { loadBalancingFieldList } from '../types'

const mockUseSettingsForm = vi.fn()

vi.mock('../hooks/useSettingsForm', () => ({
    useSettingsForm: (...args: unknown[]) => mockUseSettingsForm(...args),
}))

vi.mock('../hooks/useUnsavedChangesGuard', () => ({
    useUnsavedChangesGuard: () => ({ state: 'unblocked', reset: vi.fn(), location: null }),
}))

function makeFormState(overrides: Record<string, string> = {}): Record<string, string> {
    const form: Record<string, string> = {}
    loadBalancingFieldList.forEach((field) => {
        form[field.key] =
            field.type === 'boolean'
                ? 'false'
                : field.type === 'balanced_loads' || field.type === 'give_way_list'
                  ? '[]'
                  : ''
    })
    return { ...form, ...overrides }
}

function setupForm({ enabled, intervalSeconds }: { enabled: boolean; intervalSeconds: number }) {
    mockUseSettingsForm.mockReturnValue({
        config: {
            executor: { interval_seconds: intervalSeconds },
            ev_chargers: [],
            water_heaters: [],
        },
        form: makeFormState({ 'load_balancing.enabled': enabled ? 'true' : 'false' }),
        fieldErrors: {},
        loading: false,
        saving: false,
        statusMessage: '',
        handleChange: vi.fn(),
        save: vi.fn(),
        isDirty: false,
        haEntities: [],
        haLoading: false,
    })
}

function renderTab() {
    return render(
        <MemoryRouter>
            <LoadBalancingTab />
        </MemoryRouter>,
    )
}

describe('LoadBalancingTab slow-tick warning', () => {
    beforeEach(() => {
        mockUseSettingsForm.mockReset()
    })

    it('warns when load balancing is enabled with a slow executor tick', () => {
        setupForm({ enabled: true, intervalSeconds: 300 })
        renderTab()
        const warning = screen.getByRole('alert')
        expect(warning).toHaveTextContent('executor.interval_seconds')
        expect(warning).toHaveTextContent('load_balancing.enabled')
        expect(warning).toHaveTextContent('15 s or less')
    })

    it('does not warn with a fast tick', () => {
        setupForm({ enabled: true, intervalSeconds: 5 })
        renderTab()
        expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })

    it('does not warn while load balancing is disabled', () => {
        setupForm({ enabled: false, intervalSeconds: 300 })
        renderTab()
        expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })
})
