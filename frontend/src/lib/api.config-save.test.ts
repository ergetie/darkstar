import { afterEach, describe, expect, it, vi } from 'vitest'
import { Api, ApiError } from './api'

afterEach(() => vi.unstubAllGlobals())

describe('configuration save errors', () => {
    it.each([
        [500, { message: 'Config save failed; check persistent storage and server logs' }],
        [500, 'Config reset denied'],
    ])('preserves an actionable server message for status %s', async (status, detail) => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status, json: async () => ({ detail }) }))
        const error = await Api.configSave({}).catch((error: unknown) => error)
        expect(error).toBeInstanceOf(ApiError)
        expect(error).toMatchObject({
            message: typeof detail === 'string' ? detail : detail.message,
            status,
        })
    })

    it('retains validation guidance', async () => {
        const detail = { errors: [{ message: 'Invalid fuse', guidance: 'Choose a supported rating' }] }
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 400, json: async () => ({ detail }) }))
        await expect(Api.configSave({})).rejects.toThrow('Invalid fuse: Choose a supported rating')
    })

    it('falls back to HTTP status if no server explanation is available', async () => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 502, json: async () => ({}) }))
        await expect(Api.configSave({})).rejects.toThrow('/api/config/save -> 502')
    })
})
