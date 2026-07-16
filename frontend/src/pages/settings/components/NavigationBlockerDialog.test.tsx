import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { NavigationBlockerDialog } from './NavigationBlockerDialog'

describe('NavigationBlockerDialog', () => {
    it('renders nothing when not visible', () => {
        render(<NavigationBlockerDialog visible={false} onStay={vi.fn()} onLeave={vi.fn()} />)
        expect(screen.queryByText('Unsaved Changes')).not.toBeInTheDocument()
    })

    it("renders exactly today's dialog when changes is omitted", () => {
        render(<NavigationBlockerDialog visible onStay={vi.fn()} onLeave={vi.fn()} />)
        expect(screen.getByText('Unsaved Changes')).toBeInTheDocument()
        expect(screen.queryByText(/→/)).not.toBeInTheDocument()
    })

    it("renders exactly today's dialog when changes is empty", () => {
        render(<NavigationBlockerDialog visible onStay={vi.fn()} onLeave={vi.fn()} changes={[]} />)
        expect(screen.getByText('Unsaved Changes')).toBeInTheDocument()
        expect(screen.queryByText(/→/)).not.toBeInTheDocument()
    })

    it('lists changed fields with their old and new values', () => {
        render(
            <NavigationBlockerDialog
                visible
                onStay={vi.fn()}
                onLeave={vi.fn()}
                changes={[
                    { key: 'a', label: 'Field A', oldValue: '10', newValue: '20' },
                    { key: 'b', label: 'Field B', oldValue: 'off', newValue: 'on' },
                ]}
            />,
        )
        expect(screen.getByText('Field A')).toBeInTheDocument()
        expect(screen.getByText('10 → 20')).toBeInTheDocument()
        expect(screen.getByText('Field B')).toBeInTheDocument()
        expect(screen.getByText('off → on')).toBeInTheDocument()
    })

    it('keeps Stay/Discard buttons visible alongside a long changes list', () => {
        const changes = Array.from({ length: 20 }, (_, i) => ({
            key: `field-${i}`,
            label: `Field ${i}`,
            oldValue: 'old',
            newValue: 'new',
        }))
        render(<NavigationBlockerDialog visible onStay={vi.fn()} onLeave={vi.fn()} changes={changes} />)
        expect(screen.getAllByText('old → new')).toHaveLength(20)
        expect(screen.getByRole('button', { name: 'Stay' })).toBeInTheDocument()
        expect(screen.getByRole('button', { name: 'Discard & Leave' })).toBeInTheDocument()
    })
})
