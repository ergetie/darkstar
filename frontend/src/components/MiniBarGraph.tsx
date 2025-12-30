import { useMemo } from 'react'

interface MiniBarGraphProps {
    /** Array of values (0-100 or will be normalized) */
    data: number[]
    /** Color class for bars (e.g., 'bg-accent', 'bg-good') */
    colorClass?: string
    /** Height in pixels */
    height?: number
    /** Number of bars to show */
    bars?: number
}

/**
 * Mini bar graph component for data visualization.
 * Replaces sparklines with a more TE-style graphic look.
 */
export default function MiniBarGraph({
    data,
    colorClass = 'bg-accent',
    height = 32,
    bars = 12
}: MiniBarGraphProps) {
    // Normalize and slice data to fit bars
    const normalizedData = useMemo(() => {
        if (!data || data.length === 0) return Array(bars).fill(0.2)

        const sliced = data.slice(-bars)
        const max = Math.max(...sliced, 1)
        const min = Math.min(...sliced, 0)
        const range = max - min || 1

        // Normalize to 0.1 - 1.0 range (minimum 10% height)
        return sliced.map(v => 0.1 + 0.9 * ((v - min) / range))
    }, [data, bars])

    return (
        <div className="mini-bars" style={{ height }}>
            {normalizedData.map((value, i) => (
                <div
                    key={i}
                    className={`mini-bar ${colorClass}`}
                    style={{ height: `${Math.round(value * 100)}%` }}
                />
            ))}
        </div>
    )
}
