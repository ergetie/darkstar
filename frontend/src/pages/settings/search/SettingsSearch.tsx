import React, { useState, useMemo, useRef, useEffect, useCallback } from 'react'
import { Search, X, BookOpen, BookA } from 'lucide-react'
import { search, FieldSearchResult, GuideSearchResult, GlossarySearchResult } from './index'
import { getFieldVisibility } from './hints'
import { GuideViewer } from './GuideViewer'
import { ViewerContent, guideToContent, glossaryToContent } from './viewerContent'

interface SettingsSearchProps {
    advancedMode: boolean
    config: Record<string, unknown> | null
    onJumpToField: (tabId: string, fieldKey: string) => void
}

type CombinedItem =
    | { type: 'field'; result: FieldSearchResult }
    | { type: 'guide'; result: GuideSearchResult }
    | { type: 'glossary'; result: GlossarySearchResult }

export const SettingsSearch: React.FC<SettingsSearchProps> = ({ advancedMode, config, onJumpToField }) => {
    const [query, setQuery] = useState('')
    const [isOpen, setIsOpen] = useState(false)
    const [highlightedIndex, setHighlightedIndex] = useState(0)
    const [viewerContent, setViewerContent] = useState<ViewerContent | null>(null)
    const containerRef = useRef<HTMLDivElement>(null)
    const inputRef = useRef<HTMLInputElement>(null)

    const {
        fields: fieldResults,
        guides: guideResults,
        glossary: glossaryResults,
    } = useMemo(() => search(query), [query])

    const combined: CombinedItem[] = useMemo(
        () => [
            ...fieldResults.map((result): CombinedItem => ({ type: 'field', result })),
            ...guideResults.map((result): CombinedItem => ({ type: 'guide', result })),
            ...glossaryResults.map((result): CombinedItem => ({ type: 'glossary', result })),
        ],
        [fieldResults, guideResults, glossaryResults],
    )

    // Reset the highlighted item whenever the query changes. Adjusting state
    // during render (rather than in an effect) avoids an extra render pass.
    const [prevQuery, setPrevQuery] = useState(query)
    if (query !== prevQuery) {
        setPrevQuery(query)
        setHighlightedIndex(0)
    }

    useEffect(() => {
        const handleClickOutside = (e: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
                setIsOpen(false)
            }
        }
        document.addEventListener('mousedown', handleClickOutside)
        return () => document.removeEventListener('mousedown', handleClickOutside)
    }, [])

    const selectField = useCallback(
        (result: FieldSearchResult) => {
            setIsOpen(false)
            onJumpToField(result.entry.tabId, result.entry.fieldKey)
        },
        [onJumpToField],
    )

    const selectGuide = useCallback((result: GuideSearchResult) => {
        setIsOpen(false)
        setViewerContent(guideToContent(result.guide))
    }, [])

    const selectGlossary = useCallback((result: GlossarySearchResult) => {
        setIsOpen(false)
        setViewerContent(glossaryToContent(result.entry))
    }, [])

    const selectItem = useCallback(
        (item: CombinedItem) => {
            if (item.type === 'field') selectField(item.result)
            else if (item.type === 'guide') selectGuide(item.result)
            else selectGlossary(item.result)
        },
        [selectField, selectGuide, selectGlossary],
    )

    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (!isOpen || query.trim() === '') return
        if (e.key === 'ArrowDown') {
            e.preventDefault()
            setHighlightedIndex((i) => Math.min(i + 1, combined.length - 1))
        } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            setHighlightedIndex((i) => Math.max(i - 1, 0))
        } else if (e.key === 'Enter') {
            e.preventDefault()
            const item = combined[highlightedIndex]
            if (item) selectItem(item)
        } else if (e.key === 'Escape') {
            e.preventDefault()
            setIsOpen(false)
            inputRef.current?.blur()
        }
    }

    const showPanel = isOpen && query.trim() !== ''

    return (
        <div ref={containerRef} className="relative mb-6">
            <div className="relative">
                <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
                <input
                    ref={inputRef}
                    type="text"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    onFocus={() => setIsOpen(true)}
                    onKeyDown={handleKeyDown}
                    placeholder="Search settings and guides…"
                    aria-label="Search settings and guides"
                    className="w-full rounded-xl border border-line/50 bg-surface2 py-2.5 pl-10 pr-9 text-sm text-text placeholder:text-muted focus:border-accent focus:outline-none"
                />
                {query && (
                    <button
                        type="button"
                        onClick={() => {
                            setQuery('')
                            inputRef.current?.focus()
                        }}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-muted hover:text-text"
                        aria-label="Clear search"
                    >
                        <X size={14} />
                    </button>
                )}
            </div>

            {showPanel && (
                <div className="absolute z-30 mt-2 w-full max-h-[70vh] overflow-y-auto rounded-xl border border-line/50 bg-surface shadow-2xl">
                    {combined.length === 0 ? (
                        <div className="p-4 text-sm text-muted">No matches for &ldquo;{query}&rdquo;</div>
                    ) : (
                        <>
                            {fieldResults.length > 0 && (
                                <div className="py-1">
                                    <div className="px-3 pt-2 pb-1 text-[10px] font-bold uppercase tracking-wider text-muted">
                                        Settings
                                    </div>
                                    {fieldResults.map((result, idx) => {
                                        const visibility = getFieldVisibility(
                                            result.entry.field,
                                            result.entry.tabId,
                                            config,
                                            advancedMode,
                                        )
                                        return (
                                            <button
                                                key={result.entry.fieldKey}
                                                type="button"
                                                onClick={() => selectField(result)}
                                                onMouseEnter={() => setHighlightedIndex(idx)}
                                                className={`block w-full text-left px-3 py-2 transition-colors ${
                                                    highlightedIndex === idx ? 'bg-surface2' : 'hover:bg-surface2/60'
                                                }`}
                                            >
                                                <div className="flex items-center justify-between gap-2">
                                                    <span className="text-sm font-medium text-text">
                                                        {result.entry.label}
                                                    </span>
                                                    <span className="shrink-0 text-[10px] uppercase tracking-wide text-muted">
                                                        {result.entry.tabLabel}
                                                    </span>
                                                </div>
                                                {result.entry.helpText && (
                                                    <p className="mt-0.5 text-xs text-muted line-clamp-2">
                                                        {result.entry.helpText}
                                                    </p>
                                                )}
                                                {visibility.hidden && (
                                                    <p className="mt-0.5 text-[11px] italic text-warn">
                                                        {visibility.hint}
                                                    </p>
                                                )}
                                            </button>
                                        )
                                    })}
                                </div>
                            )}

                            {guideResults.length > 0 && (
                                <div className="py-1 border-t border-line/30">
                                    <div className="px-3 pt-2 pb-1 text-[10px] font-bold uppercase tracking-wider text-muted">
                                        Guides
                                    </div>
                                    {guideResults.map((result, i) => {
                                        const idx = fieldResults.length + i
                                        return (
                                            <button
                                                key={result.guide.id}
                                                type="button"
                                                onClick={() => selectGuide(result)}
                                                onMouseEnter={() => setHighlightedIndex(idx)}
                                                className={`flex w-full items-start gap-2 text-left px-3 py-2 transition-colors ${
                                                    highlightedIndex === idx ? 'bg-surface2' : 'hover:bg-surface2/60'
                                                }`}
                                            >
                                                <BookOpen size={14} className="mt-0.5 shrink-0 text-accent" />
                                                <div>
                                                    <div className="text-sm font-medium text-text">
                                                        {result.guide.title}
                                                    </div>
                                                    <p className="mt-0.5 text-xs text-muted line-clamp-2">
                                                        {result.guide.summary}
                                                    </p>
                                                </div>
                                            </button>
                                        )
                                    })}
                                </div>
                            )}

                            {glossaryResults.length > 0 && (
                                <div className="py-1 border-t border-line/30">
                                    <div className="px-3 pt-2 pb-1 text-[10px] font-bold uppercase tracking-wider text-muted">
                                        Glossary
                                    </div>
                                    {glossaryResults.map((result, i) => {
                                        const idx = fieldResults.length + guideResults.length + i
                                        return (
                                            <button
                                                key={result.entry.id}
                                                type="button"
                                                onClick={() => selectGlossary(result)}
                                                onMouseEnter={() => setHighlightedIndex(idx)}
                                                className={`flex w-full items-start gap-2 text-left px-3 py-2 transition-colors ${
                                                    highlightedIndex === idx ? 'bg-surface2' : 'hover:bg-surface2/60'
                                                }`}
                                            >
                                                <BookA size={14} className="mt-0.5 shrink-0 text-accent" />
                                                <div>
                                                    <div className="text-sm font-medium text-text">
                                                        {result.entry.term}
                                                    </div>
                                                    <p className="mt-0.5 text-xs text-muted line-clamp-2">
                                                        {result.entry.definition}
                                                    </p>
                                                </div>
                                            </button>
                                        )
                                    })}
                                </div>
                            )}
                        </>
                    )}
                </div>
            )}

            <GuideViewer
                content={viewerContent}
                onClose={() => setViewerContent(null)}
                onJumpToField={(tabId, fieldKey) => onJumpToField(tabId, fieldKey)}
                onOpenGuide={(guide) => setViewerContent(guideToContent(guide))}
            />
        </div>
    )
}
