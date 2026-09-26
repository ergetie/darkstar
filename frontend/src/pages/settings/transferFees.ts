/**
 * Time-of-use transfer fee matcher — TS port of backend/core/time_windows.py
 * and backend/core/prices.py:resolve_transfer_fee, used for the settings
 * preview. The backend remains the source of truth; both implementations are
 * checked against tests/fixtures/time_window_vectors.json.
 */

export type TransferFeeMode = 'flat' | 'time_of_use'

export interface TransferFeeRule {
    months?: number[]
    weekdays?: number[]
    hours?: { start: number; end: number }
    fee_sek: number
}

/** A local wall-clock moment (no timezone math: matching is by wall-clock). */
export interface LocalDateTime {
    year: number
    month: number // 1-12
    day: number
    hour: number
}

export const MONTH_LABELS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
export const WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const SATURDAY = 5
const SUNDAY = 6

const isInt = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v)

function checkIntList(raw: unknown, field: string, lo: number, hi: number): void {
    if (raw === undefined || raw === null) return
    if (!Array.isArray(raw)) throw new Error(`${field} must be a list`)
    for (const item of raw) {
        if (!isInt(item)) throw new Error(`${field} values must be integers ${lo}-${hi}`)
        if (item < lo || item > hi) throw new Error(`${field} value ${item} is outside ${lo}-${hi}`)
    }
}

/** Validate a window (months/weekdays/hours). Throws with a message on invalid input. */
export function validateWindow(raw: unknown): void {
    if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('window must be a mapping')
    const w = raw as Record<string, unknown>
    checkIntList(w.months, 'months', 1, 12)
    checkIntList(w.weekdays, 'weekdays', 0, 6)
    if (w.hours === undefined || w.hours === null) return
    if (typeof w.hours !== 'object' || Array.isArray(w.hours)) {
        throw new Error('hours must be a mapping with start and end')
    }
    const { start, end } = w.hours as Record<string, unknown>
    if (!isInt(start) || start < 0 || start > 23) throw new Error('hours.start must be an integer 0-23')
    if (!isInt(end) || end < 1 || end > 24) throw new Error('hours.end must be an integer 1-24')
    if (start === end) throw new Error('hours.start and hours.end must differ')
}

/** Validate a full rule (window + fee_sek). Throws with a message on invalid input. */
export function validateRule(raw: unknown): void {
    validateWindow(raw)
    const fee = (raw as Record<string, unknown>).fee_sek
    if (typeof fee !== 'number' || !Number.isFinite(fee)) throw new Error('fee_sek must be a number')
    if (fee < 0) throw new Error('fee_sek must not be negative')
}

/** First error message across rules, prefixed with the 1-based rule number, or null. */
export function rulesError(rules: unknown): string | null {
    if (!Array.isArray(rules)) return 'Rules must be a list'
    for (let i = 0; i < rules.length; i++) {
        try {
            validateRule(rules[i])
        } catch (e) {
            return `Rule ${i + 1}: ${e instanceof Error ? e.message : String(e)}`
        }
    }
    return null
}

function dateKey(year: number, month: number, day: number): string {
    return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

function addDays(year: number, month: number, day: number, delta: number): [number, number, number] {
    const d = new Date(Date.UTC(year, month - 1, day + delta))
    return [d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate()]
}

/** 0=Mon .. 6=Sun, like Python's weekday(). */
export function weekdayOf(year: number, month: number, day: number): number {
    return (new Date(Date.UTC(year, month - 1, day)).getUTCDay() + 6) % 7
}

function easterSunday(year: number): [number, number, number] {
    const a = year % 19
    const b = Math.floor(year / 100)
    const c = year % 100
    const d = Math.floor(b / 4)
    const e = b % 4
    const f = Math.floor((b + 8) / 25)
    const g = Math.floor((b - f + 1) / 3)
    const h = (19 * a + b - d - g + 15) % 30
    const i = Math.floor(c / 4)
    const k = c % 4
    const l = (32 + 2 * e + 2 * i - h - k) % 7
    const m = Math.floor((a + 11 * h + 22 * l) / 451)
    const month = Math.floor((h + l - 7 * m + 114) / 31)
    const day = ((h + l - 7 * m + 114) % 31) + 1
    return [year, month, day]
}

function saturdayOnOrAfter(year: number, month: number, day: number): [number, number, number] {
    return addDays(year, month, day, (SATURDAY - weekdayOf(year, month, day) + 7) % 7)
}

const holidayCache = new Map<number, Set<string>>()

/** Swedish public holidays plus Midsommarafton, Julafton and Nyårsafton, as YYYY-MM-DD keys. */
export function swedishPublicHolidays(year: number): Set<string> {
    const cached = holidayCache.get(year)
    if (cached) return cached
    const [ey, em, ed] = easterSunday(year)
    const easter = (delta: number) => dateKey(...addDays(ey, em, ed, delta))
    const [my, mm, md] = saturdayOnOrAfter(year, 6, 20)
    const days = new Set<string>([
        dateKey(year, 1, 1),
        dateKey(year, 1, 6),
        easter(-2),
        easter(0),
        easter(1),
        dateKey(year, 5, 1),
        easter(39),
        dateKey(year, 6, 6),
        easter(49),
        dateKey(...addDays(my, mm, md, -1)),
        dateKey(my, mm, md),
        dateKey(...saturdayOnOrAfter(year, 10, 31)),
        dateKey(year, 12, 24),
        dateKey(year, 12, 25),
        dateKey(year, 12, 26),
        dateKey(year, 12, 31),
    ])
    holidayCache.set(year, days)
    return days
}

/** Whether a local wall-clock moment falls inside a (valid) window. */
export function matchesWindow(
    window: Omit<TransferFeeRule, 'fee_sek'>,
    dt: LocalDateTime,
    holidaysAsWeekend = false,
): boolean {
    if (window.months && window.months.length > 0 && !window.months.includes(dt.month)) return false
    if (window.weekdays && window.weekdays.length > 0) {
        const isHoliday = holidaysAsWeekend && swedishPublicHolidays(dt.year).has(dateKey(dt.year, dt.month, dt.day))
        if (isHoliday) {
            if (!window.weekdays.includes(SATURDAY) && !window.weekdays.includes(SUNDAY)) return false
        } else if (!window.weekdays.includes(weekdayOf(dt.year, dt.month, dt.day))) {
            return false
        }
    }
    if (window.hours) {
        const { start, end } = window.hours
        const inRange = start < end ? dt.hour >= start && dt.hour < end : dt.hour >= start || dt.hour < end
        if (!inRange) return false
    }
    return true
}

/** Parse "YYYY-MM-DDTHH:MM" (or "YYYY-MM-DD" with a separate hour) into a LocalDateTime. */
export function parseLocalDateTime(value: string, hour?: number): LocalDateTime {
    const [datePart, timePart] = value.split('T')
    const [year, month, day] = datePart.split('-').map(Number)
    return { year, month, day, hour: hour ?? Number((timePart ?? '0').split(':')[0]) }
}

/**
 * Resolve the transfer fee for a local moment: first valid matching rule wins,
 * flat fee otherwise (and always in flat mode). Invalid rules are skipped.
 */
export function resolveTransferFee(
    mode: TransferFeeMode,
    rules: TransferFeeRule[],
    flatFee: number,
    dt: LocalDateTime,
    holidaysAsWeekend: boolean,
): { fee: number; ruleIndex: number | null } {
    if (mode !== 'time_of_use') return { fee: flatFee, ruleIndex: null }
    for (let i = 0; i < rules.length; i++) {
        try {
            validateRule(rules[i])
        } catch {
            continue
        }
        if (matchesWindow(rules[i], dt, holidaysAsWeekend)) return { fee: rules[i].fee_sek, ruleIndex: i }
    }
    return { fee: flatFee, ruleIndex: null }
}

/** Transfer fee settings as read from `pricing.*` config. */
export interface TransferFeeConfig {
    mode: TransferFeeMode
    rules: TransferFeeRule[]
    flatFee: number
    holidaysAsWeekend: boolean
}

/** Build a TransferFeeConfig from the raw `pricing` config section (missing keys → flat). */
export function transferFeeConfigFromPricing(pricing: {
    grid_transfer_fee_sek?: number
    transfer_fee_mode?: TransferFeeMode
    holidays_as_weekend?: boolean
    transfer_fee_rules?: TransferFeeRule[]
}): TransferFeeConfig {
    return {
        mode: pricing.transfer_fee_mode === 'time_of_use' ? 'time_of_use' : 'flat',
        rules: Array.isArray(pricing.transfer_fee_rules) ? pricing.transfer_fee_rules : [],
        flatFee: Number(pricing.grid_transfer_fee_sek ?? 0) || 0,
        holidaysAsWeekend: pricing.holidays_as_weekend === true,
    }
}

/**
 * Transfer fee for a slot. Without a slot time the flat fee applies, mirroring
 * the backend's `calculate_import_export_prices(..., slot_start=None)`.
 */
export function transferFeeAt(config: TransferFeeConfig, dt?: LocalDateTime | null): number {
    if (!dt) return config.flatFee
    return resolveTransferFee(config.mode, config.rules, config.flatFee, dt, config.holidaysAsWeekend).fee
}
