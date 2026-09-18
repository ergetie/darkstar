/* load-balancing-completion 7.3: dynamic-current explainer + no-SoC warning */
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { EntityArrayEditor, type EVChargerEntity } from './EntityArrayEditor'

function makeCharger(overrides: Partial<EVChargerEntity> = {}): EVChargerEntity {
    return {
        id: 'goe',
        name: 'Garage EV',
        enabled: true,
        max_power_kw: 11,
        battery_capacity_kwh: 82,
        sensor: '',
        soc_sensor: 'sensor.ev_soc',
        plug_sensor: '',
        type: 'current',
        nominal_power_kw: 11,
        current_entity: 'number.goe_current',
        min_current_a: 6,
        max_current_a: 16,
        ...overrides,
    }
}

function renderEditor(charger: EVChargerEntity) {
    // The first entity auto-expands, so the detail fields are visible.
    render(
        <MemoryRouter>
            <EntityArrayEditor entities={[charger]} entityType="ev_charger" onChange={vi.fn()} />
        </MemoryRouter>,
    )
}

describe('EV charger load type (EntityArrayEditor)', () => {
    it('renames the current option away from the old "Current (dynamic amps)" label', () => {
        renderEditor(makeCharger())
        expect(screen.getByRole('option', { name: /^Dynamic/ })).toHaveValue('current')
        expect(screen.queryByRole('option', { name: 'Current (dynamic amps)' })).not.toBeInTheDocument()
    })

    it('shows the consequence explainer while dynamic current is selected', () => {
        renderEditor(makeCharger())
        expect(screen.getByText('Choosing dynamic current means:')).toBeInTheDocument()
        expect(screen.getByText(/planner sets the charge current for every slot/i)).toBeInTheDocument()
        expect(screen.getByRole('link', { name: 'Load Balancing tab' })).toHaveAttribute(
            'href',
            '/settings?tab=load-balancing',
        )
        expect(screen.getByText(/eligible for PV-surplus charging/i)).toBeInTheDocument()
    })

    it('hides the explainer for binary chargers', () => {
        renderEditor(makeCharger({ type: 'binary' }))
        expect(screen.queryByText('Choosing dynamic current means:')).not.toBeInTheDocument()
    })

    it('warns when a dynamic-current charger has no SoC sensor', () => {
        renderEditor(makeCharger({ soc_sensor: '' }))
        expect(screen.getByText('No SoC sensor configured:')).toBeInTheDocument()
        expect(screen.getByText(/cannot track this car's charging progress/i)).toBeInTheDocument()
    })

    it('does not warn when the SoC sensor is set', () => {
        renderEditor(makeCharger())
        expect(screen.queryByText('No SoC sensor configured:')).not.toBeInTheDocument()
    })

    it('does not warn for binary chargers without a SoC sensor', () => {
        renderEditor(makeCharger({ type: 'binary', soc_sensor: '' }))
        expect(screen.queryByText('No SoC sensor configured:')).not.toBeInTheDocument()
    })

    it('hides mapped charge values for switch-like controls', () => {
        renderEditor(makeCharger({ switch_entity: 'switch.ev_charger' }))
        expect(screen.getByText('Charging Control Entity')).toBeInTheDocument()
        expect(screen.queryByLabelText('Charging Enabled Value')).not.toBeInTheDocument()
        expect(screen.queryByLabelText('Charging Disabled Value')).not.toBeInTheDocument()
    })

    it('uses HA options for select control, phase, and plug mappings', () => {
        render(
            <MemoryRouter>
                <EntityArrayEditor
                    entities={[
                        makeCharger({
                            switch_entity: 'select.ev_mode',
                            charge_enabled_value: 'On',
                            charge_disabled_value: 'Off',
                            plug_sensor: 'sensor.ev_state',
                            phase_mode_entity: 'select.ev_phase',
                            phase_switching_enabled: true,
                            phase_1_value: 'Force_1',
                            phase_3_value: 'Force_3',
                            plugged_in_states: 'WaitCar,Charging',
                        }),
                    ]}
                    entityType="ev_charger"
                    onChange={vi.fn()}
                    haEntities={[
                        {
                            entity_id: 'select.ev_mode',
                            friendly_name: 'Mode',
                            domain: 'select',
                            options: ['Neutral', 'Off', 'On'],
                        },
                        {
                            entity_id: 'select.ev_phase',
                            friendly_name: 'Phase',
                            domain: 'select',
                            options: ['Auto', 'Force_1', 'Force_3'],
                        },
                        {
                            entity_id: 'sensor.ev_state',
                            friendly_name: 'State',
                            domain: 'sensor',
                            options: ['WaitCar', 'Charging'],
                        },
                    ]}
                />
            </MemoryRouter>,
        )

        expect(screen.getByLabelText('Charging Enabled Value')).toHaveValue('On')
        expect(screen.getByLabelText('Charging Enabled Value')).toContainHTML('<option')
        expect(screen.getByLabelText('1-Phase Option')).toHaveValue('Force_1')
        expect(screen.getByLabelText('3-Phase Option')).toHaveValue('Force_3')
        expect(screen.getByLabelText('Connected Plug States')).toHaveValue(['WaitCar', 'Charging'])
    })

    it('falls back to text inputs and preserves values absent from HA options', () => {
        render(
            <MemoryRouter>
                <EntityArrayEditor
                    entities={[makeCharger({ switch_entity: 'select.ev_mode', charge_enabled_value: 'VendorOn' })]}
                    entityType="ev_charger"
                    onChange={vi.fn()}
                    haEntities={[{ entity_id: 'select.ev_mode', friendly_name: 'Mode', domain: 'select', options: [] }]}
                />
            </MemoryRouter>,
        )

        expect(screen.getByLabelText('Charging Enabled Value')).toHaveValue('VendorOn')
        expect(screen.getByLabelText('Charging Enabled Value').tagName).toBe('INPUT')
    })
})
