import { displayTimeZone } from './timezone'

export function clampTo48hISO(isoList: string[], nowIso?: string) {
    const now = nowIso ? new Date(nowIso).getTime() : Date.now()
    const end = now + 48 * 3600 * 1000
    return isoList
        .map((t, idx) => ({ idx, time: new Date(t).getTime() }))
        .map(({ idx, time }) => (time >= now && time < end ? idx : -1))
        .filter((idx) => idx >= 0)
}

export function isoToLocal(dateIso: string): Date {
    const d = new Date(dateIso)
    return d
}

type DatePartType = 'year' | 'month' | 'day' | 'hour' | 'minute'

/** Numeric calendar and clock parts of an instant, independent of locale and hour cycle. */
function zonedParts(date: Date, tz: string): Record<DatePartType, number> {
    const parts = new Intl.DateTimeFormat('en-US', {
        year: 'numeric',
        month: 'numeric',
        day: 'numeric',
        hour: 'numeric',
        minute: 'numeric',
        hourCycle: 'h23',
        timeZone: tz,
    }).formatToParts(date)
    const get = (type: DatePartType) => Number(parts.find((p) => p.type === type)?.value)
    // h23 can still report "24" at midnight on some engines
    return { year: get('year'), month: get('month'), day: get('day'), hour: get('hour') % 24, minute: get('minute') }
}

const pad = (n: number, width = 2) => String(n).padStart(width, '0')

/** Format YYYY-MM-DD of an instant in the given timezone (default: the browser's), not the UTC date. */
export function ymdLocal(date: Date, tz: string = displayTimeZone()): string {
    const { year, month, day } = zonedParts(date, tz)
    return `${pad(year, 4)}-${pad(month)}-${pad(day)}`
}

/** YYYY-MM-DD of the calendar day `days` after (or before, when negative) the day of `date`, in `tz`. */
export function shiftedYmdLocal(date: Date, days: number, tz: string = displayTimeZone()): string {
    const { year, month, day } = zonedParts(date, tz)
    const shifted = new Date(Date.UTC(year, month - 1, day + days))
    return `${pad(shifted.getUTCFullYear(), 4)}-${pad(shifted.getUTCMonth() + 1)}-${pad(shifted.getUTCDate())}`
}

export function isToday(dateIso: string, now = new Date()): boolean {
    return ymdLocal(isoToLocal(dateIso)) === ymdLocal(now)
}

export function isTomorrow(dateIso: string, now = new Date()): boolean {
    // Calendar arithmetic on the local date, so DST days of 23 or 25 hours do not matter.
    return ymdLocal(isoToLocal(dateIso)) === shiftedYmdLocal(now, 1)
}

/** "HH:MM" 24-hour wall clock of an instant in the browser timezone. */
export function formatHour(dateIso: string): string {
    const { hour, minute } = zonedParts(isoToLocal(dateIso), displayTimeZone())
    return `${pad(hour)}:${pad(minute)}`
}

/** The instant of 00:00 on the calendar day of `date` in the given timezone (default: the browser's). */
export function startOfLocalDay(date: Date, tz: string = displayTimeZone()): Date {
    const dayOrdinal = (p: { year: number; month: number; day: number }) => Date.UTC(p.year, p.month - 1, p.day)
    const target = dayOrdinal(zonedParts(date, tz))
    let candidate = Math.floor(date.getTime() / 60_000) * 60_000
    // Walk by wall-clock minutes instead of assuming 24 h days, so DST days resolve correctly.
    for (let i = 0; i < 4; i++) {
        const p = zonedParts(new Date(candidate), tz)
        const minutes = p.hour * 60 + p.minute
        const day = dayOrdinal(p)
        if (day === target && minutes === 0) break
        candidate += (day < target ? 24 * 60 - minutes : -minutes) * 60_000
    }
    return new Date(candidate)
}

export type DaySel = 'today' | 'tomorrow'

export function filterSlotsByDay<T extends { start_time: string }>(slots: T[], sel: DaySel, now = new Date()): T[] {
    const filtered = slots.filter((s) => (sel === 'today' ? isToday(s.start_time, now) : isTomorrow(s.start_time, now)))
    return filtered
}

/** Wall-clock parts (month 1-12, hour 0-23) of an instant in the given timezone. */
export function wallClockParts(
    dateIso: string,
    tz: string = displayTimeZone(),
): { year: number; month: number; day: number; hour: number } {
    const { year, month, day, hour } = zonedParts(isoToLocal(dateIso), tz)
    return { year, month, day, hour }
}
