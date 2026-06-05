import type { LearningStatusResponse } from '../lib/api'

export type PvForecastSourceDisplay = {
    label: string
    status: string
    statusTone: 'baseline' | 'personalized' | 'disabled'
    progressText: string
    progressWeight: number
}

export type AuroraForecastDomain = 'load' | 'pv'

export function getAuroraForecastTogglePatch(domain: AuroraForecastDomain, enabled: boolean) {
    return {
        forecasting: {
            [domain === 'load' ? 'aurora_load_enabled' : 'aurora_pv_enabled']: enabled,
        },
    }
}

export function getPvForecastSourceDisplay(
    pvPersonalization: LearningStatusResponse['pv_personalization'] | undefined,
    auroraPvEnabled: boolean,
): PvForecastSourceDisplay {
    const pvPairedDays = pvPersonalization?.paired_days ?? 0
    const pvRampDays = pvPersonalization?.ramp_days ?? 14
    const pvWeight = pvPersonalization?.weight ?? 0

    if (!auroraPvEnabled) {
        return {
            label: 'Open-Meteo baseline',
            status: 'PV tuning disabled',
            statusTone: 'disabled',
            progressText: 'Aurora PV residual is off; using Open-Meteo baseline only.',
            progressWeight: 0,
        }
    }

    const pvDaysRemaining = Math.max(0, Math.ceil(pvRampDays - pvPairedDays))
    const pvPersonalized = pvWeight > 0

    return {
        label: pvPersonalized ? 'Open-Meteo + personal tuning (active)' : 'Open-Meteo baseline',
        status: pvPersonalized ? 'Personal tuning active' : 'Baseline only',
        statusTone: pvPersonalized ? 'personalized' : 'baseline',
        progressText:
            pvWeight >= 1
                ? `${Math.round(pvPairedDays)} paired days collected; full personalization.`
                : `${Math.round(pvPairedDays)}/${Math.round(pvRampDays)} paired days; personalizing in ~${pvDaysRemaining} days.`,
        progressWeight: Math.min(100, Math.max(0, pvWeight * 100)),
    }
}
