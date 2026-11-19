import { afterEach, describe, expect, it } from 'vitest'
import {
    currencyInfo,
    formatMoney,
    formatPrice,
    getCurrency,
    moneyUnitLabel,
    priceUnitLabel,
    setCurrency,
    substituteCurrencyTokens,
} from './currency'

afterEach(() => setCurrency(null))

describe('currencyInfo', () => {
    it('derives the subunit from the code', () => {
        expect(currencyInfo('SEK')?.subunit).toEqual({ name: 'öre', factor: 100 })
        expect(currencyInfo('NOK')?.subunit?.name).toBe('øre')
        expect(currencyInfo('DKK')?.subunit?.name).toBe('øre')
        expect(currencyInfo('EUR')?.subunit).toEqual({ name: 'cent', factor: 100 })
    })

    it('normalizes case and keeps unknown codes without a subunit', () => {
        expect(currencyInfo(' eur ')?.code).toBe('EUR')
        expect(currencyInfo('CHF')).toEqual({ code: 'CHF', subunit: null })
    })

    it('rejects values that are not a 3-letter code', () => {
        expect(currencyInfo(null)).toBeNull()
        expect(currencyInfo('')).toBeNull()
        expect(currencyInfo('EURO')).toBeNull()
        expect(currencyInfo('12$')).toBeNull()
    })
})

describe('formatting', () => {
    it('renders the configured main unit', () => {
        expect(formatPrice(0.12, { currency: 'EUR' })).toBe('0.12 EUR/kWh')
        expect(formatMoney(3.4, { currency: 'EUR' })).toBe('3.40 EUR')
        expect(formatMoney(1.234, { currency: 'SEK', digits: 1 })).toBe('1.2 SEK')
        expect(priceUnitLabel('NOK')).toBe('NOK/kWh')
        expect(moneyUnitLabel('sek')).toBe('SEK')
    })

    it('renders subunits for SEK, NOK and EUR', () => {
        expect(formatPrice(1.28, { currency: 'SEK', unit: 'sub', digits: 0 })).toBe('128 öre/kWh')
        expect(formatPrice(1.28, { currency: 'NOK', unit: 'sub', digits: 0 })).toBe('128 øre/kWh')
        expect(formatPrice(0.12, { currency: 'EUR', unit: 'sub', digits: 0 })).toBe('12 cent/kWh')
        expect(priceUnitLabel('SEK', 'sub')).toBe('öre/kWh')
    })

    it('falls back to the main unit for a currency without a subunit', () => {
        expect(formatPrice(1.5, { currency: 'CHF', unit: 'sub' })).toBe('1.50 CHF/kWh')
        expect(priceUnitLabel('CHF', 'sub')).toBe('CHF/kWh')
    })

    it('renders numbers without a unit before the currency is known or when invalid', () => {
        expect(formatPrice(2.9, { currency: null })).toBe('2.90')
        expect(formatPrice(2.9, { currency: undefined, unit: 'sub', digits: 0 })).toBe('3')
        expect(formatMoney(3.4, { currency: 'nonsense' })).toBe('3.40')
        expect(priceUnitLabel(null)).toBe('')
        expect(moneyUnitLabel(null)).toBe('')
    })
})

describe('substituteCurrencyTokens', () => {
    it('resolves both tokens for SEK and EUR', () => {
        expect(substituteCurrencyTokens('Fee ({priceUnit})', 'SEK')).toBe('Fee (SEK/kWh)')
        expect(substituteCurrencyTokens('Fee ({priceUnit})', 'EUR')).toBe('Fee (EUR/kWh)')
        expect(substituteCurrencyTokens('Fee ({currency}, excl. VAT)', 'EUR')).toBe('Fee (EUR, excl. VAT)')
        expect(substituteCurrencyTokens('default 50 {priceUnit} here', 'SEK')).toBe('default 50 SEK/kWh here')
    })

    it('handles a per-kW unit and a unit-only parenthesis', () => {
        expect(substituteCurrencyTokens('Ramping Cost ({currency}/kW)', 'EUR')).toBe('Ramping Cost (EUR/kW)')
        expect(substituteCurrencyTokens('Ramping Cost ({currency}/kW)', null)).toBe('Ramping Cost (kW)')
    })

    it('drops the unit cleanly while the currency is unknown', () => {
        expect(substituteCurrencyTokens('Fee ({priceUnit})', null)).toBe('Fee')
        expect(substituteCurrencyTokens('Fee ({currency}, excl. VAT)', null)).toBe('Fee (excl. VAT)')
        expect(substituteCurrencyTokens('default 50 {priceUnit} here', null)).toBe('default 50 here')
    })

    it('leaves text without tokens alone', () => {
        expect(substituteCurrencyTokens('Plain', 'SEK')).toBe('Plain')
    })
})

describe('store', () => {
    it('keeps an upper-case code and resets on invalid input', () => {
        setCurrency('eur')
        expect(getCurrency()).toBe('EUR')
        setCurrency('x')
        expect(getCurrency()).toBeNull()
    })
})
