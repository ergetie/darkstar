import { useRef, useEffect, ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'

interface ModalProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    title?: ReactNode
    children: ReactNode
    footer?: ReactNode
    size?: 'sm' | 'md' | 'lg' | 'xl'
    className?: string
}

/**
 * Modal Component
 *
 * Renders a dialog overlay using a React Portal.
 * Handles click-outside, escape key, and scroll locking.
 */
export default function Modal({
    open,
    onOpenChange,
    title,
    children,
    footer,
    size = 'md',
    className = '',
}: ModalProps) {
    const overlayRef = useRef<HTMLDivElement>(null)

    // Close on Escape
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            if (open && e.key === 'Escape') {
                onOpenChange(false)
            }
        }
        window.addEventListener('keydown', handleKeyDown)
        return () => window.removeEventListener('keydown', handleKeyDown)
    }, [open, onOpenChange])

    // Lock body scroll
    useEffect(() => {
        if (open) {
            document.body.style.overflow = 'hidden'
        } else {
            document.body.style.overflow = ''
        }
        return () => {
            document.body.style.overflow = ''
        }
    }, [open])

    if (!open) return null

    const sizeClasses = {
        sm: 'max-w-sm',
        md: 'max-w-md',
        lg: 'max-w-2xl',
        xl: 'max-w-4xl',
    }

    const content = (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 sm:p-6">
            {/* Backdrop */}
            <div
                ref={overlayRef}
                className="absolute inset-0 bg-black/60 backdrop-blur-sm animate-in fade-in duration-200"
                onClick={(e) => {
                    if (e.target === overlayRef.current) onOpenChange(false)
                }}
            />

            {/* Dialog */}
            <div
                className={`
                    relative w-full ${sizeClasses[size]} 
                    bg-surface rounded-ds-lg border border-line shadow-2xl 
                    animate-in zoom-in-95 fade-in duration-200
                    flex flex-col max-h-[90vh]
                    ${className}
                `}
                role="dialog"
                aria-modal="true"
            >
                {/* Header */}
                <div className="flex items-center justify-between px-6 py-4 border-b border-line shrink-0">
                    <div className="text-lg font-semibold text-text">{title}</div>
                    <button
                        onClick={() => onOpenChange(false)}
                        className="p-1 rounded-md text-muted hover:text-text hover:bg-surface2 transition-colors"
                    >
                        <X className="h-5 w-5" />
                    </button>
                </div>

                {/* Body */}
                <div className="px-6 py-4 overflow-y-auto scrollbar-thin">{children}</div>

                {/* Footer */}
                {footer && (
                    <div className="px-6 py-4 border-t border-line bg-surface2/30 flex justify-end gap-3 shrink-0 rounded-b-ds-lg">
                        {footer}
                    </div>
                )}
            </div>
        </div>
    )

    return createPortal(content, document.body)
}
