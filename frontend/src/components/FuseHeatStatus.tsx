import { useFuseStale } from './useFuseStatus'
import type { LoadBalancerStatusResponse } from '../lib/api'

const HEAT_LABELS: Record<string, string> = {
    heating: '↑ Heating up',
    cooling: '↓ Cooling down',
    holding: '→ Heat holding',
    cold: 'Cold',
    stale: 'Stale · frozen',
    unavailable: 'Unavailable',
}

export default function FuseHeatStatus({
    status,
    stale = false,
    showReason = false,
}: {
    status: LoadBalancerStatusResponse
    stale?: boolean
    showReason?: boolean
}) {
    const allStale = useFuseStale(status, stale, false)
    const safety = status.fuse_safety_percent
    const hasHeat = status.enabled && status.phase_heat_percent != null && safety != null
    const fuseA = status.main_fuse_a ?? 0
    const margin = status.target_margin_percent ?? 85
    return (
        <section aria-label="Phase current and estimated fuse heat" className="space-y-ds-3">
            <div className="grid grid-cols-1 gap-ds-3">
                {[1, 2, 3].map((phase) => {
                    const rawHeat = status.phase_heat_percent?.[phase]
                    const heat = rawHeat != null && Number.isFinite(rawHeat) ? Math.max(0, rawHeat) : null
                    const state = allStale ? 'stale' : (status.phase_heat_state?.[phase] ?? 'unavailable')
                    const frozen = state === 'stale' || state === 'unavailable'
                    const color = frozen
                        ? 'bg-muted'
                        : heat != null && heat >= (safety ?? 100)
                          ? 'bg-warn'
                          : 'bg-accent'
                    return (
                        <div key={phase} className="min-w-0 space-y-ds-1">
                            <div className="flex items-baseline justify-between gap-ds-2 text-sm text-muted">
                                <span className="font-semibold">L{phase}</span>
                                <span
                                    className="font-mono"
                                    title={`Raw current: ${(status.phase_current_a[phase] ?? 0).toFixed(3)}A`}
                                >
                                    {(status.phase_current_a[phase] ?? 0).toFixed(1)} / {fuseA} A
                                </span>
                                <span className="sr-only" data-testid={`lb-raw-l${phase}`}>
                                    {(status.phase_current_a[phase] ?? 0).toFixed(3)}A
                                </span>
                            </div>
                            <div
                                className="relative h-2 overflow-hidden rounded-full bg-surface2"
                                aria-label={`L${phase} current`}
                            >
                                <div
                                    className={`h-full rounded-full ${allStale || state === 'stale' ? 'bg-muted' : (status.phase_current_a[phase] ?? 0) > fuseA ? 'bg-bad' : (status.phase_current_a[phase] ?? 0) >= (fuseA * margin) / 100 ? 'bg-accent' : 'bg-good'}`}
                                    style={{
                                        width: `${fuseA > 0 ? Math.max(0, Math.min(100, ((status.phase_current_a[phase] ?? 0) / fuseA) * 100)) : 0}%`,
                                    }}
                                />
                                <span
                                    className="absolute inset-y-0 w-px bg-line"
                                    style={{ left: `${margin}%` }}
                                    title={`Ramp-up target: ${margin}% of fuse rating`}
                                />
                            </div>
                            {hasHeat && (
                                <div className="flex items-center gap-ds-2 pt-ds-1 text-xs text-muted">
                                    <span>Heat</span>
                                    <div
                                        role="meter"
                                        aria-label={`L${phase} estimated fuse heat`}
                                        aria-valuemin={0}
                                        aria-valuemax={100}
                                        aria-valuenow={heat === null ? undefined : Math.min(100, heat)}
                                        aria-valuetext={`${heat === null ? 'Unavailable' : `${Math.round(heat)}%`}; ${HEAT_LABELS[state] ?? 'Unavailable'}; intervention threshold ${safety}%`}
                                        className="relative h-1 min-w-[32px] flex-1 rounded-full bg-surface2"
                                    >
                                        <div
                                            className={`h-full rounded-full ${color}`}
                                            style={{ width: `${Math.min(100, heat ?? 0)}%` }}
                                        />
                                        <span
                                            aria-hidden="true"
                                            className="absolute top-0 h-full w-px -translate-x-1/2 bg-text"
                                            style={{ left: `${safety}%` }}
                                        />
                                    </div>
                                    <span
                                        className={`shrink-0 ${frozen ? 'text-muted' : state === 'cooling' ? 'text-good' : 'text-muted'}`}
                                    >
                                        {heat === null ? '—' : `${Math.round(heat)}%`} ·{' '}
                                        {HEAT_LABELS[state] ?? 'Unavailable'}
                                    </span>
                                </div>
                            )}
                        </div>
                    )
                })}
            </div>
            <details className="text-sm text-muted">
                <summary className="cursor-pointer rounded-ds-sm py-ds-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
                    About fuse protection
                </summary>
                <div className="space-y-ds-2 pt-ds-1 leading-relaxed">
                    <p>
                        The upper bar shows current through the protected fuse. Its sensors and selected loads must
                        refer to that same circuit. The thinner bar estimates accumulated fuse heat, not measured
                        temperature.
                    </p>
                    {hasHeat && (
                        <p>
                            Intervene at {safety}% heat; increases and restores require heat below 50%, plus enough
                            current headroom and the configured timing conditions.
                        </p>
                    )}
                    {(allStale || Object.values(status.phase_heat_state ?? {}).includes('stale')) && (
                        <p>Readings are stale. Heat estimates are frozen until fresh readings return.</p>
                    )}
                    {showReason && status.reason && (
                        <p>{status.reason.replace(/(?:^|;\s*)Fuse heat:.*$/, '').trim()}</p>
                    )}
                </div>
            </details>
        </section>
    )
}
