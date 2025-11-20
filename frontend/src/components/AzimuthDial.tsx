import { useMemo, useState } from 'react'
import type { PointerEvent } from 'react'

type AzimuthDialProps = {
    value: number | null
    onChange: (value: number) => void
}

export default function AzimuthDial({ value, onChange }: AzimuthDialProps) {
    const clampedValue = useMemo(() => {
        if (typeof value !== 'number' || Number.isNaN(value)) return 0
        let v = value % 360
        if (v < 0) v += 360
        return v
    }, [value])

    const [dragging, setDragging] = useState(false)

    const updateFromEvent = (event: PointerEvent<HTMLDivElement>) => {
        const rect = event.currentTarget.getBoundingClientRect()
        const cx = rect.left + rect.width / 2
        const cy = rect.top + rect.height / 2
        const dx = event.clientX - cx
        const dy = event.clientY - cy

        // Screen coordinates: y increases downwards.
        // We want 0° = North (up), 90° = East (right), 180° = South, 270° = West.
        const radians = Math.atan2(dx, -dy)
        let deg = (radians * 180) / Math.PI
        if (deg < 0) deg += 360
        const snapped = Math.round(deg)
        onChange(snapped)
    }

    const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
        setDragging(true)
        try {
            event.currentTarget.setPointerCapture(event.pointerId)
        } catch {
            // ignore if not supported
        }
        updateFromEvent(event)
    }

    const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
        if (!dragging) return
        updateFromEvent(event)
    }

    const handlePointerUp = (event: PointerEvent<HTMLDivElement>) => {
        if (!dragging) return
        setDragging(false)
        try {
            event.currentTarget.releasePointerCapture(event.pointerId)
        } catch {
            // ignore if not supported
        }
    }

    const pointerTransform = `rotate(${clampedValue} 24 24)`

    return (
        <div className="flex items-center gap-3">
            <div
                className="relative h-16 w-16 cursor-pointer"
                onPointerDown={handlePointerDown}
                onPointerMove={handlePointerMove}
                onPointerUp={handlePointerUp}
                aria-label="Solar azimuth dial"
                role="slider"
                aria-valuemin={0}
                aria-valuemax={360}
                aria-valuenow={Math.round(clampedValue)}
            >
                <svg viewBox="0 0 48 48" className="h-full w-full">
                    <circle
                        cx="24"
                        cy="24"
                        r="21"
                        className="fill-surface2 stroke-line/60"
                        strokeWidth="2"
                    />
                    {/* Cardinal markers */}
                    <text x="24" y="9" textAnchor="middle" className="fill-muted text-[8px]">
                        N
                    </text>
                    <text x="24" y="45" textAnchor="middle" className="fill-muted text-[8px]">
                        S
                    </text>
                    <text x="43" y="25" textAnchor="middle" className="fill-muted text-[8px]">
                        E
                    </text>
                    <text x="5" y="25" textAnchor="middle" className="fill-muted text-[8px]">
                        W
                    </text>
                    {/* Pointer: base at center, pointing up (north) before rotation */}
                    <g transform={pointerTransform}>
                        <line
                            x1="24"
                            y1="24"
                            x2="24"
                            y2="6"
                            className="stroke-accent"
                            strokeWidth="2.2"
                            strokeLinecap="round"
                        />
                        <circle cx="24" cy="24" r="2.5" className="fill-accent" />
                    </g>
                </svg>
            </div>
            <div className="text-[11px] text-muted leading-tight">
                <div className="font-medium text-text">
                    {Math.round(clampedValue)}°
                </div>
                <div>
                    0° = North · 90° = East · 180° = South · 270° = West
                </div>
            </div>
        </div>
    )
}
