import { Plug, Unplug, Zap } from 'lucide-react'
import { describe, expect, it } from 'vitest'
import { deriveEvNodeView, type EvChargerStatus, type EvLiveReading } from './evNodeView'

const live = (overrides: Partial<EvLiveReading> = {}): EvLiveReading => ({
    id: 'ev1',
    name: 'Car',
    kw: 0,
    soc: 49,
    pluggedIn: true,
    ...overrides,
})

const status = (overrides: Partial<EvChargerStatus> = {}): EvChargerStatus => ({
    id: 'ev1',
    name: 'Car',
    target_soc_percent: null,
    manual_charge: null,
    ...overrides,
})

const manual = (target_soc: number) => ({ target_soc, current_a: null, started_at: '2026-09-24T10:00:00+02:00' })

describe('deriveEvNodeView — single charger', () => {
    it('charging with manual target shows lightning and SoC → target', () => {
        const view = deriveEvNodeView(
            [live({ kw: 7.2 })],
            [status({ manual_charge: manual(80), target_soc_percent: 60 })],
        )
        expect(view).toEqual({ state: 'charging', icon: Zap, text: '49% → 80%', muted: false })
    })

    it('charging falls back to the goal target', () => {
        const view = deriveEvNodeView([live({ kw: 7.2 })], [status({ target_soc_percent: 60 })])
        expect(view?.text).toBe('49% → 60%')
    })

    it('charging without any target shows only SoC', () => {
        expect(deriveEvNodeView([live({ kw: 7.2 })], [status()])?.text).toBe('49%')
        expect(deriveEvNodeView([live({ kw: 7.2 })])?.text).toBe('49%')
    })

    it('plugged and idle shows plug and SoC', () => {
        const view = deriveEvNodeView([live({ kw: 0.05 })], [status({ target_soc_percent: 80 })])
        expect(view).toEqual({ state: 'plugged', icon: Plug, text: '49%', muted: false })
    })

    it('unplugged shows unplug and muted "away"', () => {
        const view = deriveEvNodeView([live({ pluggedIn: false })])
        expect(view).toEqual({ state: 'unplugged', icon: Unplug, text: 'away', muted: true })
    })

    it('unknown SoC shows --%', () => {
        expect(deriveEvNodeView([live({ soc: null })])?.text).toBe('--%')
        expect(deriveEvNodeView([live({ soc: null, kw: 3 })], [status({ target_soc_percent: 80 })])?.text).toBe(
            '--% → 80%',
        )
    })

    it('joins by id, not by position', () => {
        const view = deriveEvNodeView(
            [live({ id: 'ev2', kw: 7 })],
            [status({ id: 'ev1', target_soc_percent: 90 }), status({ id: 'ev2', target_soc_percent: 70 })],
        )
        expect(view?.text).toBe('49% → 70%')
    })

    it('no chargers → no view', () => {
        expect(deriveEvNodeView([])).toBeNull()
        expect(deriveEvNodeView(undefined)).toBeNull()
    })
})

describe('deriveEvNodeView — multiple chargers', () => {
    it('one charging, one unplugged → lightning and "1 connected"', () => {
        const view = deriveEvNodeView([live({ kw: 7 }), live({ id: 'ev2', pluggedIn: false })])
        expect(view).toEqual({ state: 'charging', icon: Zap, text: '1 connected', muted: false })
    })

    it('none charging, one plugged → plug', () => {
        const view = deriveEvNodeView([live(), live({ id: 'ev2', pluggedIn: false })])
        expect(view?.icon).toBe(Plug)
        expect(view?.text).toBe('1 connected')
    })

    it('none plugged → unplug, muted', () => {
        const view = deriveEvNodeView([live({ pluggedIn: false }), live({ id: 'ev2', pluggedIn: false })])
        expect(view).toEqual({ state: 'unplugged', icon: Unplug, text: '0 connected', muted: true })
    })
})
