import { ReactNode } from 'react'
import { cls } from '../theme'

export default function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
    return <div className={`${cls.card} ${className}`}>{children}</div>
}
