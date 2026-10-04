import { describe, expect, it } from 'vitest'
import { MIN_PX_PER_HOUR_LABEL, hourLabelStep, hourOfLabel } from './chartTicks'

const labelledHours = (widthPx: number, hours: number) => {
    const step = hourLabelStep(widthPx, hours)
    return Array.from({ length: hours }, (_, i) => i % 24).filter((h) => h % step === 0)
}

describe('hourLabelStep', () => {
    it('labels every hour on a wide chart (48 h at ~1200 px)', () => {
        expect(hourLabelStep(1150, 48)).toBe(1)
    })

    it('labels every third hour on a narrow chart (48 h at ~350 px)', () => {
        // ~350 px card leaves roughly 270-310 px of x scale after padding and the price axis
        expect(hourLabelStep(270, 48)).toBe(3)
        expect(hourLabelStep(310, 48)).toBe(3)
        expect(labelledHours(270, 48)).toEqual([0, 3, 6, 9, 12, 15, 18, 21, 0, 3, 6, 9, 12, 15, 18, 21])
    })

    it('depends on width, not on a device flag: a narrow desktop window thins too', () => {
        expect(hourLabelStep(700, 48)).toBe(3)
        expect(hourLabelStep(960, 48)).toBe(1)
    })

    it('never places labels closer than the minimum spacing', () => {
        for (let width = 50; width <= 2000; width += 10) {
            for (const hours of [6, 12, 24, 48]) {
                const step = hourLabelStep(width, hours)
                if (step < 12) expect((width / hours) * step).toBeGreaterThanOrEqual(MIN_PX_PER_HOUR_LABEL)
            }
        }
    })

    it('labels every hour when zoomed in or before layout', () => {
        expect(hourLabelStep(310, 6)).toBe(1)
        expect(hourLabelStep(0, 48)).toBe(1)
        expect(hourLabelStep(310, 0)).toBe(1)
    })
})

describe('hourOfLabel', () => {
    it('returns the hour for full-hour labels only', () => {
        expect(hourOfLabel('03:00')).toBe('03')
        expect(hourOfLabel('03:15')).toBeNull()
        expect(hourOfLabel('bad')).toBeNull()
        expect(hourOfLabel(5)).toBeNull()
    })
})
