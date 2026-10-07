import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
    listProfiles: vi.fn(),
    useSettingsForm: vi.fn(),
    handleChange: vi.fn(),
    save: vi.fn(),
}))

vi.mock('../../lib/api', () => ({ Api: { listProfiles: mocked.listProfiles } }))
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
