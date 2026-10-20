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
    // Battery give-way entry is covered separately below.
    system: { has_battery: false },
}

function renderEditor({
    order = [
        { kind: 'charger', id: 'goe' },
        { kind: 'shed', id: 'main_tank' },
    ] as GiveWayEntry[],
    loads = [{ device_type: 'water_heater', device_id: 'main_tank', phases: [2] }],
    onChangeOrder = vi.fn(),
    onChangeLoads = vi.fn(),
    config = CONFIG,
} = {}) {
    render(
        <MemoryRouter>
            <GiveWayListEditor
                orderValue={JSON.stringify(order)}
                loadsValue={JSON.stringify(loads)}
                onChangeOrder={onChangeOrder}
                onChangeLoads={onChangeLoads}
                config={config}
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

describe('healOrderForDisplay battery', () => {
    it('appends the battery at the end when available', () => {
        expect(healOrderForDisplay([{ kind: 'charger', id: 'a' }], ['a'], ['wh'], true)).toEqual([
            { kind: 'charger', id: 'a' },
            { kind: 'shed', id: 'wh' },
            { kind: 'battery', id: 'battery' },
        ])
    })

    it('keeps one battery entry in place and normalises its id', () => {
        expect(
            healOrderForDisplay(
                [
                    { kind: 'battery', id: 'house' },
                    { kind: 'charger', id: 'a' },
                    { kind: 'battery', id: 'battery' },
                ],
                ['a'],
                [],
                true,
            ),
        ).toEqual([
            { kind: 'battery', id: 'battery' },
            { kind: 'charger', id: 'a' },
        ])
    })

    it('drops the battery when no battery is available', () => {
        expect(
            healOrderForDisplay(
                [
                    { kind: 'battery', id: 'battery' },
                    { kind: 'charger', id: 'a' },
                ],
                ['a'],
                [],
                false,
            ),
        ).toEqual([{ kind: 'charger', id: 'a' }])
    })
})

describe('GiveWayListEditor battery entry', () => {
    it('renders the house battery entry', () => {
        renderEditor({ config: { ...CONFIG, system: { has_battery: true } } })
        expect(screen.getByText('House battery (grid charging)')).toBeInTheDocument()
    })

    it('hides the battery entry when the system has no battery', () => {
        renderEditor({ config: CONFIG })
        expect(screen.queryByText('House battery (grid charging)')).not.toBeInTheDocument()
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

    it('shows an empty-state message naming water heater/custom entity when no charger or load exists', () => {
        renderEditor({
            order: [],
            loads: [],
            config: { ev_chargers: [], water_heaters: [], system: { has_battery: false } },
        })
        expect(screen.getByText(/water heater or custom entity/)).toBeInTheDocument()
    })

    it('hides the empty-state message once a load exists, even with no EV charger configured', () => {
        renderEditor({
            order: [{ kind: 'shed', id: 'main_tank' }],
            loads: [{ device_type: 'water_heater', device_id: 'main_tank', phases: [2] }],
            config: {
                ev_chargers: [],
                water_heaters: [{ id: 'main_tank', name: 'Main Tank' }],
                system: { has_battery: false },
            },
        })
        expect(screen.queryByText(/Nothing to balance yet/)).not.toBeInTheDocument()
    })
})
