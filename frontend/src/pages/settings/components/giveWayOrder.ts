export interface GiveWayEntry {
    kind: 'charger' | 'shed'
    id: string
}

/**
 * Mirror of the backend's give_way_order self-healing, for display: drop
 * dangling entries, insert missing chargers after the last charger entry
 * (or at the top), append missing shed loads at the end.
 */
export function healOrderForDisplay(entries: GiveWayEntry[], chargerIds: string[], shedIds: string[]): GiveWayEntry[] {
    const healed = entries.filter(
        (e) => (e.kind === 'charger' && chargerIds.includes(e.id)) || (e.kind === 'shed' && shedIds.includes(e.id)),
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
    return healed
}
