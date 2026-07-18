const MAX_ATTEMPTS = 40
const POLL_INTERVAL_MS = 100
const HIGHLIGHT_MS = 5000

function findFieldElement(fieldKey: string): HTMLElement | null {
    if (typeof document === 'undefined') return null
    const escaped =
        typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(fieldKey) : fieldKey.replace(/(["\\])/g, '\\$1')
    return document.querySelector<HTMLElement>(`[data-field-key="${escaped}"]`)
}

/**
 * Polls for the field's DOM anchor (it may not exist yet — the target tab is
 * still loading its config) and, once found, scrolls to and briefly
 * highlights it. No-ops safely (after MAX_ATTEMPTS) if the field never
 * appears, e.g. it's hidden by the current config.
 *
 * Returns a cancel function to stop polling (call from an effect cleanup).
 */
export function jumpToField(fieldKey: string, onSettled?: () => void): () => void {
    let cancelled = false
    let attempts = 0
    let timeoutId: ReturnType<typeof setTimeout> | undefined

    const tryScroll = () => {
        if (cancelled) return
        const el = findFieldElement(fieldKey)
        if (el) {
            el.scrollIntoView({ behavior: 'smooth', block: 'center' })
            el.classList.remove('settings-field-highlight')
            void el.offsetWidth // restart the animation if the field was just highlighted
            el.classList.add('settings-field-highlight')
            window.setTimeout(() => el.classList.remove('settings-field-highlight'), HIGHLIGHT_MS)
            onSettled?.()
            return
        }
        attempts += 1
        if (attempts >= MAX_ATTEMPTS) {
            onSettled?.()
            return
        }
        timeoutId = window.setTimeout(tryScroll, POLL_INTERVAL_MS)
    }

    tryScroll()

    return () => {
        cancelled = true
        if (timeoutId) window.clearTimeout(timeoutId)
    }
}
