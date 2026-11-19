import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const sensorUnits = vi.hoisted(() => vi.fn())
vi.mock('./api', () => ({ Api: { setup: { sensorUnits } } }))

import { UNIT_NEEDED_DEBOUNCE_MS, useUnitNeeded } from './useUnitNeeded'

const needed = (entityId: string, override: 'W' | 'kW' | null = null) => ({
    entity_id: entityId,
    settings_path: 'x.y',
    live_value: 1,
    override,
})

async function settle(ms = UNIT_NEEDED_DEBOUNCE_MS) {
    await act(async () => {
        await vi.advanceTimersByTimeAsync(ms)
    })
}

describe('useUnitNeeded', () => {
    beforeEach(() => {
        vi.useFakeTimers()
        sensorUnits.mockReset()
        sensorUnits.mockResolvedValue({ unit_needed: [] })
    })
    afterEach(() => {
        vi.useRealTimers()
    })

    it('posts the draft config once after the 300 ms debounce', async () => {
        const { rerender } = renderHook(({ config }) => useUnitNeeded(config), {
            initialProps: { config: { a: 1 } as Record<string, unknown> | null },
        })
        await settle(UNIT_NEEDED_DEBOUNCE_MS - 1)
        expect(sensorUnits).not.toHaveBeenCalled()

        rerender({ config: { a: 2 } })
        await settle(UNIT_NEEDED_DEBOUNCE_MS - 1)
        expect(sensorUnits).not.toHaveBeenCalled()

        await settle(1)
        expect(sensorUnits).toHaveBeenCalledTimes(1)
        expect(sensorUnits).toHaveBeenCalledWith({ a: 2 })
    })

    it('does not post without a draft config', async () => {
        renderHook(() => useUnitNeeded(null))
        await settle()
        expect(sensorUnits).not.toHaveBeenCalled()
    })

    it('does not post again when only the object identity changes', async () => {
        const { rerender } = renderHook(({ config }) => useUnitNeeded(config), {
            initialProps: { config: { a: 1 } as Record<string, unknown> },
        })
        await settle()
        rerender({ config: { a: 1 } })
        await settle()
        expect(sensorUnits).toHaveBeenCalledTimes(1)
    })

    it('lists the backend entities and refetches when the selection changes', async () => {
        sensorUnits.mockImplementation(async (config: { pick: string }) => ({
            unit_needed: config.pick === 'sensor.unitless' ? [needed('sensor.unitless')] : [],
        }))
        const { result, rerender } = renderHook(({ config }) => useUnitNeeded(config), {
            initialProps: { config: { pick: 'sensor.unitless' } as Record<string, unknown> },
        })
        expect(result.current.isChoiceVisible('sensor.unitless')).toBe(false)

        await settle()
        expect(result.current.isChoiceVisible('sensor.unitless')).toBe(true)
        expect(result.current.isChoiceVisible('sensor.watts')).toBe(false)

        rerender({ config: { pick: 'sensor.watts' } })
        await settle()
        expect(sensorUnits).toHaveBeenCalledTimes(2)
        expect(result.current.isChoiceVisible('sensor.unitless')).toBe(false)
    })

    it('keeps the selector for a listed entity once the user chose its unit', async () => {
        sensorUnits.mockImplementation(async (config: { sensor_unit_overrides: Record<string, 'W' | 'kW'> }) => ({
            unit_needed: [needed('sensor.unitless', config.sensor_unit_overrides['sensor.unitless'] ?? null)],
        }))
        const { result, rerender } = renderHook(({ config }) => useUnitNeeded(config), {
            initialProps: { config: { sensor_unit_overrides: {} } as Record<string, unknown> },
        })
        await settle()
        expect(result.current.isChoiceVisible('sensor.unitless')).toBe(true)
        expect(result.current.unitNeeded[0].override).toBeNull()

        rerender({ config: { sensor_unit_overrides: { 'sensor.unitless': 'W' } } })
        await settle()

        expect(sensorUnits).toHaveBeenCalledTimes(2)
        expect(result.current.isChoiceVisible('sensor.unitless')).toBe(true)
        expect(result.current.unitNeeded[0].override).toBe('W')
    })

    it('never shows the selector for an entity the backend did not list, even with an override', async () => {
        const { result } = renderHook(() => useUnitNeeded({ sensor_unit_overrides: { 'sensor.watts': 'kW' } }))
        await settle()
        expect(result.current.isChoiceVisible('sensor.watts')).toBe(false)
    })

    it('keeps the previous answer when the request fails', async () => {
        const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
        sensorUnits.mockResolvedValueOnce({ unit_needed: [needed('sensor.unitless')] })
        sensorUnits.mockRejectedValueOnce(new Error('offline'))
        const { result, rerender } = renderHook(({ config }) => useUnitNeeded(config), {
            initialProps: { config: { n: 1 } as Record<string, unknown> },
        })
        await settle()
        rerender({ config: { n: 2 } })
        await settle()

        expect(result.current.isChoiceVisible('sensor.unitless')).toBe(true)
        warn.mockRestore()
    })

    it('ignores a response that arrives after the draft changed', async () => {
        let resolveFirst!: (value: unknown) => void
        sensorUnits.mockImplementationOnce(() => new Promise((resolve) => (resolveFirst = resolve)))
        const { result, rerender } = renderHook(({ config }) => useUnitNeeded(config), {
            initialProps: { config: { n: 1 } as Record<string, unknown> },
        })
        await settle()
        rerender({ config: { n: 2 } })
        await act(async () => {
            resolveFirst({ unit_needed: [needed('sensor.stale')] })
        })
        await settle()

        expect(result.current.isChoiceVisible('sensor.stale')).toBe(false)
    })
})
