import { describe, expect, it } from 'vitest'
import {
    buildLiveData,
    pricingBreakdownFromConfig,
    splitPriceBreakdown,
    type PricingBreakdownConfig,
} from './ChartCard'
import type { TransferFeeConfig } from '../pages/settings/transferFees'
import type { ScheduleSlot } from '../lib/types'

const flat = (flatFee: number): TransferFeeConfig => ({
    mode: 'flat',
    rules: [],
    flatFee,
    holidaysAsWeekend: false,
})

const pricingWith = (vat: number, fees: number): PricingBreakdownConfig => ({
    vat,
    energyTax: 0,
    transferFee: flat(fees),
    timezone: 'Europe/Stockholm',
})

// Winter weekdays 06-22 cost 0.76; everything else falls back to 0.20.
const touPricing: PricingBreakdownConfig = {
    vat: 25,
    energyTax: 0.4,
    transferFee: {
        mode: 'time_of_use',
        rules: [{ months: [11, 12, 1, 2, 3], weekdays: [0, 1, 2, 3, 4], hours: { start: 6, end: 22 }, fee_sek: 0.76 }],
        flatFee: 0.2,
        holidaysAsWeekend: false,
    },
    timezone: 'Europe/Stockholm',
}

describe('splitPriceBreakdown', () => {
    it('splits spot and feesAndVat so they sum back to the input value', () => {
        const value = 2.5
        const result = splitPriceBreakdown(value, pricingWith(25, 0.3))
        expect(result).not.toBeNull()
        expect(result!.spot + result!.feesAndVat).toBeCloseTo(value)
    })

    it('falls back to the raw value (no division) when vat = -100 would zero the divisor', () => {
        const value = 2.5
        const result = splitPriceBreakdown(value, pricingWith(-100, 0.3))
        expect(result).not.toBeNull()
        expect(Number.isFinite(result!.spot)).toBe(true)
        expect(Number.isFinite(result!.feesAndVat)).toBe(true)
        // basePrice falls back to `value` itself when vatMul <= 0
        expect(result!.spot).toBeCloseTo(Math.max(0, value - 0.3))
    })

    it('returns null when pricing is undefined', () => {
        expect(splitPriceBreakdown(2.5, undefined)).toBeNull()
    })

    it('clamps spot to 0 when fees exceed the base price', () => {
        const value = 0.1
        const result = splitPriceBreakdown(value, pricingWith(0, 5))
        expect(result!.spot).toBe(0)
        expect(result!.feesAndVat).toBeCloseTo(value)
    })

    it('adds energy tax and flat fee in flat mode regardless of slot time', () => {
        const pricing: PricingBreakdownConfig = {
            vat: 25,
            energyTax: 0.4,
            transferFee: flat(0.2),
            timezone: 'Europe/Stockholm',
        }
        // (1.0 + 0.4 + 0.2) * 1.25 = 2.0
        const a = splitPriceBreakdown(2.0, pricing, '2027-01-12T10:00:00+01:00')
        const b = splitPriceBreakdown(2.0, pricing)
        expect(a!.spot).toBeCloseTo(1.0)
        expect(b!.spot).toBeCloseTo(1.0)
    })

    it('uses the matching rule fee for the slot in time-of-use mode', () => {
        // Tue 2027-01-12 10:00 Stockholm → rule fee 0.76. (1.0 + 0.4 + 0.76) * 1.25 = 2.7
        const result = splitPriceBreakdown(2.7, touPricing, '2027-01-12T10:00:00+01:00')
        expect(result!.spot).toBeCloseTo(1.0)
        expect(result!.feesAndVat).toBeCloseTo(1.7)
    })

    it('uses the catch-all fee when no rule matches the slot', () => {
        // 23:00 is outside 06-22 → 0.20. (1.0 + 0.4 + 0.2) * 1.25 = 2.0
        expect(splitPriceBreakdown(2.0, touPricing, '2027-01-12T23:00:00+01:00')!.spot).toBeCloseTo(1.0)
        // Saturday 10:00 → weekday filter excludes it
        expect(splitPriceBreakdown(2.0, touPricing, '2027-01-16T10:00:00+01:00')!.spot).toBeCloseTo(1.0)
    })

    it('matches on Stockholm wall-clock time even when the slot is given in UTC', () => {
        // 05:30Z = 06:30 Stockholm (CET) → inside the rule
        expect(splitPriceBreakdown(2.7, touPricing, '2027-01-12T05:30:00Z')!.spot).toBeCloseTo(1.0)
        // 04:45Z = 05:45 Stockholm → outside
        expect(splitPriceBreakdown(2.0, touPricing, '2027-01-12T04:45:00Z')!.spot).toBeCloseTo(1.0)
    })

    it('matches on wall-clock time in the configured non-Stockholm timezone', () => {
        const helsinki: PricingBreakdownConfig = { ...touPricing, timezone: 'Europe/Helsinki' }
        // 04:30Z = 06:30 Helsinki (EET) → inside the rule, but 05:30 Stockholm (outside)
        expect(splitPriceBreakdown(2.7, helsinki, '2027-01-12T04:30:00Z')!.spot).toBeCloseTo(1.0)
        expect(splitPriceBreakdown(2.0, touPricing, '2027-01-12T04:30:00Z')!.spot).toBeCloseTo(1.0)
        // 20:30Z = 22:30 Helsinki → outside, but 21:30 Stockholm (inside)
        expect(splitPriceBreakdown(2.0, helsinki, '2027-01-12T20:30:00Z')!.spot).toBeCloseTo(1.0)
        expect(splitPriceBreakdown(2.7, touPricing, '2027-01-12T20:30:00Z')!.spot).toBeCloseTo(1.0)
    })

    it('uses the configured timezone for the weekday across midnight', () => {
        const tokyo: PricingBreakdownConfig = { ...touPricing, timezone: 'Asia/Tokyo' }
        // Fri 2027-01-15 23:30Z = Sat 08:30 Tokyo → weekday filter excludes it (catch-all)
        expect(splitPriceBreakdown(2.0, tokyo, '2027-01-15T23:30:00Z')!.spot).toBeCloseTo(1.0)
        // Sun 2027-01-17 23:30Z = Mon 08:30 Tokyo → rule applies
        expect(splitPriceBreakdown(2.7, tokyo, '2027-01-17T23:30:00Z')!.spot).toBeCloseTo(1.0)
    })

    it('falls back to the flat fee in time-of-use mode when the slot time is unknown', () => {
        expect(splitPriceBreakdown(2.0, touPricing, null)!.spot).toBeCloseTo(1.0)
    })
})

describe('pricingBreakdownFromConfig', () => {
    const pricing = { vat_percent: 25, energy_tax_sek: 0.4, grid_transfer_fee_sek: 0.2 }

    it('uses the configured timezone', () => {
        expect(pricingBreakdownFromConfig({ timezone: 'Europe/Helsinki', pricing })!.timezone).toBe('Europe/Helsinki')
    })

    it('falls back to Europe/Stockholm when timezone is unset or empty', () => {
        expect(pricingBreakdownFromConfig({ pricing })!.timezone).toBe('Europe/Stockholm')
        expect(pricingBreakdownFromConfig({ timezone: '', pricing })!.timezone).toBe('Europe/Stockholm')
    })

    it('returns null without a pricing section', () => {
        expect(pricingBreakdownFromConfig({ timezone: 'Europe/Helsinki' })).toBeNull()
    })
})

describe('buildLiveData slotStarts', () => {
    it('exposes one ISO start time per chart index', () => {
        const now = new Date()
        now.setMinutes(0, 0, 0)
        const slot = { start_time: now.toISOString(), import_price_sek_kwh: 1.5 } as ScheduleSlot
        const data = buildLiveData([slot], 'today', {}, touPricing)
        expect(data).not.toBeNull()
        expect(data!.slotStarts).toHaveLength(data!.labels!.length)
        const idx = data!.slotStarts!.indexOf(now.toISOString())
        expect(idx).toBeGreaterThanOrEqual(0)
        expect(data!.datasets[0].data[idx]).toBe(1.5)
    })
})
