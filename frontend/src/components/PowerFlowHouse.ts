/**
 * Residual House power for the Power Flow card.
 *
 * The gross whole-home meter includes EV charging and water heating. When those
 * loads are shown on their own nodes, subtract them so House shows base load only.
 * `evKw` / `waterKw` are backend totals that already exclude disabled devices.
 */
export function computeHouseKw(
    grossKw: number | null | undefined,
    evKw: number | null | undefined,
    waterKw: number | null | undefined,
    enabledNodeIds: ReadonlySet<string>,
): number {
    const ev = enabledNodeIds.has('ev') ? (evKw ?? 0) : 0
    const water = enabledNodeIds.has('water') ? (waterKw ?? 0) : 0
    return Math.max(0, (grossKw ?? 0) - ev - water)
}
