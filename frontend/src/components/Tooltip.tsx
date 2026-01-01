import { useState } from 'react'
import { HelpCircle } from 'lucide-react'

interface TooltipProps {
    text?: string
    className?: string
}

export default function Tooltip({ text, className = '' }: TooltipProps) {
    const [isVisible, setIsVisible] = useState(false)

    if (!text) return null

    return (
        <div className={`relative inline-block ${className}`}>
            <button
                type="button"
                className="ml-1.5 text-muted/60 hover:text-accent transition-colors"
                onMouseEnter={() => setIsVisible(true)}
                onMouseLeave={() => setIsVisible(false)}
                onFocus={() => setIsVisible(true)}
                onBlur={() => setIsVisible(false)}
            >
                <HelpCircle className="w-3.5 h-3.5" />
            </button>

            {isVisible && (
                <div className="absolute z-50 w-64 p-2.5 text-xs bg-surface2 border border-line rounded-lg shadow-lg left-0 bottom-full mb-1.5">
                    <div className="text-muted leading-relaxed">{text}</div>
                    {/* Arrow */}
                    <div className="absolute w-2 h-2 bg-surface2 border-r border-b border-line transform rotate-45 left-3 -bottom-1" />
                </div>
            )}
        </div>
    )
}
