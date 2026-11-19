import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { SettingsField } from './SettingsField'
import { systemSections, batteryFieldList, type BaseField } from '../types'
import { guides } from '../search/guides'
import { searchFields } from '../search'
import { setCurrency, substituteCurrencyTokens } from '../../../lib/currency'

afterEach(() => setCurrency(null))

const field = (key: string): BaseField => {
    const found = [...systemSections.flatMap((s) => s.fields), ...batteryFieldList].find((f) => f.key === key)
    if (!found) throw new Error(`field ${key} not found`)
    return found
}

describe('currency tokens in settings', () => {
    it.each([
        ['SEK', 'Energy tax (SEK/kWh, excl. VAT)'],
        ['EUR', 'Energy tax (EUR/kWh, excl. VAT)'],
    ])('resolves a field label for %s', (code, expected) => {
        setCurrency(code)
        render(<SettingsField field={field('pricing.energy_tax_sek')} value="0.36" onChange={() => {}} />)
        expect(screen.getByText(expected)).toBeInTheDocument()
    })

    it('resolves a monetary label with the main unit', () => {
        setCurrency('EUR')
        render(<SettingsField field={field('pricing.subscription_fee_sek_per_month')} value="" onChange={() => {}} />)
        expect(screen.getByText('Monthly subscription fee (EUR, excl. VAT)')).toBeInTheDocument()
    })

    it('shows the bare label while the currency is unknown', () => {
        render(<SettingsField field={field('pricing.energy_tax_sek')} value="0.36" onChange={() => {}} />)
        expect(screen.getByText('Energy tax (excl. VAT)')).toBeInTheDocument()
    })

    it('resolves guide text and search results', () => {
        const guide = guides.find((g) => g.body.includes('{priceUnit}'))
        expect(guide).toBeDefined()
        expect(substituteCurrencyTokens(guide!.body, 'EUR')).toContain('50 EUR/kWh')
        setCurrency('EUR')
        expect(searchFields('energy tax')[0].entry.label).toContain('{priceUnit}')
        expect(searchFields('EUR/kWh').length).toBeGreaterThan(0)
        expect(searchFields('SEK/kWh')).toHaveLength(0)
    })
})
