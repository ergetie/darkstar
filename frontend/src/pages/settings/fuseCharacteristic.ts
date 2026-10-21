import { defaultFusePoints, fuseCurveError, type FusePoint } from './fuseCurve'

export type CurvePoint = readonly [multiple: number, seconds: number]
// Keep these graph-derived anchors and interpolation aligned with executor/fuse_model.py.
export const typCPoints: readonly CurvePoint[] = [
    [1.13, 3600],
    [1.2, 3600],
    [1.3, 1200],
    [1.5, 300],
    [2, 30],
    [3, 4],
    [5, 0.1],
]
export const diazedPoints: readonly CurvePoint[] = [
    [1.25, 14400],
    [1.6, 3600],
    [1.8, 900],
    [2.5, 100],
    [4, 10],
]

export function fuseTripTime(multiple: number, points: readonly CurvePoint[], instantaneous: boolean): number {
    if (multiple < points[0][0]) return Infinity
    if (instantaneous && multiple >= points[points.length - 1][0]) return points[points.length - 1][1]
    let left = points[points.length - 2]
    let right = points[points.length - 1]
    for (let i = 1; i < points.length; i++) {
        if (multiple <= points[i][0]) {
            left = points[i - 1]
            right = points[i]
            break
        }
    }
    return left[1] * (multiple / left[0]) ** (Math.log(right[1] / left[1]) / Math.log(right[0] / left[0]))
}

export function fuseCharacteristic(preset: string, safetyRaw: string, customRaw: string) {
    const safety = safetyRaw.trim() === '' ? (preset === 'diazed_gg' ? 65 : 80) : Number(safetyRaw)
    if (!Number.isFinite(safety) || safety < 50 || safety > 100)
        return { error: 'Enter a safety percentage from 50 to 100 to preview the curve.' } as const
    if (preset === 'custom') {
        const error = fuseCurveError(customRaw)
        if (error) return { error } as const
    }
    const points: readonly CurvePoint[] =
        preset === 'custom'
            ? (JSON.parse(customRaw || JSON.stringify(defaultFusePoints)) as FusePoint[])
                  .map((point): CurvePoint => [point.overload_percent! / 100, point.time_s!])
                  .sort((a, b) => a[0] - b[0])
            : preset === 'diazed_gg'
              ? diazedPoints
              : typCPoints
    // End custom previews at the second entered point; preset previews include extension to 6x.
    const maxMultiple = preset === 'custom' ? points[points.length - 1][0] : 6
    const multiples = [
        ...new Set([
            ...points.map(([multiple]) => multiple),
            ...Array.from({ length: 81 }, (_, index) => points[0][0] * (maxMultiple / points[0][0]) ** (index / 80)),
        ]),
    ].sort((a, b) => a - b)
    return {
        points,
        safety,
        samples: multiples.map((multiple) => ({
            multiple,
            trip: fuseTripTime(multiple, points, preset === 'typ_c' || !preset),
            response: (fuseTripTime(multiple, points, preset === 'typ_c' || !preset) * safety) / 100,
        })),
    }
}
