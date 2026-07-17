import { describe, expect, it } from 'vitest'
import { chargerSetpointText, formatAge, phaseColor } from './LoadBalancerStatusCard'
import type { LoadBalancerEvStatus } from '../lib/api'

function makeEv(overrides: Partial<LoadBalancerEvStatus> = {}): LoadBalancerEvStatus {
    return {
        charger_id: 'c1',
        charger_name: 'Charger 1',
        setpoint_a: 16,
        planned_target_a: 16,
        state: 'idle',
        reason: '',
        ...overrides,
    }
}

describe('phaseColor', () => {
    it('returns good below the margin threshold', () => {
        // fuse 20A, margin 90% -> threshold 18A; 10A is well below
        expect(phaseColor(10, 20, 90)).toBe('bg-good')
    })

    it('returns accent when within the margin band (at or above threshold, at or below fuse)', () => {
        expect(phaseColor(18, 20, 90)).toBe('bg-accent')
        expect(phaseColor(20, 20, 90)).toBe('bg-accent')
    })

    it('returns bad when current exceeds the fuse rating', () => {
        expect(phaseColor(20.1, 20, 90)).toBe('bg-bad')
    })
})

describe('chargerSetpointText', () => {
    it('shows "Paused" when setpoint_a is null', () => {
        expect(chargerSetpointText(makeEv({ setpoint_a: null }))).toBe('Paused')
    })

    it('shows the setpoint alone when planned matches setpoint', () => {
        expect(chargerSetpointText(makeEv({ setpoint_a: 16, planned_target_a: 16 }))).toBe('16A')
    })

    it('shows "(planned XA)" when planned target differs from setpoint', () => {
        expect(chargerSetpointText(makeEv({ setpoint_a: 10, planned_target_a: 16 }))).toBe('10A (planned 16A)')
    })
})

describe('formatAge', () => {
    it('formats under 60s as seconds', () => {
        expect(formatAge(59)).toBe('59s ago')
    })

    it('flips to minutes exactly at 60s', () => {
        expect(formatAge(60)).toBe('1m ago')
    })

    it('formats just under an hour as minutes', () => {
        expect(formatAge(3599)).toBe('59m ago')
    })

    it('flips to hours exactly at 3600s', () => {
        expect(formatAge(3600)).toBe('1h ago')
    })
})
