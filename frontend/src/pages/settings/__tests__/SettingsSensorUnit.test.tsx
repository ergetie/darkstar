import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { UNITLESS_ENTITY, fakeSensorUnits } from '../../../test/sensorUnitsMock'

const api = vi.hoisted(() => ({
    config: vi.fn(),
    haEntities: vi.fn(),
    configSave: vi.fn(),
    sensorUnits: vi.fn(),
}))

vi.mock('../../../lib/api', () => ({
    ApiError: class ApiError extends Error {},
    Api: {
        config: api.config,
        haEntities: api.haEntities,
        configSave: api.configSave,
        setup: { sensorUnits: api.sensorUnits },
    },
}))
vi.mock('../../../lib/useToast', () => ({ useToast: () => ({ toast: vi.fn() }) }))

import { SensorUnitContext } from '../../../lib/sensorUnits'
import { SettingsField } from '../components/SettingsField'
import { useSettingsForm } from '../hooks/useSettingsForm'
import type { BaseField } from '../types'

const fields: BaseField[] = [
    {
        key: 'input_sensors.load_power',
        label: 'House load power',
        path: ['input_sensors', 'load_power'],
        type: 'entity',
    },
]

function Harness() {
    const form = useSettingsForm(fields, [])
    return (
        <SensorUnitContext.Provider value={form.sensorUnits}>
            <SettingsField
                field={fields[0]}
                value={form.form[fields[0].key] ?? ''}
                onChange={form.handleChange}
                haEntities={form.haEntities}
                config={form.config as unknown as Record<string, unknown>}
            />
            <button type="button" onClick={() => void form.save()}>
                Save
            </button>
            <span data-testid="dirty">{String(form.isDirty)}</span>
        </SensorUnitContext.Provider>
    )
}

function setup(loadPower: string) {
    api.config.mockResolvedValue({ input_sensors: { load_power: loadPower }, sensor_unit_overrides: {} })
    api.haEntities.mockResolvedValue({
        entities: [
            { entity_id: UNITLESS_ENTITY, friendly_name: 'Unitless power', domain: 'sensor', state: '1200' },
            {
                entity_id: 'sensor.watts',
                friendly_name: 'Watt power',
                domain: 'sensor',
                state: '1200',
                unit_of_measurement: 'W',
            },
        ],
    })
    api.configSave.mockResolvedValue({ status: 'success' })
    api.sensorUnits.mockImplementation(async (draft) => fakeSensorUnits(draft))
    render(<Harness />)
}

describe('Settings sensor unit selector', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        Element.prototype.scrollIntoView = vi.fn()
        vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    })

    it('asks the backend about the settings draft and shows the selector for a unitless sensor', async () => {
        setup(UNITLESS_ENTITY)

        expect(await screen.findByTestId('sensor-unit-select')).toBeInTheDocument()
        expect(api.sensorUnits).toHaveBeenCalledWith(
            expect.objectContaining({ input_sensors: { load_power: UNITLESS_ENTITY } }),
        )
    })

    it('shows no selector for a sensor that reports a unit', async () => {
        setup('sensor.watts')

        await waitFor(() => expect(api.sensorUnits).toHaveBeenCalled())
        expect(await screen.findByText('Watt power')).toBeInTheDocument()
        expect(screen.queryByTestId('sensor-unit-select')).not.toBeInTheDocument()
    })

    it('checks the unsaved selection, not only the saved config', async () => {
        setup('sensor.watts')
        await screen.findByText('Watt power')

        fireEvent.click(screen.getByRole('button', { name: /Watt power/ }))
        fireEvent.click(screen.getByText('Unitless power'))

        expect(await screen.findByTestId('sensor-unit-select')).toBeInTheDocument()
        expect(api.sensorUnits).toHaveBeenLastCalledWith(
            expect.objectContaining({ input_sensors: { load_power: UNITLESS_ENTITY } }),
        )
    })

    it('marks the form dirty and saves the chosen unit', async () => {
        setup(UNITLESS_ENTITY)
        await screen.findByTestId('sensor-unit-select')
        expect(screen.getByTestId('dirty')).toHaveTextContent('false')

        fireEvent.click(screen.getByRole('button', { name: 'kW' }))

        expect(screen.getByTestId('dirty')).toHaveTextContent('true')
        await waitFor(() =>
            expect(api.sensorUnits).toHaveBeenLastCalledWith(
                expect.objectContaining({ sensor_unit_overrides: { [UNITLESS_ENTITY]: 'kW' } }),
            ),
        )
        fireEvent.click(screen.getByRole('button', { name: 'Save' }))

        await waitFor(() =>
            expect(api.configSave).toHaveBeenCalledWith({ sensor_unit_overrides: { [UNITLESS_ENTITY]: 'kW' } }),
        )
    })
})
