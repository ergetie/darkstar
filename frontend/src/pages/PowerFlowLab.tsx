/**
 * PowerFlowLab.tsx
 *
 * Test page for evaluating different energy flow animation styles.
 * Updated with user feedback: cleaner particles, hub glow + flow, and 5 new alternatives.
 */

import { useState, useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import Card from '../components/Card'
import { Sun, Home, Battery, BatteryCharging, Zap, Droplets } from 'lucide-react'

// Types
interface FlowData {
    solar: number // kW (positive = producing)
    battery: number // kW (positive = charging, negative = discharging)
    grid: number // kW (positive = importing, negative = exporting)
    house: number // kW (always positive = consuming)
    water: number // kW (always positive = heating)
    batterySOC: number // 0-100%
}

type AnimationStyle = 'particles' | 'glow-flow' | 'dash-flow' | 'arrows' | 'thickness' | 'heat-trail' | 'ping'

// Mock data for demo
const createMockData = (preset: string): FlowData => {
    switch (preset) {
        case 'sunny':
            return { solar: 4.2, battery: 1.5, grid: -2.0, house: 2.5, water: 0.3, batterySOC: 75 }
        case 'evening':
            return { solar: 0.0, battery: -2.8, grid: 0.5, house: 3.1, water: 0.2, batterySOC: 45 }
        case 'charging':
            return { solar: 0.5, battery: 3.0, grid: 2.5, house: 1.0, water: 0.0, batterySOC: 30 }
        case 'exporting':
            return { solar: 6.0, battery: 0.5, grid: -4.5, house: 1.5, water: 0.5, batterySOC: 95 }
        default:
            return { solar: 2.0, battery: 0.0, grid: 0.5, house: 2.5, water: 0.0, batterySOC: 60 }
    }
}

// =============================================================================
// SHARED: Calculate path length
// =============================================================================
function pathLength(from: { x: number; y: number }, to: { x: number; y: number }): number {
    const dx = to.x - from.x
    const dy = to.y - from.y
    return Math.sqrt(dx * dx + dy * dy)
}

// =============================================================================
// OPTION 1: PARTICLE STREAMS (Improved - no glow, regular spacing, always show line)
// =============================================================================

interface ParticleStreamProps {
    from: { x: number; y: number }
    to: { x: number; y: number }
    power: number
    color: string
    reverse?: boolean
}

function ParticleStream({ from, to, power, color, reverse }: ParticleStreamProps) {
    const absPower = Math.abs(power)
    const actualFrom = reverse ? to : from
    const actualTo = reverse ? from : to

    // Fixed particle count, speed based on power
    const particleCount = 4
    const duration = Math.max(3 - absPower * 0.4, 0.8)

    return (
        <g>
            {/* Always visible base line */}
            <line
                x1={actualFrom.x}
                y1={actualFrom.y}
                x2={actualTo.x}
                y2={actualTo.y}
                stroke={color}
                strokeWidth={2}
                strokeOpacity={0.25}
            />
            {/* Animated particles - no glow, regular spacing */}
            {absPower > 0.1 &&
                Array.from({ length: particleCount }).map((_, i) => (
                    <motion.circle
                        key={i}
                        r={4}
                        fill={color}
                        initial={{ opacity: 0 }}
                        animate={{
                            cx: [actualFrom.x, actualTo.x],
                            cy: [actualFrom.y, actualTo.y],
                            opacity: [0, 0.9, 0.9, 0],
                        }}
                        transition={{
                            duration,
                            repeat: Infinity,
                            delay: (i / particleCount) * duration, // Regular spacing
                            ease: 'linear',
                        }}
                    />
                ))}
        </g>
    )
}

// =============================================================================
// OPTION 2: HUB GLOW + DASH FLOW (Combined - glow on nodes, animated dashes)
// =============================================================================

interface GlowFlowProps {
    from: { x: number; y: number }
    to: { x: number; y: number }
    power: number
    color: string
    id: string
    reverse?: boolean
}

function GlowFlow({ from, to, power, color, reverse }: GlowFlowProps) {
    const absPower = Math.abs(power)
    const actualFrom = reverse ? to : from
    const actualTo = reverse ? from : to
    const length = pathLength(actualFrom, actualTo)
    const duration = Math.max(2 - absPower * 0.3, 0.6)

    return (
        <g>
            {/* Base line */}
            <line
                x1={actualFrom.x}
                y1={actualFrom.y}
                x2={actualTo.x}
                y2={actualTo.y}
                stroke={color}
                strokeWidth={2}
                strokeOpacity={0.2}
            />
            {/* Animated dashes */}
            {absPower > 0.1 && (
                <motion.line
                    x1={actualFrom.x}
                    y1={actualFrom.y}
                    x2={actualTo.x}
                    y2={actualTo.y}
                    stroke={color}
                    strokeWidth={3}
                    strokeOpacity={0.7}
                    strokeDasharray="8 12"
                    initial={{ strokeDashoffset: 0 }}
                    animate={{ strokeDashoffset: -length }}
                    transition={{ duration, repeat: Infinity, ease: 'linear' }}
                />
            )}
        </g>
    )
}

// =============================================================================
// OPTION 3: DASH FLOW (Simple animated dashes)
// =============================================================================

function DashFlow({ from, to, power, color, reverse }: ParticleStreamProps) {
    const absPower = Math.abs(power)
    const actualFrom = reverse ? to : from
    const actualTo = reverse ? from : to
    const length = pathLength(actualFrom, actualTo)
    const duration = Math.max(2.5 - absPower * 0.4, 0.8)

    return (
        <g>
            {/* Base line */}
            <line
                x1={actualFrom.x}
                y1={actualFrom.y}
                x2={actualTo.x}
                y2={actualTo.y}
                stroke={color}
                strokeWidth={2}
                strokeOpacity={0.15}
            />
            {/* Animated dashes */}
            {absPower > 0.1 && (
                <motion.line
                    x1={actualFrom.x}
                    y1={actualFrom.y}
                    x2={actualTo.x}
                    y2={actualTo.y}
                    stroke={color}
                    strokeWidth={4}
                    strokeOpacity={0.8}
                    strokeLinecap="round"
                    strokeDasharray="6 14"
                    initial={{ strokeDashoffset: 0 }}
                    animate={{ strokeDashoffset: -length }}
                    transition={{ duration, repeat: Infinity, ease: 'linear' }}
                />
            )}
        </g>
    )
}

// =============================================================================
// OPTION 4: ARROW MARKERS (Chevrons traveling along path)
// =============================================================================

function ArrowFlow({ from, to, power, color, reverse }: ParticleStreamProps) {
    const absPower = Math.abs(power)
    const actualFrom = reverse ? to : from
    const actualTo = reverse ? from : to
    const duration = Math.max(2 - absPower * 0.3, 0.6)

    // Calculate angle for arrow rotation
    const dx = actualTo.x - actualFrom.x
    const dy = actualTo.y - actualFrom.y
    const angle = (Math.atan2(dy, dx) * 180) / Math.PI

    const arrowCount = 3

    return (
        <g>
            {/* Base line */}
            <line
                x1={actualFrom.x}
                y1={actualFrom.y}
                x2={actualTo.x}
                y2={actualTo.y}
                stroke={color}
                strokeWidth={2}
                strokeOpacity={0.2}
            />
            {/* Animated arrows */}
            {absPower > 0.1 &&
                Array.from({ length: arrowCount }).map((_, i) => (
                    <motion.g
                        key={i}
                        initial={{ opacity: 0 }}
                        animate={{
                            x: [actualFrom.x, actualTo.x],
                            y: [actualFrom.y, actualTo.y],
                            opacity: [0, 1, 1, 0],
                        }}
                        transition={{
                            duration,
                            repeat: Infinity,
                            delay: (i / arrowCount) * duration,
                            ease: 'linear',
                        }}
                    >
                        <polygon points="-6,-4 0,0 -6,4" fill={color} transform={`rotate(${angle})`} />
                    </motion.g>
                ))}
        </g>
    )
}

// =============================================================================
// OPTION 5: THICKNESS PULSE (Line breathes based on power)
// =============================================================================

function ThicknessPulse({ from, to, power, color, reverse }: ParticleStreamProps) {
    const absPower = Math.abs(power)
    const actualFrom = reverse ? to : from
    const actualTo = reverse ? from : to
    const baseWidth = 2
    const maxWidth = 2 + absPower * 2

    return (
        <g>
            {/* Pulsing line */}
            <motion.line
                x1={actualFrom.x}
                y1={actualFrom.y}
                x2={actualTo.x}
                y2={actualTo.y}
                stroke={color}
                strokeLinecap="round"
                initial={{ strokeWidth: baseWidth, strokeOpacity: 0.3 }}
                animate={
                    absPower > 0.1
                        ? {
                              strokeWidth: [baseWidth, maxWidth, baseWidth],
                              strokeOpacity: [0.3, 0.7, 0.3],
                          }
                        : { strokeWidth: baseWidth, strokeOpacity: 0.2 }
                }
                transition={{ duration: 1.5, repeat: Infinity, ease: 'easeInOut' }}
            />
        </g>
    )
}

// =============================================================================
// OPTION 6: HEAT TRAIL (Gradient fills from source to destination)
// =============================================================================

function HeatTrail({ from, to, power, color, id, reverse }: GlowFlowProps) {
    const absPower = Math.abs(power)
    const actualFrom = reverse ? to : from
    const actualTo = reverse ? from : to
    const duration = Math.max(2.5 - absPower * 0.4, 1)

    return (
        <g>
            <defs>
                <linearGradient
                    id={`heat-${id}`}
                    gradientUnits="userSpaceOnUse"
                    x1={actualFrom.x}
                    y1={actualFrom.y}
                    x2={actualTo.x}
                    y2={actualTo.y}
                >
                    <motion.stop
                        offset="0%"
                        stopColor={color}
                        initial={{ stopOpacity: 0.8 }}
                        animate={{ stopOpacity: [0.8, 0.2, 0.8] }}
                        transition={{ duration, repeat: Infinity }}
                    />
                    <motion.stop
                        offset="100%"
                        stopColor={color}
                        initial={{ stopOpacity: 0.1 }}
                        animate={{ stopOpacity: [0.1, 0.6, 0.1] }}
                        transition={{ duration, repeat: Infinity, delay: duration * 0.5 }}
                    />
                </linearGradient>
            </defs>
            {/* Heat trail line */}
            <line
                x1={actualFrom.x}
                y1={actualFrom.y}
                x2={actualTo.x}
                y2={actualTo.y}
                stroke={absPower > 0.1 ? `url(#heat-${id})` : color}
                strokeWidth={4 + absPower}
                strokeOpacity={absPower > 0.1 ? 1 : 0.15}
                strokeLinecap="round"
            />
        </g>
    )
}

// =============================================================================
// OPTION 7: PING/RIPPLE (Circles emanate from source)
// =============================================================================

function PingFlow({ from, to, power, color, reverse }: ParticleStreamProps) {
    const absPower = Math.abs(power)
    const actualFrom = reverse ? to : from
    const actualTo = reverse ? from : to
    const duration = Math.max(2 - absPower * 0.25, 0.8)

    // Calculate midpoint and direction
    const midX = (actualFrom.x + actualTo.x) / 2
    const midY = (actualFrom.y + actualTo.y) / 2

    return (
        <g>
            {/* Base line */}
            <line
                x1={actualFrom.x}
                y1={actualFrom.y}
                x2={actualTo.x}
                y2={actualTo.y}
                stroke={color}
                strokeWidth={2}
                strokeOpacity={0.2}
            />
            {/* Ping circles from source */}
            {absPower > 0.1 && (
                <>
                    <motion.circle
                        cx={actualFrom.x}
                        cy={actualFrom.y}
                        fill="none"
                        stroke={color}
                        strokeWidth={2}
                        initial={{ r: 5, opacity: 0.8 }}
                        animate={{ r: 25, opacity: 0 }}
                        transition={{ duration: duration * 0.8, repeat: Infinity }}
                    />
                    <motion.circle
                        cx={midX}
                        cy={midY}
                        fill="none"
                        stroke={color}
                        strokeWidth={2}
                        initial={{ r: 5, opacity: 0.6 }}
                        animate={{ r: 20, opacity: 0 }}
                        transition={{ duration: duration * 0.8, repeat: Infinity, delay: duration * 0.4 }}
                    />
                </>
            )}
        </g>
    )
}

// =============================================================================
// NODE COMPONENT (With Lucide icons)
// =============================================================================

interface NodeProps {
    x: number
    y: number
    iconType: 'solar' | 'house' | 'battery' | 'grid' | 'water'
    label: string
    value: string
    color: string
    glowIntensity?: number
    isCharging?: boolean
}

function Node({ x, y, iconType, label, value, color, glowIntensity = 0, isCharging }: NodeProps) {
    const baseRadius = 35
    const glowRadius = baseRadius + 20 * glowIntensity

    const IconComponent = {
        solar: Sun,
        house: Home,
        battery: isCharging ? BatteryCharging : Battery,
        grid: Zap,
        water: Droplets,
    }[iconType]

    return (
        <g transform={`translate(${x}, ${y})`}>
            {/* Glow effect */}
            {glowIntensity > 0.1 && (
                <motion.circle
                    r={glowRadius}
                    fill={color}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 0.12 + glowIntensity * 0.15 }}
                    transition={{ duration: 0.3 }}
                />
            )}
            {/* Base circle */}
            <circle r={baseRadius} fill="rgb(var(--color-surface))" stroke={color} strokeWidth={3} />
            {/* Lucide Icon */}
            <foreignObject x={-12} y={-12} width={24} height={24}>
                <IconComponent size={24} style={{ color }} strokeWidth={1.5} />
            </foreignObject>
            {/* Value */}
            <text y={55} textAnchor="middle" fill="rgb(var(--color-text))" fontSize="11" fontWeight="600">
                {value}
            </text>
            {/* Label */}
            <text y={70} textAnchor="middle" fill="rgb(var(--color-muted))" fontSize="9">
                {label}
            </text>
        </g>
    )
}

// =============================================================================
// POWER FLOW VISUALIZATION
// =============================================================================

interface PowerFlowVisualizationProps {
    data: FlowData
    style: AnimationStyle
}

function PowerFlowVisualization({ data, style }: PowerFlowVisualizationProps) {
    const nodes = {
        solar: { x: 100, y: 60 },
        house: { x: 200, y: 150 },
        battery: { x: 200, y: 260 },
        grid: { x: 100, y: 260 },
        water: { x: 300, y: 150 },
    }

    const colors = {
        solar: 'rgb(var(--color-accent))',
        battery: 'rgb(var(--color-good))',
        grid: 'rgb(var(--color-grid))',
        house: 'rgb(var(--color-house))',
        water: 'rgb(var(--color-water))',
    }

    const maxPower = 6
    const glowIntensities = {
        solar: Math.min(data.solar / maxPower, 1),
        battery: Math.min(Math.abs(data.battery) / maxPower, 1),
        grid: Math.min(Math.abs(data.grid) / maxPower, 1),
        house: Math.min(data.house / maxPower, 1),
        water: Math.min(data.water / maxPower, 1),
    }

    // Connection renderer based on style
    const renderConnection = (
        id: string,
        from: { x: number; y: number },
        to: { x: number; y: number },
        power: number,
        color: string,
        reverse?: boolean,
    ) => {
        if (Math.abs(power) < 0.1) {
            // Still show faint line for inactive connections
            return (
                <line
                    key={id}
                    x1={from.x}
                    y1={from.y}
                    x2={to.x}
                    y2={to.y}
                    stroke={color}
                    strokeWidth={1}
                    strokeOpacity={0.1}
                />
            )
        }

        switch (style) {
            case 'particles':
                return <ParticleStream key={id} from={from} to={to} power={power} color={color} reverse={reverse} />
            case 'glow-flow':
                return <GlowFlow key={id} id={id} from={from} to={to} power={power} color={color} reverse={reverse} />
            case 'dash-flow':
                return <DashFlow key={id} from={from} to={to} power={power} color={color} reverse={reverse} />
            case 'arrows':
                return <ArrowFlow key={id} from={from} to={to} power={power} color={color} reverse={reverse} />
            case 'thickness':
                return <ThicknessPulse key={id} from={from} to={to} power={power} color={color} reverse={reverse} />
            case 'heat-trail':
                return <HeatTrail key={id} id={id} from={from} to={to} power={power} color={color} reverse={reverse} />
            case 'ping':
                return <PingFlow key={id} from={from} to={to} power={power} color={color} reverse={reverse} />
        }
    }

    return (
        <svg viewBox="0 0 400 320" className="w-full max-w-lg mx-auto">
            {/* Connections */}
            {renderConnection('solar-house', nodes.solar, nodes.house, data.solar, colors.solar, false)}
            {renderConnection(
                'battery-house',
                nodes.battery,
                nodes.house,
                Math.abs(data.battery),
                colors.battery,
                data.battery > 0,
            )}
            {renderConnection('grid-house', nodes.grid, nodes.house, Math.abs(data.grid), colors.grid, data.grid < 0)}
            {renderConnection('house-water', nodes.house, nodes.water, data.water, colors.water, false)}

            {/* Nodes */}
            <Node
                {...nodes.solar}
                iconType="solar"
                label="Solar"
                value={`${data.solar.toFixed(1)} kW`}
                color={colors.solar}
                glowIntensity={style === 'glow-flow' ? glowIntensities.solar : 0}
            />
            <Node
                {...nodes.house}
                iconType="house"
                label="House"
                value={`${data.house.toFixed(1)} kW`}
                color={colors.house}
                glowIntensity={style === 'glow-flow' ? glowIntensities.house : 0}
            />
            <Node
                {...nodes.battery}
                iconType="battery"
                label={data.battery >= 0 ? 'Charging' : 'Discharging'}
                value={`${data.batterySOC}%`}
                color={colors.battery}
                glowIntensity={style === 'glow-flow' ? glowIntensities.battery : 0}
                isCharging={data.battery > 0}
            />
            <Node
                {...nodes.grid}
                iconType="grid"
                label={data.grid >= 0 ? 'Import' : 'Export'}
                value={`${Math.abs(data.grid).toFixed(1)} kW`}
                color={colors.grid}
                glowIntensity={style === 'glow-flow' ? glowIntensities.grid : 0}
            />
            <Node
                {...nodes.water}
                iconType="water"
                label="Water"
                value={`${data.water.toFixed(1)} kW`}
                color={colors.water}
                glowIntensity={style === 'glow-flow' ? glowIntensities.water : 0}
            />
        </svg>
    )
}

// =============================================================================
// MAIN PAGE COMPONENT
// =============================================================================

export default function PowerFlowLab() {
    const [activeStyle, setActiveStyle] = useState<AnimationStyle>('particles')
    const [preset, setPreset] = useState('sunny')
    const [customData, setCustomData] = useState<FlowData | null>(null)

    const flowData = useMemo(() => {
        return customData ?? createMockData(preset)
    }, [customData, preset])

    const styleOptions: { id: AnimationStyle; label: string; description: string }[] = [
        { id: 'particles', label: '1. Particles', description: 'Clean dots, regular spacing' },
        { id: 'glow-flow', label: '2. Glow + Dash', description: 'Hub glow + animated dashes' },
        { id: 'dash-flow', label: '3. Dash Flow', description: 'Simple animated dashes' },
        { id: 'arrows', label: '4. Arrows', description: 'Chevrons traveling along path' },
        { id: 'thickness', label: '5. Thickness', description: 'Line breathes with power' },
        { id: 'heat-trail', label: '6. Heat Trail', description: 'Gradient fills like liquid' },
        { id: 'ping', label: '7. Ping', description: 'Ripples from source nodes' },
    ]

    const presets = [
        { id: 'sunny', label: '☀️ Sunny' },
        { id: 'evening', label: '🌙 Evening' },
        { id: 'charging', label: '🔋 Charging' },
        { id: 'exporting', label: '📤 Exporting' },
    ]

    const updateValue = (key: keyof FlowData, value: number) => {
        const base = customData ?? createMockData(preset)
        setCustomData({ ...base, [key]: value })
    }

    return (
        <div className="px-4 pt-16 pb-10 lg:px-8 lg:pt-10 space-y-6">
            {/* Header */}
            <div>
                <h1 className="text-lg font-medium text-text flex items-center gap-2">
                    ⚡ Power Flow Lab
                    <span className="px-2 py-0.5 rounded-full bg-accent/20 text-[10px] text-accent uppercase tracking-wider">
                        v2
                    </span>
                </h1>
                <p className="text-[11px] text-muted">Compare 7 animation styles • Lucide icons • Improved spacing</p>
            </div>

            {/* Style Selector - Grid for more options */}
            <Card className="p-4">
                <div className="text-[10px] uppercase font-bold text-muted tracking-wider mb-3">Animation Style</div>
                <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-2">
                    {styleOptions.map((opt) => (
                        <button
                            key={opt.id}
                            onClick={() => setActiveStyle(opt.id)}
                            className={`p-3 rounded-xl border transition-all text-left ${
                                activeStyle === opt.id
                                    ? 'border-accent bg-accent/10'
                                    : 'border-line/50 hover:border-line'
                            }`}
                        >
                            <div className="text-[11px] font-medium text-text">{opt.label}</div>
                            <div className="text-[9px] text-muted leading-tight">{opt.description}</div>
                        </button>
                    ))}
                </div>
            </Card>

            {/* Visualization */}
            <Card className="p-6">
                <AnimatePresence mode="wait">
                    <motion.div
                        key={activeStyle}
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.3 }}
                    >
                        <PowerFlowVisualization data={flowData} style={activeStyle} />
                    </motion.div>
                </AnimatePresence>
            </Card>

            {/* Controls */}
            <div className="grid lg:grid-cols-2 gap-4">
                {/* Presets */}
                <Card className="p-4">
                    <div className="text-[10px] uppercase font-bold text-muted tracking-wider mb-3">Presets</div>
                    <div className="grid grid-cols-4 gap-2">
                        {presets.map((p) => (
                            <button
                                key={p.id}
                                onClick={() => {
                                    setPreset(p.id)
                                    setCustomData(null)
                                }}
                                className={`px-3 py-2 rounded-lg border text-xs transition-all ${
                                    preset === p.id && !customData
                                        ? 'border-accent bg-accent/10 text-text'
                                        : 'border-line/50 text-muted hover:text-text'
                                }`}
                            >
                                {p.label}
                            </button>
                        ))}
                    </div>
                </Card>

                {/* Sliders */}
                <Card className="p-4">
                    <div className="text-[10px] uppercase font-bold text-muted tracking-wider mb-3">Custom Values</div>
                    <div className="space-y-3">
                        {[
                            { key: 'solar', label: 'Solar', min: 0, max: 8 },
                            { key: 'battery', label: 'Battery', min: -5, max: 5 },
                            { key: 'grid', label: 'Grid', min: -6, max: 6 },
                            { key: 'house', label: 'House', min: 0, max: 6 },
                            { key: 'water', label: 'Water', min: 0, max: 3 },
                        ].map((s) => (
                            <div key={s.key} className="flex items-center gap-3">
                                <span className="text-xs text-muted w-14">{s.label}</span>
                                <input
                                    type="range"
                                    min={s.min}
                                    max={s.max}
                                    step={0.1}
                                    value={flowData[s.key as keyof FlowData]}
                                    onChange={(e) => updateValue(s.key as keyof FlowData, parseFloat(e.target.value))}
                                    className="flex-1 h-1 bg-line rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-accent [&::-webkit-slider-thumb]:rounded-full"
                                />
                                <span className="text-xs text-text w-16 text-right">
                                    {flowData[s.key as keyof FlowData].toFixed(1)} kW
                                </span>
                            </div>
                        ))}
                    </div>
                </Card>
            </div>
        </div>
    )
}
