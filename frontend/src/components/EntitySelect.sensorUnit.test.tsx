import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useMemo, useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const sensorUnits = vi.hoisted(() => vi.fn())
vi.mock('../lib/api', () => ({ Api: { setup: { sensorUnits } } }))

import { SensorUnitContext, readUnitOverrides, withUnitOverride, type SensorUnitControl } from '../lib/sensorUnits'
import { useUnitNeeded } from '../lib/useUnitNeeded'
import type { SensorUnit } from '../lib/api'
import EntitySelect from './EntitySelect'

const entities = [
    { entity_id: 'sensor.unitless', friendly_name: 'Unitless power', domain: 'sensor' },
    { entity_id: 'sensor.watts', friendly_name: 'Watt power', domain: 'sensor' },
]

/** The same wiring onboarding and Settings use: a draft config, the hook and the context. */
function Harness({ initial = '' }: { initial?: string }) {
    const [selected, setSelected] = useState(initial)
    const [overrides, setOverrides] = useState<Record<string, SensorUnit>>({})
    const draft = useMemo(() => ({ pick: selected, sensor_unit_overrides: overrides }), [selected, overrides])
    const { isChoiceVisible } = useUnitNeeded(draft)
    const control = useMemo<SensorUnitControl>(
        () => ({
            isChoiceVisible,
            overrides: readUnitOverrides(draft),
            setOverride: (id, unit) => setOverrides((current) => withUnitOverride(current, id, unit)),
        }),
        [isChoiceVisible, draft],
    )
    return (
        <SensorUnitContext.Provider value={control}>
            <EntitySelect entities={entities} value={selected} onChange={setSelected} />
        </SensorUnitContext.Provider>
    )
}

function pick(name: string) {
    fireEvent.click(screen.getByRole('button', { name: /Unitless power|Watt power|Select entity/ }))
    fireEvent.click(screen.getByText(name))
}

describe('EntitySelect sensor unit selector', () => {
    beforeEach(() => {
        Element.prototype.scrollIntoView = vi.fn()
        sensorUnits.mockReset()
        sensorUnits.mockImplementation(async (config: { pick: string; sensor_unit_overrides: object }) => ({
            unit_needed:
                config.pick === 'sensor.unitless'
                    ? [
                          {
                              entity_id: 'sensor.unitless',
                              settings_path: 'input_sensors.pv_power',
                              live_value: 1200,
                              override:
                                  (config.sensor_unit_overrides as Record<string, 'W' | 'kW'>)['sensor.unitless'] ??
                                  null,
                          },
                      ]
                    : [],
        }))
    })

    it('appears for a unitless sensor and disappears when another sensor is selected', async () => {
        render(<Harness initial="sensor.unitless" />)
        expect(screen.queryByTestId('sensor-unit-select')).not.toBeInTheDocument()

        expect(await screen.findByTestId('sensor-unit-select')).toBeInTheDocument()

        pick('Watt power')
        await waitFor(() => expect(screen.queryByTestId('sensor-unit-select')).not.toBeInTheDocument())
        await waitFor(() =>
            expect(sensorUnits).toHaveBeenLastCalledWith(expect.objectContaining({ pick: 'sensor.watts' })),
        )
    })

    it('appears after selecting the unitless sensor', async () => {
        render(<Harness initial="sensor.watts" />)
        await waitFor(() => expect(sensorUnits).toHaveBeenCalled())
        expect(screen.queryByTestId('sensor-unit-select')).not.toBeInTheDocument()

        pick('Unitless power')

        expect(await screen.findByTestId('sensor-unit-select')).toBeInTheDocument()
    })

    it('writes the choice to the draft overrides, refetches and keeps the choice editable', async () => {
        render(<Harness initial="sensor.unitless" />)
        await screen.findByTestId('sensor-unit-select')

        fireEvent.click(screen.getByRole('button', { name: 'W' }))

        await waitFor(() =>
            expect(sensorUnits).toHaveBeenLastCalledWith(
                expect.objectContaining({ sensor_unit_overrides: { 'sensor.unitless': 'W' } }),
            ),
        )
        expect(screen.getByRole('button', { name: 'W' })).toHaveAttribute('aria-pressed', 'true')
        expect(screen.getByRole('button', { name: 'kW' })).toHaveAttribute('aria-pressed', 'false')

        fireEvent.click(screen.getByRole('button', { name: 'kW' }))
        expect(screen.getByRole('button', { name: 'kW' })).toHaveAttribute('aria-pressed', 'true')
    })

    it('shows nothing outside a provider', () => {
        render(<EntitySelect entities={entities} value="sensor.unitless" onChange={vi.fn()} />)
        expect(screen.queryByTestId('sensor-unit-select')).not.toBeInTheDocument()
    })

    it('shows nothing when no entity is selected', async () => {
        render(<Harness />)
        await waitFor(() => expect(sensorUnits).toHaveBeenCalled())
        expect(screen.queryByTestId('sensor-unit-select')).not.toBeInTheDocument()
    })
})
