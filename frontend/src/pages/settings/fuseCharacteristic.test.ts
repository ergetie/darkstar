import { describe, expect, it, vi } from 'vitest'
import { diazedPoints, fuseCharacteristic, fuseTripTime, typCPoints } from './fuseCharacteristic'

describe('fuse characteristic agreement with executor/fuse_model.py', () => {
    it('keeps preset anchors in sync with the executor source', async () => {
        const { readFileSync } = await vi.importActual<{ readFileSync: (path: string, encoding: string) => string }>(
            'node:fs',
        )
        const backendFuseModel = readFileSync('../executor/fuse_model.py', 'utf8')
        for (const [name, points] of [
            ['TYP_C_POINTS', typCPoints],
            ['DIAZED_GG_POINTS', diazedPoints],
        ] as const) {
            const block = backendFuseModel.match(new RegExp(`${name} = ([\\s\\S]*?)\\n(?:#|\\n)`))?.[1]
            expect(block).toBeDefined()
            const anchors = [...block!.matchAll(/\((\d+(?:\.\d+)?),\s*(\d+(?:\.\d+)?)\)/g)].map((match) => [
                Number(match[1]),
                Number(match[2]),
            ])
            expect(points).toEqual(anchors)
        }
    })
    it('matches every backend preset anchor and has no timed heating below the first anchor', () => {
        for (const [points, instantaneous] of [
            [typCPoints, true],
            [diazedPoints, false],
        ] as const) {
            for (const [multiple, seconds] of points)
                expect(fuseTripTime(multiple, points, instantaneous)).toBeCloseTo(seconds)
            expect(fuseTripTime(points[0][0] - 0.01, points, instantaneous)).toBe(Infinity)
        }
    })
    it('interpolates geometrically and preserves the Typ C instantaneous floor', () => {
        expect(fuseTripTime(Math.sqrt(1.5 * 2), typCPoints, true)).toBeCloseTo(Math.sqrt(300 * 30))
        expect(fuseTripTime(6, typCPoints, true)).toBe(0.1)
        expect(fuseTripTime(8, diazedPoints, false)).toBeCloseTo(10 * 2 ** (Math.log(10 / 100) / Math.log(4 / 2.5)))
    })
    it('applies preset defaults and live safety overrides to the cold-start threshold', () => {
        for (const [preset, safety] of [
            ['typ_c', 80],
            ['diazed_gg', 65],
            ['custom', 80],
        ] as const) {
            const curve = fuseCharacteristic(preset, '', '')
            expect(curve.safety).toBe(safety)
            expect(curve.samples?.[0].response).toBeCloseTo((curve.samples![0].trip * safety) / 100)
        }
        expect(fuseCharacteristic('typ_c', '50', '').samples?.[0].response).toBe(1800)
    })
    it('sorts custom points and uses log-log interpolation and extrapolation', () => {
        const curve = fuseCharacteristic(
            'custom',
            '75',
            '[{"overload_percent":300,"time_s":4},{"overload_percent":130,"time_s":1200}]',
        )
        expect(curve.points?.[0]).toEqual([1.3, 1200])
        expect(fuseTripTime(Math.sqrt(1.3 * 3), curve.points!, false)).toBeCloseTo(Math.sqrt(1200 * 4))
        expect(fuseTripTime(6, curve.points!, false)).toBeLessThan(4)
    })
    it.each([
        '{',
        'null',
        '[]',
        '[{"overload_percent":130,"time_s":null},{"overload_percent":300,"time_s":4}]',
        '[{"overload_percent":130,"time_s":4},{"overload_percent":130,"time_s":1200}]',
    ])('does not draw invalid custom input %s', (raw) => {
        expect(fuseCharacteristic('custom', '', raw).error).toBeTruthy()
    })
    it.each(['0', '49', '101', 'NaN', 'Infinity'])('does not draw invalid safety %s', (raw) => {
        expect(fuseCharacteristic('typ_c', raw, '').error).toBeTruthy()
    })
})
