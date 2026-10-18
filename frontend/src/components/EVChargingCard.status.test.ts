import { describe, expect, it } from 'vitest'
import { computeProgressPercent, deriveChargerStatus, describeProgress } from './EVChargingCard'
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
        planned_by_day: [],
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
    it('uses soc / target for chargers with SoC, ignoring delivered kWh', () => {
        const charger = baseCharger({ soc_percent: 50, target_soc_percent: 80, delivered_kwh: 22 })
        expect(computeProgressPercent(charger)).toBe(63)
    })

    it('is 100 once SoC reaches the target', () => {
        const charger = baseCharger({ soc_percent: 82, target_soc_percent: 80 })
        expect(computeProgressPercent(charger)).toBe(100)
    })

    it('is 100 for a complete charger without a SoC reading', () => {
        const charger = baseCharger({ soc_percent: null, status: 'complete' })
        expect(computeProgressPercent(charger)).toBe(100)
    })

    it('uses delivered / (delivered + remaining) without a SoC sensor', () => {
        const charger = baseCharger({ soc_percent: null, required_kwh: 7.5, delivered_kwh: 2.5 })
        expect(computeProgressPercent(charger)).toBe(25)
    })

    it('is hidden when neither SoC nor kWh data is available', () => {
        expect(computeProgressPercent(baseCharger({ soc_percent: null, delivered_kwh: null }))).toBeNull()
        expect(computeProgressPercent(baseCharger({ soc_percent: null, required_kwh: null }))).toBeNull()
        expect(computeProgressPercent(baseCharger({ soc_percent: null, status: 'soc_unavailable' }))).toBeNull()
    })
})

describe('describeProgress', () => {
    it('shows SoC text with a SoC and remaining kWh without', () => {
        expect(describeProgress(baseCharger({ soc_percent: 62, target_soc_percent: 80 }))).toBe('62% to 80%')
        expect(describeProgress(baseCharger({ soc_percent: null, required_kwh: 7.5 }))).toBe('7.5 kWh remaining')
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
