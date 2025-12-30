/**
 * PillButton Component
 * 
 * Uses CSS custom property for dynamic color support.
 * Default color is accent gold if not specified.
 */

import React from 'react'

interface PillButtonProps {
    label: string
    color?: string
    textColor?: string
    onClick?: () => void
    disabled?: boolean
}

export default function PillButton({
    label,
    color,
    textColor,
    onClick,
    disabled
}: PillButtonProps) {
    return (
        <button
            className="btn btn-pill btn-dynamic shadow-float"
            onClick={onClick}
            disabled={disabled}
            style={{
                '--btn-bg': color,
                '--btn-text': textColor,
            } as React.CSSProperties}
        >
            {label}
        </button>
    )
}
