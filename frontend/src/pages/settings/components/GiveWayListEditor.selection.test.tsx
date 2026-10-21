import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Api } from '../../../lib/api'
import { useSettingsForm } from '../hooks/useSettingsForm'
import { loadBalancingFieldList } from '../types'
import { SettingsField } from './SettingsField'

vi.mock('../../../lib/api', () => ({
    Api: { config: vi.fn(), configSave: vi.fn(), haEntities: vi.fn() },
    ApiError: class extends Error {},
}))
vi.mock('../../../lib/useToast', () => ({ useToast: () => ({ toast: vi.fn() }) }))

const fields = loadBalancingFieldList.filter((field) =>
    ['load_balancing.give_way_order', 'load_balancing.loads', 'load_balancing.auto_include_devices'].includes(
        field.key,
    ),
)
const orderField = fields.find((field) => field.type === 'give_way_list')!
const initial = {
    system: { has_battery: true },
    ev_chargers: [
        {
            id: 'ev1',
            name: 'Garage EV',
            type: 'current' as const,
            enabled: true,
            battery_capacity_kwh: 60,
            min_soc_percent: 10,
            target_soc_percent: 80,
            sensor: '',
            phases: [1, 2, 3],
        },
        {
            id: 'ev2',
            name: 'Other EV',
            type: 'current' as const,
            enabled: true,
            battery_capacity_kwh: 60,
            min_soc_percent: 10,
            target_soc_percent: 80,
            sensor: '',
            phases: [1],
        },
    ],
    load_balancing: {
        auto_include_devices: false,
        give_way_order: [
            { kind: 'charger', id: 'ev1' },
            { kind: 'battery', id: 'battery' },
        ],
        loads: [],
    },
}
function Harness() {
    const state = useSettingsForm(fields, [])
    if (state.loading) return <p>Loading…</p>
    return (
        <>
            <SettingsField
                field={orderField}
                value={state.form[orderField.key]}
                fullForm={state.form}
                config={state.config as unknown as Record<string, unknown>}
                onChange={state.handleChange}
            />
            <button onClick={() => state.save()}>Save selection</button>
        </>
    )
}

describe('explicit give-way selection save and reload', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        let stored = structuredClone(initial)
        vi.mocked(Api.config).mockImplementation(async () => structuredClone(stored))
        vi.mocked(Api.haEntities).mockResolvedValue({ entities: [] })
        vi.mocked(Api.configSave).mockImplementation(async (patch) => {
            stored = { ...stored, load_balancing: { ...stored.load_balancing, ...(patch.load_balancing as object) } }
            return { status: 'success' }
        })
    })
    it('removes every device, saves an empty list, re-adds and reorders devices without altering charger config', async () => {
        render(
            <MemoryRouter>
                <Harness />
            </MemoryRouter>,
        )
        await screen.findByLabelText('Remove Garage EV')
        fireEvent.click(screen.getByLabelText('Remove Garage EV'))
        fireEvent.click(screen.getByLabelText('Remove House battery (grid charging)'))
        fireEvent.click(screen.getByText('Save selection'))
        await waitFor(() =>
            expect(Api.configSave).toHaveBeenCalledWith({
                load_balancing: { auto_include_devices: false, give_way_order: [] },
            }),
        )
        await waitFor(() => expect(Api.config).toHaveBeenCalledTimes(2))
        expect(screen.queryByLabelText('Remove Garage EV')).not.toBeInTheDocument()
        for (const value of ['battery', 'charger:ev2', 'charger:ev1']) {
            fireEvent.click(screen.getByRole('button', { name: 'Add Load' }))
            fireEvent.change(screen.getByLabelText('Load to add'), { target: { value } })
            fireEvent.click(screen.getByRole('button', { name: 'Add selected load' }))
        }
        fireEvent.click(screen.getAllByLabelText('Move give-way entry up')[2])
        fireEvent.click(screen.getByText('Save selection'))
        await waitFor(() =>
            expect(Api.configSave).toHaveBeenLastCalledWith({
                load_balancing: {
                    auto_include_devices: false,
                    give_way_order: [
                        { kind: 'battery', id: 'battery' },
                        { kind: 'charger', id: 'ev1' },
                        { kind: 'charger', id: 'ev2' },
                    ],
                },
            }),
        )
        await waitFor(() => expect(Api.config).toHaveBeenCalledTimes(3))
        expect(screen.getByLabelText('Remove Garage EV')).toBeInTheDocument()
        expect(screen.getByLabelText('Remove Other EV')).toBeInTheDocument()
        fireEvent.click(screen.getByRole('button', { name: 'Add Load' }))
        const options = screen.getByLabelText('Load to add').querySelectorAll('option')
        expect([...options].map((option) => option.value)).toEqual(['', 'on_off'])
        expect((await Api.config()).ev_chargers).toEqual(initial.ev_chargers)
        expect(initial.load_balancing.give_way_order).toHaveLength(2)
    })
    it('sends the explicit flag when editing a legacy auto-included order', async () => {
        vi.mocked(Api.config).mockResolvedValue({
            ...structuredClone(initial),
            load_balancing: { ...structuredClone(initial.load_balancing), auto_include_devices: true },
        })
        render(
            <MemoryRouter>
                <Harness />
            </MemoryRouter>,
        )
        await screen.findByLabelText('Remove Garage EV')
        fireEvent.click(screen.getByLabelText('Remove Garage EV'))
        fireEvent.click(screen.getByText('Save selection'))
        await waitFor(() =>
            expect(Api.configSave).toHaveBeenCalledWith({
                load_balancing: { auto_include_devices: false, give_way_order: [{ kind: 'battery', id: 'battery' }] },
            }),
        )
    })
})
