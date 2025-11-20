import { useMemo, useState } from 'react'
import type { PointerEvent } from 'react'

type TiltDialProps = {
    value: number | null
    onChange: (value: number) => void
}

export default function TiltDial({ value, onChange }: TiltDialProps) {
    const clampedValue = useMemo(() => {
        if (typeof value !== 'number' || Number.isNaN(value)) return 0
        let v = value
        if (v < 0) v = 0
        if (v > 90) v = 90
        return v
    }, [value])

    const [dragging, setDragging] = useState(false)

    const updateFromEvent = (event: PointerEvent<HTMLDivElement>) => {
        const rect = event.currentTarget.getBoundingClientRect()
        const y = event.clientY - rect.top
        const fraction = 1 - y / rect.height // 0 at bottom, 1 at top
        let deg = fraction * 90
        if (deg < 0) deg = 0
        if (deg > 90) deg = 90
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

    const pointerOffset = useMemo(() => {
        const frac = 1 - clampedValue / 90
        const bounded = Math.min(1, Math.max(0, frac))
        return `${bounded * 100}%`
    }, [clampedValue])

    return (
        <div className="flex items-center gap-3">
            <div
                className="relative h-16 w-8 cursor-pointer"
                onPointerDown={handlePointerDown}
                onPointerMove={handlePointerMove}
                onPointerUp={handlePointerUp}
                aria-label="Solar tilt dial"
                role="slider"
                aria-valuemin={0}
                aria-valuemax={90}
                aria-valuenow={Math.round(clampedValue)}
            >
                <div className="absolute inset-x-3 top-1 bottom-1 rounded-full bg-surface2 border border-line/60" />
                <div
                    className="absolute left-1 right-1 h-2 rounded-full bg-accent"
                    style={{ top: `calc(${pointerOffset} - 4px)` }}
                />
            </div>
            <div className="text-[11px] text-muted leading-tight">
                <div className="font-medium text-text">
                    {Math.round(clampedValue)}°
                </div>
                <div>0° = flat · 90° = vertical panel</div>
            </div>
        </div>
    )
}

