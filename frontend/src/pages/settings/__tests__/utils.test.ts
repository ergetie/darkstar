import { describe, it, expect } from 'vitest'
import { getDeepValue, setDeepValueCorrect, parseFieldInput, buildFormState, buildPatch } from '../utils'
import { BaseField } from '../types'

describe('Settings Utilities', () => {
    describe('getDeepValue', () => {
        it('accesses shallow properties', () => {
            const source = { a: 1 }
            expect(getDeepValue(source, ['a'])).toBe(1)
        })
        it('accesses deeply nested properties', () => {
            const source = { a: { b: { c: 123 } } }
            expect(getDeepValue(source, ['a', 'b', 'c'])).toBe(123)
        })
        it('returns undefined for missing paths', () => {
            const source = { a: { b: 1 } }
            expect(getDeepValue(source, ['a', 'c'])).toBeUndefined()
        })
    })

    describe('setDeepValueCorrect', () => {
        it('sets shallow properties immutably', () => {
            const source = { a: 1 }
            const result = setDeepValueCorrect(source, ['a'], 2)
            expect(result.a).toBe(2)
            expect(source.a).toBe(1)
        })
        it('sets deeply nested properties immutably', () => {
            const source = { a: { b: 1 } }
            const result = setDeepValueCorrect(source, ['a', 'c'], 2)
            expect(result.a.c).toBe(2)
            expect(result.a.b).toBe(1)
            expect(source.a).not.toHaveProperty('c')
        })
    })

    describe('parseFieldInput', () => {
        const field: BaseField = { key: 'test', label: 'Test', path: ['test'], type: 'number' }

        it('parses numbers', () => {
            expect(parseFieldInput(field, '12.5')).toBe(12.5)
        })
        it('returns null for empty number input', () => {
            expect(parseFieldInput(field, '   ')).toBeNull()
        })
        it('parses booleans', () => {
            const boolField = { ...field, type: 'boolean' as const }
            expect(parseFieldInput(boolField, 'true')).toBe(true)
            expect(parseFieldInput(boolField, 'false')).toBe(false)
        })
        it('parses comma-separated arrays', () => {
            const arrayField = { ...field, type: 'array' as const }
            expect(parseFieldInput(arrayField, '1, 2, hello')).toEqual([1, 2, 'hello'])
        })
    })

    describe('buildFormState', () => {
        const fields: BaseField[] = [
            { key: 'a', label: 'A', path: ['a'], type: 'number' },
            { key: 'b', label: 'B', path: ['b', 'c'], type: 'boolean' },
        ]

        it('builds string-based form state from nested object', () => {
            const config = { a: 123, b: { c: true } }
            const result = buildFormState(config, fields)
            expect(result).toEqual({ a: '123', b: 'true' })
        })

        it('handles missing values with empty strings', () => {
            const config = { a: 123 }
            const result = buildFormState(config, fields)
            expect(result).toEqual({ a: '123', b: 'false' }) // boolean defaults to false in builder
        })
    })

    describe('buildPatch', () => {
        const fields: BaseField[] = [
            { key: 'a', label: 'A', path: ['a'], type: 'number' },
            { key: 'b', label: 'B', path: ['b', 'c'], type: 'text' },
        ]

        it('generates patches only for changed fields', () => {
            const original = { a: 10, b: { c: 'old' } }
            const form = { a: '10', b: 'new' }
            const patch = buildPatch(original, form, fields)
            expect(patch).toEqual({ b: { c: 'new' } })
            expect(patch).not.toHaveProperty('a')
        })

        it('returns empty object when nothing changed', () => {
            const original = { a: 10, b: { c: 'same' } }
            const form = { a: '10', b: 'same' }
            expect(buildPatch(original, form, fields)).toEqual({})
        })
    })
})
