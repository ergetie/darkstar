import { useCallback, useRef, useState } from 'react'

/**
 * Width in pixels of the element the returned ref is attached to, kept current with a
 * ResizeObserver. 0 until the element is measured (and where layout does not exist, as in jsdom).
 */
export function useElementWidth<T extends HTMLElement>(): [(node: T | null) => void, number] {
    const [width, setWidth] = useState(0)
    const observer = useRef<ResizeObserver | null>(null)
    const ref = useCallback((node: T | null) => {
        observer.current?.disconnect()
        observer.current = null
        if (!node) return
        setWidth(node.getBoundingClientRect().width)
        if (typeof ResizeObserver === 'undefined') return
        observer.current = new ResizeObserver((entries) => {
            const entry = entries[entries.length - 1]
            if (entry) setWidth(entry.contentRect.width)
        })
        observer.current.observe(node)
    }, [])
    return [ref, width]
}
