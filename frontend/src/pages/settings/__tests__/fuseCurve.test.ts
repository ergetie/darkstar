import { describe, expect, it } from 'vitest'
import { defaultFusePoints, fuseCurveError } from '../fuseCurve'
import { buildFormState, buildPatch } from '../utils'
import { loadBalancingFieldList } from '../types'

describe('fuse curve settings', () => {
    it('validates ranges, shape and ordering', () => {
        expect(fuseCurveError(JSON.stringify(defaultFusePoints))).toBeUndefined()
        expect(fuseCurveError(JSON.stringify([...defaultFusePoints].reverse()))).toBeUndefined()
        for (const value of [
            'bad',
            '[]',
            '[null,null]',
            '[{"overload_percent":100,"time_s":1},{"overload_percent":300,"time_s":2}]',
            '[{"overload_percent":130,"time_s":1},{"overload_percent":300,"time_s":2}]',
        ]) {
            expect(fuseCurveError(value)).toBeTruthy()
        }
    })
    it('prefills missing custom points without making the form dirty', () => {
        const config = { load_balancing: { fuse_preset: 'custom' } }
        const fields = loadBalancingFieldList.filter((field) => field.key.startsWith('load_balancing.fuse_'))
        const form = buildFormState(config, fields)
        expect(JSON.parse(form['load_balancing.fuse_custom_points'])).toEqual(defaultFusePoints)
        expect(fuseCurveError(form['load_balancing.fuse_custom_points'])).toBeUndefined()
        expect(buildPatch(config, form, fields)).toEqual({})
    })
    it('patches both custom points together and preserves an unset safety', () => {
        const config = { load_balancing: { fuse_preset: 'typ_c', fuse_safety_percent: null } }
        const form = buildFormState(config, loadBalancingFieldList)
        form['load_balancing.fuse_preset'] = 'custom'
        const editedPoints = [{ ...defaultFusePoints[0], time_s: 600 }, defaultFusePoints[1]]
        form['load_balancing.fuse_custom_points'] = JSON.stringify(editedPoints)
        const patch = buildPatch(config, form, loadBalancingFieldList) as { load_balancing: Record<string, unknown> }
        expect(patch.load_balancing.fuse_custom_points).toEqual(editedPoints)
        expect(patch.load_balancing.fuse_preset).toBe('custom')
        expect(patch.load_balancing).not.toHaveProperty('fuse_safety_percent')
    })
})
