import { describe, expect, it } from 'vitest'
import { batteryCapText, batteryRowVisible, chargerSetpointText, formatAge, phaseColor } from './LoadBalancerStatusCard'
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

    it('shows the measured draw when present', () => {
        expect(chargerSetpointText(makeEv({ setpoint_a: 16, planned_target_a: 16, measured_a: 10 }))).toBe(
            '16A, drawing 10.0A',
        )
    })

    it('omits the measured draw when null', () => {
        expect(chargerSetpointText(makeEv({ setpoint_a: 16, planned_target_a: 16, measured_a: null }))).toBe('16A')
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

describe('batteryCapText', () => {
    const base = { planned_w: 10000, cap_w: 10000, state: 'idle', reason: '', phases: [1, 2, 3] }
    it('shows the plan alone when uncapped', () => {
        expect(batteryCapText(base)).toBe('10.0 kW')
    })
    it('shows capped vs planned while throttling', () => {
        expect(batteryCapText({ ...base, cap_w: 7000, state: 'throttling' })).toBe('7.0 kW (planned 10.0 kW)')
    })
    it('shows paused with the plan', () => {
        expect(batteryCapText({ ...base, cap_w: 0, state: 'paused' })).toBe('Paused (planned 10.0 kW)')
    })
})

describe('batteryRowVisible', () => {
    it('hides a missing or inactive battery', () => {
        expect(batteryRowVisible(null)).toBe(false)
        expect(batteryRowVisible({ planned_w: 0, cap_w: 0, state: 'idle', reason: '', phases: [1, 2, 3] })).toBe(false)
    })
    it('shows planned grid charging', () => {
        expect(batteryRowVisible({ planned_w: 5000, cap_w: 5000, state: 'idle', reason: '', phases: [1, 2, 3] })).toBe(
            true,
        )
    })
})
