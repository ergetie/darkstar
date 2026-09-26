import { useState } from 'react'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { TransferFeeRulesEditor } from './TransferFeeRulesEditor'
import { SettingsField } from './SettingsField'
import { systemSections } from '../types'
import type { TransferFeeMode, TransferFeeRule } from '../transferFees'

const WINTER: TransferFeeRule = {
    months: [11, 12, 1, 2, 3],
    weekdays: [0, 1, 2, 3, 4],
    hours: { start: 6, end: 22 },
    fee_sek: 0.76,
}
const NIGHT: TransferFeeRule = { hours: { start: 22, end: 6 }, fee_sek: 0.1 }

function Harness({
    initialMode = 'time_of_use' as TransferFeeMode,
    initialRules = [WINTER, NIGHT],
    holidays = false,
    onRules = vi.fn(),
}) {
    const [mode, setMode] = useState<TransferFeeMode>(initialMode)
    const [rules, setRules] = useState<TransferFeeRule[]>(initialRules)
    const [flat, setFlat] = useState('0.25')
    const [hol, setHol] = useState(holidays)
    return (
        <TransferFeeRulesEditor
            mode={mode}
            rules={rules}
            flatFee={flat}
            holidaysAsWeekend={hol}
            onModeChange={setMode}
            onRulesChange={(r) => {
                setRules(r)
                onRules(r)
            }}
            onFlatFeeChange={setFlat}
            onHolidaysChange={setHol}
        />
    )
}

const ruleCards = () => screen.queryAllByTestId('transfer-fee-rule')
const previewFees = () => screen.getAllByTestId('transfer-fee-preview-hour').map((el) => Number(el.dataset.fee))

describe('TransferFeeRulesEditor', () => {
    beforeAll(() => {
        // jsdom has no layout; Select scrolls the highlighted option into view.
        Element.prototype.scrollIntoView = vi.fn()
    })

    it('switching to flat and back keeps the rules', () => {
        const onRules = vi.fn()
        render(<Harness onRules={onRules} />)
        expect(ruleCards()).toHaveLength(2)
        fireEvent.click(screen.getByRole('button', { name: 'Flat' }))
        expect(ruleCards()).toHaveLength(0)
        expect(screen.getByLabelText('Flat transfer fee')).toBeInTheDocument()
        fireEvent.click(screen.getByRole('button', { name: 'Time-of-use' }))
        expect(ruleCards()).toHaveLength(2)
        expect(onRules).not.toHaveBeenCalled()
    })

    it('shows the fixed, non-deletable catch-all row', () => {
        render(<Harness />)
        const catchAll = screen.getByTestId('transfer-fee-catch-all')
        expect(within(catchAll).getByText('All other times')).toBeInTheDocument()
        expect(within(catchAll).queryByRole('button', { name: /Delete/ })).toBeNull()
        expect(screen.getByLabelText('All other times fee')).toHaveValue(0.25)
    })

    it('reorders rules', () => {
        const onRules = vi.fn()
        render(<Harness onRules={onRules} />)
        expect(screen.getByRole('button', { name: 'Move rule 1 up' })).toBeDisabled()
        fireEvent.click(screen.getByRole('button', { name: 'Move rule 2 up' }))
        expect(onRules).toHaveBeenLastCalledWith([NIGHT, WINTER])
    })

    it('adds and deletes rules', () => {
        const onRules = vi.fn()
        render(<Harness onRules={onRules} />)
        fireEvent.click(screen.getByRole('button', { name: /Add rule/ }))
        expect(ruleCards()).toHaveLength(3)
        expect(onRules).toHaveBeenLastCalledWith([WINTER, NIGHT, { hours: { start: 6, end: 22 }, fee_sek: 0.25 }])
        fireEvent.click(screen.getByRole('button', { name: 'Delete rule 1' }))
        expect(ruleCards()).toHaveLength(2)
        expect(onRules).toHaveBeenLastCalledWith([NIGHT, { hours: { start: 6, end: 22 }, fee_sek: 0.25 }])
    })

    it('toggles weekday chips', () => {
        const onRules = vi.fn()
        render(<Harness onRules={onRules} />)
        const weekdays = within(ruleCards()[0]).getByRole('group', { name: 'Weekdays' })
        fireEvent.click(within(weekdays).getByRole('button', { name: 'Sat' }))
        expect(onRules.mock.lastCall?.[0][0].weekdays).toEqual([0, 1, 2, 3, 4, 5])
    })

    it('previews fees per hour for the chosen date', () => {
        render(<Harness />)
        fireEvent.change(screen.getByLabelText('Preview date'), { target: { value: '2026-12-01' } })
        const fees = previewFees()
        expect(fees).toHaveLength(24)
        expect(fees[5]).toBe(0.1) // night rule (wraps midnight)
        expect(fees[6]).toBe(0.76) // winter weekday
        expect(fees[21]).toBe(0.76)
        expect(fees[22]).toBe(0.1)
    })

    it('updates the preview immediately on unsaved edits without changing the date', () => {
        render(<Harness />)
        fireEvent.change(screen.getByLabelText('Preview date'), { target: { value: '2026-12-01' } })
        expect(previewFees()[10]).toBe(0.76)

        // Rule fee
        fireEvent.change(screen.getByLabelText('Rule 1 fee'), { target: { value: '0.9' } })
        expect(previewFees()[10]).toBe(0.9)

        // Rule hours: narrow the winter rule to end at 10 → 10:00 falls to the catch-all
        const toSelect = within(ruleCards()[0])
            .getAllByRole('button')
            .find((b) => b.textContent?.includes('22:00'))
        expect(toSelect).toBeDefined()
        fireEvent.click(toSelect!)
        fireEvent.click(screen.getByText('10:00'))
        expect(previewFees()[9]).toBe(0.9)
        expect(previewFees()[10]).toBe(0.25)

        // Catch-all fee
        fireEvent.change(screen.getByLabelText('All other times fee'), { target: { value: '0.3' } })
        expect(previewFees()[10]).toBe(0.3)

        // Weekday chips: drop Tuesday (2026-12-01) → the winter rule no longer matches
        const weekdays = within(ruleCards()[0]).getByRole('group', { name: 'Weekdays' })
        fireEvent.click(within(weekdays).getByRole('button', { name: 'Tue' }))
        expect(previewFees()[9]).toBe(0.3)

        // Mode
        fireEvent.click(screen.getByRole('button', { name: 'Flat' }))
        expect(new Set(previewFees())).toEqual(new Set([0.3]))
        expect(screen.getByLabelText('Preview date')).toHaveValue('2026-12-01')
    })

    it('updates the preview when the holiday toggle changes', () => {
        render(<Harness initialRules={[WINTER]} />)
        fireEvent.change(screen.getByLabelText('Preview date'), { target: { value: '2026-12-25' } })
        expect(previewFees()[10]).toBe(0.76)
        fireEvent.click(screen.getByTestId('transfer-fee-holidays').firstElementChild!)
        expect(previewFees()[10]).toBe(0.25)
    })

    it('updates the preview through the Settings form wiring', () => {
        function FormHarness() {
            const [form, setForm] = useState<Record<string, string>>({
                'pricing.transfer_fee_rules': JSON.stringify([WINTER]),
                'pricing.transfer_fee_mode': 'time_of_use',
                'pricing.grid_transfer_fee_sek': '0.25',
                'pricing.holidays_as_weekend': 'false',
            })
            const field = systemSections.flatMap((s) => s.fields).find((f) => f.key === 'pricing.transfer_fee_rules')!
            return (
                <SettingsField
                    field={field}
                    value={form[field.key]}
                    onChange={(k, v) => setForm((prev) => ({ ...prev, [k]: v }))}
                    fullForm={form}
                />
            )
        }
        render(<FormHarness />)
        fireEvent.change(screen.getByLabelText('Preview date'), { target: { value: '2026-12-01' } })
        expect(previewFees()[10]).toBe(0.76)
        fireEvent.change(screen.getByLabelText('Rule 1 fee'), { target: { value: '0.9' } })
        expect(previewFees()[10]).toBe(0.9)
        fireEvent.change(screen.getByLabelText('All other times fee'), { target: { value: '0.3' } })
        expect(previewFees()[23]).toBe(0.3)
    })

    it('previews holidays as weekend when the toggle is on', () => {
        render(<Harness initialRules={[WINTER]} holidays />)
        fireEvent.change(screen.getByLabelText('Preview date'), { target: { value: '2026-12-25' } })
        expect(previewFees()[10]).toBe(0.25)
    })

    it('previews the flat fee in flat mode', () => {
        render(<Harness initialMode="flat" />)
        fireEvent.change(screen.getByLabelText('Preview date'), { target: { value: '2026-12-01' } })
        expect(new Set(previewFees())).toEqual(new Set([0.25]))
    })

    it('labels each preview hour with range, fee and matched rule', () => {
        render(<Harness />)
        fireEvent.change(screen.getByLabelText('Preview date'), { target: { value: '2026-12-01' } })
        const hours = screen.getAllByTestId('transfer-fee-preview-hour')
        expect(hours[6]).toHaveAccessibleName('06:00–07:00: 0.76 SEK/kWh (Rule 1)')
        expect(hours[6]).toHaveAttribute('title', '06:00–07:00: 0.76 SEK/kWh (Rule 1)')
        expect(hours[23]).toHaveAccessibleName('23:00–24:00: 0.10 SEK/kWh (Rule 2)')
    })

    it('names the catch-all row when no rule matches', () => {
        render(<Harness initialRules={[WINTER]} />)
        fireEvent.change(screen.getByLabelText('Preview date'), { target: { value: '2026-12-01' } })
        expect(screen.getAllByTestId('transfer-fee-preview-hour')[2]).toHaveAccessibleName(
            '02:00–03:00: 0.25 SEK/kWh (All other times)',
        )
    })

    it('shows a tooltip on hover and hides it on leave', () => {
        render(<Harness />)
        fireEvent.change(screen.getByLabelText('Preview date'), { target: { value: '2026-12-01' } })
        const hour = screen.getAllByTestId('transfer-fee-preview-hour')[6]
        fireEvent.pointerEnter(hour, { pointerType: 'mouse' })
        const tip = screen.getByRole('tooltip')
        expect(tip).toHaveTextContent('06:00–07:00')
        expect(tip).toHaveTextContent('0.76 SEK/kWh')
        expect(tip).toHaveTextContent('Rule 1')
        expect(hour).toHaveAttribute('aria-describedby', tip.id)
        fireEvent.pointerLeave(hour.parentElement!, { pointerType: 'mouse' })
        expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
    })

    it('toggles the tooltip on tap and on keyboard focus', () => {
        render(<Harness initialRules={[WINTER]} />)
        fireEvent.change(screen.getByLabelText('Preview date'), { target: { value: '2026-12-01' } })
        const hours = screen.getAllByTestId('transfer-fee-preview-hour')
        fireEvent.click(hours[2])
        expect(screen.getByRole('tooltip')).toHaveTextContent('All other times')
        fireEvent.click(hours[2])
        expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
        fireEvent.focus(hours[10])
        expect(screen.getByRole('tooltip')).toHaveTextContent('10:00–11:00')
        fireEvent.blur(hours[10])
        expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
    })

    it('renders the holiday switch as a non-shrinking control', () => {
        render(<Harness />)
        const row = screen.getByTestId('transfer-fee-holidays')
        expect(row.querySelector('.toggle')).toHaveClass('shrink-0')
    })
})
