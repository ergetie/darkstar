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
        const cx = rect.left + rect.width / 2
        const cy = rect.top + rect.height / 2
        const dx = event.clientX - cx
        const dy = event.clientY - cy

        const radians = Math.atan2(dx, -dy)
        let deg = (radians * 180) / Math.PI
        if (deg < 0) deg += 360

        // Constrain to the top-left quarter (270°–360°) which we use for 90°–0° tilt.
        if (deg < 270 || deg > 360) {
            // Map clicks outside the arc to the nearest endpoint.
            if (deg >= 0 && deg <= 135) {
                deg = 360
            } else {
                deg = 270
            }
        }

        let tilt = 360 - deg
        if (tilt < 0) tilt = 0
        if (tilt > 90) tilt = 90

        // Snap to 5° steps on the dial
        const snapped = Math.round(tilt / 5) * 5
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

    const pointerAngle = useMemo(() => {
        // 0° tilt = 360° (north), 90° tilt = 270° (west)
        return 360 - clampedValue
    }, [clampedValue])

    const pointerTransform = `rotate(${pointerAngle} 24 24)`

    return (
        <div className="flex items-center gap-3">
            <div
                className="relative h-16 w-16 cursor-pointer"
                onPointerDown={handlePointerDown}
                onPointerMove={handlePointerMove}
                onPointerUp={handlePointerUp}
                aria-label="Solar tilt dial"
                role="slider"
                aria-valuemin={0}
                aria-valuemax={90}
                aria-valuenow={Math.round(clampedValue)}
            >
                <svg viewBox="0 0 48 48" className="h-full w-full">
                    {/* Base circle */}
                    <circle
                        cx="24"
                        cy="24"
                        r="21"
                        className="fill-surface2 stroke-line/40"
                        strokeWidth="2"
                    />
                    {/* Highlighted quarter arc for 90°–0° tilt */}
                    <path
                        d="M3 24 A21 21 0 0 1 24 3"
                        className="fill-none stroke-accent/70"
                        strokeWidth="2.2"
                    />
                    {/* Tick marks every 15° of tilt (0–90) */}
                    <g>
                        {Array.from({ length: 7 }).map((_, i) => {
                            const tilt = i * 15
                            const angle = 360 - tilt
                            const outerR = 21
                            const innerR = tilt % 30 === 0 ? 18 : 19
                            const rad = ((angle - 90) * Math.PI) / 180
                            const x1 = 24 + outerR * Math.cos(rad)
                            const y1 = 24 + outerR * Math.sin(rad)
                            const x2 = 24 + innerR * Math.cos(rad)
                            const y2 = 24 + innerR * Math.sin(rad)
                            const cls =
                                tilt === 0 || tilt === 90 ? 'stroke-line/80' : 'stroke-line/60'
                            const width = tilt === 0 || tilt === 90 ? 1.6 : 1.2
                            return (
                                <line
                                    key={tilt}
                                    x1={x1}
                                    y1={y1}
                                    x2={x2}
                                    y2={y2}
                                    className={cls}
                                    strokeWidth={width}
                                />
                            )
                        })}
                    </g>
                    {/* Labels for 0° and 90° */}
                    <text x="24" y="9" textAnchor="middle" className="fill-muted text-[8px]">
                        0°
                    </text>
                    <text x="5" y="25" textAnchor="middle" className="fill-muted text-[8px]">
                        90°
                    </text>
                    {/* Pointer along the quarter arc */}
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
                <div>Drag along the arc: 0° = flat · 90° = vertical panel</div>
            </div>
        </div>
    )
}

