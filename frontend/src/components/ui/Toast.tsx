import { createContext, useContext, useState, useCallback, ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { X, CheckCircle, AlertTriangle, Info, AlertCircle } from 'lucide-react'

export type ToastVariant = 'success' | 'error' | 'warning' | 'info'

interface Toast {
    id: string
    message: string
    description?: string
    variant: ToastVariant
}

interface ToastContextType {
    toast: (props: Omit<Toast, 'id'>) => void
    dismiss: (id: string) => void
}

const ToastContext = createContext<ToastContextType | undefined>(undefined)

/**
 * Toast Provider
 *
 * Wrap the app in this provider to enable usage of the useToast hook.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
    const [toasts, setToasts] = useState<Toast[]>([])

    const dismiss = useCallback((id: string) => {
        setToasts((prev) => prev.filter((t) => t.id !== id))
    }, [])

    const toast = useCallback(
        ({ message, description, variant }: Omit<Toast, 'id'>) => {
            const id = Math.random().toString(36).substring(2, 9)
            setToasts((prev) => [...prev, { id, message, description, variant }])

            // Auto dismiss after 5 seconds
            setTimeout(() => {
                dismiss(id)
            }, 5000)
        },
        [dismiss],
    )

    return (
        <ToastContext.Provider value={{ toast, dismiss }}>
            {children}
            {createPortal(
                <div className="fixed bottom-0 right-0 z-[100] p-6 space-y-4 max-w-sm w-full pointer-events-none">
                    {toasts.map((t) => (
                        <div
                            key={t.id}
                            className={`
                                pointer-events-auto
                                flex gap-3 p-4 rounded-ds-lg shadow-2xl border
                                animate-in slide-in-from-right-full duration-300
                                ${getToastStyles(t.variant)}
                            `}
                        >
                            <div className="shrink-0 mt-0.5">{getToastIcon(t.variant)}</div>
                            <div className="flex-1">
                                <div className="font-semibold text-sm">{t.message}</div>
                                {t.description && <div className="text-xs opacity-90 mt-1">{t.description}</div>}
                            </div>
                            <button
                                onClick={() => dismiss(t.id)}
                                className="shrink-0 -mt-1 -mr-1 p-1 rounded hover:bg-black/10 transition-colors"
                            >
                                <X className="h-4 w-4" />
                            </button>
                        </div>
                    ))}
                </div>,
                document.body,
            )}
        </ToastContext.Provider>
    )
}

export function useToast() {
    const context = useContext(ToastContext)
    if (context === undefined) {
        throw new Error('useToast must be used within a ToastProvider')
    }
    return context
}

function getToastStyles(variant: ToastVariant): string {
    switch (variant) {
        case 'success':
            return 'bg-surface2 border-good text-text' // Using border color for accent
        case 'error':
            return 'bg-bad text-white border-bad'
        case 'warning':
            return 'bg-warn text-black border-warn'
        case 'info':
            return 'bg-surface2 border-line text-text'
    }
}

function getToastIcon(variant: ToastVariant) {
    switch (variant) {
        case 'success':
            return <CheckCircle className="h-5 w-5 text-good" />
        case 'error':
            return <AlertCircle className="h-5 w-5 text-white" />
        case 'warning':
            return <AlertTriangle className="h-5 w-5 text-black" />
        case 'info':
            return <Info className="h-5 w-5 text-accent" />
    }
}
