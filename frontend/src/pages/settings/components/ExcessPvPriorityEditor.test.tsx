import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ExcessPvPriorityEditor, type ExcessPvPriorityEntry } from './ExcessPvPriorityEditor'

// jsdom doesn't implement scrollIntoView; the custom Select dropdown calls it
// on open/highlight.
Element.prototype.scrollIntoView = vi.fn()

const CONFIG = {
    system: { has_water_heater: true },
    ev_chargers: [
        { id: 'goe', name: 'Garage EV', type: 'current', enabled: true },
        { id: 'old_ev', name: 'Old EV', type: 'binary', enabled: true },
    ],
}

function renderEditor({
    entries = [] as ExcessPvPriorityEntry[],
    onChange = vi.fn(),
    config = CONFIG,
    disabled = false,
} = {}) {
    render(
        <ExcessPvPriorityEditor
            value={JSON.stringify(entries)}
            onChange={onChange}
            config={config}
            disabled={disabled}
        />,
    )
    return { onChange }
}

describe('ExcessPvPriorityEditor', () => {
    it('shows the disabled hint when the priority list is empty', () => {
        renderEditor()
        expect(screen.getByText(/Excess-PV dispatch is disabled/)).toBeInTheDocument()
    })

    it('offers all three entry types when a water heater and current-type charger exist', () => {
        renderEditor()
        fireEvent.click(screen.getByText('Add a sink...'))
        expect(screen.getByText('EV Surplus Charging')).toBeInTheDocument()
        expect(screen.getByText('Water Heater Boost')).toBeInTheDocument()
        expect(screen.getByText('Custom Entity')).toBeInTheDocument()
    })

    it('does not offer Water Heater Boost when has_water_heater is false', () => {
        renderEditor({ config: { ...CONFIG, system: { has_water_heater: false } } })
        fireEvent.click(screen.getByText('Add a sink...'))
        expect(screen.queryByText('Water Heater Boost')).not.toBeInTheDocument()
    })

    it('does not offer EV Surplus Charging when no current-type charger exists', () => {
        renderEditor({
            config: { ...CONFIG, ev_chargers: [{ id: 'old_ev', name: 'Old EV', type: 'binary', enabled: true }] },
        })
        fireEvent.click(screen.getByText('Add a sink...'))
        expect(screen.queryByText('EV Surplus Charging')).not.toBeInTheDocument()
        expect(screen.getByText(/Enable variable current control/)).toBeInTheDocument()
    })

    it('adding an EV entry defaults to the first current-type charger and 0.2kW deadband', () => {
        const { onChange } = renderEditor()
        fireEvent.click(screen.getByText('Add a sink...'))
        fireEvent.click(screen.getByText('EV Surplus Charging'))
        expect(onChange).toHaveBeenCalledWith([{ type: 'ev', charger_id: 'goe', surplus_deadband_kw: 0.2 }])
    })

    it('adding a custom entity entry defaults on/off values and power_kw', () => {
        const { onChange } = renderEditor()
        fireEvent.click(screen.getByText('Add a sink...'))
        fireEvent.click(screen.getByText('Custom Entity'))
        expect(onChange).toHaveBeenCalledWith([
            { type: 'custom_entity', entity: '', on_value: '1', off_value: '0', power_kw: 1.0 },
        ])
    })

    it('adding a boost entry is only offered once', () => {
        renderEditor({ entries: [{ type: 'water_heater_boost' }] })
        fireEvent.click(screen.getByText('Add a sink...'))
        // Only the existing row's label should be present — no dropdown option.
        expect(screen.getAllByText('Water Heater Boost')).toHaveLength(1)
    })

    it('flags an EV entry with no charger selected as incomplete', () => {
        renderEditor({ entries: [{ type: 'ev', charger_id: '' }] })
        expect(screen.getByText('incomplete')).toBeInTheDocument()
    })

    it('removing an entry updates the list', () => {
        const { onChange } = renderEditor({
            entries: [{ type: 'water_heater_boost' }, { type: 'custom_entity', entity: 'switch.pool' }],
        })
        fireEvent.click(screen.getByLabelText('Remove Water Heater Boost entry'))
        expect(onChange).toHaveBeenCalledWith([{ type: 'custom_entity', entity: 'switch.pool' }])
    })

    it('reordering writes the full new priority list', () => {
        const { onChange } = renderEditor({
            entries: [{ type: 'water_heater_boost' }, { type: 'custom_entity', entity: 'switch.pool' }],
        })
        fireEvent.click(screen.getAllByLabelText('Move excess-PV sink up')[1])
        expect(onChange).toHaveBeenCalledWith([
            { type: 'custom_entity', entity: 'switch.pool' },
            { type: 'water_heater_boost' },
        ])
    })

    it('expanding a custom entity entry shows its fields', () => {
        renderEditor({ entries: [{ type: 'custom_entity', entity: 'switch.pool', power_kw: 2.0 }] })
        fireEvent.click(screen.getByText('Custom Entity'))
        expect(screen.getByText('On Value')).toBeInTheDocument()
        expect(screen.getByText('Off Value')).toBeInTheDocument()
        expect(screen.getByText('Power (kW)')).toBeInTheDocument()
    })

    it('does not render remove/add controls when disabled', () => {
        renderEditor({ entries: [{ type: 'water_heater_boost' }], disabled: true })
        expect(screen.queryByLabelText('Remove Water Heater Boost entry')).not.toBeInTheDocument()
        expect(screen.queryByText('Add a sink...')).not.toBeInTheDocument()
    })
})
