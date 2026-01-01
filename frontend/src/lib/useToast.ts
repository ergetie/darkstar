import { createContext, useContext } from 'react'
import type { Toast } from './types'

export interface ToastContextType {
    toast: (props: Omit<Toast, 'id'>) => void
    dismiss: (id: string) => void
}

export const ToastContext = createContext<ToastContextType | undefined>(undefined)

export function useToast() {
    const context = useContext(ToastContext)
    if (context === undefined) {
        throw new Error('useToast must be used within a ToastProvider')
    }
    return context
}
