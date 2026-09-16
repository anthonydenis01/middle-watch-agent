import { describe, expect, it, vi, afterEach } from 'vitest'
import { parseNumbers, request } from './api'
afterEach(() => vi.unstubAllGlobals())
describe('input and API errors', () => {
  it('accepts pasted columns and lines without empty entries', () => { expect(parseNumbers(' CSQU3054383,\nCSQU3054384; BAD ')).toEqual(['CSQU3054383', 'CSQU3054384', 'BAD']) })
  it('explains service unavailability', async () => { vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))); await expect(request('/api/watchlists/sample')).rejects.toThrow('wake up') })
  it('preserves safe server explanations', async () => { vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 413, json: async () => ({ detail: 'CSV must be at most 200 KB.' }) })); await expect(request('/api/watchlists/csv')).rejects.toThrow('200 KB') })
})
