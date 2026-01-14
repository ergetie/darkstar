import React from 'react'

interface BadgeProps {
    variant: 'warning' | 'info' | 'error' | 'success'
    children: React.ReactNode
}

export const Badge: React.FC<BadgeProps> = ({ variant, children }) => {
    const variantClasses = {
        warning: 'bg-yellow-500/10 text-yellow-500 border-yellow-500/30',
        info: 'bg-blue-500/10 text-blue-500 border-blue-500/30',
        error: 'bg-red-500/10 text-red-500 border-red-500/30',
        success: 'bg-green-500/10 text-green-500 border-green-500/30',
    }

    return (
        <span
            className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${variantClasses[variant]}`}
        >
            {children}
        </span>
    )
}
