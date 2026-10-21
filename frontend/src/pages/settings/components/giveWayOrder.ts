export interface GiveWayEntry {
    kind: 'charger' | 'shed' | 'battery'
    id: string
}

/** Fixed id of the single battery give-way entry (house battery grid charging). */
export const BATTERY_GIVE_WAY_ID = 'battery'

/**
 * Whether the battery give-way entry is controllable, mirroring the backend:
 * the system has a battery (every shipped inverter profile, including the
 * generic fallback, defines a `charge` mode).
 */
export function batteryGiveWayAvailable(config?: Record<string, unknown>): boolean {
    const system = config?.system as { has_battery?: boolean } | undefined
    return system?.has_battery !== false
}

/** Filter stale/duplicate entries without adding devices the user has not selected. */
export function healOrderForDisplay(
    entries: GiveWayEntry[],
    chargerIds: string[],
    shedIds: string[],
    batteryAvailable = false,
): GiveWayEntry[] {
    const seen = new Set<string>()
    return entries.flatMap((entry): GiveWayEntry[] => {
        const normalized: GiveWayEntry = entry.kind === 'battery' ? { kind: 'battery', id: BATTERY_GIVE_WAY_ID } : entry
        const valid =
            normalized.kind === 'battery'
                ? batteryAvailable
                : normalized.kind === 'charger'
                  ? chargerIds.includes(normalized.id)
                  : normalized.kind === 'shed' && shedIds.includes(normalized.id)
        const key = `${normalized.kind}:${normalized.id}`
        if (!valid || seen.has(key)) return []
        seen.add(key)
        return [normalized]
    })
}
