import { act, renderHook } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { useClampedPagination } from './useClampedPagination'

describe('useClampedPagination', () => {
  it('clamps the current page when the total count shrinks', () => {
    const { result, rerender } = renderHook(
      ({ totalCount }) => {
        const [page, setPage] = useState(0)
        const totalPages = useClampedPagination({
          page,
          setPage,
          totalCount,
          pageSize: 10,
        })

        return { page, setPage, totalPages }
      },
      {
        initialProps: { totalCount: 31 },
      },
    )

    act(() => {
      result.current.setPage(2)
    })

    rerender({ totalCount: 9 })

    expect(result.current.page).toBe(0)
    expect(result.current.totalPages).toBe(1)
  })

  it('preserves the current page when it is still valid', () => {
    const { result, rerender } = renderHook(
      ({ totalCount }) => {
        const [page, setPage] = useState(0)
        const totalPages = useClampedPagination({
          page,
          setPage,
          totalCount,
          pageSize: 10,
        })

        return { page, setPage, totalPages }
      },
      {
        initialProps: { totalCount: 31 },
      },
    )

    act(() => {
      result.current.setPage(1)
    })

    rerender({ totalCount: 25 })

    expect(result.current.page).toBe(1)
    expect(result.current.totalPages).toBe(3)
  })
})
