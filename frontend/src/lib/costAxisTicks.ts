export type AxisTick = {
    /** Position along the axis in percent */
    x: number
    label: string
    row: 0 | 1
    align: 'start' | 'center' | 'end'
    /** The label belongs to a repeated local hour (DST fall-back) and carries its UTC offset */
    repeated?: boolean
}

/** Rendered size of an axis label: `text-[10px]` with tabular figures is about 6 px per character. */
const CHAR_WIDTH_PX = 6
/** Smallest clear space between two labels of the same row. */
const MIN_GAP_PX = 4

/** "02:00 +01:00" is drawn as "02+1"; any other label is drawn as is. */
export function compactAxisLabel(label: string): string {
    const repeatedHour = /^(\d{2}):\d{2} ([+−-])(\d{2}):(\d{2})$/.exec(label)
    if (!repeatedHour) return label
    const [, hour, sign, offsetHour, offsetMinute] = repeatedHour
    return `${hour}${sign}${offsetMinute === '00' ? Number(offsetHour) : `${Number(offsetHour)}:${offsetMinute}`}`
}

export function estimateLabelWidth(label: string): number {
    return compactAxisLabel(label).length * CHAR_WIDTH_PX
}

/** Lower rank is placed first and wins a collision: axis ends, then repeated hours, then the rest. */
function rankOf(tick: AxisTick): number {
    if (tick.x <= 0 || tick.x >= 100) return 0
    return tick.repeated ? 1 : 2
}

/**
 * Lay the axis labels out for a chart `widthPx` wide so that no two labels in a row overlap.
 *
 * Positions are percentages while labels have a fixed pixel size, so a collision depends on the
 * width. Labels are placed in priority order; each keeps its preferred row, tries the other row
 * when that collides and is omitted when both do. The input order is kept. An unknown width
 * (0, before layout) leaves the ticks untouched.
 */
export function layoutAxisTicks(ticks: AxisTick[], widthPx: number): AxisTick[] {
    if (!(widthPx > 0)) return ticks
    const placed: Record<0 | 1, { left: number; right: number }[]> = { 0: [], 1: [] }
    const result = new Map<AxisTick, AxisTick>()
    const order = ticks
        .map((tick, index) => ({ tick, index }))
        .sort((a, b) => rankOf(a.tick) - rankOf(b.tick) || a.index - b.index)
    for (const { tick } of order) {
        const labelWidth = estimateLabelWidth(tick.label)
        const x = (tick.x / 100) * widthPx
        const left = tick.align === 'start' ? x : tick.align === 'end' ? x - labelWidth : x - labelWidth / 2
        const right = left + labelWidth
        for (const row of [tick.row, tick.row === 0 ? 1 : 0] as const) {
            const free = placed[row].every(
                (other) => right + MIN_GAP_PX <= other.left || other.right + MIN_GAP_PX <= left,
            )
            if (!free) continue
            placed[row].push({ left, right })
            result.set(tick, row === tick.row ? tick : { ...tick, row })
            break
        }
    }
    return ticks.flatMap((tick) => {
        const laidOut = result.get(tick)
        return laidOut ? [laidOut] : []
    })
}
