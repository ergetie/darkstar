/** Horizontal room one hour label needs: "00" in 10px monospace (~12px) plus a 4px gap. */
export const MIN_PX_PER_HOUR_LABEL = 16

/** Label strides tried in order; all divide 24 so labels stay aligned to midnight. */
const HOUR_LABEL_STEPS = [1, 3, 6, 12] as const

/**
 * Smallest hour stride whose labels fit in `widthPx` when `visibleHours` hours
 * share it. Wide charts keep a label per hour; narrow ones label every 3rd hour
 * (then 6th, 12th if even that overlaps).
 */
export function hourLabelStep(widthPx: number, visibleHours: number): number {
    if (visibleHours <= 0 || widthPx <= 0) return 1
    const pxPerHour = widthPx / visibleHours
    for (const step of HOUR_LABEL_STEPS) {
        if (pxPerHour * step >= MIN_PX_PER_HOUR_LABEL) return step
    }
    return HOUR_LABEL_STEPS[HOUR_LABEL_STEPS.length - 1]
}

/** Hour text ("HH") for an "HH:MM" axis label at a full hour, else null. */
export function hourOfLabel(label: unknown): string | null {
    if (typeof label !== 'string') return null
    const parts = label.split(':')
    if (parts.length < 2) return null
    const [hh, mm] = parts
    return mm === '00' ? hh : null
}
