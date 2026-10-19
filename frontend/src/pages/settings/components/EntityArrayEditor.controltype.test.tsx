import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { EntityArrayEditor, type WaterHeaterEntity } from './EntityArrayEditor'

vi.mock('../../../components/EntitySelect', () => ({
    default: ({
        value,
        onChange,
        placeholder,
    }: {
        value: string
        onChange: (v: string) => void
        placeholder?: string
    }) => <input aria-label={placeholder} value={value} onChange={(e) => onChange(e.target.value)} />,
}))

const heater: WaterHeaterEntity = {
    id: 'tank',
    name: 'Main Tank',
    enabled: true,
    power_kw: 3,
    min_kwh_per_day: 6,
    max_hours_between_heating: 8,
    water_min_spacing_hours: 4,
    idle_power_threshold_kw: 0.1,
    sensor: '',
    target_entity: '',
    control_type: 'temperature',
    type: 'binary',
}

function renderEditor(entity: WaterHeaterEntity, onChange = vi.fn(), entityErrors = {}) {
    render(
        <MemoryRouter>
            <EntityArrayEditor
                entities={[entity]}
                entityType="water_heater"
                onChange={onChange}
                entityErrors={entityErrors}
            />
        </MemoryRouter>,
    )
    return onChange
}

describe('water heater control type auto-detection', () => {
    afterEach(cleanup)

    it('sets switch control when a switch entity is selected', () => {
        const onChange = renderEditor(heater)
        fireEvent.change(screen.getByLabelText(/Select Home Assistant (switch|number)/), {
            target: { value: 'switch.vvb' },
        })
        expect(onChange).toHaveBeenLastCalledWith([
            expect.objectContaining({ target_entity: 'switch.vvb', control_type: 'switch' }),
        ])
    })

    it('sets temperature control when a number entity is selected', () => {
        const onChange = renderEditor({ ...heater, control_type: 'switch' })
        fireEvent.change(screen.getByLabelText(/Select Home Assistant (switch|number)/), {
            target: { value: 'number.vvb' },
        })
        expect(onChange).toHaveBeenLastCalledWith([
            expect.objectContaining({ target_entity: 'number.vvb', control_type: 'temperature' }),
        ])
    })

    it('leaves control type alone for an unsupported domain', () => {
        const onChange = renderEditor(heater)
        fireEvent.change(screen.getByLabelText(/Select Home Assistant (switch|number)/), {
            target: { value: 'climate.vvb' },
        })
        expect(onChange).toHaveBeenLastCalledWith([
            expect.objectContaining({ target_entity: 'climate.vvb', control_type: 'temperature' }),
        ])
    })

    it('clears an entity of the wrong domain when control type is changed manually', () => {
        const onChange = renderEditor({ ...heater, target_entity: 'number.vvb' })
        fireEvent.change(screen.getByDisplayValue('Temperature setpoint'), { target: { value: 'switch' } })
        expect(onChange).toHaveBeenLastCalledWith([
            expect.objectContaining({ control_type: 'switch', target_entity: '' }),
        ])
    })

    it('shows a server mismatch error inline on the heater', () => {
        renderEditor({ ...heater, target_entity: 'switch.vvb' }, vi.fn(), {
            0: "Water heater 'tank' target_entity 'switch.vvb' is a switch",
        })
        expect(screen.getByRole('alert')).toHaveTextContent(/switch\.vvb/)
    })
})
