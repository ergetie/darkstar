import { describe, it, expect } from 'vitest'
import { fieldSearchIndex, searchFields, searchGuides, search } from './index'
import {
    systemSections,
    parameterSections,
    solarSections,
    batterySections,
    evSections,
    waterSections,
    loadBalancingSections,
    uiSections,
    advancedSections,
} from '../types'
import { guides } from './guides'

const totalFieldCount = [
    systemSections,
    parameterSections,
    solarSections,
    batterySections,
    evSections,
    waterSections,
    loadBalancingSections,
    uiSections,
    advancedSections,
].reduce((sum, sections) => sum + sections.reduce((s, section) => s + section.fields.length, 0), 0)

describe('fieldSearchIndex', () => {
    it('indexes every field across every tab (new fields are indexed automatically)', () => {
        expect(fieldSearchIndex.length).toBe(totalFieldCount)
    })

    it('merges help text from config-help.json falling back to field.helper', () => {
        const entry = fieldSearchIndex.find((e) => e.fieldKey === 'system.grid.main_fuse_a')
        expect(entry?.helpText).toBe(entry?.helper)
    })
})

describe('searchFields', () => {
    it('finds a field on another tab, case-insensitively', () => {
        const lower = searchFields('fuse')
        const upper = searchFields('FUSE')
        expect(lower.length).toBeGreaterThan(0)
        expect(lower.map((r) => r.entry.fieldKey)).toEqual(upper.map((r) => r.entry.fieldKey))
        const fuseResult = lower.find((r) => r.entry.fieldKey === 'system.grid.main_fuse_a')
        expect(fuseResult).toBeDefined()
        expect(fuseResult?.entry.tabId).toBe('load-balancing')
    })

    it('matches on partial word position ("main fu")', () => {
        const results = searchFields('main fu')
        expect(results.some((r) => r.entry.fieldKey === 'system.grid.main_fuse_a')).toBe(true)
    })

    it('ranks label matches above key-only and help-text-only matches', () => {
        const results = searchFields('main fuse rating')
        const labelMatch = results.find((r) => r.entry.fieldKey === 'system.grid.main_fuse_a')
        expect(labelMatch).toBeDefined()
        // A field whose label contains the whole phrase should score at or above one that only matches partially
        expect(results[0].entry.fieldKey).toBe('system.grid.main_fuse_a')
    })

    it('returns no results for an empty query', () => {
        expect(searchFields('')).toEqual([])
        expect(searchFields('   ')).toEqual([])
    })

    it('returns no results for a query that matches nothing', () => {
        expect(searchFields('zzzznonexistentquery')).toEqual([])
    })

    it('requires every token to match somewhere for multi-word queries', () => {
        const results = searchFields('fuse zzzznonexistent')
        expect(results).toEqual([])
    })
})

describe('searchGuides', () => {
    it('finds all five guides by their topic name', () => {
        for (const guide of guides) {
            const results = searchGuides(guide.title)
            expect(results.some((r) => r.guide.id === guide.id)).toBe(true)
        }
    })

    it('returns no results for an empty query', () => {
        expect(searchGuides('')).toEqual([])
    })
})

describe('search', () => {
    it('returns both field and guide groups', () => {
        const result = search('load balancing')
        expect(result.fields.length).toBeGreaterThan(0)
        expect(result.guides.some((r) => r.guide.id === 'load-balancing')).toBe(true)
    })
})
