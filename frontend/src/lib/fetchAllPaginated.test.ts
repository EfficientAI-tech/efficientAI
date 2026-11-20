import { describe, expect, it, vi } from 'vitest'
import { fetchAllPaginated } from './fetchAllPaginated'

describe('fetchAllPaginated', () => {
  it('returns the first page when it contains every item', async () => {
    const fetchPage = vi.fn().mockResolvedValue({
      items: [{ id: '1' }, { id: '2' }],
      total: 2,
    })

    const result = await fetchAllPaginated(100, fetchPage)

    expect(result).toEqual({
      items: [{ id: '1' }, { id: '2' }],
      total: 2,
    })
    expect(fetchPage).toHaveBeenCalledTimes(1)
    expect(fetchPage).toHaveBeenCalledWith(0, 100)
  })

  it('fetches additional pages until total is reached', async () => {
    const fetchPage = vi
      .fn()
      .mockResolvedValueOnce({ items: [{ id: '1' }], total: 3 })
      .mockResolvedValueOnce({ items: [{ id: '2' }], total: 3 })
      .mockResolvedValueOnce({ items: [{ id: '3' }], total: 3 })

    const result = await fetchAllPaginated(1, fetchPage)

    expect(result.items).toHaveLength(3)
    expect(result.total).toBe(3)
    expect(fetchPage).toHaveBeenCalledTimes(3)
    expect(fetchPage).toHaveBeenNthCalledWith(1, 0, 1)
    expect(fetchPage).toHaveBeenNthCalledWith(2, 1, 1)
    expect(fetchPage).toHaveBeenNthCalledWith(3, 2, 1)
  })

  it('stops when a page returns no rows', async () => {
    const fetchPage = vi
      .fn()
      .mockResolvedValueOnce({ items: [{ id: '1' }], total: 5 })
      .mockResolvedValueOnce({ items: [], total: 5 })

    const result = await fetchAllPaginated(1, fetchPage)

    expect(result.items).toEqual([{ id: '1' }])
    expect(result.total).toBe(5)
    expect(fetchPage).toHaveBeenCalledTimes(2)
  })
})