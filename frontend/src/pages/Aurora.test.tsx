import { describe, expect, it } from 'vitest'
import { getAuroraForecastTogglePatch, getPvForecastSourceDisplay } from './auroraDisplay'

describe('getPvForecastSourceDisplay', () => {
    it('shows baseline-only Open-Meteo mode before personalization starts', () => {
        const display = getPvForecastSourceDisplay(
            { source: 'openmeteo', paired_days: 0, ramp_days: 14, weight: 0, mode: 'baseline' },
            true,
        )

        expect(display.label).toBe('Open-Meteo baseline')
        expect(display.status).toBe('Baseline only')
        expect(display.progressText).toBe('0/14 paired days; personalizing in ~14 days.')
        expect(display.progressWeight).toBe(0)
    })

    it('shows active personal tuning and progress', () => {
        const display = getPvForecastSourceDisplay(
            { source: 'openmeteo', paired_days: 5, ramp_days: 10, weight: 0.5, mode: 'personalized' },
            true,
        )

        expect(display.label).toBe('Open-Meteo + personal tuning (active)')
        expect(display.status).toBe('Personal tuning active')
        expect(display.progressText).toBe('5/10 paired days; personalizing in ~5 days.')
        expect(display.progressWeight).toBe(50)
    })

    it('shows PV tuning disabled when Aurora PV forecasting is off', () => {
        const display = getPvForecastSourceDisplay(
            { source: 'openmeteo', paired_days: 10, ramp_days: 10, weight: 1, mode: 'personalized' },
            false,
        )

        expect(display.label).toBe('Open-Meteo baseline')
        expect(display.status).toBe('PV tuning disabled')
        expect(display.statusTone).toBe('disabled')
        expect(display.progressText).toBe('Aurora PV residual is off; using Open-Meteo baseline only.')
        expect(display.progressWeight).toBe(0)
    })
})

describe('getAuroraForecastTogglePatch', () => {
    it('builds the load forecasting toggle payload', () => {
        expect(getAuroraForecastTogglePatch('load', false)).toEqual({
            forecasting: { aurora_load_enabled: false },
        })
    })

    it('builds the PV forecasting toggle payload', () => {
        expect(getAuroraForecastTogglePatch('pv', true)).toEqual({
            forecasting: { aurora_pv_enabled: true },
        })
    })
})
