import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ModelTrainingCard from './ModelTrainingCard'
import { Api } from '../../lib/api'
import * as timezone from '../../lib/timezone'

vi.mock('../../lib/api', () => ({
    Api: {
        learningTrainingStatus: vi.fn(),
        learningTrainingHistory: vi.fn(),
        schedulerStatus: vi.fn(),
        learningTrain: vi.fn(),
    },
}))

vi.mock('../../lib/hooks', () => ({ useSocket: vi.fn() }))

describe('ModelTrainingCard display timezone', () => {
    beforeEach(() => {
        vi.spyOn(timezone, 'displayTimeZone').mockReturnValue('Pacific/Auckland')
        vi.spyOn(timezone, 'displayLocale').mockReturnValue('en-GB')
        vi.mocked(Api.learningTrainingStatus).mockResolvedValue({
            is_training: false,
            lock_age_seconds: null,
            models: {},
        } as never)
        vi.mocked(Api.learningTrainingHistory).mockResolvedValue({
            runs: [
                {
                    id: 1,
                    run_date: '2026-07-15T08:05:00+02:00',
                    status: 'success',
                    training_type: 'full',
                    models_trained: [],
                    training_duration_seconds: 12,
                    partial_failure: false,
                },
            ],
            count: 1,
        })
        vi.mocked(Api.schedulerStatus).mockResolvedValue({ next_training_at: '2026-07-16T03:00:00+02:00' } as never)
    })

    afterEach(() => {
        vi.restoreAllMocks()
    })

    it('shows next and past run times as the browser wall clock on a 24-hour clock', async () => {
        render(<ModelTrainingCard />)
        // 03:00+02:00 Stockholm is 13:00 Auckland (NZST, UTC+12)
        expect(await screen.findByText(/Next:\s*13:00/)).toBeInTheDocument()
        // 08:05+02:00 Stockholm is 18:05 Auckland
        expect(await screen.findByText(/15\/07\/2026,? 18:05/)).toBeInTheDocument()
    })
})
