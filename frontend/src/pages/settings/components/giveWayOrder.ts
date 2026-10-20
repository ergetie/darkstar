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

/**
 * Mirror of the backend's give_way_order self-healing, for display: drop
 * dangling entries, insert missing chargers after the last charger entry
 * (or at the top), append missing shed loads at the end, and keep one
 * battery entry while a battery is available (appended last when missing).
 */
export function healOrderForDisplay(
    entries: GiveWayEntry[],
    chargerIds: string[],
    shedIds: string[],
    batteryAvailable = false,
): GiveWayEntry[] {
    let batterySeen = false
    const healed = entries
        .filter((e) => {
            if (e.kind !== 'battery') return true
            if (!batteryAvailable || batterySeen) return false
            batterySeen = true
            return true
        })
        .map((e): GiveWayEntry => (e.kind === 'battery' ? { kind: 'battery', id: BATTERY_GIVE_WAY_ID } : e))
        .filter(
            (e) =>
                e.kind === 'battery' ||
                (e.kind === 'charger' && chargerIds.includes(e.id)) ||
                (e.kind === 'shed' && shedIds.includes(e.id)),
        )
    const listedChargers = new Set(healed.filter((e) => e.kind === 'charger').map((e) => e.id))
    const missingChargers = chargerIds.filter((id) => !listedChargers.has(id))
    if (missingChargers.length > 0) {
        let lastChargerIdx = -1
        healed.forEach((e, i) => {
            if (e.kind === 'charger') lastChargerIdx = i
        })
        healed.splice(lastChargerIdx + 1, 0, ...missingChargers.map((id): GiveWayEntry => ({ kind: 'charger', id })))
    }
    const listedSheds = new Set(healed.filter((e) => e.kind === 'shed').map((e) => e.id))
    shedIds.forEach((id) => {
        if (!listedSheds.has(id)) healed.push({ kind: 'shed', id })
    })
    if (batteryAvailable && !healed.some((e) => e.kind === 'battery')) {
        healed.push({ kind: 'battery', id: BATTERY_GIVE_WAY_ID })
    }
    return healed
}
