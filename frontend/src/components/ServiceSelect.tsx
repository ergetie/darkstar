import { useState, useRef, useEffect, useMemo } from 'react'
import { ChevronDown, X, Search } from 'lucide-react'
import { Api } from '../lib/api'

interface ServiceSelectProps {
    value: string
    onChange: (value: string) => void
    placeholder?: string
    disabled?: boolean
}

/**
 * Searchable combobox for selecting Home Assistant services.
 * Dynamically fetches services and groups them by domain.
 */
export default function ServiceSelect({
    value,
    onChange,
    placeholder = 'Select service (e.g. notify.mobile_app)...',
    disabled = false,
}: ServiceSelectProps) {
    const [open, setOpen] = useState(false)
    const [search, setSearch] = useState('')
    const [services, setServices] = useState<string[]>([])
    const [loading, setLoading] = useState(false)
    const [highlightIndex, setHighlightIndex] = useState(0)
    const containerRef = useRef<HTMLDivElement>(null)
    const inputRef = useRef<HTMLInputElement>(null)
    const listRef = useRef<HTMLDivElement>(null)

    // Fetch services when dropdown opens for the first time
    useEffect(() => {
        if (open && services.length === 0 && !loading) {
            // eslint-disable-next-line react-hooks/set-state-in-effect
            setLoading(true)
            Api.haServices()
                .then((res) => {
                    setServices(res.services || [])
                })
                .catch((err) => {
                    console.error('Failed to fetch HA services:', err)
                })
                .finally(() => {
                    setLoading(false)
                })
        }
    }, [open, services.length, loading])

    // Filter services based on search
    const filtered = useMemo(() => {
        if (!search.trim()) return services
        const lower = search.toLowerCase()
        return services.filter((s) => s.toLowerCase().includes(lower))
    }, [services, search])

    // Group by domain (first part of service string)
    const grouped = useMemo(() => {
        const groups: Record<string, string[]> = {}
        filtered.forEach((s) => {
            const domain = s.split('.')[0] || 'other'
            if (!groups[domain]) groups[domain] = []
            groups[domain].push(s)
        })
        return groups
    }, [filtered])

    // Flat list for keyboard navigation
    const flatList = useMemo(() => {
        const list: string[] = []
        Object.values(grouped).forEach((group) => list.push(...group))
        return list
    }, [grouped])

    // Reset highlight when filtered list changes
    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect
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

    const handleSelect = (service: string) => {
        onChange(service)
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
                <span className={value ? 'text-text' : 'text-muted'}>
                    {loading && services.length === 0 ? 'Loading services...' : value || placeholder}
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
                    {/* Search input stack */}
                    <div className="p-2 border-b border-line">
                        <div className="relative">
                            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted" />
                            <input
                                ref={inputRef}
                                type="text"
                                value={search}
                                onChange={(e) => setSearch(e.target.value)}
                                onKeyDown={handleKeyDown}
                                placeholder="Search services..."
                                className="w-full pl-8 pr-3 py-1.5 rounded-md bg-surface2 border border-line text-sm text-text placeholder:text-muted focus:outline-none focus:ring-1 focus:ring-accent/40"
                            />
                        </div>
                    </div>

                    {/* Service list */}
                    <div ref={listRef} className="max-h-[240px] overflow-y-auto p-1 scrollbar-thin">
                        {loading && services.length === 0 ? (
                            <div className="px-3 py-4 text-center text-sm text-muted animate-pulse">
                                Loading from Home Assistant...
                            </div>
                        ) : filtered.length === 0 ? (
                            <div className="px-3 py-4 text-center text-sm text-muted">No services found</div>
                        ) : (
                            Object.entries(grouped).map(([domain, domainServices]) => (
                                <div key={domain} className="mb-1">
                                    <div className="px-2 py-1 text-[10px] uppercase tracking-wider text-muted/70 font-medium">
                                        {domain}
                                    </div>
                                    {domainServices.map((service) => {
                                        const idx = flatList.indexOf(service)
                                        const isHighlighted = idx === highlightIndex
                                        const isSelected = service === value

                                        return (
                                            <button
                                                key={service}
                                                type="button"
                                                data-highlighted={isHighlighted}
                                                onClick={() => handleSelect(service)}
                                                className={`
                                                    w-full text-left px-2 py-1.5 rounded-md text-sm
                                                    transition-colors
                                                    ${isHighlighted ? 'bg-accent/20 text-text' : 'text-text hover:bg-surface2'}
                                                    ${isSelected ? 'font-medium' : ''}
                                                `}
                                            >
                                                <div className="truncate">{service}</div>
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
