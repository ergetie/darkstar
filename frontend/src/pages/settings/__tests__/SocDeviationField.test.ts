import { describe, expect, it } from 'vitest'
import { advancedSections } from '../types'

describe('executor.soc_deviation_replan_percent setting', () => {
    const field = advancedSections
        .flatMap((section) => section.fields)
        .find((f) => f.key === 'executor.soc_deviation_replan_percent')

    it('is an advanced number field bounded 0-50', () => {
        expect(field).toBeDefined()
        expect(field?.type).toBe('number')
        expect(field?.isAdvanced).toBe(true)
        expect(field?.path).toEqual(['executor', 'soc_deviation_replan_percent'])
        expect(field?.min).toBe(0)
        expect(field?.max).toBe(50)
    })

    it('help text says 0 disables and the deviation must last 5 minutes', () => {
        expect(field?.helper).toContain('0 to disable')
        expect(field?.helper).toContain('5 minutes')
    })
})
