import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const sensorUnits = vi.hoisted(() => vi.fn())
vi.mock('../../lib/api', () => ({ Api: { setup: { sensorUnits } } }))

import { useMemo } from 'react'
import { SensorUnitContext, type SensorUnitControl } from '../../lib/sensorUnits'
import { useUnitNeeded } from '../../lib/useUnitNeeded'
import { fakeSensorUnits } from '../../test/sensorUnitsMock'
import { EntityField } from './EntityField'

function Harness({ value }: { value: string }) {
    const draft = useMemo(() => ({ input_sensors: { load_power: value } }), [value])
    const { isChoiceVisible } = useUnitNeeded(draft)
    const control = useMemo<SensorUnitControl>(
        () => ({ isChoiceVisible, overrides: {}, setOverride: vi.fn() }),
        [isChoiceVisible],
    )
    return (
        <SensorUnitContext.Provider value={control}>
            <EntityField
                label="House load power"
                value={value}
                onChange={vi.fn()}
                entities={[
                    {
                        entity_id: 'sensor.watts',
                        friendly_name: 'Watt power',
                        domain: 'sensor',
                        state: '1200',
                        unit_of_measurement: 'W',
                    },
                ]}
            />
        </SensorUnitContext.Provider>
    )
}

describe('EntityField current value', () => {
    beforeEach(() => {
        sensorUnits.mockReset()
        sensorUnits.mockImplementation(async (draft) => fakeSensorUnits(draft))
    })

    it('keeps "Current value: <state> <unit>" and shows no selector for a sensor with a unit', async () => {
        render(<Harness value="sensor.watts" />)

        expect(screen.getByText(/Current value:/)).toHaveTextContent('Current value: 1200 W')
        await waitFor(() => expect(sensorUnits).toHaveBeenCalled())
        expect(screen.queryByTestId('sensor-unit-select')).not.toBeInTheDocument()
        expect(screen.queryByRole('group', { name: 'Sensor unit' })).not.toBeInTheDocument()
    })
})
