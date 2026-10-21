import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { FuseCharacteristicGraph } from './FuseCharacteristicGraph'

describe('FuseCharacteristicGraph', () => {
    it('keeps technical details collapsed until requested', () => {
        render(<FuseCharacteristicGraph form={{}} />)
        const summary = screen.getByText('Technical details')
        const details = summary.closest('details')!
        expect(details).not.toHaveAttribute('open')
        fireEvent.click(summary)
        expect(details).toHaveAttribute('open')
        fireEvent.click(summary)
        expect(details).not.toHaveAttribute('open')
    })

    it('reacts to unsaved preset, safety and custom-point edits with accessible descriptions', () => {
        const { rerender, container } = render(<FuseCharacteristicGraph form={{}} />)
        expect(screen.getByRole('img')).toHaveAccessibleName(/Typ C fuse characteristics.*80%/)
        expect(screen.getByText(/approximately ±30%/)).toBeInTheDocument()
        const initial = container.querySelectorAll('path')[1].getAttribute('d')
        rerender(<FuseCharacteristicGraph form={{ 'load_balancing.fuse_preset': 'diazed_gg' }} />)
        expect(screen.getByRole('img')).toHaveAccessibleName(/Diazed gG fuse characteristics.*65%/)
        expect(container.querySelectorAll('path')[1].getAttribute('d')).not.toBe(initial)
        rerender(
            <FuseCharacteristicGraph
                form={{
                    'load_balancing.fuse_preset': 'custom',
                    'load_balancing.fuse_safety_percent': '70',
                    'load_balancing.fuse_custom_points':
                        '[{"overload_percent":150,"time_s":500},{"overload_percent":400,"time_s":5}]',
                }}
            />,
        )
        expect(screen.getByRole('img')).toHaveAccessibleName(/Custom fuse characteristics.*70%.*1.5 times/)
        expect(screen.getByText(/Repeated overloads retain heat/)).toBeInTheDocument()
        rerender(
            <FuseCharacteristicGraph
                form={{ 'load_balancing.fuse_preset': 'custom', 'load_balancing.fuse_custom_points': 'broken' }}
            />,
        )
        expect(screen.queryByRole('img')).not.toBeInTheDocument()
        expect(screen.getByText(/Curve preview unavailable/)).toBeInTheDocument()
    })
})
