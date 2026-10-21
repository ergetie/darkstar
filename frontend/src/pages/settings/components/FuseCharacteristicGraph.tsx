import { useId } from 'react'
import { fuseCharacteristic } from '../fuseCharacteristic'

export function FuseCharacteristicGraph({ form }: { form: Record<string, string> }) {
    const id = useId()
    const preset = form['load_balancing.fuse_preset'] || 'typ_c'
    const curve = fuseCharacteristic(
        preset,
        form['load_balancing.fuse_safety_percent'] || '',
        form['load_balancing.fuse_custom_points'] || '',
    )
    const title = `${preset === 'diazed_gg' ? 'Diazed gG' : preset === 'custom' ? 'Custom' : 'Typ C'} fuse characteristics`
    if ('error' in curve)
        return <p className="px-6 pb-6 text-sm text-muted">Curve preview unavailable: {curve.error}</p>
    const { samples, points, safety } = curve
    const minY = 10 ** Math.floor(Math.log10(Math.min(...samples.map((p) => p.response))))
    const maxY = 10 ** Math.ceil(Math.log10(Math.max(...samples.map((p) => p.trip))))
    const maxX = samples[samples.length - 1].multiple
    const x = (multiple: number) => 58 + (Math.log(multiple) / Math.log(maxX)) * 366
    const y = (seconds: number) =>
        204 - ((Math.log(seconds) - Math.log(minY)) / (Math.log(maxY) - Math.log(minY))) * 184
    const path = (key: 'trip' | 'response') =>
        samples.map((p, i) => `${i ? 'L' : 'M'}${x(p.multiple)},${y(p[key])}`).join(' ')
    const yTicks = Array.from({ length: Math.round(Math.log10(maxY / minY)) + 1 }, (_, i) => minY * 10 ** i)
    const xTicks = [1, 1.5, 2, 3, 4, 6, 10].filter((tick) => tick <= maxX)
    return (
        <figure
            className="mx-ds-6 grid min-w-0 gap-ds-3 border-t border-line py-ds-5 md:grid-cols-2 md:gap-x-ds-6"
            aria-labelledby={`${id}-title`}
        >
            <figcaption id={`${id}-title`} className="text-lg font-semibold text-text md:col-span-2">
                {title}
            </figcaption>
            <div className="min-w-0">
                <div className="w-full max-w-[600px]">
                    <svg
                        viewBox="0 0 440 260"
                        className="block w-full"
                        role="img"
                        aria-labelledby={`${id}-title ${id}-description`}
                    >
                        <desc id={`${id}-description`}>
                            Logarithmic axes: current as a multiple of rated fuse current, and time in seconds.
                            Estimated fuse trip curve and Darkstar cold-start threshold at {safety}% of trip time. No
                            timed heating below {points[0][0]} times rated current.
                        </desc>
                        {yTicks.map((tick) => (
                            <g key={tick}>
                                <line x1="58" x2="424" y1={y(tick)} y2={y(tick)} className="stroke-line" />
                                <text x="50" y={y(tick) + 4} textAnchor="end" className="fill-muted text-lg">
                                    {tick.toLocaleString('en-GB', { maximumFractionDigits: 5 })}
                                </text>
                            </g>
                        ))}
                        {xTicks.map((tick) => (
                            <g key={tick}>
                                <line x1={x(tick)} x2={x(tick)} y1="20" y2="204" className="stroke-line" />
                                <text x={x(tick)} y="224" textAnchor="middle" className="fill-muted text-lg">
                                    {tick}×
                                </text>
                            </g>
                        ))}
                        <path d={path('trip')} fill="none" className="stroke-muted" strokeWidth="2" />
                        <path
                            d={path('response')}
                            fill="none"
                            className="stroke-accent"
                            strokeWidth="2"
                            strokeDasharray="7 4"
                        />
                        <text x="241" y="250" textAnchor="middle" className="fill-muted text-lg">
                            Current / fuse rating (log)
                        </text>
                        <text
                            transform="translate(13 112) rotate(-90)"
                            textAnchor="middle"
                            className="fill-muted text-lg"
                        >
                            Seconds (log)
                        </text>
                    </svg>
                </div>
            </div>
            <div className="min-w-0 space-y-ds-4 md:pt-ds-1">
                <h4 className="text-lg font-semibold text-text">How to read this</h4>
                <div className="space-y-ds-3 text-base">
                    <div className="flex items-start gap-ds-2">
                        <span aria-hidden="true" className="mt-ds-2 w-6 shrink-0 border-t-2 border-muted" />
                        <p>
                            <span className="font-medium text-text">Estimated fuse trip time</span>
                            <br />
                            <span className="text-muted">How long the fuse tolerates a steady overload.</span>
                        </p>
                    </div>
                    <div className="flex items-start gap-ds-2">
                        <span
                            aria-hidden="true"
                            className="mt-ds-2 w-6 shrink-0 border-t-2 border-dashed border-accent"
                        />
                        <p>
                            <span className="font-medium text-accent">Darkstar threshold · {safety}%</span>
                            <br />
                            <span className="text-muted">
                                When Darkstar requests relief, starting with a cold fuse.
                            </span>
                        </p>
                    </div>
                </div>
                <p className="text-base leading-relaxed text-muted">
                    Repeated overloads retain heat and can cause earlier intervention. Higher current means less time
                    before loads give way.
                </p>
                <details className="border-t border-line pt-ds-2 text-base text-muted">
                    <summary className="cursor-pointer py-ds-2 text-text rounded-ds-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
                        Technical details
                    </summary>
                    <div className="space-y-ds-3 pt-ds-2 leading-relaxed">
                        <p>
                            Both axes use logarithmic scales. The dashed line is {safety}% of the estimated trip time at
                            constant current from cold. If this time is shorter than one executor tick, relief is
                            requested immediately on the next reading. Actual response depends on sensor updates,
                            executor timing and controlled equipment.
                        </p>
                        <p>
                            {preset === 'custom'
                                ? 'Preview shows the interval between your two points with log-log interpolation. The executor extends the same line above the higher point.'
                                : 'Preset points are read from manufacturer graphs with approximately ±30% accuracy; they are estimates, not certified trip curves.'}{' '}
                            No timed heating below {points[0][0]}× rated current; existing heat holds between 1× and
                            that point.
                        </p>
                        {preset !== 'custom' && (
                            <p>
                                {preset === 'diazed_gg'
                                    ? 'Assumptions: 1.25× is treated as 4 hours; above 4×, extend the last log-log segment.'
                                    : 'Assumptions: 1.13× is treated as 1 hour; 5× and above as 0.1 seconds, with log-log interpolation from 3×.'}{' '}
                                This approximation does not guarantee fuse protection.
                            </p>
                        )}
                    </div>
                </details>
            </div>
        </figure>
    )
}
