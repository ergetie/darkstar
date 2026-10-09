import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
    config: vi.fn(),
    listProfiles: vi.fn(),
    useSettingsForm: vi.fn(),
    jumpToField: vi.fn((_key: string, _onSettled?: () => void) => () => {}),
    dirty: false,
    configResponse: {} as Record<string, unknown>,
}))

vi.mock('../../lib/api', () => ({
    Api: { config: mocked.config, listProfiles: mocked.listProfiles },
}))
vi.mock('../../lib/useToast', () => ({ useToast: () => ({ toast: vi.fn() }) }))
vi.mock('./hooks/useSettingsForm', () => ({
    useSettingsForm: (fields: { key: string }[]) => mocked.useSettingsForm(fields),
}))
vi.mock('./search/SettingsSearch', () => ({ SettingsSearch: () => null }))
vi.mock('./search/jump', () => ({
    jumpToField: (key: string, onSettled?: () => void) => mocked.jumpToField(key, onSettled),
}))
vi.mock('./ParametersTab', () => ({ ParametersTab: () => <div>parameters-tab</div> }))
vi.mock('./SolarTab', () => ({ SolarTab: () => <div>solar-tab</div> }))
vi.mock('./BatteryTab', () => ({ BatteryTab: () => <div>battery-tab</div> }))
vi.mock('./EVTab', () => ({ EVTab: () => <div>ev-tab</div> }))
vi.mock('./LoadBalancingTab', () => ({ LoadBalancingTab: () => <div>load-balancing-tab</div> }))
vi.mock('./UITab', () => ({ UITab: () => <div>ui-tab</div> }))
vi.mock('../Debug', () => ({ DebugContent: () => null }))
vi.mock('./components/SettingsField', async (importOriginal) => {
    const actual = await importOriginal<typeof import('./components/SettingsField')>()
    return {
        SettingsField: (props: React.ComponentProps<typeof actual.SettingsField>) =>
            props.field.key === 'water_heaters' ? (
                <actual.SettingsField {...props} />
            ) : (
                <div data-testid={`field-${props.field.key}`}>{props.field.label}</div>
            ),
    }
})
vi.mock('./components/ProfileSetupHelper', () => ({ ProfileSetupHelper: () => null }))
vi.mock('./components/AdvancedLockedNotice', () => ({
    AdditionalAdvancedNotice: () => null,
    GlobalAdvancedLockedNotice: () => null,
}))
vi.mock('./components/UnsavedChangesBanner', () => ({ UnsavedChangesBanner: () => null }))

import Settings from './index'

function makeMemoryStorage(): Storage {
    const store = new Map<string, string>()
    return {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => void store.set(key, value),
        removeItem: (key: string) => void store.delete(key),
        clear: () => store.clear(),
        key: (i: number) => Array.from(store.keys())[i] ?? null,
        get length() {
            return store.size
        },
    }
}

function renderAt(url: string) {
    const router = createMemoryRouter([{ path: '/settings', element: <Settings /> }], { initialEntries: [url] })
    render(<RouterProvider router={router} />)
    return router
}

describe('Settings navigation', () => {
    beforeEach(() => {
        vi.stubGlobal('localStorage', makeMemoryStorage())
        mocked.dirty = false
        mocked.configResponse = {
            system: {
                has_solar: false,
                has_battery: false,
                has_ev_charger: false,
                has_water_heater: false,
                inverter_profile: 'generic',
            },
        }
        mocked.config.mockResolvedValue(mocked.configResponse)
        mocked.listProfiles.mockResolvedValue([
            {
                name: 'generic',
                description: 'Generic inverter',
                supported_brands: [],
                version: '1',
                schema_version: 2,
                entities: {},
                modes: {},
                behavior: { control_unit: 'W' },
            },
        ])
        mocked.useSettingsForm.mockImplementation((fields: { key: string }[]) => ({
            config: mocked.configResponse,
            form: Object.fromEntries(
                fields.map(({ key }) => [key, key === 'system.inverter_profile' ? 'generic' : '']),
            ),
            fields,
            fieldErrors: {},
            loading: false,
            saving: false,
            statusMessage: null,
            handleChange: vi.fn(),
            save: vi.fn(async () => true),
            reload: vi.fn(async () => {}),
            reloadEntities: vi.fn(),
            isDirty: mocked.dirty,
            haEntities: [],
            haLoading: false,
        }))
    })

    it('keeps feature configuration tabs reachable while those features are disabled', async () => {
        const router = renderAt('/settings?tab=system')

        for (const [label, tabId, content] of [
            ['Solar', 'solar', 'solar-tab'],
            ['Battery', 'battery', 'battery-tab'],
            ['EV', 'ev', 'ev-tab'],
            ['Heating', 'water', 'Heating Devices'],
        ]) {
            const tab = await screen.findByRole('button', { name: label })
            fireEvent.click(tab)
            expect(await screen.findByText(content)).toBeInTheDocument()
            expect(screen.getByRole('button', { name: label })).toHaveClass('bg-accent')
            expect(router.state.location.search).toBe(`?tab=${tabId}`)
        }
        expect(screen.getByRole('button', { name: 'Add Heater' })).toBeEnabled()
    })

    it('keeps the unsaved-change guard when switching to a visible feature tab', async () => {
        mocked.dirty = true
        const router = renderAt('/settings?tab=system')

        expect(await screen.findByText('System Profile')).toBeInTheDocument()
        fireEvent.click(await screen.findByRole('button', { name: 'Battery' }))
        expect(await screen.findByText('Unsaved Changes')).toBeInTheDocument()
        expect(router.state.location.search).toBe('?tab=system')

        fireEvent.click(screen.getByRole('button', { name: 'Stay' }))
        await waitFor(() => expect(screen.queryByText('Unsaved Changes')).not.toBeInTheDocument())
        expect(screen.getByText('System Profile')).toBeInTheDocument()

        fireEvent.click(screen.getByRole('button', { name: 'Battery' }))
        fireEvent.click(await screen.findByRole('button', { name: 'Discard & Leave' }))
        expect(await screen.findByText('battery-tab')).toBeInTheDocument()
        expect(router.state.location.search).toBe('?tab=battery')
    })

    it('keeps Excess PV Dispatch editable while solar is disabled', async () => {
        renderAt('/settings?tab=advanced&field=executor.excess_pv.priority')

        expect(await screen.findByText('Excess PV Dispatch')).toBeInTheDocument()
        expect(screen.getByText('Sink priority list')).toBeInTheDocument()
    })
})
