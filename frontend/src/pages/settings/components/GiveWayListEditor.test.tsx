import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { GiveWayListEditor } from './GiveWayListEditor'
import { healOrderForDisplay, type GiveWayEntry } from './giveWayOrder'

const CONFIG = {
    ev_chargers: [
        {
            id: 'goe',
            name: 'Garage EV',
            type: 'current',
            phases: [1, 2, 3],
            min_current_a: 6,
            max_current_a: 16,
        },
        { id: 'old_ev', name: 'Old EV', type: 'binary' },
    ],
    water_heaters: [{ id: 'main_tank', name: 'Main Tank' }],
}

function renderEditor({
    order = [
        { kind: 'charger', id: 'goe' },
        { kind: 'shed', id: 'main_tank' },
    ] as GiveWayEntry[],
    loads = [{ device_type: 'water_heater', device_id: 'main_tank', phases: [2] }],
    onChangeOrder = vi.fn(),
    onChangeLoads = vi.fn(),
} = {}) {
    render(
        <MemoryRouter>
            <GiveWayListEditor
                orderValue={JSON.stringify(order)}
                loadsValue={JSON.stringify(loads)}
                onChangeOrder={onChangeOrder}
                onChangeLoads={onChangeLoads}
                config={CONFIG}
            />
        </MemoryRouter>,
    )
    return { onChangeOrder, onChangeLoads }
}

describe('healOrderForDisplay', () => {
    it('appends a missing charger after the last charger entry', () => {
        expect(
            healOrderForDisplay(
                [
                    { kind: 'charger', id: 'a' },
                    { kind: 'shed', id: 'wh' },
                ],
                ['a', 'b'],
                ['wh'],
            ),
        ).toEqual([
            { kind: 'charger', id: 'a' },
            { kind: 'charger', id: 'b' },
            { kind: 'shed', id: 'wh' },
        ])
    })

    it('drops dangling entries and appends missing sheds at the end', () => {
        expect(healOrderForDisplay([{ kind: 'charger', id: 'gone' }], ['a'], ['wh'])).toEqual([
            { kind: 'charger', id: 'a' },
            { kind: 'shed', id: 'wh' },
        ])
    })
})

describe('GiveWayListEditor', () => {
    it('auto-lists dynamic-current chargers with a capability line and EV-tab link', () => {
        renderEditor()
        expect(screen.getByText('Garage EV')).toBeInTheDocument()
        expect(screen.getByText('Throttle 16 → 6 A, then pause')).toBeInTheDocument()
        expect(screen.getByRole('link', { name: /Configured in EV tab/ })).toHaveAttribute('href', '/settings?tab=ev')
    })

    it('charger rows are not removable; shed rows are', () => {
        renderEditor()
        // Only the shed row has a remove button
        expect(screen.getByLabelText('Remove Main Tank')).toBeInTheDocument()
        expect(screen.queryByLabelText('Remove Garage EV')).not.toBeInTheDocument()
    })

    it('shed rows show the switch-off capability line', () => {
        renderEditor()
        expect(screen.getByText('Switch off')).toBeInTheDocument()
    })

    it('reordering writes the full new give_way_order', () => {
        const { onChangeOrder } = renderEditor()
        // Move the shed row (index 1) above the charger
        fireEvent.click(screen.getAllByLabelText('Move give-way entry up')[1])
        expect(onChangeOrder).toHaveBeenCalledWith([
            { kind: 'shed', id: 'main_tank' },
            { kind: 'charger', id: 'goe' },
        ])
    })

    it('adding a shed load updates both loads and the order', () => {
        const { onChangeOrder, onChangeLoads } = renderEditor({
            order: [{ kind: 'charger', id: 'goe' }],
            loads: [],
        })
        fireEvent.click(screen.getByRole('button', { name: /Add Load/ }))
        expect(onChangeLoads).toHaveBeenCalledWith([
            { device_type: 'water_heater', device_id: 'main_tank', phases: [] },
        ])
        expect(onChangeOrder).toHaveBeenCalledWith([
            { kind: 'charger', id: 'goe' },
            { kind: 'shed', id: 'main_tank' },
        ])
    })

    it('removing a shed load updates both loads and the order', () => {
        const { onChangeOrder, onChangeLoads } = renderEditor()
        fireEvent.click(screen.getByLabelText('Remove Main Tank'))
        expect(onChangeLoads).toHaveBeenCalledWith([])
        expect(onChangeOrder).toHaveBeenCalledWith([{ kind: 'charger', id: 'goe' }])
    })

    it('offers only binary chargers in the shed device picker', () => {
        renderEditor({
            order: [
                { kind: 'charger', id: 'goe' },
                { kind: 'shed', id: 'old_ev' },
            ],
            loads: [{ device_type: 'ev_charger', device_id: 'old_ev', phases: [1] }],
        })
        const deviceSelects = screen.getAllByRole('combobox')
        // Second combobox is the device picker (first is device type)
        const devicePicker = deviceSelects[1]
        const optionValues = Array.from(devicePicker.querySelectorAll('option')).map(
            (o) => (o as HTMLOptionElement).value,
        )
        expect(optionValues).toContain('old_ev')
        expect(optionValues).not.toContain('goe')
    })

    it('shows a missing charger even when absent from the stored order (display self-heal)', () => {
        renderEditor({ order: [{ kind: 'shed', id: 'main_tank' }] })
        expect(screen.getByText('Garage EV')).toBeInTheDocument()
    })
})
