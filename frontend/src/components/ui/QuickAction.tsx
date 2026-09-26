import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { X, type LucideIcon } from 'lucide-react'

export type QuickActionTone = 'accent' | 'good' | 'ai' | 'water' | 'warn'

interface QuickActionProps {
    /** Button label, e.g. "Top Up" */
    label: string
    icon: LucideIcon
    tone: QuickActionTone
    /** Current value / status shown next to the label, e.g. "60%" or "→ 80% · 12:30" */
    value?: string
    active: boolean
    disabled?: boolean
    /** Popover heading */
    title: string
    /** Popover body; call `close` after starting or stopping the action */
    children: (close: () => void) => ReactNode
}

const SHEET_BREAKPOINT = 640
const POPOVER_WIDTH = 288
const GUTTER = 12

type Placement = { mode: 'sheet' } | { mode: 'anchored'; top: number; left: number }

/**
 * Command bar quick action: one large button (icon + label + value) that opens a
 * popover holding the action's settings and its Start / Stop button. On narrow
 * screens the popover becomes a bottom sheet.
 */
export default function QuickAction({
    label,
    icon: Icon,
    tone,
    value,
    active,
    disabled = false,
    title,
    children,
}: QuickActionProps) {
    const [open, setOpen] = useState(false)
    const [placement, setPlacement] = useState<Placement | null>(null)
    const buttonRef = useRef<HTMLButtonElement>(null)
    const panelRef = useRef<HTMLDivElement>(null)

    const close = useCallback(() => setOpen(false), [])

    const place = useCallback(() => {
        const button = buttonRef.current
        if (!button) return
        if (window.innerWidth < SHEET_BREAKPOINT) {
            setPlacement({ mode: 'sheet' })
            return
        }
        const rect = button.getBoundingClientRect()
        const maxLeft = window.innerWidth - POPOVER_WIDTH - GUTTER
        setPlacement({
            mode: 'anchored',
            top: rect.bottom + 8,
            left: Math.max(GUTTER, Math.min(rect.left, maxLeft)),
        })
    }, [])

    useEffect(() => {
        if (!open) return
        const onPointerDown = (e: PointerEvent) => {
            const target = e.target as Node
            if (panelRef.current?.contains(target) || buttonRef.current?.contains(target)) return
            setOpen(false)
        }
        const onKeyDown = (e: KeyboardEvent) => {
            if (e.key === 'Escape') {
                setOpen(false)
                buttonRef.current?.focus()
            }
        }
        document.addEventListener('pointerdown', onPointerDown)
        document.addEventListener('keydown', onKeyDown)
        window.addEventListener('resize', place)
        window.addEventListener('scroll', place, true)
        return () => {
            document.removeEventListener('pointerdown', onPointerDown)
            document.removeEventListener('keydown', onKeyDown)
            window.removeEventListener('resize', place)
            window.removeEventListener('scroll', place, true)
        }
    }, [open, place])

    const panel =
        open && placement
            ? createPortal(
                  <>
                      {placement.mode === 'sheet' && <div className="qa-backdrop" aria-hidden="true" />}
                      <div
                          ref={panelRef}
                          role="dialog"
                          aria-label={title}
                          className={`qa-popover ${placement.mode === 'sheet' ? 'qa-popover-sheet' : ''}`}
                          data-tone={tone}
                          style={
                              placement.mode === 'anchored'
                                  ? { top: placement.top, left: placement.left, width: POPOVER_WIDTH }
                                  : undefined
                          }
                      >
                          <div className="qa-popover-header">
                              <span className="qa-popover-title">
                                  <Icon className="h-4 w-4" />
                                  {title}
                              </span>
                              <button type="button" className="qa-popover-close" aria-label="Close" onClick={close}>
                                  <X className="h-4 w-4" />
                              </button>
                          </div>
                          {children(close)}
                      </div>
                  </>,
                  document.body,
              )
            : null

    return (
        <>
            <button
                ref={buttonRef}
                type="button"
                className="qa-btn"
                data-tone={tone}
                data-active={active || undefined}
                aria-label={value ? `${label} ${value}` : label}
                aria-haspopup="dialog"
                aria-expanded={open}
                disabled={disabled}
                onClick={() => {
                    if (!open) place()
                    setOpen(!open)
                }}
            >
                <Icon className={`h-4 w-4 shrink-0 ${active ? 'animate-pulse' : ''}`} />
                <span className="qa-btn-label">{label}</span>
                {value && <span className="qa-btn-value">{value}</span>}
            </button>
            {panel}
        </>
    )
}

interface QuickActionSectionProps {
    label: string
    children: ReactNode
}

/** Labelled group inside a quick action popover */
export function QuickActionSection({ label, children }: QuickActionSectionProps) {
    return (
        <div className="qa-section">
            <div className="qa-section-label">{label}</div>
            {children}
        </div>
    )
}

interface QuickActionChipsProps<T extends string | number> {
    options: { value: T; label: string }[]
    value: T
    onChange: (value: T) => void
    /** Accessible group name, e.g. "Top Up target" */
    label: string
    disabled?: boolean
}

/** Large single-select preset chips */
export function QuickActionChips<T extends string | number>({
    options,
    value,
    onChange,
    label,
    disabled = false,
}: QuickActionChipsProps<T>) {
    return (
        <div className="qa-chips" role="radiogroup" aria-label={label}>
            {options.map((opt) => (
                <button
                    key={String(opt.value)}
                    type="button"
                    role="radio"
                    aria-checked={opt.value === value}
                    className="qa-chip"
                    data-selected={opt.value === value || undefined}
                    disabled={disabled}
                    onClick={() => onChange(opt.value)}
                >
                    {opt.label}
                </button>
            ))}
        </div>
    )
}
