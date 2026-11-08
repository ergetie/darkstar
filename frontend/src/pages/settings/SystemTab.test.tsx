import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
    listProfiles: vi.fn(),
    recalculatePrices: vi.fn(),
    toast: vi.fn(),
    useSettingsForm: vi.fn(),
    handleChange: vi.fn(),
    save: vi.fn(),
}))

vi.mock('../../lib/api', () => ({
    Api: { listProfiles: mocked.listProfiles, recalculatePrices: mocked.recalculatePrices },
}))
vi.mock('../../lib/useToast', () => ({ useToast: () => ({ toast: mocked.toast, dismiss: vi.fn() }) }))
vi.mock('./hooks/useSettingsForm', () => ({ useSettingsForm: mocked.useSettingsForm }))
vi.mock('./hooks/useUnsavedChangesGuard', () => ({
    useUnsavedChangesGuard: () => ({ state: 'unblocked', reset: vi.fn(), location: null }),
}))
vi.mock('./components/ProfileSetupHelper', () => ({ ProfileSetupHelper: () => null }))

import { SystemTab } from './SystemTab'
import { systemFieldList } from './types'

const genericProfile = {
    name: 'generic',
    description: 'Generic inverter',
    supported_brands: [],
    version: '1',
    schema_version: 2,
    entities: {},
    modes: {},
    behavior: { control_unit: 'W' as const },
}

describe('SystemTab installation statistics controls', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        mocked.listProfiles.mockResolvedValue([genericProfile])
        const form = Object.fromEntries(
            systemFieldList.map((field) => [
                field.key,
                field.key === 'installation_stats.enabled'
                    ? 'true'
                    : field.key === 'installation_stats.endpoint'
                      ? 'https://telemetry.wxl.se/api/ping'
                      : '',
            ]),
        )
        mocked.useSettingsForm.mockReturnValue({
            config: { system: { inverter_profile: 'generic' } },
            form,
            fields: systemFieldList,
            fieldErrors: {},
            loading: false,
            saving: false,
            statusMessage: null,
            haEntities: [],
            haLoading: false,
            handleChange: mocked.handleChange,
            save: mocked.save,
            reloadEntities: vi.fn(),
            isDirty: false,
        })
    })

    it('shows default enabled reporting and an editable endpoint in normal mode', async () => {
        render(
            <MemoryRouter>
                <SystemTab />
            </MemoryRouter>,
        )

        expect(await screen.findByText('Installation statistics')).toBeInTheDocument()
        expect(screen.getByDisplayValue('https://telemetry.wxl.se/api/ping')).toBeInTheDocument()
        const toggle = document.querySelector('[data-field-key="installation_stats.enabled"] .toggle')
        expect(toggle).toHaveClass('active')
        expect(toggle).toBeVisible()
        expect(
            screen.getByText(/daily heartbeat includes a random installation ID, version, release channel/i),
        ).toBeInTheDocument()
        expect(screen.getByText(/executor mode \(shadow, live, or unknown\)/i)).toBeInTheDocument()

        fireEvent.change(screen.getByDisplayValue('https://telemetry.wxl.se/api/ping'), {
            target: { value: 'https://stats.example/ping' },
        })
        expect(mocked.handleChange).toHaveBeenCalledWith('installation_stats.endpoint', 'https://stats.example/ping')
    })
})

describe('SystemTab pricing groups and cost recalculation', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        mocked.listProfiles.mockResolvedValue([genericProfile])
        mocked.recalculatePrices.mockResolvedValue({ from_date: '2026-10-01', repriced: 2880, skipped: 3 })
        mocked.useSettingsForm.mockReturnValue({
            config: { system: { inverter_profile: 'generic' } },
            form: Object.fromEntries(systemFieldList.map((field) => [field.key, ''])),
            fields: systemFieldList,
            fieldErrors: {},
            loading: false,
            saving: false,
            statusMessage: null,
            haEntities: [],
            haLoading: false,
            handleChange: mocked.handleChange,
            save: mocked.save,
            reloadEntities: vi.fn(),
            isDirty: false,
        })
    })

    const renderTab = () =>
        render(
            <MemoryRouter>
                <SystemTab advancedMode />
            </MemoryRouter>,
        )

    it('groups pricing into Grid operator and Electricity supplier with excl. VAT labels', async () => {
        renderTab()
        await screen.findByText('Grid operator')
        expect(screen.getByText('Electricity supplier')).toBeInTheDocument()
        expect(screen.getByText('Monthly subscription fee (SEK, excl. VAT)')).toBeInTheDocument()
        expect(screen.getByText('Energy tax (SEK/kWh, excl. VAT)')).toBeInTheDocument()
        expect(screen.getByText('Yearly supplier fee (SEK, excl. VAT)')).toBeInTheDocument()
        expect(screen.getByText('Supplier markup (SEK/kWh, excl. VAT)')).toBeInTheDocument()
        expect(screen.getByText('VAT (%)')).toBeInTheDocument()
        expect(screen.queryByText(/\[FUTURE\]/)).not.toBeInTheDocument()
    })

    it('documents the learning metric step next to the recalculate action', async () => {
        renderTab()
        expect(await screen.findByText(/learning plan-versus-actual cost metric shows a step/i)).toBeInTheDocument()
    })

    it('confirms in a modal before recalculating and toasts the counts', async () => {
        renderTab()
        const dateInput = (await screen.findByTestId('recalculate-costs')).querySelector('input[type="date"]')
        fireEvent.change(dateInput as Element, { target: { value: '2026-10-01' } })
        fireEvent.click(screen.getByRole('button', { name: 'Recalculate costs from 2026-10-01' }))

        expect(mocked.recalculatePrices).not.toHaveBeenCalled()
        fireEvent.click(await screen.findByRole('button', { name: 'Yes, Recalculate' }))

        await waitFor(() => expect(mocked.recalculatePrices).toHaveBeenCalledWith('2026-10-01'))
        await waitFor(() =>
            expect(mocked.toast).toHaveBeenCalledWith({
                message: 'Costs recalculated from 2026-10-01: 2880 slots repriced, 3 skipped',
                variant: 'success',
            }),
        )
    })

    it('toasts an error when recalculation fails', async () => {
        mocked.recalculatePrices.mockRejectedValue(new Error('boom'))
        renderTab()
        fireEvent.click(await screen.findByRole('button', { name: /Recalculate costs from/ }))
        fireEvent.click(await screen.findByRole('button', { name: 'Yes, Recalculate' }))
        await waitFor(() =>
            expect(mocked.toast).toHaveBeenCalledWith({
                message: 'Recalculation failed: boom',
                variant: 'error',
            }),
        )
    })
})
