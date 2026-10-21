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
    it('does not insert configured devices absent from explicit selection', () => {
        expect(healOrderForDisplay([], ['a', 'b'], ['wh'], true)).toEqual([])
    })
    it('drops stale and duplicate entries while preserving selected order', () => {
        expect(
            healOrderForDisplay(
                [
                    { kind: 'charger', id: 'gone' },
                    { kind: 'shed', id: 'wh' },
                    { kind: 'charger', id: 'a' },
                    { kind: 'charger', id: 'a' },
                ],
                ['a'],
                ['wh'],
            ),
        ).toEqual([
            { kind: 'shed', id: 'wh' },
            { kind: 'charger', id: 'a' },
        ])
    })
})

describe('healOrderForDisplay battery', () => {
    it('does not insert an unselected battery even when available', () => {
        expect(healOrderForDisplay([{ kind: 'charger', id: 'a' }], ['a'], ['wh'], true)).toEqual([
            { kind: 'charger', id: 'a' },
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
        renderEditor({
            config: { ...CONFIG, system: { has_battery: true } },
            order: [{ kind: 'battery', id: 'battery' }],
        })
        expect(screen.getByText('House battery (grid charging)')).toBeInTheDocument()
    })

    it('hides the battery entry when the system has no battery', () => {
        renderEditor({ config: CONFIG })
        expect(screen.queryByText('House battery (grid charging)')).not.toBeInTheDocument()
    })
})

describe('GiveWayListEditor', () => {
    it('lists selected dynamic-current chargers with a capability line and EV-tab link', () => {
        renderEditor()
        expect(screen.getByText('Garage EV')).toBeInTheDocument()
        expect(screen.getByText('Throttle 16 → 6 A, then pause')).toBeInTheDocument()
        expect(screen.getByRole('link', { name: /Configured in EV tab/ })).toHaveAttribute('href', '/settings?tab=ev')
    })

    it('charger and shed rows are removable', () => {
        renderEditor()
        expect(screen.getByLabelText('Remove Main Tank')).toBeInTheDocument()
        expect(screen.getByLabelText('Remove Garage EV')).toBeInTheDocument()
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
        fireEvent.change(screen.getByLabelText('Load to add'), { target: { value: 'on_off' } })
        fireEvent.click(screen.getByRole('button', { name: 'Add selected load' }))
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

    it('keeps a configured charger excluded when absent from the stored order)', () => {
        renderEditor({ order: [{ kind: 'shed', id: 'main_tank' }] })
        expect(screen.queryByText('Garage EV')).not.toBeInTheDocument()
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

describe('GiveWayListEditor restore power and anti-wear fields', () => {
    const CUSTOM = { device_type: 'custom_entity', device_id: 'pump', phases: [1], entity: 'switch.pump' }

    it('custom loads show power and power sensor fields with restore help text', () => {
        renderEditor({
            order: [{ kind: 'shed', id: 'pump' }],
            loads: [CUSTOM],
        })
        expect(screen.getByText('Power (kW)')).toBeTruthy()
        expect(screen.getByText('Power sensor (optional)')).toBeTruthy()
        expect(screen.getByText(/whole phase is free/i)).toBeTruthy()
    })

    it('editing the power writes power_kw, clearing it removes the value', () => {
        const { onChangeLoads } = renderEditor({
            order: [{ kind: 'shed', id: 'pump' }],
            loads: [CUSTOM],
        })
        const input = screen.getByPlaceholderText('Unknown')
        fireEvent.change(input, { target: { value: '2.2' } })
        expect(onChangeLoads).toHaveBeenLastCalledWith([{ ...CUSTOM, power_kw: 2.2 }])
    })

    it('every load shows minimum on and off time with a 300 s default', () => {
        renderEditor()
        const inputs = screen.getAllByRole('spinbutton') as HTMLInputElement[]
        const values = inputs.map((i) => i.value)
        expect(values.filter((v) => v === '300')).toHaveLength(2)
    })

    it('editing the minimum off time writes min_off_s', () => {
        const { onChangeLoads } = renderEditor()
        const inputs = screen.getAllByRole('spinbutton') as HTMLInputElement[]
        fireEvent.change(inputs[1], { target: { value: '600' } })
        expect(onChangeLoads).toHaveBeenLastCalledWith([
            { device_type: 'water_heater', device_id: 'main_tank', phases: [2], min_off_s: 600 },
        ])
    })

    it('non-custom loads do not show the power fields', () => {
        renderEditor()
        expect(screen.queryByText('Power (kW)')).toBeNull()
    })
})
