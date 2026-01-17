'use client'

import { clsx } from 'clsx'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import {
  DEFAULT_ITEMS_PER_PAGE,
  generatePageNumbers,
  getPaginationInfo,
} from '@/lib/utils/pagination'

interface PaginationProps {
  currentPage: number
  totalItems: number
  itemsPerPage?: number
  onPageChange: (page: number) => void
}

export function Pagination({
  currentPage,
  totalItems,
  itemsPerPage = DEFAULT_ITEMS_PER_PAGE,
  onPageChange,
}: PaginationProps) {
  const { totalPages, startItem, endItem } = getPaginationInfo(
    currentPage,
    totalItems,
    itemsPerPage,
  )

  if (totalPages <= 1) return null

  const pageNumbers = generatePageNumbers(currentPage, totalPages)

  return (
    <div className="flex items-center justify-center gap-2 mt-4 pt-4 border-t border-slate-700/50">
      <button
        onClick={() => onPageChange(currentPage - 1)}
        disabled={currentPage === 1}
        className={clsx(
          'flex items-center gap-1 px-3 py-1.5 text-sm rounded-lg transition-colors',
          currentPage === 1
            ? 'text-slate-600 cursor-not-allowed'
            : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800',
        )}
      >
        <ChevronLeft className="w-4 h-4" />
        Prev
      </button>

      <div className="flex items-center gap-1">
        {pageNumbers.map((page, idx) =>
          page === 'ellipsis' ? (
            <span
              key={`ellipsis-${idx}`}
              className="w-8 h-8 flex items-center justify-center text-slate-500"
            >
              ...
            </span>
          ) : (
            <button
              key={page}
              onClick={() => onPageChange(page)}
              className={clsx(
                'w-8 h-8 text-sm rounded-lg transition-colors',
                page === currentPage
                  ? 'bg-outrun-500/20 text-outrun-400 font-medium'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800',
              )}
            >
              {page}
            </button>
          ),
        )}
      </div>

      <button
        onClick={() => onPageChange(currentPage + 1)}
        disabled={currentPage === totalPages}
        className={clsx(
          'flex items-center gap-1 px-3 py-1.5 text-sm rounded-lg transition-colors',
          currentPage === totalPages
            ? 'text-slate-600 cursor-not-allowed'
            : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800',
        )}
      >
        Next
        <ChevronRight className="w-4 h-4" />
      </button>

      <span className="ml-2 text-xs text-slate-500">
        {startItem}-{endItem} of {totalItems}
      </span>
    </div>
  )
}

export { DEFAULT_ITEMS_PER_PAGE as ITEMS_PER_PAGE }
