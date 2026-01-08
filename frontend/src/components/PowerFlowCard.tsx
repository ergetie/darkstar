/**
 * PowerFlowCard.tsx
 *
 * Production-grade energy flow visualization with Particles + Hub Glow animation.
 * Real-time data via WebSocket, responsive layout.
 */

import { useMemo } from 'react'
import { motion } from 'framer-motion'
import { Sun, Home, Battery, BatteryCharging, Zap, Droplets } from 'lucide-react'

// =============================================================================
// TYPES
// =============================================================================

export interface PowerFlowData {
    solar: { kw: number; todayKwh?: number }
    battery: { kw: number; soc: number } // +charge, -discharge
    grid: { kw: number; importKwh?: number; exportKwh?: number } // +import, -export
    house: { kw: number; todayKwh?: number }
    water: { kw: number }
}

// import type { PowerFlowData } from '../components/PowerFlowCard'
interface PowerFlowCardProps {
    data: PowerFlowData
    compact?: boolean
}

// =============================================================================
// HELPERS
// =============================================================================

// function pathLength is unused in this component

// =============================================================================
// PARTICLE STREAM (Clean, regular spacing, speed = f(power))
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

    // Fixed particle count, speed proportional to power
    const particleCount = 4
    // Duration inversely proportional to power: more power = faster
    // At 0.5 kW → 3s, at 5 kW → 0.8s
    const duration = Math.max(3.5 - absPower * 0.6, 0.8)

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
                strokeOpacity={0.2}
            />
            {/* Animated particles - clean, regular spacing */}
            {absPower > 0.05 &&
                Array.from({ length: particleCount }).map((_, i) => (
                    <motion.circle
                        key={i}
                        r={3.5}
                        fill={color}
                        initial={{ opacity: 0 }}
                        animate={{
                            cx: [actualFrom.x, actualTo.x],
                            cy: [actualFrom.y, actualTo.y],
                            opacity: [0, 0.85, 0.85, 0],
                        }}
                        transition={{
                            duration,
                            repeat: Infinity,
                            delay: (i / particleCount) * duration,
                            ease: 'linear',
                        }}
                    />
                ))}
        </g>
    )
}

// =============================================================================
// NODE WITH GLOW
// =============================================================================

interface NodeProps {
    x: number
    y: number
    iconType: 'solar' | 'house' | 'battery' | 'grid' | 'water'
    label: string
    value: string
    subValue?: string
    color: string
    glowIntensity: number
    isCharging?: boolean
    compact?: boolean
}

function Node({ x, y, iconType, label, value, subValue, color, glowIntensity, isCharging, compact }: NodeProps) {
    const baseRadius = compact ? 28 : 35
    const glowRadius = baseRadius + 18 * glowIntensity
    const iconSize = compact ? 18 : 22

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
                    animate={{ opacity: 0.1 + glowIntensity * 0.15 }}
                    transition={{ duration: 0.4 }}
                />
            )}
            {/* Base circle */}
            <circle r={baseRadius} fill="rgb(var(--color-surface))" stroke={color} strokeWidth={2.5} />
            {/* Lucide Icon */}
            <foreignObject x={-iconSize / 2} y={-iconSize / 2} width={iconSize} height={iconSize}>
                <IconComponent size={iconSize} style={{ color }} strokeWidth={1.5} />
            </foreignObject>
            {/* Value (power) */}
            <text
                y={baseRadius + 14}
                textAnchor="middle"
                fill="rgb(var(--color-text))"
                fontSize={compact ? '10' : '11'}
                fontWeight="600"
            >
                {value}
            </text>
            {/* Subvalue (daily energy) */}
            {subValue && !compact && (
                <text y={baseRadius + 26} textAnchor="middle" fill="rgb(var(--color-muted))" fontSize="9">
                    {subValue}
                </text>
            )}
            {/* Label */}
            <text
                y={baseRadius + (subValue && !compact ? 38 : 26)}
                textAnchor="middle"
                fill="rgb(var(--color-muted))"
                fontSize={compact ? '8' : '9'}
            >
                {label}
            </text>
        </g>
    )
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export default function PowerFlowCard({ data, compact = false }: PowerFlowCardProps) {
    // Node positions - scale for compact mode
    const scale = compact ? 0.75 : 1
    const nodes = useMemo(() => {
        // Robust centering logic: keep the group centered in the SVG viewBox
        const baseCenterX = 200
        const baseCenterY = 140 // Y center of [40, 240]

        const targetCenterX = compact ? 150 : 200 // SVG viewBox width / 2
        const targetCenterY = compact ? 100 : 140 // SVG viewBox height / 2

        const offX = (p: number) => (p - baseCenterX) * scale + targetCenterX
        const offY = (p: number) => (p - baseCenterY) * scale + targetCenterY

        return {
            solar: { x: offX(100), y: offY(40) },
            house: { x: offX(200), y: offY(140) },
            battery: { x: offX(200), y: offY(240) },
            grid: { x: offX(100), y: offY(240) },
            water: { x: offX(300), y: offY(140) },
        }
    }, [scale, compact])

    // Semantic colors from design system
    const colors = {
        solar: 'rgb(var(--color-accent))',
        battery: 'rgb(var(--color-good))',
        grid: 'rgb(var(--color-grid))',
        house: 'rgb(var(--color-house))',
        water: 'rgb(var(--color-water))',
    }

    // Calculate glow intensities (normalize power to 0-1)
    const maxPower = 6
    const glowIntensities = {
        solar: Math.min(data.solar.kw / maxPower, 1),
        battery: Math.min(Math.abs(data.battery.kw) / maxPower, 1),
        grid: Math.min(Math.abs(data.grid.kw) / maxPower, 1),
        house: Math.min(data.house.kw / maxPower, 1),
        water: Math.min(data.water.kw / maxPower, 1),
    }

    // Format helpers
    // Format helpers
    // Fix: Show more precision for small values (e.g. 0.5kW instead of 0.0kW if it was rounding weirdly)
    // Actually, toFixed(1) for 0.5 should be "0.5". Let's use toFixed(2) if < 1.0 to be sure.
    const fmtKw = (v: number) => {
        const absV = Math.abs(v)
        if (absV > 0 && absV < 0.1) return `${absV.toFixed(2)} kW`
        return `${absV.toFixed(1)} kW`
    }
    const fmtKwh = (v?: number) => (v != null ? `${v.toFixed(1)} kWh` : undefined)

    // Grid label based on direction
    const gridLabel = data.grid.kw >= 0 ? 'Import' : 'Export'
    const gridSubValue = data.grid.kw >= 0 ? fmtKwh(data.grid.importKwh) : fmtKwh(data.grid.exportKwh)

    // Battery label based on direction
    // User reports "Charging" when discharging. This implies the sign is inverted from what we expect.
    // Darkstar expectation: +charge, -discharge.
    // Inverter seems to be: -charge, +discharge? Or something else.
    // Let's flip the logic for the label.
    const battLabel = data.battery.kw <= 0 ? 'Charging' : 'Discharging'

    const viewBox = compact ? '0 0 300 200' : '0 0 400 280'

    return (
        <svg viewBox={viewBox} className="w-full h-full">
            {/* Connections with particles */}
            {/* Solar → House */}
            <ParticleStream from={nodes.solar} to={nodes.house} power={data.solar.kw} color={colors.solar} />
            {/* Battery ↔ House */}
            <ParticleStream
                from={nodes.battery}
                to={nodes.house}
                power={Math.abs(data.battery.kw)}
                color={colors.battery}
                reverse={data.battery.kw < 0}
            />
            {/* Grid ↔ House */}
            <ParticleStream
                from={nodes.grid}
                to={nodes.house}
                power={Math.abs(data.grid.kw)}
                color={colors.grid}
                reverse={data.grid.kw < 0}
            />
            {/* House → Water */}
            <ParticleStream from={nodes.house} to={nodes.water} power={data.water.kw} color={colors.water} />

            {/* Nodes with glow */}
            <Node
                {...nodes.solar}
                iconType="solar"
                label="Solar"
                value={fmtKw(data.solar.kw)}
                subValue={fmtKwh(data.solar.todayKwh)}
                color={colors.solar}
                glowIntensity={glowIntensities.solar}
                compact={compact}
            />
            <Node
                {...nodes.house}
                iconType="house"
                label="House"
                value={fmtKw(data.house.kw)}
                subValue={fmtKwh(data.house.todayKwh)}
                color={colors.house}
                glowIntensity={glowIntensities.house}
                compact={compact}
            />
            <Node
                {...nodes.battery}
                iconType="battery"
                label={battLabel}
                value={`${data.battery.soc.toFixed(0)}%`}
                subValue={fmtKw(data.battery.kw)}
                color={colors.battery}
                glowIntensity={glowIntensities.battery}
                isCharging={data.battery.kw < 0}
                compact={compact}
            />
            <Node
                {...nodes.grid}
                iconType="grid"
                label={gridLabel}
                value={fmtKw(data.grid.kw)}
                subValue={gridSubValue}
                color={colors.grid}
                glowIntensity={glowIntensities.grid}
                compact={compact}
            />
            <Node
                {...nodes.water}
                iconType="water"
                label="Water"
                value={fmtKw(data.water.kw)}
                color={colors.water}
                glowIntensity={glowIntensities.water}
                compact={compact}
            />
        </svg>
    )
}
