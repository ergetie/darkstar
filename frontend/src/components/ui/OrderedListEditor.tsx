import React, { useState } from 'react'
import { ChevronDown, ChevronUp, GripVertical } from 'lucide-react'

export interface OrderedListEditorProps<T> {
    items: T[]
    /** Stable key per item (used for React keys and drag bookkeeping). */
    keyFor: (item: T) => string
    /** Row content — the editor renders the drag handle and up/down buttons around it. */
    renderItem: (item: T, index: number) => React.ReactNode
    /** Called with the full reordered list after a drag or button move. */
    onReorder: (items: T[]) => void
    disabled?: boolean
    /** aria-label prefix for the move buttons, e.g. "give-way entry". */
    itemLabel?: string
}

function moveItem<T>(items: T[], from: number, to: number): T[] {
    if (to < 0 || to >= items.length || from === to) return items
    const next = [...items]
    const [moved] = next.splice(from, 1)
    next.splice(to, 0, moved)
    return next
}

/**
 * Generic reorderable list: pointer-based drag with always-available up/down
 * button fallback (keyboard + touch accessible). Row content is caller-supplied.
 * Used by the load-balancing give-way list; built reusable for future ordered
 * lists (e.g. the excess-PV sink priority list).
 */
export function OrderedListEditor<T>({
    items,
    keyFor,
    renderItem,
    onReorder,
    disabled = false,
    itemLabel = 'item',
}: OrderedListEditorProps<T>) {
    const [dragIndex, setDragIndex] = useState<number | null>(null)
    const [dropIndex, setDropIndex] = useState<number | null>(null)

    const finishDrag = () => {
        if (dragIndex !== null && dropIndex !== null && dragIndex !== dropIndex) {
            onReorder(moveItem(items, dragIndex, dropIndex))
        }
        setDragIndex(null)
        setDropIndex(null)
    }

    return (
        <div className="space-y-2" role="list">
            {items.map((item, index) => {
                const key = keyFor(item)
                const isDragging = dragIndex === index
                const isDropTarget = dropIndex === index && dragIndex !== null && dragIndex !== index
                return (
                    <div
                        key={key}
                        role="listitem"
                        draggable={!disabled}
                        onDragStart={(e) => {
                            e.dataTransfer.effectAllowed = 'move'
                            setDragIndex(index)
                        }}
                        onDragOver={(e) => {
                            e.preventDefault()
                            if (dragIndex !== null) setDropIndex(index)
                        }}
                        onDrop={(e) => {
                            e.preventDefault()
                            finishDrag()
                        }}
                        onDragEnd={finishDrag}
                        className={`flex items-stretch gap-2 rounded-xl border bg-surface-elevated transition-colors ${
                            isDropTarget ? 'border-accent' : 'border-line/40'
                        } ${isDragging ? 'opacity-50' : ''}`}
                    >
                        <div
                            className={`flex shrink-0 items-center pl-2 text-muted ${
                                disabled ? 'opacity-30' : 'cursor-grab'
                            }`}
                            title="Drag to reorder"
                        >
                            <GripVertical size={16} />
                        </div>
                        <div className="min-w-0 flex-1 py-1">{renderItem(item, index)}</div>
                        <div className="flex shrink-0 flex-col justify-center gap-0.5 pr-2">
                            <button
                                type="button"
                                aria-label={`Move ${itemLabel} up`}
                                disabled={disabled || index === 0}
                                onClick={() => onReorder(moveItem(items, index, index - 1))}
                                className="rounded p-0.5 text-muted transition-colors hover:bg-surface2 hover:text-text disabled:opacity-25"
                            >
                                <ChevronUp size={14} />
                            </button>
                            <button
                                type="button"
                                aria-label={`Move ${itemLabel} down`}
                                disabled={disabled || index === items.length - 1}
                                onClick={() => onReorder(moveItem(items, index, index + 1))}
                                className="rounded p-0.5 text-muted transition-colors hover:bg-surface2 hover:text-text disabled:opacity-25"
                            >
                                <ChevronDown size={14} />
                            </button>
                        </div>
                    </div>
                )
            })}
        </div>
    )
}

export default OrderedListEditor
