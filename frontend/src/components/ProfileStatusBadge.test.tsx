import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ProfileStatusBadge } from './ProfileStatusBadge'

describe('ProfileStatusBadge', () => {
    it('shows a good Tested badge for tested profiles', () => {
        render(<ProfileStatusBadge status="tested" />)
        const badge = screen.getByText('Tested')
        expect(badge).toHaveClass('badge', 'badge-good')
    })

    it('shows a muted Community badge for community profiles', () => {
        render(<ProfileStatusBadge status="community" />)
        expect(screen.getByText('Community')).toHaveClass('badge', 'badge-muted')
    })

    it('treats a missing status from an older backend as community', () => {
        render(<ProfileStatusBadge status={undefined} />)
        expect(screen.getByText('Community')).toHaveClass('badge', 'badge-muted')
    })
})
