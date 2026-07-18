import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SettingsSearch } from './SettingsSearch'
import { search } from './index'

// "soc" matches all three result kinds: SoC fields, guide bodies, and the
// SoC glossary term — which is what the traversal test needs.
const QUERY = 'soc'

function openSearch() {
    const onJumpToField = vi.fn()
    render(<SettingsSearch advancedMode={true} config={null} onJumpToField={onJumpToField} />)
    const input = screen.getByLabelText('Search settings and guides')
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: QUERY } })
    return { input, onJumpToField }
}

describe('SettingsSearch panel', () => {
    it('renders all three result sections for a query matching each kind', () => {
        openSearch()
        expect(screen.getByText('Settings')).toBeTruthy()
        expect(screen.getByText('Guides')).toBeTruthy()
        expect(screen.getByText('Glossary')).toBeTruthy()
    })

    it('arrow keys traverse fields → guides → glossary and Enter opens the glossary entry', () => {
        const { input } = openSearch()
        const { fields, guides: guideResults, glossary } = search(QUERY)
        expect(glossary.length).toBeGreaterThan(0)

        // Walk the highlight from the first field result down to the first
        // glossary result, then select it.
        const stepsToFirstGlossaryItem = fields.length + guideResults.length
        for (let i = 0; i < stepsToFirstGlossaryItem; i++) {
            fireEvent.keyDown(input, { key: 'ArrowDown' })
        }
        fireEvent.keyDown(input, { key: 'Enter' })

        // The viewer modal shows the entry's full definition (the results
        // panel only ever shows a clamped snippet inside a button).
        expect(screen.getByText(glossary[0].entry.definition)).toBeTruthy()
    })
})
