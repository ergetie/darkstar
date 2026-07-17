import { describe, expect, it } from 'vitest'
import { computeProgressPercent, deriveChargerStatus } from './EVChargingCard'
import type { EVChargerState, LoadBalancerEvStatus } from '../lib/api'

function baseCharger(overrides: Partial<EVChargerState> = {}): EVChargerState {
    return {
        id: 'ev1',
        name: 'Tesla',
        plugged_in: true,
        soc_percent: 50,
        power_kw: 0,
        target_soc_percent: 80,
        ready_by: '07:00',
        repeat: 'daily',
        ready_by_date: null,
        deadline: null,
        required_kwh: 10,
        delivered_kwh: 2,
        remaining_kwh: 8,
        daily_quota_kwh: null,
        quota_schedule: null,
        keep_on_after_target: false,
        ha_ready_by_entity: null,
        ha_target_soc_entity: null,
        type: 'current',
        n_days: null,
        status: 'on_track',
        source: 'api',
        externally_controlled: false,
        last_updated: null,
        last_planned_at: null,
        ...overrides,
    }
}

function baseEvStatus(overrides: Partial<LoadBalancerEvStatus> = {}): LoadBalancerEvStatus {
    return {
        charger_id: 'ev1',
        charger_name: 'Tesla',
        setpoint_a: null,
        planned_target_a: null,
        state: 'idle',
        reason: '',
        ...overrides,
    }
}

describe('computeProgressPercent', () => {
    it('returns 0 without dividing by zero when required_kwh is 0', () => {
        const charger = baseCharger({ required_kwh: 0, delivered_kwh: 5 })
        expect(computeProgressPercent(charger)).toBe(0)
    })

    it('returns 0 when required_kwh is null', () => {
        const charger = baseCharger({ required_kwh: null, delivered_kwh: 5 })
        expect(computeProgressPercent(charger)).toBe(0)
    })

    it('caps progress at 100 when delivered exceeds required', () => {
        const charger = baseCharger({ required_kwh: 10, delivered_kwh: 15 })
        expect(computeProgressPercent(charger)).toBe(100)
    })

    it('computes a normal in-progress percentage', () => {
        const charger = baseCharger({ required_kwh: 10, delivered_kwh: 2.5 })
        expect(computeProgressPercent(charger)).toBe(25)
    })
})

describe('deriveChargerStatus', () => {
    it('lets balancer states (throttling/paused/stale_fallback) take priority over charger.status', () => {
        const charger = baseCharger({ status: 'on_track' })
        const throttling = deriveChargerStatus(charger, baseEvStatus({ state: 'throttling' }))
        expect(throttling.statusText).toBe('Throttling by Load Balancer')

        const paused = deriveChargerStatus(charger, baseEvStatus({ state: 'paused' }))
        expect(paused.statusText).toBe('Paused by Load Balancer')

        const staleFallback = deriveChargerStatus(charger, baseEvStatus({ state: 'stale_fallback' }))
        expect(staleFallback.statusText).toBe('Load Balancer Fail-Safe')
    })

    it('passes charger.status through when there is no balancer entry', () => {
        const charger = baseCharger({ status: 'on_track' })
        const result = deriveChargerStatus(charger, undefined)
        expect(result.statusText).toBe('On track')
    })

    it('passes charger.status through when the balancer entry is idle (no override)', () => {
        const charger = baseCharger({ status: 'behind' })
        const result = deriveChargerStatus(charger, baseEvStatus({ state: 'idle' }))
        expect(result.statusText).toBe('Behind')
    })
})
