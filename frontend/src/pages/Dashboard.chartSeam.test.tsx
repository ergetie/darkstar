import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { buildLiveData } from '../components/ChartCard'
import type { ScheduleSlot } from '../lib/types'
import * as timezone from '../lib/timezone'
import { useChartSlots } from './Dashboard'

const STEP_MS = 15 * 60 * 1000
const STOCKHOLM_OFFSET_MS = 2 * 3600 * 1000 // CEST in July

// Browser in Auckland (NZST, UTC+12), plan timezone Europe/Stockholm (CEST, UTC+2).
// Auckland 2026-07-15 00:00 is 2026-07-14T12:00:00Z.
const AUCKLAND_TODAY_START = Date.UTC(2026, 6, 14, 12)
const NOW = new Date('2026-07-15T03:00:00Z') // 15:00 Auckland

/** Slot serialized the way the plan API does: ISO with the Stockholm offset. */
function planSlot(startMs: number, price: number): ScheduleSlot {
    const local = new Date(startMs + STOCKHOLM_OFFSET_MS).toISOString().slice(0, 19)
    return { start_time: `${local}+02:00`, import_price_sek_kwh: price } as ScheduleSlot
}

/** Slot serialized the way the history API does: a UTC instant. */
function historySlot(startMs: number, price: number): ScheduleSlot {
    return { start_time: new Date(startMs).toISOString(), import_price_sek_kwh: price } as ScheduleSlot
}

describe('48 h window across the history and forecast seam, browser Auckland and plan Stockholm', () => {
    beforeEach(() => {
        vi.useFakeTimers()
        vi.setSystemTime(NOW)
        vi.spyOn(timezone, 'displayTimeZone').mockReturnValue('Pacific/Auckland')
    })
    afterEach(() => {
        vi.useRealTimers()
        vi.restoreAllMocks()
    })

    it('shows every slot of the Auckland today and tomorrow exactly once', () => {
        // Plan covers Auckland yesterday .. the day after tomorrow, 15-minute slots.
        const firstMs = AUCKLAND_TODAY_START - 96 * STEP_MS
        const plan = Array.from({ length: 96 * 4 }, (_, i) => planSlot(firstMs + i * STEP_MS, firstMs + i * STEP_MS))
        // History replaces the whole browser day today, delivered as instants.
        const history = Array.from({ length: 96 }, (_, i) =>
            historySlot(AUCKLAND_TODAY_START + i * STEP_MS, AUCKLAND_TODAY_START + i * STEP_MS),
        )

        const { result } = renderHook(() => useChartSlots(plan, history))
        const slots = result.current ?? []
        const instants = slots.map((s) => new Date(s.start_time).getTime())

        const expected = Array.from({ length: 192 }, (_, i) => AUCKLAND_TODAY_START + i * STEP_MS)
        expect([...instants].sort((a, b) => a - b)).toEqual(expected)
        expect(new Set(instants).size).toBe(instants.length)

        const data = buildLiveData(slots, 'today')
        expect(data).not.toBeNull()
        expect(data!.labels).toHaveLength(192)
        expect(data!.labels![0]).toBe('00:00')
        expect(data!.labels![96]).toBe('00:00')
        // Each bucket carries its own slot's price (the slot start in ms): none dropped, none duplicated.
        const priceDataset = data!.datasets.find((d) => (d as { label?: string }).label?.startsWith('Import Price'))
        expect(priceDataset?.data).toEqual(expected)
        expect(data!.slotStarts).toEqual(expected.map((ms) => new Date(ms).toISOString()))
    })

    it('does not merge the Stockholm day into the Auckland day when history is missing', () => {
        const firstMs = AUCKLAND_TODAY_START - 96 * STEP_MS
        const plan = Array.from({ length: 96 * 4 }, (_, i) => planSlot(firstMs + i * STEP_MS, firstMs + i * STEP_MS))
        const { result } = renderHook(() => useChartSlots(plan, null))
        const instants = (result.current ?? []).map((s) => new Date(s.start_time).getTime())
        expect(instants[0]).toBe(AUCKLAND_TODAY_START)
        expect(instants).toHaveLength(192)
        expect(new Set(instants).size).toBe(192)
    })
})
