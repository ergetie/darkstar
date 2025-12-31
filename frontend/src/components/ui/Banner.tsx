import { ReactNode } from 'react'

type BannerVariant = 'info' | 'success' | 'warning' | 'error' | 'purple'

interface BannerProps {
    variant?: BannerVariant
    children: ReactNode
    className?: string
}

export function Banner({ variant = 'info', children, className = '' }: BannerProps) {
    return (
        <div className={`banner banner-${variant} ${className}`}>
            {children}
        </div>
    )
}

type BadgeVariant = 'accent' | 'good' | 'warn' | 'bad' | 'muted'

interface BadgeProps {
    variant?: BadgeVariant
    children: ReactNode
    className?: string
}

export function Badge({ variant = 'muted', children, className = '' }: BadgeProps) {
    return (
        <span className={`badge badge-${variant} ${className}`}>
            {children}
        </span>
    )
}
