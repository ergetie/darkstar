import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import PowerFlowCard from './PowerFlowCard'
import type { PowerFlowData } from './PowerFlowRegistry'

const config = { system: { has_ev_charger: true } } as never

function renderWithEv(ev: NonNullable<PowerFlowData['evChargers']>[number]) {
    const data: PowerFlowData = {
        solar: { kw: 0 },
        battery: { kw: 0, soc: 50 },
        grid: { kw: 0 },
        house: { kw: 1 },
        water: { kw: 0 },
        ev: { kw: ev.kw },
        evChargers: [ev],
    }
    render(<PowerFlowCard data={data} systemConfig={config} />)
    const sub = screen.getByTestId('ev-node-sub')
    return { sub, icon: sub.querySelector('svg')! }
}

describe('PowerFlowCard EV node icon colour', () => {
    it('plugged in and idle: green plug', () => {
        const { sub, icon } = renderWithEv({ id: 'ev1', name: 'Car', kw: 0, soc: 49, pluggedIn: true })
        expect(sub).toHaveAttribute('data-ev-state', 'plugged')
        expect(icon).toHaveAttribute('stroke', 'rgb(var(--color-good))')
        expect(sub.closest('g[opacity]')).toHaveAttribute('opacity', '1')
    })

    it('charging: EV violet lightning', () => {
        const { icon } = renderWithEv({ id: 'ev1', name: 'Car', kw: 7.2, soc: 49, pluggedIn: true })
        expect(icon).toHaveAttribute('stroke', 'rgb(var(--color-ai))')
    })

    it('away: muted', () => {
        const { icon } = renderWithEv({ id: 'ev1', name: 'Car', kw: 0, soc: null, pluggedIn: false })
        expect(icon).toHaveAttribute('stroke', 'rgb(var(--color-muted))')
        expect(screen.getByTestId('ev-node-sub').closest('g[opacity]')).toHaveAttribute('opacity', '0.45')
    })
})
