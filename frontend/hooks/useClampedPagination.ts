'use client'

import { useEffect } from 'react'

interface UseClampedPaginationOptions {
  page: number
  setPage: React.Dispatch<React.SetStateAction<number>>
  totalCount: number
  pageSize: number
}

export function useClampedPagination({
  page,
  setPage,
  totalCount,
  pageSize,
}: UseClampedPaginationOptions): number {
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize))

  useEffect(() => {
    if (page > totalPages - 1) {
      setPage(totalPages - 1)
    }
  }, [page, setPage, totalPages])

  return totalPages
}
