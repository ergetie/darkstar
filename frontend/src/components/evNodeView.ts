/**
 * What the power-flow EV node shows (powerflow-ev-node spec).
 *
 * Single charger: lightning + "SoC → target%" while charging, plug + "SoC%"
 * when plugged in and idle, unplug + "away" (muted) when not connected.
 * Multiple chargers: aggregate icon + "N connected"; per-car details stay in
 * the node's popup.
 */

import { Plug, Unplug, Zap } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { EVChargerState } from '../lib/api'

/** Live per-charger reading as held by the dashboard. */
export interface EvLiveReading {
    id?: string
    name: string
    kw: number
    soc: number | null
    pluggedIn: boolean
}

/** The slice of GET /api/ev/chargers the node needs. */
export type EvChargerStatus = Pick<EVChargerState, 'id' | 'name' | 'target_soc_percent' | 'manual_charge'>

export type EvNodeState = 'charging' | 'plugged' | 'unplugged'

export interface EvNodeView {
    state: EvNodeState
    icon: LucideIcon
    text: string
    muted: boolean
}

/** Charger power above which a car counts as charging. */
export const EV_CHARGING_KW = 0.1

const ICONS: Record<EvNodeState, LucideIcon> = { charging: Zap, plugged: Plug, unplugged: Unplug }

const fmtSoc = (soc: number | null | undefined) => (soc != null ? `${soc.toFixed(0)}%` : '--%')

function stateOf(ev: EvLiveReading): EvNodeState {
    if (ev.kw > EV_CHARGING_KW) return 'charging'
    return ev.pluggedIn ? 'plugged' : 'unplugged'
}

function statusFor(ev: EvLiveReading, statuses: EvChargerStatus[]): EvChargerStatus | undefined {
    return ev.id != null ? statuses.find((s) => s.id === ev.id) : statuses.find((s) => s.name === ev.name)
}

/** Manual charge target first, then the goal target, else none. */
export function evTargetSoc(status: EvChargerStatus | undefined): number | null {
    return status?.manual_charge?.target_soc ?? status?.target_soc_percent ?? null
}

export function deriveEvNodeView(
    evChargers: EvLiveReading[] | undefined,
    chargerStatuses: EvChargerStatus[] = [],
): EvNodeView | null {
    if (!evChargers || evChargers.length === 0) return null

    if (evChargers.length === 1) {
        const ev = evChargers[0]
        const state = stateOf(ev)
        if (state === 'unplugged') return { state, icon: ICONS[state], text: 'away', muted: true }
        const target = state === 'charging' ? evTargetSoc(statusFor(ev, chargerStatuses)) : null
        const text = target != null ? `${fmtSoc(ev.soc)} → ${target.toFixed(0)}%` : fmtSoc(ev.soc)
        return { state, icon: ICONS[state], text, muted: false }
    }

    const states = evChargers.map(stateOf)
    const state: EvNodeState = states.includes('charging')
        ? 'charging'
        : states.includes('plugged')
          ? 'plugged'
          : 'unplugged'
    const connected = states.filter((s) => s !== 'unplugged').length
    return { state, icon: ICONS[state], text: `${connected} connected`, muted: state === 'unplugged' }
}
