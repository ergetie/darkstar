export interface FusePoint {
    overload_percent: number | null
    time_s: number | null
}
export const defaultFusePoints: FusePoint[] = [
    { overload_percent: 130, time_s: 1200 },
    { overload_percent: 300, time_s: 4 },
]

export function fuseCurveError(raw: string): string | undefined {
    let points: unknown
    try {
        points = JSON.parse(raw || JSON.stringify(defaultFusePoints))
    } catch {
        return 'Enter two valid fuse curve points.'
    }
    if (!Array.isArray(points) || points.length !== 2) return 'Enter exactly two fuse curve points.'
    for (const point of points) {
        if (
            typeof point !== 'object' ||
            point === null ||
            typeof point.overload_percent !== 'number' ||
            !Number.isFinite(point.overload_percent) ||
            point.overload_percent < 101 ||
            point.overload_percent > 1000 ||
            typeof point.time_s !== 'number' ||
            !Number.isFinite(point.time_s) ||
            point.time_s < 0.5 ||
            point.time_s > 86400
        )
            return 'Overload must be 101–1000% and trip time 0.5–86400 s.'
    }
    const [first, second] = [...points].sort((a, b) => a.overload_percent - b.overload_percent)
    if (first.overload_percent === second.overload_percent || first.time_s <= second.time_s)
        return 'The higher overload must have a strictly shorter trip time.'
}
