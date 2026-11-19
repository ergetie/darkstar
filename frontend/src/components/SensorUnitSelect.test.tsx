import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import SensorUnitSelect from './SensorUnitSelect'

describe('SensorUnitSelect', () => {
    it('offers W and kW with nothing pressed until a unit is chosen', () => {
        render(<SensorUnitSelect onChange={vi.fn()} />)

        expect(screen.getByRole('group', { name: 'Sensor unit' })).toBeInTheDocument()
        expect(screen.getByRole('button', { name: 'W' })).toHaveAttribute('aria-pressed', 'false')
        expect(screen.getByRole('button', { name: 'kW' })).toHaveAttribute('aria-pressed', 'false')
        expect(screen.getByText(/read as kW until you do/)).toBeInTheDocument()
    })

    it('marks the chosen unit as pressed and says it was set manually', () => {
        render(<SensorUnitSelect value="W" onChange={vi.fn()} />)

        expect(screen.getByRole('button', { name: 'W' })).toHaveAttribute('aria-pressed', 'true')
        expect(screen.getByRole('button', { name: 'kW' })).toHaveAttribute('aria-pressed', 'false')
        expect(screen.getByText(/Unit set manually/)).toBeInTheDocument()
    })

    it('reports the clicked unit', () => {
        const onChange = vi.fn()
        render(<SensorUnitSelect value="kW" onChange={onChange} />)

        fireEvent.click(screen.getByRole('button', { name: 'W' }))
        fireEvent.click(screen.getByRole('button', { name: 'kW' }))

        expect(onChange.mock.calls).toEqual([['W'], ['kW']])
    })

    it('does not report clicks while disabled', () => {
        const onChange = vi.fn()
        render(<SensorUnitSelect onChange={onChange} disabled />)

        fireEvent.click(screen.getByRole('button', { name: 'W' }))

        expect(onChange).not.toHaveBeenCalled()
    })
})
