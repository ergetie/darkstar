import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { EntityArrayEditor, type WaterHeaterEntity } from './EntityArrayEditor'
import { waterSections } from '../types'

const heater: WaterHeaterEntity = {
    id: 'tank',
    name: 'Main Tank',
    enabled: true,
    power_kw: 3,
    min_kwh_per_day: 6,
    max_hours_between_heating: 28,
    water_min_spacing_hours: 4,
    idle_power_threshold_kw: 0.1,
    sensor: 'sensor.tank_power',
    target_entity: 'number.tank_target',
    control_type: 'temperature',
    type: 'binary',
}

describe('water heater scheduling settings', () => {
    it('renders long gap and the idle power cutoff in watts with generic help', () => {
        const { container } = render(
            <MemoryRouter>
                <EntityArrayEditor entities={[heater]} entityType="water_heater" onChange={vi.fn()} />
            </MemoryRouter>,
        )

        const values = [...container.querySelectorAll<HTMLInputElement>('input[type="number"]')].map(
            (input) => input.value,
        )
        expect(values).toContain('28')
        expect(screen.getByLabelText('Idle Power Cutoff (W)')).toHaveValue(100)
        expect(screen.getByText(/Values above 24 hours are supported/)).toBeInTheDocument()
        expect(
            screen.getByText(
                'Power at or below this threshold is treated as idle and excluded from heating totals. Set to 0 to disable idle filtering.',
            ),
        ).toBeInTheDocument()
    })

    it('saves watts as kW and ignores negative entries', () => {
        const onChange = vi.fn()
        render(
            <MemoryRouter>
                <EntityArrayEditor
                    entities={[{ ...heater, idle_power_threshold_kw: 0 }]}
                    entityType="water_heater"
                    onChange={onChange}
                />
            </MemoryRouter>,
        )

        const threshold = screen.getByLabelText('Idle Power Cutoff (W)')
        fireEvent.change(threshold, { target: { value: '100' } })
        expect(onChange).toHaveBeenLastCalledWith([expect.objectContaining({ idle_power_threshold_kw: 0.1 })])

        fireEvent.change(threshold, { target: { value: '-1' } })
        expect(onChange).toHaveBeenCalledTimes(1)
    })

    it('shows zero watts when idle filtering is unset', () => {
        render(
            <MemoryRouter>
                <EntityArrayEditor
                    entities={[{ ...heater, idle_power_threshold_kw: undefined }]}
                    entityType="water_heater"
                    onChange={vi.fn()}
                />
            </MemoryRouter>,
        )

        expect(screen.getByLabelText('Idle Power Cutoff (W)')).toHaveValue(0)
    })

    it('constrains deferral to 0–23 and explains the local-time bucket boundary', () => {
        const field = waterSections
            .flatMap((section) => section.fields)
            .find((item) => item.key === 'water_heating.defer_up_to_hours')
        expect(field).toMatchObject({ min: 0, max: 23 })
        expect(field?.helper).toMatch(/Local-time quota boundary/)
    })
})
