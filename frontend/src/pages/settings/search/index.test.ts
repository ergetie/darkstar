import { describe, it, expect } from 'vitest'
import { fieldSearchIndex, searchFields, searchGuides, searchGlossary, search } from './index'
import { glossaryEntries } from './glossary'
import { fieldAliases } from './aliases'
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
    it('ships the full fourteen-guide library', () => {
        expect(guides.length).toBe(14)
    })

    it('finds every guide by its topic name', () => {
        for (const guide of guides) {
            const results = searchGuides(guide.title)
            expect(results.some((r) => r.guide.id === guide.id)).toBe(true)
        }
    })

    it('returns no results for an empty query', () => {
        expect(searchGuides('')).toEqual([])
    })
})

describe('content integrity', () => {
    const fieldKeys = new Set(fieldSearchIndex.map((e) => e.fieldKey))
    const guideIds = new Set(guides.map((g) => g.id))

    it('every guide relatedFieldKey exists in the field index', () => {
        for (const guide of guides) {
            for (const key of guide.relatedFieldKeys) {
                expect(fieldKeys.has(key), `guide "${guide.id}" references unknown field "${key}"`).toBe(true)
            }
        }
    })

    it('every glossary relatedFieldKey exists in the field index', () => {
        for (const entry of glossaryEntries) {
            for (const key of entry.relatedFieldKeys ?? []) {
                expect(fieldKeys.has(key), `glossary "${entry.id}" references unknown field "${key}"`).toBe(true)
            }
        }
    })

    it('every glossary relatedGuideId exists in the guide library', () => {
        for (const entry of glossaryEntries) {
            for (const id of entry.relatedGuideIds ?? []) {
                expect(guideIds.has(id), `glossary "${entry.id}" references unknown guide "${id}"`).toBe(true)
            }
        }
    })

    it('every fieldAliases key is a real field key', () => {
        for (const key of Object.keys(fieldAliases)) {
            expect(fieldKeys.has(key), `fieldAliases references unknown field "${key}"`).toBe(true)
        }
    })
})

describe('alias matching', () => {
    it('an alias-only token finds the field ("breaker" → main fuse)', () => {
        const results = searchFields('breaker')
        expect(results.some((r) => r.entry.fieldKey === 'system.grid.main_fuse_a')).toBe(true)
    })

    it('an alias-only token finds the guide ("breaker" → Load Balancing)', () => {
        const results = searchGuides('breaker')
        expect(results.some((r) => r.guide.id === 'load-balancing')).toBe(true)
    })

    it('an alias token combines with a literal token', () => {
        const results = searchFields('breaker rating')
        expect(results.some((r) => r.entry.fieldKey === 'system.grid.main_fuse_a')).toBe(true)
    })

    it('a query matching nothing (not even aliases) yields empty results', () => {
        expect(searchFields('zzzznonexistentquery')).toEqual([])
        expect(searchGuides('zzzznonexistentquery')).toEqual([])
        expect(searchGlossary('zzzznonexistentquery')).toEqual([])
    })
})

describe('searchGlossary', () => {
    it('finds an entry by its term', () => {
        const results = searchGlossary('arbitrage')
        expect(results.some((r) => r.entry.id === 'arbitrage')).toBe(true)
    })

    it('finds an entry by an alias', () => {
        const results = searchGlossary('state of charge')
        expect(results.some((r) => r.entry.id === 'soc')).toBe(true)
    })

    it('returns no results for an empty query', () => {
        expect(searchGlossary('')).toEqual([])
    })
})

describe('search', () => {
    it('returns field, guide, and glossary groups', () => {
        const result = search('load balancing')
        expect(result.fields.length).toBeGreaterThan(0)
        expect(result.guides.some((r) => r.guide.id === 'load-balancing')).toBe(true)
        expect(Array.isArray(result.glossary)).toBe(true)
    })
})
