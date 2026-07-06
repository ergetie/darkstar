import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { BalancedLoadsEditor } from './BalancedLoadsEditor'

describe('BalancedLoadsEditor', () => {
    it('renders an empty state and adds a row on click', () => {
        const onChange = vi.fn()
        render(
            <BalancedLoadsEditor
                value={[]}
                onChange={onChange}
                config={{ water_heaters: [{ id: 'main_tank', name: 'Main Tank' }] }}
            />,
        )

        expect(screen.getByText('No balanced loads configured')).toBeInTheDocument()

        fireEvent.click(screen.getByRole('button', { name: /Add Load/i }))

        expect(onChange).toHaveBeenCalledWith([
            expect.objectContaining({ device_type: 'water_heater', device_id: 'main_tank', priority: 1 }),
        ])
    })

    it('renders existing rows and toggles a phase checkbox', () => {
        const onChange = vi.fn()
        const loads = [{ device_type: 'water_heater' as const, device_id: 'main_tank', phases: [2], priority: 1 }]
        render(
            <BalancedLoadsEditor
                value={loads}
                onChange={onChange}
                config={{ water_heaters: [{ id: 'main_tank', name: 'Main Tank' }] }}
            />,
        )

        const l1Checkbox = screen.getByLabelText('L1')
        fireEvent.click(l1Checkbox)

        expect(onChange).toHaveBeenCalledWith([expect.objectContaining({ phases: [1, 2] })])
    })

    it('shows entity/on/off fields only for custom_entity loads', () => {
        const onChange = vi.fn()
        const loads = [{ device_type: 'custom_entity' as const, device_id: 'pump', phases: [3], priority: 2 }]
        render(<BalancedLoadsEditor value={loads} onChange={onChange} />)

        expect(screen.getByText('On Value')).toBeInTheDocument()
        expect(screen.getByText('Off Value')).toBeInTheDocument()
    })
})
