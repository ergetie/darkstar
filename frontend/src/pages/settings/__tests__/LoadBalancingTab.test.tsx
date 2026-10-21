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
        fields: loadBalancingFieldList,
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

it('shows coordination settings and their help text in the advanced view', () => {
    setupForm({ enabled: true, intervalSeconds: 5 })
    render(
        <MemoryRouter>
            <LoadBalancingTab advancedMode />
        </MemoryRouter>,
    )
    expect(screen.getByText('Coordination & Wear')).toBeInTheDocument()
    expect(screen.getByText('Max time between ramp-up steps (seconds)')).toBeInTheDocument()
    expect(screen.getByText('Write deadband (%)')).toBeInTheDocument()
    expect(screen.getByText('Pending increase timeout (seconds)')).toBeInTheDocument()
    expect(screen.getByText('Phase sensor sign')).toBeInTheDocument()
})

it.each([
    ['typ_c', '80'],
    ['diazed_gg', '65'],
    ['custom', '80'],
])('shows preset %s and its safety placeholder', (preset, safety) => {
    setupForm({ enabled: true, intervalSeconds: 5 })
    const state = mockUseSettingsForm.getMockImplementation()!()
    mockUseSettingsForm.mockReturnValue({ ...state, form: { ...state.form, 'load_balancing.fuse_preset': preset } })
    renderTab()
    expect(screen.getByRole('spinbutton', { name: 'Intervene at (% of estimated fuse heat)' })).toHaveAttribute(
        'placeholder',
        safety,
    )
    expect(screen.queryByText('Pause delay (seconds)')).not.toBeInTheDocument()
    expect(screen.queryByText('Immediate pause above (% of fuse)')).not.toBeInTheDocument()
    if (preset === 'custom') {
        expect(screen.getByLabelText('Custom point 1 overload (%)')).toHaveValue(130)
        expect(screen.getByLabelText('Custom point 1 trip time (s)')).toHaveValue(1200)
        expect(screen.getByLabelText('Custom point 2 overload (%)')).toHaveValue(300)
        expect(screen.getByLabelText('Custom point 2 trip time (s)')).toHaveValue(4)
    } else {
        expect(screen.queryByLabelText('Custom point 1 overload (%)')).not.toBeInTheDocument()
    }
})

it('includes the fuse characteristic graph directly in Overload Handling', () => {
    setupForm({ enabled: false, intervalSeconds: 5 })
    renderTab()
    const graph = screen.getByRole('img', { name: /Typ C fuse characteristics/ })
    expect(graph.closest('figure')?.parentElement).toHaveTextContent('Overload Handling')
})

it('uses separate protected-fuse and grid-connection ratings', () => {
    const protectedFuse = loadBalancingFieldList.find((field) => field.key === 'load_balancing.protected_fuse_a')
    expect(protectedFuse?.label).toBe('Protected fuse (A)')
    expect(protectedFuse?.path).toEqual(['load_balancing', 'protected_fuse_a'])
    expect(loadBalancingFieldList.some((field) => field.key === 'system.grid.main_fuse_a')).toBe(false)
    expect(loadBalancingFieldList.find((field) => field.key === 'input_sensors.grid_current_l1')?.label).toBe(
        'Phase current/power sensor — L1',
    )
})
