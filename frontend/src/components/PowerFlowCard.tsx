/**
 * PowerFlowCard.tsx
 *
 * Highway layout energy flow visualization.
 * Two rows of bracket nodes connected by a central bus line.
 * Flow dots animate from sources through the bus to loads.
 */

import { useMemo, useState, useCallback, useEffect } from 'react'
import { NODE_REGISTRY, type PowerFlowData } from './PowerFlowRegistry'
import type { ConfigResponse } from '../lib/api'
import { Plug } from 'lucide-react'

interface PowerFlowCardProps {
    data: PowerFlowData
    systemConfig?: ConfigResponse | null
}

interface Entity {
    id: string
    kw: number
    color: string
}

// =============================================================================
// CONSTANTS
// =============================================================================

const COLORS: Record<string, string> = {
    solar: 'rgb(var(--color-accent))',
    battery: 'rgb(var(--color-good))',
    grid: 'rgb(var(--color-grid))',
    house: 'rgb(var(--color-house))',
    water: 'rgb(var(--color-water))',
    ev: 'rgb(var(--color-ai))',
}

const TEXT = 'rgb(var(--color-text))'
const SURFACE = 'rgb(var(--color-surface))'
const MUTED = 'rgb(var(--color-muted))'
const MONO = 'JetBrains Mono, monospace'

const TOP_ORDER = ['solar', 'battery', 'grid'] as const
const BOT_ORDER = ['house', 'water', 'ev'] as const

const W = 400,
    H = 180
const PAD_X = 12
const SPAN = W - 2 * PAD_X
const B_W = 40,
    B_H = 20,
    B_SIZE = 10,
    B_R = 4
const CORNER_R = 6
// Anchored independently of H so the extra bottom whitespace doesn't shift the bus/rows.
const BUS_Y = 80
const TOP_CY = 32,
    BOT_CY = 128

// =============================================================================
// PURE HELPERS (module-level — no closure over component state)
// =============================================================================

// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function cxFor(idx: number, count: number) {
    return PAD_X + (SPAN * (idx + 0.5)) / count
}

// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function exitYFor(row: 'top' | 'bot') {
    return row === 'top' ? TOP_CY + B_H : BOT_CY - B_H
}

// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function toPathD(pts: { x: number; y: number }[]): string {
    if (!pts.length) return ''
    return pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ')
}

// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function computeEnabledNodes(configMap: Record<string, unknown> | null, data: PowerFlowData) {
    if (!configMap) return NODE_REGISTRY.filter((n) => !n.configKey || ['solar', 'battery', 'water'].includes(n.id))
    return NODE_REGISTRY.filter((node) => {
        if (node.configKey) {
            const val = configMap[node.configKey]
            if (val !== undefined) {
                if (val === false) return false
            } else {
                if (!['solar', 'battery', 'water'].includes(node.id)) return false
            }
        }
        if (node.shouldRender) return node.shouldRender(data, configMap)
        return true
    })
}

// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function partitionFlow(data: PowerFlowData, enabledIds: Set<string>): { sources: Entity[]; loads: Entity[] } {
    const sources: Entity[] = []
    const loads: Entity[] = []

    if (enabledIds.has('solar') && data.solar.kw > 0.05)
        sources.push({ id: 'solar', kw: data.solar.kw, color: COLORS.solar })
    if (enabledIds.has('battery') && data.battery.kw > 0.05)
        sources.push({ id: 'battery', kw: data.battery.kw, color: COLORS.battery })
    if (enabledIds.has('grid') && data.grid.kw > 0.05)
        sources.push({ id: 'grid', kw: data.grid.kw, color: COLORS.grid })

    if (data.house.kw > 0.05) loads.push({ id: 'house', kw: data.house.kw, color: COLORS.house })
    if (enabledIds.has('water') && data.water.kw > 0.05)
        loads.push({ id: 'water', kw: data.water.kw, color: COLORS.water })
    if (enabledIds.has('ev') && (data.ev?.kw ?? 0) > 0.05) loads.push({ id: 'ev', kw: data.ev!.kw, color: COLORS.ev })

    if (enabledIds.has('battery') && data.battery.kw < -0.05)
        loads.push({ id: 'battery', kw: -data.battery.kw, color: COLORS.battery })
    if (enabledIds.has('grid') && data.grid.kw < -0.05)
        loads.push({ id: 'grid', kw: -data.grid.kw, color: COLORS.grid })

    return { sources, loads }
}

// =============================================================================
// FLOW DOTS — CSS offset-path animation (GPU-composited, no SMIL)
// =============================================================================

function FlowDots({
    waypoints,
    color,
    power,
    dotCount = 3,
}: {
    waypoints: { x: number; y: number }[]
    color: string
    power: number
    dotCount?: number
}) {
    const speed = Math.min(power * 0.2, 1.5)
    const duration = Math.max(2.8 - speed, 0.7)
    const pathD = toPathD(waypoints)

    return (
        <>
            {Array.from({ length: dotCount }, (_, i) => (
                <circle
                    key={i}
                    r={3}
                    fill={color}
                    className="flow-dot"
                    style={
                        {
                            offsetPath: `path('${pathD}')`,
                            '--flow-dur': `${duration}s`,
                            '--flow-delay': `${-(i / dotCount) * duration}s`,
                        } as React.CSSProperties
                    }
                />
            ))}
        </>
    )
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export default function PowerFlowCard({ data, systemConfig }: PowerFlowCardProps) {
    const [showEvTooltip, setShowEvTooltip] = useState(false)

    const handleOutsideClick = useCallback(() => setShowEvTooltip(false), [])

    useEffect(() => {
        if (showEvTooltip) {
            const tid = setTimeout(() => {
                document.addEventListener('click', handleOutsideClick)
                document.addEventListener('touchstart', handleOutsideClick)
            }, 0)
            return () => {
                clearTimeout(tid)
                document.removeEventListener('click', handleOutsideClick)
                document.removeEventListener('touchstart', handleOutsideClick)
            }
        }
    }, [showEvTooltip, handleOutsideClick])

    const handleEvInteract = useCallback(() => setShowEvTooltip((p) => !p), [])

    const evTooltipContent = useMemo(() => {
        if (!data.evChargers || data.evChargers.length === 0) return null
        const evCount = data.evChargers.length
        const header = evCount > 1 ? `${evCount} EVs Connected` : data.evChargers[0]?.name || 'EV'
        return (
            <div
                className="bg-surface-elevated"
                style={{
                    borderRadius: '8px',
                    border: '1px solid rgba(255,255,255,0.2)',
                    boxShadow: '0 4px 20px rgba(0,0,0,0.7)',
                    padding: '10px 14px',
                    fontFamily: MONO,
                    fontSize: '11px',
                    color: TEXT,
                    maxHeight: '180px',
                    overflowY: 'auto',
                    minWidth: '180px',
                    width: 'max-content',
                    zIndex: 1000,
                    opacity: 0.98,
                }}
            >
                <div style={{ fontWeight: 'bold', marginBottom: '6px', color: COLORS.ev, whiteSpace: 'nowrap' }}>
                    {header}
                </div>
                {data.evChargers.map((ev, idx) => (
                    <div
                        key={idx}
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '8px',
                            padding: '4px 0',
                            borderTop: idx > 0 ? '1px solid rgba(255,255,255,0.1)' : 'none',
                            whiteSpace: 'nowrap',
                        }}
                    >
                        <Plug
                            size={12}
                            style={{ color: ev.pluggedIn ? 'rgb(var(--color-good))' : MUTED, flexShrink: 0 }}
                        />
                        <span style={{ flex: 1 }}>{ev.name}</span>
                        <span>{ev.kw.toFixed(1)} kW</span>
                        {ev.soc !== null && <span>{ev.soc.toFixed(0)}%</span>}
                    </div>
                ))}
            </div>
        )
    }, [data.evChargers])

    // Config-based node visibility
    const configMap = useMemo(() => {
        if (!systemConfig || typeof systemConfig !== 'object') return null
        const map: Record<string, unknown> = {}
        const flatten = (obj: unknown, prefix = '') => {
            if (obj && typeof obj === 'object' && !Array.isArray(obj)) {
                const record = obj as Record<string, unknown>
                for (const k in record) {
                    const path = prefix ? `${prefix}.${k}` : k
                    const val = record[k]
                    if (typeof val === 'object' && !Array.isArray(val)) flatten(val, path)
                    else map[path] = val
                }
            }
        }
        flatten(systemConfig)
        return map
    }, [systemConfig])

    const enabledNodes = useMemo(() => computeEnabledNodes(configMap, data), [configMap, data])

    const enabledIds = useMemo(() => new Set(enabledNodes.map((n) => n.id)), [enabledNodes])

    // Enabled slots per row (memoized for stable references)
    const topSlots = useMemo(() => TOP_ORDER.filter((id) => enabledIds.has(id)), [enabledIds])
    const botSlots = useMemo(() => BOT_ORDER.filter((id) => enabledIds.has(id)), [enabledIds])

    // Flow pairs
    const { sources, loads } = useMemo(() => partitionFlow(data, enabledIds), [data, enabledIds])
    const totalSrc = sources.reduce((s, x) => s + x.kw, 0)

    const pairs = useMemo(() => {
        const result: { src: Entity; load: Entity; kw: number }[] = []
        if (totalSrc > 0) {
            for (const load of loads) {
                for (const src of sources) {
                    const kw = load.kw * (src.kw / totalSrc)
                    if (kw >= 0.1) result.push({ src, load, kw })
                }
            }
        }
        return result
    }, [sources, loads, totalSrc])

    // Node value helpers
    const getKw = (id: string): number => {
        switch (id) {
            case 'solar':
                return data.solar.kw
            case 'battery':
                return Math.abs(data.battery.kw)
            case 'grid':
                return Math.abs(data.grid.kw)
            case 'house':
                return data.house.kw
            case 'water':
                return data.water.kw
            case 'ev':
                return data.ev?.kw ?? 0
            default:
                return 0
        }
    }

    const getLabel = (id: string): string => {
        switch (id) {
            case 'solar':
                return 'SOLAR'
            case 'battery':
                if (data.battery.kw < -0.05) return 'CHARGE'
                if (data.battery.kw > 0.05) return 'DISCHG'
                return 'BATT'
            case 'grid':
                if (data.grid.kw < -0.05) return 'EXPORT'
                if (data.grid.kw > 0.05) return 'IMPORT'
                return 'GRID'
            case 'house':
                return 'HOUSE'
            case 'water':
                return 'WATER'
            case 'ev':
                return 'EV'
            default:
                return id.toUpperCase()
        }
    }

    const getSubValue = (id: string): string | undefined => {
        switch (id) {
            case 'solar':
                return data.solar.todayKwh != null ? `${data.solar.todayKwh.toFixed(1)} kWh` : undefined
            case 'battery':
                return `${data.battery.soc.toFixed(0)}%`
            case 'grid': {
                const kwh = data.grid.kw < -0.05 ? data.grid.exportKwh : data.grid.importKwh
                return kwh != null && kwh > 0 ? `${kwh.toFixed(1)} kWh` : undefined
            }
            case 'house':
                return data.house.todayKwh != null ? `${data.house.todayKwh.toFixed(1)} kWh` : undefined
            case 'water':
                return data.water.todayKwh != null && data.water.todayKwh > 0
                    ? `${data.water.todayKwh.toFixed(1)} kWh`
                    : undefined
            case 'ev':
                if (!data.evChargers || data.evChargers.length === 0) return undefined
                return data.evSoc != null ? `${data.evSoc.toFixed(0)}%` : data.evPluggedIn ? 'plugged' : 'away'
            default:
                return undefined
        }
    }

    const renderBracketNode = (id: string, row: 'top' | 'bot', idx: number, count: number) => {
        const kw = getKw(id)
        const active = kw > 0.05 || id === 'house'
        const color = COLORS[id] ?? MUTED
        const strokeColor = active ? color : MUTED
        const cx = cxFor(idx, count)
        const cy = row === 'top' ? TOP_CY : BOT_CY
        const label = getLabel(id)
        const subValue = getSubValue(id)
        const isEvNode = id === 'ev' && evTooltipContent != null

        const lbp = [
            `M ${cx - B_W + B_SIZE} ${cy - B_H}`,
            `L ${cx - B_W + B_R} ${cy - B_H}`,
            `Q ${cx - B_W} ${cy - B_H} ${cx - B_W} ${cy - B_H + B_R}`,
            `L ${cx - B_W} ${cy + B_H - B_R}`,
            `Q ${cx - B_W} ${cy + B_H} ${cx - B_W + B_R} ${cy + B_H}`,
            `L ${cx - B_W + B_SIZE} ${cy + B_H}`,
        ].join(' ')
        const rbp = [
            `M ${cx + B_W - B_SIZE} ${cy - B_H}`,
            `L ${cx + B_W - B_R} ${cy - B_H}`,
            `Q ${cx + B_W} ${cy - B_H} ${cx + B_W} ${cy - B_H + B_R}`,
            `L ${cx + B_W} ${cy + B_H - B_R}`,
            `Q ${cx + B_W} ${cy + B_H} ${cx + B_W - B_R} ${cy + B_H}`,
            `L ${cx + B_W - B_SIZE} ${cy + B_H}`,
        ].join(' ')

        return (
            <g
                key={id}
                opacity={active ? 1 : 0.45}
                onClick={isEvNode ? handleEvInteract : undefined}
                style={isEvNode ? { cursor: 'pointer' } : undefined}
            >
                <path d={lbp} fill="none" stroke={strokeColor} strokeWidth={1.5} />
                <path d={rbp} fill="none" stroke={strokeColor} strokeWidth={1.5} />
                <text
                    x={cx}
                    y={cy - 9}
                    textAnchor="middle"
                    fill={MUTED}
                    fontSize={8}
                    fontFamily={MONO}
                    letterSpacing="1"
                >
                    {label}
                </text>
                <text
                    x={cx}
                    y={cy + 4}
                    textAnchor="middle"
                    fill={active ? color : TEXT}
                    fontSize={12}
                    fontWeight="bold"
                    fontFamily={MONO}
                >
                    {kw.toFixed(1)} kW
                </text>
                {subValue && (
                    <text
                        x={cx}
                        y={cy + 17}
                        textAnchor="middle"
                        fill={active ? TEXT : MUTED}
                        fontSize={9}
                        fontFamily={MONO}
                    >
                        {subValue}
                    </text>
                )}
            </g>
        )
    }

    const pairPaths = useMemo(() => {
        const slotOf = (id: string) => {
            const tIdx = (topSlots as readonly string[]).indexOf(id)
            if (tIdx >= 0) return { row: 'top' as const, idx: tIdx, count: topSlots.length }
            const bIdx = (botSlots as readonly string[]).indexOf(id)
            if (bIdx >= 0) return { row: 'bot' as const, idx: bIdx, count: botSlots.length }
            return null
        }

        const mkPath = (srcId: string, loadId: string) => {
            const s = slotOf(srcId)
            const l = slotOf(loadId)
            if (!s || !l) return null
            const sX = cxFor(s.idx, s.count)
            const lX = cxFor(l.idx, l.count)
            const sExit = exitYFor(s.row)
            const lExit = exitYFor(l.row)
            const sBusEdge = s.row === 'top' ? BUS_Y - CORNER_R : BUS_Y + CORNER_R
            const lBusEdge = l.row === 'top' ? BUS_Y - CORNER_R : BUS_Y + CORNER_R
            if (Math.abs(lX - sX) < 1)
                return [
                    { x: sX, y: sExit },
                    { x: sX, y: lExit },
                ]
            const goLeft = lX < sX
            return [
                { x: sX, y: sExit },
                { x: sX, y: sBusEdge },
                { x: goLeft ? sX - CORNER_R : sX + CORNER_R, y: BUS_Y },
                { x: goLeft ? lX + CORNER_R : lX - CORNER_R, y: BUS_Y },
                { x: lX, y: lBusEdge },
                { x: lX, y: lExit },
            ]
        }

        return pairs
            .map((p) => {
                const pts = mkPath(p.src.id, p.load.id)
                return pts ? { src: p.src, load: p.load, kw: p.kw, pts } : null
            })
            .filter((p): p is { src: Entity; load: Entity; kw: number; pts: { x: number; y: number }[] } => p != null)
    }, [pairs, topSlots, botSlots])

    return (
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full block mx-auto" preserveAspectRatio="xMidYMid meet">
            <rect x="-4000" y="-4000" width="10000" height="10000" fill={SURFACE} />
            {pairPaths.map((p, i) => (
                <path
                    key={`trace-${i}`}
                    d={toPathD(p.pts)}
                    stroke={p.src.color}
                    strokeWidth={1.5}
                    strokeOpacity={0.3}
                    fill="none"
                />
            ))}
            {pairPaths.map((p) => (
                <FlowDots
                    key={`${p.src.id}-${p.load.id}`}
                    waypoints={p.pts}
                    color={p.src.color}
                    power={p.kw}
                    dotCount={Math.max(1, Math.min(3, Math.round(p.kw * 0.8)))}
                />
            ))}
            {topSlots.map((id, i) => renderBracketNode(id, 'top', i, topSlots.length))}
            {botSlots.map((id, i) => renderBracketNode(id, 'bot', i, botSlots.length))}
            {showEvTooltip && evTooltipContent && (
                <foreignObject x={100} y={20} width={200} height={140} style={{ overflow: 'visible' }}>
                    <div style={{ display: 'flex', justifyContent: 'center' }}>{evTooltipContent}</div>
                </foreignObject>
            )}
        </svg>
    )
}
