/* water-heater-disabled-guard 3.4: the Heating tab stays reachable with a notice */
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { WaterTab } from '../WaterTab'
import { waterFieldList } from '../types'

const mockUseSettingsForm = vi.fn()

vi.mock('../hooks/useSettingsForm', () => ({
    useSettingsForm: (...args: unknown[]) => mockUseSettingsForm(...args),
}))

vi.mock('../hooks/useUnsavedChangesGuard', () => ({
    useUnsavedChangesGuard: () => ({ state: 'unblocked', reset: vi.fn(), location: null }),
}))

function setup(hasWaterHeater: boolean | undefined) {
    mockUseSettingsForm.mockReturnValue({
        config: { system: hasWaterHeater === undefined ? {} : { has_water_heater: hasWaterHeater } },
        form: {},
        fields: waterFieldList,
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
    return render(
        <MemoryRouter>
            <WaterTab />
        </MemoryRouter>,
    )
}

describe('WaterTab disabled notice', () => {
    beforeEach(() => vi.clearAllMocks())

    it('shows the notice and still renders the tab when the flag is off', () => {
        setup(false)
        expect(screen.getByTestId('water-heating-off-notice')).toHaveTextContent('Water heating is off')
        expect(screen.getByRole('button', { name: 'Save Heating Settings' })).toBeInTheDocument()
    })

    it.each([true, undefined])('shows no notice when the flag is %s', (flag) => {
        setup(flag)
        expect(screen.queryByTestId('water-heating-off-notice')).toBeNull()
    })
})
