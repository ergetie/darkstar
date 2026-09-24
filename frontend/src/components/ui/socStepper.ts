export const SOC_STEP = 15

/** Clamp and round a SoC value into [min, max]. */
export function clampSoc(value: number, min: number, max: number): number {
    return Math.min(max, Math.max(min, Math.round(value)))
}

/** Parse typed input: an integer within [min, max], else null (rejected). */
export function parseSocInput(raw: string, min: number, max: number): number | null {
    const trimmed = raw.trim()
    if (!/^\d+$/.test(trimmed)) return null
    const value = Number(trimmed)
    return value >= min && value <= max ? value : null
}
