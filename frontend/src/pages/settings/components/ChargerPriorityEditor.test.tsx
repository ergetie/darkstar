import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ChargerPriorityEditor } from './ChargerPriorityEditor'

describe('ChargerPriorityEditor', () => {
    it('shows an empty state when no type: current chargers are configured', () => {
        render(
            <ChargerPriorityEditor
                value="{}"
                onChange={vi.fn()}
                config={{ ev_chargers: [{ id: 'binary_ev', name: 'Binary EV', type: 'binary' }] }}
            />,
        )

        expect(screen.getByText(/No dynamically-throttled chargers configured/)).toBeInTheDocument()
    })

    it('lists every type: current charger with its name and phases', () => {
        render(
            <ChargerPriorityEditor
                value="{}"
                onChange={vi.fn()}
                config={{
                    ev_chargers: [
                        { id: 'goe', name: 'Garage EV', type: 'current', phases: [1, 2, 3] },
                        { id: 'binary_ev', name: 'Binary EV', type: 'binary' },
                    ],
                }}
            />,
        )

        expect(screen.getByText('Garage EV')).toBeInTheDocument()
        expect(screen.getByText('Phases: L1, L2, L3')).toBeInTheDocument()
        expect(screen.queryByText('Binary EV')).not.toBeInTheDocument()
    })

    it('updates the priority map for the edited charger without touching others', () => {
        const onChange = vi.fn()
        render(
            <ChargerPriorityEditor
                value={JSON.stringify({ main_ev: 1, garage_ev: 2 })}
                onChange={onChange}
                config={{
                    ev_chargers: [
                        { id: 'main_ev', name: 'Main EV', type: 'current' },
                        { id: 'garage_ev', name: 'Garage EV', type: 'current' },
                    ],
                }}
            />,
        )

        const inputs = screen.getAllByRole('spinbutton')
        fireEvent.change(inputs[0], { target: { value: '5' } })

        expect(onChange).toHaveBeenCalledWith({ main_ev: 5, garage_ev: 2 })
    })
})
