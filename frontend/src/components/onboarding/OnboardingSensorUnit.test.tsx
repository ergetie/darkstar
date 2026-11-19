import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { UNITLESS_ENTITY, fakeSensorUnits } from '../../test/sensorUnitsMock'

const api = vi.hoisted(() => ({
    config: vi.fn(),
    configSave: vi.fn(),
    listProfiles: vi.fn(),
    profileSuggestions: vi.fn(),
    haDiscovery: vi.fn(),
    haCoreConfig: vi.fn(),
    suggestions: vi.fn(),
    readiness: vi.fn(),
    onboarding: vi.fn(),
    saveOnboarding: vi.fn(),
    sensorUnits: vi.fn(),
}))

vi.mock('../../lib/api', () => ({
    Api: {
        config: api.config,
        configSave: api.configSave,
        listProfiles: api.listProfiles,
        profileSuggestions: api.profileSuggestions,
        haDiscovery: api.haDiscovery,
        haCoreConfig: api.haCoreConfig,
        setup: {
            suggestions: api.suggestions,
            readiness: api.readiness,
            onboarding: api.onboarding,
            saveOnboarding: api.saveOnboarding,
            sensorUnits: api.sensorUnits,
        },
    },
    ApiError: class ApiError extends Error {},
}))

import { OnboardingWizard } from './OnboardingWizard'

const profile = {
    name: 'generic',
    description: 'Generic inverter',
    supported_brands: [],
    version: '1',
    schema_version: 2,
    entities: {},
    modes: {},
    behavior: { control_unit: 'W' as const },
}

const discovery = [
    { entity_id: UNITLESS_ENTITY, friendly_name: 'Unitless power', domain: 'sensor', state: '1200' },
    {
        entity_id: 'sensor.watts',
        friendly_name: 'Watt power',
        domain: 'sensor',
        state: '1200',
        unit_of_measurement: 'W',
    },
]

function config(loadPower: string) {
    return {
        system: {
            inverter_profile: 'generic',
            has_solar: false,
            has_battery: false,
            has_water_heater: false,
            has_ev_charger: false,
            grid_meter_type: 'net',
            grid: { max_power_kw: 5, main_fuse_a: 25 },
            location: { latitude: 59.3, longitude: 18 },
        },
        nordpool: { price_area: 'SE3', currency: 'SEK' },
        timezone: 'Europe/Stockholm',
        pricing: { vat_percent: 25, energy_tax_sek: 0.5, grid_transfer_fee_sek: 0.1 },
        installation_stats: { enabled: true, endpoint: 'https://telemetry.wxl.se/api/ping' },
        battery: { capacity_kwh: 8, min_soc_percent: 10, max_soc_percent: 90 },
        input_sensors: { load_power: loadPower, grid_power: 'sensor.watts' },
        sensor_unit_overrides: {},
        executor: { shadow_mode: true },
    }
}

function setup(step: string, loadPower: string, readiness: unknown = { ready: true, checks: [] }) {
    api.config.mockResolvedValue(config(loadPower))
    api.configSave.mockResolvedValue({ warnings: [] })
    api.listProfiles.mockResolvedValue([profile])
    api.profileSuggestions.mockResolvedValue({ patch: {}, candidates: {}, current: {}, missing_required: [] })
    api.haDiscovery.mockResolvedValue({ entities: discovery, registry_available: true })
    api.haCoreConfig.mockResolvedValue({
        latitude: 59.3,
        longitude: 18,
        time_zone: 'Europe/Stockholm',
        currency: 'SEK',
    })
    api.suggestions.mockResolvedValue({ patch: {}, candidates: {}, missing_required: [], brands: [] })
    api.readiness.mockResolvedValue(readiness)
    api.onboarding.mockResolvedValue({ status: 'in_progress', current_step: step, completed_steps: ['connect'] })
    api.saveOnboarding.mockImplementation(async (value) => value)
    api.sensorUnits.mockImplementation(async (draft) => fakeSensorUnits(draft))
    render(<OnboardingWizard onClose={vi.fn()} />)
}

describe('OnboardingWizard sensor units', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        Element.prototype.scrollIntoView = vi.fn()
        window.history.pushState({}, '', '/')
    })

    it('asks the backend about the onboarding draft and shows the selector for a unitless sensor', async () => {
        setup('sensors', UNITLESS_ENTITY)

        expect(await screen.findByTestId('sensor-unit-select')).toBeInTheDocument()
        expect(api.sensorUnits).toHaveBeenCalledWith(
            expect.objectContaining({ input_sensors: expect.objectContaining({ load_power: UNITLESS_ENTITY }) }),
        )
    })

    it('shows no selector for a sensor that reports a unit', async () => {
        setup('sensors', 'sensor.watts')

        await screen.findByRole('heading', { name: 'Core sensors' })
        await waitFor(() => expect(api.sensorUnits).toHaveBeenCalled())
        expect(screen.queryByTestId('sensor-unit-select')).not.toBeInTheDocument()
    })

    it('saves the chosen unit with the step and the draft carries it to the next check', async () => {
        setup('sensors', UNITLESS_ENTITY)
        await screen.findByTestId('sensor-unit-select')

        fireEvent.click(screen.getByRole('button', { name: 'W' }))
        await waitFor(() =>
            expect(api.sensorUnits).toHaveBeenLastCalledWith(
                expect.objectContaining({ sensor_unit_overrides: { [UNITLESS_ENTITY]: 'W' } }),
            ),
        )
        fireEvent.click(screen.getByRole('button', { name: 'Next' }))

        await waitFor(() =>
            expect(api.configSave).toHaveBeenCalledWith(
                expect.objectContaining({ sensor_unit_overrides: { [UNITLESS_ENTITY]: 'W' } }),
            ),
        )
    })

    it('does not send overrides when none were chosen', async () => {
        setup('sensors', UNITLESS_ENTITY)
        await screen.findByTestId('sensor-unit-select')

        fireEvent.click(screen.getByRole('button', { name: 'Next' }))

        await waitFor(() => expect(api.configSave).toHaveBeenCalled())
        expect(api.configSave.mock.calls[0][0]).not.toHaveProperty('sensor_unit_overrides')
    })

    it('navigates from the readiness "Set unit" action to the step that owns the sensor', async () => {
        setup('review', UNITLESS_ENTITY, {
            ready: true,
            checks: [
                {
                    id: 'load_power',
                    group: 'sensors',
                    status: 'warn',
                    message: 'load_power: no unit reported by Home Assistant. Choose W or kW for this sensor.',
                    fix_hint: 'Choose W or kW.',
                    settings_path: 'input_sensors.load_power',
                    action: { kind: 'set_sensor_unit', entity_id: UNITLESS_ENTITY, path: 'input_sensors.load_power' },
                },
                {
                    id: 'other',
                    group: 'sensors',
                    status: 'warn',
                    message: 'Another warning',
                    fix_hint: '',
                    settings_path: 'input_sensors.load_power',
                },
            ],
        })
        expect(await screen.findByText(/no unit reported by Home Assistant/)).toBeInTheDocument()
        expect(screen.getAllByRole('button', { name: 'Set unit' })).toHaveLength(1)

        fireEvent.click(screen.getByRole('button', { name: 'Set unit' }))

        expect(await screen.findByRole('heading', { name: 'Core sensors' })).toBeInTheDocument()
        await waitFor(() =>
            expect(api.saveOnboarding).toHaveBeenLastCalledWith(expect.objectContaining({ current_step: 'sensors' })),
        )
        expect(await screen.findByTestId('sensor-unit-select')).toBeInTheDocument()
    })
})
