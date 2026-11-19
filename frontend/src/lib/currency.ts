import { Fragment, createElement, useEffect, useSyncExternalStore, type ReactNode } from 'react'
import { Api } from './api'

/**
 * Single source of the currency every amount is shown in: `nordpool.currency` from `/api/config`.
 *
 * Amounts in config keys, API fields and database columns are in the configured currency
 * (legacy `_sek` suffix, never renamed). Only this file may name a currency or subunit; the
 * guard test `currency.guard.test.ts` fails on literals elsewhere in the frontend sources.
 */

type CurrencyInfo = {
    /** Upper-case ISO 4217 code. */
    code: string
    /** Subunit name and how many make one main unit; null when the currency has no entry. */
    subunit: { name: string; factor: number } | null
}

const SUBUNITS: Readonly<Record<string, { name: string; factor: number }>> = {
    SEK: { name: 'öre', factor: 100 },
    EUR: { name: 'cent', factor: 100 },
    NOK: { name: 'øre', factor: 100 },
    DKK: { name: 'øre', factor: 100 },
}

/** Currency codes offered in Settings, in display order. */
export const SUPPORTED_CURRENCIES: readonly string[] = Object.keys(SUBUNITS)

/** Code and subunit for a currency code, or null when the code is not a 3-letter ISO code. */
export function currencyInfo(code: string | null | undefined): CurrencyInfo | null {
    if (typeof code !== 'string') return null
    const normalized = code.trim().toUpperCase()
    if (!/^[A-Z]{3}$/.test(normalized)) return null
    return { code: normalized, subunit: SUBUNITS[normalized] ?? null }
}

export type CurrencyOptions = {
    /** Currency code; null or invalid renders the number without a unit. */
    currency: string | null | undefined
    digits?: number
}

export type PriceOptions = CurrencyOptions & {
    /** `main` shows e.g. SEK/kWh, `sub` shows e.g. öre/kWh (main unit when the currency has no subunit). */
    unit?: 'main' | 'sub'
}

/** Unit text for an amount (e.g. "SEK"), or an empty string when the currency is unknown. */
export function moneyUnitLabel(currency: string | null | undefined): string {
    return currencyInfo(currency)?.code ?? ''
}

/** Unit text for a per-kWh price (e.g. "SEK/kWh" or "öre/kWh"), or an empty string when unknown. */
export function priceUnitLabel(currency: string | null | undefined, unit: 'main' | 'sub' = 'main'): string {
    const info = currencyInfo(currency)
    if (!info) return ''
    return `${unit === 'sub' && info.subunit ? info.subunit.name : info.code}/kWh`
}

/** A field label with its unit in parentheses, e.g. "Fee (SEK/kWh)"; the bare label when the unit is empty. */
export function labelWithUnit(label: string, unit: string): string {
    return unit ? `${label} (${unit})` : label
}

function withUnit(text: string, unit: string): string {
    return unit ? `${text} ${unit}` : text
}

/** An amount of money, e.g. "3.40 EUR"; just the number before the currency is known. */
export function formatMoney(value: number, { currency, digits = 2 }: CurrencyOptions): string {
    return withUnit(value.toFixed(digits), moneyUnitLabel(currency))
}

/** A price per kWh, e.g. "0.12 EUR/kWh" or in subunits "128 öre/kWh". */
export function formatPrice(value: number, { currency, digits = 2, unit = 'main' }: PriceOptions): string {
    const info = currencyInfo(currency)
    const subunit = unit === 'sub' ? (info?.subunit ?? null) : null
    const asSub = subunit != null
    const shown = subunit ? value * subunit.factor : value
    return withUnit(shown.toFixed(digits), priceUnitLabel(currency, asSub ? 'sub' : 'main'))
}

/**
 * Replaces `{currency}` (e.g. "SEK") and `{priceUnit}` (e.g. "SEK/kWh") tokens in a static UI
 * string. While the currency is unknown the tokens vanish together with the parentheses and
 * separators around them, so "Fee ({priceUnit}, excl. VAT)" reads "Fee (excl. VAT)".
 */
export function substituteCurrencyTokens(text: string, currency: string | null | undefined): string {
    if (!text.includes('{')) return text
    return text
        .replace(/\{currency\}/g, moneyUnitLabel(currency))
        .replace(/\{priceUnit\}/g, priceUnitLabel(currency))
        .replace(/\s*\(\s*\)/g, '')
        .replace(/\(\s*,\s*/g, '(')
        .replace(/\(\//g, '(')
        .replace(/ {2,}/g, ' ')
}

// ---- store ----

let current: string | null = null
const listeners = new Set<() => void>()

/** Sets the configured currency; an invalid or empty code resets to unknown. */
export function setCurrency(code: string | null | undefined): void {
    const next = currencyInfo(code)?.code ?? null
    if (next === current) return
    current = next
    listeners.forEach((listener) => listener())
}

export function getCurrency(): string | null {
    return current
}

export function subscribe(listener: () => void): () => void {
    listeners.add(listener)
    return () => {
        listeners.delete(listener)
    }
}

/** The configured currency code, or null until it has loaded. Re-renders when it changes. */
export function useCurrency(): string | null {
    return useSyncExternalStore(subscribe, getCurrency, getCurrency)
}

/** Formatting helpers bound to the configured currency. */
export function useCurrencyFormat() {
    const currency = useCurrency()
    return {
        currency,
        moneyUnit: moneyUnitLabel(currency),
        priceUnit: (unit: 'main' | 'sub' = 'main') => priceUnitLabel(currency, unit),
        money: (value: number, digits?: number) => formatMoney(value, { currency, digits }),
        price: (value: number, opts: { unit?: 'main' | 'sub'; digits?: number } = {}) =>
            formatPrice(value, { currency, ...opts }),
    }
}

/** Loads the configured currency once and again whenever the configuration changes. */
export function CurrencyProvider({ children }: { children?: ReactNode }): ReactNode {
    useEffect(() => {
        let cancelled = false
        const load = () => {
            Api.config()
                .then((config) => {
                    if (!cancelled) setCurrency(config.nordpool?.currency)
                })
                .catch((err) => console.error('Failed to load currency', err))
        }
        load()
        window.addEventListener('config-changed', load)
        return () => {
            cancelled = true
            window.removeEventListener('config-changed', load)
        }
    }, [])
    return createElement(Fragment, null, children)
}
