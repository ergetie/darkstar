import { useState, useEffect } from 'react'
import { Sun, Moon } from 'lucide-react'
import { Api } from '../lib/api'

type ThemeMode = 'light' | 'dark' | 'system'

/**
 * Theme toggle button for switching between light and dark mode.
 * Persists preference to backend config and localStorage as fallback.
 */
export default function ThemeToggle() {
    const [mode, setMode] = useState<ThemeMode>('dark')
    const [loading, setLoading] = useState(true)

    // Determine the actual theme based on mode and system preference
    const getEffectiveTheme = (m: ThemeMode): 'light' | 'dark' => {
        if (m === 'system') {
            return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
        }
        return m
    }

    // Apply theme to document
    const applyTheme = (theme: 'light' | 'dark') => {
        const root = document.documentElement
        if (theme === 'dark') {
            root.classList.add('dark')
        } else {
            root.classList.remove('dark')
        }
    }

    // Load initial theme from backend config or localStorage
    useEffect(() => {
        const loadTheme = async () => {
            try {
                const config = await Api.config()
                const savedMode = config?.ui?.theme_mode as ThemeMode | undefined
                if (savedMode && ['light', 'dark', 'system'].includes(savedMode)) {
                    setMode(savedMode)
                    applyTheme(getEffectiveTheme(savedMode))
                } else {
                    // Fallback to localStorage
                    const local = localStorage.getItem('darkstar-theme') as ThemeMode | null
                    if (local && ['light', 'dark', 'system'].includes(local)) {
                        setMode(local)
                        applyTheme(getEffectiveTheme(local))
                    } else {
                        // Default to dark (current behavior)
                        setMode('dark')
                        applyTheme('dark')
                    }
                }
            } catch {
                // On error, use localStorage or default
                const local = localStorage.getItem('darkstar-theme') as ThemeMode | null
                const m = local || 'dark'
                setMode(m as ThemeMode)
                applyTheme(getEffectiveTheme(m as ThemeMode))
            } finally {
                setLoading(false)
            }
        }
        loadTheme()
    }, [])

    // Listen for system theme changes when mode is 'system'
    useEffect(() => {
        if (mode !== 'system') return

        const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
        const handler = (e: MediaQueryListEvent) => {
            applyTheme(e.matches ? 'dark' : 'light')
        }
        mediaQuery.addEventListener('change', handler)
        return () => mediaQuery.removeEventListener('change', handler)
    }, [mode])

    const handleToggle = async () => {
        // Simple toggle: dark -> light -> dark
        const newMode: ThemeMode = mode === 'dark' ? 'light' : 'dark'

        // Apply immediately for responsiveness
        setMode(newMode)
        applyTheme(newMode)
        localStorage.setItem('darkstar-theme', newMode)

        // Persist to backend
        try {
            await Api.configSave({ ui: { theme_mode: newMode } })
        } catch (err) {
            console.warn('[ThemeToggle] Failed to save theme to backend:', err)
        }
    }

    if (loading) {
        return (
            <div className="h-12 w-12 rounded-2xl border border-line/70 bg-surface/80 flex items-center justify-center">
                <div className="h-5 w-5 rounded-full bg-muted/30 animate-pulse" />
            </div>
        )
    }

    const effectiveTheme = getEffectiveTheme(mode)

    return (
        <button
            type="button"
            onClick={handleToggle}
            className="group relative flex items-center justify-center w-12 h-12 rounded-2xl border border-line/70 bg-surface/80 hover:bg-surface2 transition"
            title={`Switch to ${effectiveTheme === 'dark' ? 'light' : 'dark'} mode`}
        >
            {effectiveTheme === 'dark' ? (
                <Sun className="h-5 w-5 text-muted group-hover:text-accent transition-colors" />
            ) : (
                <Moon className="h-5 w-5 text-muted group-hover:text-accent transition-colors" />
            )}
            <span className="absolute -right-2 top-1 rounded-full bg-surface2/90 border border-line/60 px-2 py-0.5 text-[10px] text-muted opacity-0 group-hover:opacity-100 transition z-50 whitespace-nowrap">
                {effectiveTheme === 'dark' ? 'Light mode' : 'Dark mode'}
            </span>
        </button>
    )
}
