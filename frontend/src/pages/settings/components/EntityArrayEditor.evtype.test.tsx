/* load-balancing-completion 7.3: dynamic-current explainer + no-SoC warning */
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { EntityArrayEditor, type EVChargerEntity } from './EntityArrayEditor'
import { evChargerDisabledReason, evChargerPowerLimits } from '../evPower'
import { evChargerArrayError } from '../utils'

function makeCharger(overrides: Partial<EVChargerEntity> = {}): EVChargerEntity {
    return {
        id: 'goe',
        name: 'Garage EV',
        enabled: true,
        battery_capacity_kwh: 82,
        sensor: '',
        soc_sensor: 'sensor.ev_soc',
        plug_sensor: '',
        type: 'current',
        phases: [1, 2, 3],
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

describe('EV charger charging-control entity requirement', () => {
    it('flags a missing control entity as required for current-type chargers', () => {
        renderEditor(makeCharger({ switch_entity: '' }))
        expect(screen.getByRole('alert')).toHaveTextContent(/Required for current-type chargers/)
    })

    it('does not flag the control entity once set', () => {
        renderEditor(makeCharger({ switch_entity: 'select.goe_frc' }))
        expect(screen.queryByText(/Required for current-type chargers/)).not.toBeInTheDocument()
    })

    it('does not require the control entity check for binary chargers', () => {
        renderEditor(makeCharger({ type: 'binary', switch_entity: '' }))
        expect(screen.queryByText(/Required for current-type chargers/)).not.toBeInTheDocument()
    })

    it('blocks the EV charger array while a current charger lacks it', () => {
        const missing = JSON.stringify([makeCharger({ switch_entity: '' })])
        expect(evChargerArrayError(missing)).toMatch(/Charging Control Entity is required.*'Garage EV'/)
        expect(evChargerArrayError(JSON.stringify([makeCharger({ switch_entity: 'switch.goe' })]))).toBeNull()
        expect(evChargerArrayError(JSON.stringify([makeCharger({ switch_entity: '', enabled: false })]))).toBeNull()
    })
})

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
        expect(screen.getByText(/^Charging Control Entity/)).toBeInTheDocument()
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

describe('EV charger derived power (ev-charging-power)', () => {
    it('shows derived min/max kW read-only for current chargers and updates with amps', () => {
        const { rerender } = render(
            <MemoryRouter>
                <EntityArrayEditor
                    entities={[makeCharger({ max_current_a: 12 })]}
                    entityType="ev_charger"
                    onChange={vi.fn()}
                />
            </MemoryRouter>,
        )
        expect(screen.getByTestId('ev-derived-power')).toHaveTextContent('8.3 kW')
        expect(screen.queryByText(/Rated Charging Power/)).not.toBeInTheDocument()

        rerender(
            <MemoryRouter>
                <EntityArrayEditor
                    entities={[makeCharger({ max_current_a: 10 })]}
                    entityType="ev_charger"
                    onChange={vi.fn()}
                />
            </MemoryRouter>,
        )
        expect(screen.getByTestId('ev-derived-power')).toHaveTextContent('4.2–6.9 kW')
    })

    it('uses the configured nominal voltage', () => {
        render(
            <MemoryRouter>
                <EntityArrayEditor
                    entities={[makeCharger({ max_current_a: 10 })]}
                    entityType="ev_charger"
                    onChange={vi.fn()}
                    nominalVoltageV={240}
                />
            </MemoryRouter>,
        )
        expect(screen.getByTestId('ev-derived-power')).toHaveTextContent('7.2 kW')
    })

    it('offers rated_power_kw for binary chargers', () => {
        renderEditor(makeCharger({ type: 'binary', rated_power_kw: 3.7 }))
        expect(screen.getByText(/Rated Charging Power/)).toBeInTheDocument()
        expect(screen.queryByTestId('ev-derived-power')).not.toBeInTheDocument()
    })

    it('derives limits like the backend helper', () => {
        expect(
            evChargerPowerLimits({ type: 'current', max_current_a: 10, min_current_a: 6, phases: [1, 2, 3] }),
        ).toEqual({
            minKw: expect.closeTo(4.1814, 3),
            maxKw: expect.closeTo(6.9, 5),
        })
        expect(evChargerPowerLimits({ type: 'current', max_current_a: 10 })).toBeNull()
        expect(evChargerPowerLimits({ type: 'binary', rated_power_kw: 3.7 })).toEqual({ minKw: 3.7, maxKw: 3.7 })
        expect(evChargerPowerLimits({ type: 'binary' })).toBeNull()
    })
})

describe('EV charger phases requirement (ev-planning-model 7.x)', () => {
    it('shows a required-phases warning naming the charger when phases are missing', () => {
        renderEditor(makeCharger({ phases: undefined, switch_entity: 'select.goe_frc' }))
        expect(screen.getByTestId('ev-phases-required')).toHaveTextContent(
            'Configure phases for Garage EV to enable planning',
        )
        expect(screen.getByTestId('ev-derived-power')).toHaveTextContent(
            'Configure phases for Garage EV to enable planning',
        )
    })

    it('shows no warning once phases are set', () => {
        renderEditor(makeCharger({ switch_entity: 'select.goe_frc' }))
        expect(screen.queryByTestId('ev-phases-required')).not.toBeInTheDocument()
    })

    it('blocks saving a current charger without phases, naming it', () => {
        const value = JSON.stringify([makeCharger({ phases: [], switch_entity: 'select.goe_frc' })])
        expect(evChargerArrayError(value)).toBe('Configure phases for Garage EV to enable planning')
        expect(
            evChargerArrayError(JSON.stringify([makeCharger({ phases: [], switch_entity: 'x', enabled: false })])),
        ).toBeNull()
    })

    it('never requires phases or voltage for binary chargers', () => {
        const binary = makeCharger({ type: 'binary', phases: undefined, rated_power_kw: 3.7 })
        expect(evChargerDisabledReason(binary, 120)).toBeNull()
        expect(evChargerPowerLimits(binary, 120)).toEqual({ minKw: 3.7, maxKw: 3.7 })
        expect(evChargerArrayError(JSON.stringify([binary]))).toBeNull()
    })
})

describe('EV charger plug-in reminder moved to Notifications', () => {
    it('no longer shows a per-charger plug-in reminder field', () => {
        render(
            <MemoryRouter>
                <EntityArrayEditor entities={[makeCharger()]} entityType="ev_charger" onChange={vi.fn()} />
            </MemoryRouter>,
        )
        expect(screen.queryByLabelText('Plug-in reminder')).toBeNull()
        expect(screen.queryByText(/plug-in reminder/i)).toBeNull()
    })
})

describe('Phase switching: 1-phase line and phase-mode picker (load-balancer-graceful-degradation)', () => {
    const haEntities = [
        {
            entity_id: 'select.go_echarger_417263_psm',
            friendly_name: 'go-e PSM',
            domain: 'select',
            options: ['auto', 'one_phase', 'three_phases'],
        },
        { entity_id: 'binary_sensor.go_echarger_417263_fsp', friendly_name: 'go-e FSP', domain: 'binary_sensor' },
        { entity_id: 'input_select.ev_phase', friendly_name: 'EV phase helper', domain: 'input_select' },
    ]

    function renderWith(overrides: Partial<EVChargerEntity>) {
        render(
            <MemoryRouter>
                <EntityArrayEditor
                    entities={[
                        makeCharger({ switch_entity: 'switch.goe', phase_switching_enabled: true, ...overrides }),
                    ]}
                    entityType="ev_charger"
                    onChange={vi.fn()}
                    haEntities={haEntities}
                />
            </MemoryRouter>,
        )
    }

    it('lists only writable select entities in the phase-mode picker', () => {
        // jsdom has no layout: EntitySelect scrolls the highlighted option into view
        Element.prototype.scrollIntoView = vi.fn()
        renderWith({ phase_mode_entity: '' })
        fireEvent.click(screen.getByText('Select Home Assistant phase-mode entity...'))
        expect(screen.getByText('select.go_echarger_417263_psm')).toBeInTheDocument()
        expect(screen.getByText('input_select.ev_phase')).toBeInTheDocument()
        expect(screen.queryByText('binary_sensor.go_echarger_417263_fsp')).not.toBeInTheDocument()
    })

    it('offers the select options for the 1- and 3-phase values', () => {
        renderWith({
            phase_mode_entity: 'select.go_echarger_417263_psm',
            phase_1_value: 'one_phase',
            phase_3_value: 'three_phases',
        })
        const one = screen.getByLabelText('1-Phase Option')
        expect(one).toHaveValue('one_phase')
        expect(one).toContainHTML('<option value="auto"')
    })

    it('keeps a saved read-only entity visible with an inline error', () => {
        renderWith({ phase_mode_entity: 'binary_sensor.go_echarger_417263_fsp' })
        expect(screen.getByText('go-e FSP')).toBeInTheDocument()
        expect(screen.getByTestId('ev-phase-mode-domain-error')).toHaveTextContent(/read-only/)
    })

    it('shows the 1-phase line selector limited to the charger phases, default L1', () => {
        renderWith({ phases: [1, 2], phase_mode_entity: 'select.go_echarger_417263_psm' })
        const block = screen.getByTestId('ev-phase-1-line')
        expect(block).toBeInTheDocument()
        expect(screen.getByRole('button', { name: 'L1', pressed: true })).toBeInTheDocument()
        const l3Buttons = screen.getAllByRole('button', { name: 'L3' })
        // the phase-line L3 button is disabled because the charger has no L3
        expect(l3Buttons.some((b) => b.hasAttribute('disabled') && b.getAttribute('aria-pressed') === 'false')).toBe(
            true,
        )
    })

    it('hides the 1-phase line selector while phase switching is off', () => {
        renderWith({ phase_switching_enabled: false })
        expect(screen.queryByTestId('ev-phase-1-line')).not.toBeInTheDocument()
    })

    it('flags a 1-phase line outside the charger phases and blocks saving', () => {
        renderWith({ phases: [1, 2], phase_1_line: 3, phase_mode_entity: 'select.go_echarger_417263_psm' })
        expect(screen.getByTestId('ev-phase-1-line-error')).toHaveTextContent('L3 is not one of')
        const invalid = JSON.stringify([
            makeCharger({
                switch_entity: 'switch.goe',
                phases: [1, 2],
                phase_switching_enabled: true,
                phase_1_line: 3,
            }),
        ])
        expect(evChargerArrayError(invalid)).toMatch(/1-phase line/)
        const readOnly = JSON.stringify([
            makeCharger({
                switch_entity: 'switch.goe',
                phase_switching_enabled: true,
                phase_mode_entity: 'binary_sensor.x',
            }),
        ])
        expect(evChargerArrayError(readOnly)).toMatch(/writable select/)
    })
})
