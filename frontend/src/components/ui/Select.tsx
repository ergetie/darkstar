import { useState, useRef, useEffect, useMemo, ReactNode } from 'react'
import { ChevronDown, Check, Search } from 'lucide-react'

export interface SelectOption {
    label: string
    value: string
    group?: string
}

interface SelectProps {
    value?: string
    onChange: (value: string) => void
    options: SelectOption[]
    placeholder?: string
    disabled?: boolean
    className?: string
    searchable?: boolean
}

/**
 * Generic Select Component
 * 
 * A reusable dropdown that matches the design system.
 * Supports grouping, search, and keyboard navigation.
 */
export default function Select({
    value,
    onChange,
    options,
    placeholder = 'Select...',
    disabled = false,
    className = '',
    searchable = false
}: SelectProps) {
    const [open, setOpen] = useState(false)
    const [search, setSearch] = useState('')
    const [highlightIndex, setHighlightIndex] = useState(0)
    const containerRef = useRef<HTMLDivElement>(null)
    const inputRef = useRef<HTMLInputElement>(null)
    const listRef = useRef<HTMLDivElement>(null)

    // Find selected option
    const selectedOption = options.find(o => o.value === value)

    // Filter options
    const filtered = useMemo(() => {
        if (!search.trim()) return options
        const lower = search.toLowerCase()
        return options.filter(o =>
            o.label.toLowerCase().includes(lower) ||
            o.value.toLowerCase().includes(lower) ||
            o.group?.toLowerCase().includes(lower)
        )
    }, [options, search])

    // Group options
    const grouped = useMemo(() => {
        const groups: Record<string, SelectOption[]> = {}
        const noGroup: SelectOption[] = []

        filtered.forEach(o => {
            if (o.group) {
                if (!groups[o.group]) groups[o.group] = []
                groups[o.group].push(o)
            } else {
                noGroup.push(o)
            }
        })

        return { groups, noGroup }
    }, [filtered])

    // Flat list for keyboard nav
    const flatList = useMemo(() => {
        return [...grouped.noGroup, ...Object.values(grouped.groups).flat()]
    }, [grouped])

    // Reset highlight on change
    useEffect(() => {
        setHighlightIndex(0)
    }, [filtered.length, open])

    // Click outside
    useEffect(() => {
        const handleClickOutside = (e: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
                setOpen(false)
                setSearch('')
            }
        }
        document.addEventListener('mousedown', handleClickOutside)
        return () => document.removeEventListener('mousedown', handleClickOutside)
    }, [])

    // Scroll correction
    useEffect(() => {
        if (open && listRef.current) {
            const el = listRef.current.querySelector(`[data-index="${highlightIndex}"]`)
            if (el) el.scrollIntoView({ block: 'nearest' })
        }
    }, [highlightIndex, open])

    const handleSelect = (val: string) => {
        onChange(val)
        setOpen(false)
        setSearch('')
    }

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (disabled) return

        if (!open) {
            if (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowDown') {
                e.preventDefault()
                setOpen(true)
            }
            return
        }

        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault()
                setHighlightIndex(prev => Math.min(prev + 1, flatList.length - 1))
                break
            case 'ArrowUp':
                e.preventDefault()
                setHighlightIndex(prev => Math.max(prev - 1, 0))
                break
            case 'Enter':
                e.preventDefault()
                if (flatList[highlightIndex]) {
                    handleSelect(flatList[highlightIndex].value)
                }
                break
            case 'Escape':
                e.preventDefault()
                setOpen(false)
                setSearch('')
                break
            case 'Tab':
                setOpen(false)
                break
        }
    }

    return (
        <div ref={containerRef} className={`relative ${className}`}>
            <button
                type="button"
                disabled={disabled}
                onClick={() => {
                    if (!disabled) {
                        setOpen(!open)
                        if (!open && searchable) {
                            setTimeout(() => inputRef.current?.focus(), 0)
                        }
                    }
                }}
                onKeyDown={handleKeyDown}
                className={`
                    w-full flex items-center justify-between gap-2 px-3 py-2
                    rounded-lg border border-line bg-surface2 text-left text-sm
                    hover:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/40
                    disabled:opacity-50 disabled:cursor-not-allowed
                    transition-colors
                `}
            >
                <span className={selectedOption ? 'text-text' : 'text-muted'}>
                    {selectedOption?.label || placeholder}
                </span>
                <ChevronDown className={`h-4 w-4 text-muted transition-transform ${open ? 'rotate-180' : ''}`} />
            </button>

            {open && (
                <div className="absolute z-50 mt-1 w-full min-w-[180px] max-h-[300px] overflow-hidden rounded-lg border border-line bg-surface shadow-float animate-in fade-in zoom-in-95 duration-100">
                    {searchable && (
                        <div className="p-2 border-b border-line">
                            <div className="relative">
                                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted" />
                                <input
                                    ref={inputRef}
                                    type="text"
                                    value={search}
                                    onChange={e => setSearch(e.target.value)}
                                    placeholder="Search..."
                                    className="w-full pl-8 pr-3 py-1.5 rounded-md bg-surface2 border border-line text-sm text-text placeholder:text-muted focus:outline-none focus:ring-1 focus:ring-accent/40"
                                    onKeyDown={handleKeyDown}
                                />
                            </div>
                        </div>
                    )}

                    <div ref={listRef} className="max-h-[240px] overflow-y-auto p-1 scrollbar-thin">
                        {flatList.length === 0 ? (
                            <div className="px-3 py-4 text-center text-sm text-muted">No options found</div>
                        ) : (
                            <>
                                {/* Ungrouped items */}
                                {grouped.noGroup.map((option, i) => {
                                    const isActive = selectedOption?.value === option.value
                                    const isHighlighted = flatList[highlightIndex]?.value === option.value
                                    return (
                                        <div
                                            key={option.value}
                                            data-index={highlightIndex} // Only works if ungrouped is first, logic simplified for now
                                            className={`
                                                flex items-center justify-between px-2 py-1.5 rounded-md text-sm cursor-pointer
                                                ${isHighlighted ? 'bg-accent/20 text-text' : 'text-text'}
                                                ${isActive ? 'font-medium' : ''}
                                            `}
                                            onClick={() => handleSelect(option.value)}
                                            onMouseEnter={() => setHighlightIndex(flatList.findIndex(o => o.value === option.value))}
                                        >
                                            <span>{option.label}</span>
                                            {isActive && <Check className="h-3.5 w-3.5 text-accent" />}
                                        </div>
                                    )
                                })}

                                {/* Grouped items */}
                                {Object.entries(grouped.groups).map(([group, groupOptions]) => (
                                    <div key={group} className="mt-1 first:mt-0">
                                        <div className="px-2 py-1 text-[10px] uppercase tracking-wider text-muted/70 font-medium">
                                            {group}
                                        </div>
                                        {groupOptions.map(option => {
                                            const isActive = selectedOption?.value === option.value
                                            const idx = flatList.findIndex(o => o.value === option.value)
                                            const isHighlighted = idx === highlightIndex

                                            return (
                                                <div
                                                    key={option.value}
                                                    data-index={idx}
                                                    className={`
                                                        flex items-center justify-between px-2 py-1.5 rounded-md text-sm cursor-pointer
                                                        ${isHighlighted ? 'bg-accent/20 text-text' : 'text-text'}
                                                        ${isActive ? 'font-medium' : ''}
                                                    `}
                                                    onClick={() => handleSelect(option.value)}
                                                    onMouseEnter={() => setHighlightIndex(idx)}
                                                >
                                                    <span>{option.label}</span>
                                                    {isActive && <Check className="h-3.5 w-3.5 text-accent" />}
                                                </div>
                                            )
                                        })}
                                    </div>
                                ))}
                            </>
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}
