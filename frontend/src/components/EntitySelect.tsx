import { useState, useRef, useEffect, useMemo } from 'react'
import { ChevronDown, X, Search } from 'lucide-react'

interface Entity {
    entity_id: string
    friendly_name: string
    domain: string
}

interface EntitySelectProps {
    entities: Entity[]
    value: string
    onChange: (value: string) => void
    placeholder?: string
    disabled?: boolean
    loading?: boolean
}

/**
 * Searchable combobox for selecting Home Assistant entities.
 * Features fuzzy search, keyboard navigation, and domain grouping.
 */
export default function EntitySelect({
    entities,
    value,
    onChange,
    placeholder = 'Select entity...',
    disabled = false,
    loading = false,
}: EntitySelectProps) {
    const [open, setOpen] = useState(false)
    const [search, setSearch] = useState('')
    const [highlightIndex, setHighlightIndex] = useState(0)
    const containerRef = useRef<HTMLDivElement>(null)
    const inputRef = useRef<HTMLInputElement>(null)
    const listRef = useRef<HTMLDivElement>(null)

    // Find the selected entity for display
    const selectedEntity = entities.find((e) => e.entity_id === value)

    // Filter entities based on search
    const filtered = useMemo(() => {
        if (!search.trim()) return entities
        const lower = search.toLowerCase()
        return entities.filter(
            (e) => e.entity_id.toLowerCase().includes(lower) || e.friendly_name.toLowerCase().includes(lower),
        )
    }, [entities, search])

    // Group by domain
    const grouped = useMemo(() => {
        const groups: Record<string, Entity[]> = {}
        filtered.forEach((e) => {
            const domain = e.domain || e.entity_id.split('.')[0]
            if (!groups[domain]) groups[domain] = []
            groups[domain].push(e)
        })
        return groups
    }, [filtered])

    // Flat list for keyboard navigation
    const flatList = useMemo(() => {
        const list: Entity[] = []
        Object.values(grouped).forEach((group) => list.push(...group))
        return list
    }, [grouped])

    // Reset highlight when filtered list changes
    useEffect(() => {
        setHighlightIndex(0)
    }, [filtered.length])

    // Close on outside click
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

    // Scroll highlighted item into view
    useEffect(() => {
        if (open && listRef.current) {
            const highlighted = listRef.current.querySelector('[data-highlighted="true"]')
            if (highlighted) {
                highlighted.scrollIntoView({ block: 'nearest' })
            }
        }
    }, [highlightIndex, open])

    const handleSelect = (entity: Entity) => {
        onChange(entity.entity_id)
        setOpen(false)
        setSearch('')
    }

    const handleKeyDown = (e: React.KeyboardEvent) => {
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
                setHighlightIndex((prev) => Math.min(prev + 1, flatList.length - 1))
                break
            case 'ArrowUp':
                e.preventDefault()
                setHighlightIndex((prev) => Math.max(prev - 1, 0))
                break
            case 'Enter':
                e.preventDefault()
                if (flatList[highlightIndex]) {
                    handleSelect(flatList[highlightIndex])
                }
                break
            case 'Escape':
                e.preventDefault()
                setOpen(false)
                setSearch('')
                break
        }
    }

    const handleClear = (e: React.MouseEvent) => {
        e.stopPropagation()
        onChange('')
        setOpen(false)
        setSearch('')
    }

    return (
        <div ref={containerRef} className="relative">
            {/* Trigger button */}
            <button
                type="button"
                disabled={disabled}
                onClick={() => {
                    if (!disabled) {
                        setOpen(!open)
                        if (!open) {
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
                <span className={selectedEntity ? 'text-text' : 'text-muted'}>
                    {loading ? 'Loading...' : selectedEntity?.friendly_name || selectedEntity?.entity_id || placeholder}
                </span>
                <div className="flex items-center gap-1">
                    {value && !disabled && (
                        <button
                            type="button"
                            onClick={handleClear}
                            className="p-0.5 rounded hover:bg-line/60 text-muted hover:text-text"
                            tabIndex={-1}
                        >
                            <X className="h-3.5 w-3.5" />
                        </button>
                    )}
                    <ChevronDown className={`h-4 w-4 text-muted transition-transform ${open ? 'rotate-180' : ''}`} />
                </div>
            </button>

            {/* Dropdown */}
            {open && (
                <div className="absolute z-50 mt-1 w-full min-w-[280px] max-h-[300px] overflow-hidden rounded-lg border border-line bg-surface shadow-float">
                    {/* Search input */}
                    <div className="p-2 border-b border-line">
                        <div className="relative">
                            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted" />
                            <input
                                ref={inputRef}
                                type="text"
                                value={search}
                                onChange={(e) => setSearch(e.target.value)}
                                onKeyDown={handleKeyDown}
                                placeholder="Search entities..."
                                className="w-full pl-8 pr-3 py-1.5 rounded-md bg-surface2 border border-line text-sm text-text placeholder:text-muted focus:outline-none focus:ring-1 focus:ring-accent/40"
                            />
                        </div>
                    </div>

                    {/* Entity list */}
                    <div ref={listRef} className="max-h-[240px] overflow-y-auto p-1">
                        {filtered.length === 0 ? (
                            <div className="px-3 py-4 text-center text-sm text-muted">No entities found</div>
                        ) : (
                            Object.entries(grouped).map(([domain, domainEntities]) => (
                                <div key={domain} className="mb-1">
                                    <div className="px-2 py-1 text-[10px] uppercase tracking-wider text-muted/70 font-medium">
                                        {domain}
                                    </div>
                                    {domainEntities.map((entity) => {
                                        const idx = flatList.findIndex((e) => e.entity_id === entity.entity_id)
                                        const isHighlighted = idx === highlightIndex
                                        const isSelected = entity.entity_id === value

                                        return (
                                            <button
                                                key={entity.entity_id}
                                                type="button"
                                                data-highlighted={isHighlighted}
                                                onClick={() => handleSelect(entity)}
                                                className={`
                                                    w-full text-left px-2 py-1.5 rounded-md text-sm
                                                    transition-colors
                                                    ${isHighlighted ? 'bg-accent/20 text-text' : 'text-text hover:bg-surface2'}
                                                    ${isSelected ? 'font-medium' : ''}
                                                `}
                                            >
                                                <div className="truncate">
                                                    {entity.friendly_name || entity.entity_id}
                                                </div>
                                                <div className="text-[10px] text-muted truncate">
                                                    {entity.entity_id}
                                                </div>
                                            </button>
                                        )
                                    })}
                                </div>
                            ))
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}
