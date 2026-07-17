import { describe, expect, it } from 'vitest'
import { computeEnabledNodes } from './PowerFlowCard'
import type { PowerFlowData } from './PowerFlowRegistry'

const data: PowerFlowData = {
    solar: { kw: 0 },
    battery: { kw: 0, soc: 50 },
    grid: { kw: 0 },
    house: { kw: 0 },
    water: { kw: 0 },
}

describe('computeEnabledNodes', () => {
    it('with a null configMap (no systemConfig) allows exactly solar/battery/water, excluding EV', () => {
        // Pinned surprising-but-current behavior: a null systemConfig silently
        // excludes the EV node from the power-flow diagram. See change notes.
        const ids = computeEnabledNodes(null, data).map((n) => n.id)
        expect(new Set(ids)).toEqual(new Set(['solar', 'house', 'battery', 'grid', 'water']))
        expect(ids).not.toContain('ev')
    })

    it('drops the battery node when configMap explicitly sets has_battery: false', () => {
        const configMap = { 'system.has_battery': false }
        const ids = computeEnabledNodes(configMap, data).map((n) => n.id)
        expect(ids).not.toContain('battery')
    })

    it('includes the EV node when configMap sets has_ev_charger: true', () => {
        const configMap = { 'system.has_ev_charger': true }
        const ids = computeEnabledNodes(configMap, data).map((n) => n.id)
        expect(ids).toContain('ev')
    })
})
