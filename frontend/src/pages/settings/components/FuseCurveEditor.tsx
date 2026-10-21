import React from 'react'

import { defaultFusePoints, type FusePoint } from '../fuseCurve'

export const FuseCurveEditor: React.FC<{ value: string; onChange: (value: string) => void; disabled?: boolean }> = ({
    value,
    onChange,
    disabled,
}) => {
    let parsed: unknown
    try {
        parsed = JSON.parse(value || 'null')
    } catch {
        parsed = null
    }
    const points: FusePoint[] =
        Array.isArray(parsed) && parsed.length === 2 && parsed.every((p) => typeof p === 'object' && p !== null)
            ? parsed
            : defaultFusePoints
    return (
        <div className="space-y-ds-3">
            {points.map((point, index) => (
                <div key={index} className="grid grid-cols-2 gap-ds-2">
                    {(['overload_percent', 'time_s'] as const).map((key) => (
                        <label key={key} className="text-sm text-muted">
                            {key === 'overload_percent' ? 'Overload (%)' : 'Trip time (s)'} — point {index + 1}
                            <input
                                className="input w-full"
                                type="number"
                                disabled={disabled}
                                aria-label={`Custom point ${index + 1} ${key === 'overload_percent' ? 'overload (%)' : 'trip time (s)'}`}
                                min={key === 'overload_percent' ? 101 : 0.5}
                                max={key === 'overload_percent' ? 1000 : 86400}
                                step={key === 'overload_percent' ? 1 : 0.5}
                                value={point[key] ?? ''}
                                onChange={(event) =>
                                    onChange(
                                        JSON.stringify(
                                            points.map((p, i) =>
                                                i === index
                                                    ? {
                                                          ...p,
                                                          [key]:
                                                              event.target.value === ''
                                                                  ? null
                                                                  : Number(event.target.value),
                                                      }
                                                    : p,
                                            ),
                                        ),
                                    )
                                }
                            />
                        </label>
                    ))}
                </div>
            ))}
        </div>
    )
}
