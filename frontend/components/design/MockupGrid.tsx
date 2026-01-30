'use client'

import type { Mockup } from '@/lib/api/mockups'
import { MockupCard } from './MockupCard'
import type { ViewMode } from './DesignHeader'

interface MockupGridProps {
  mockups: Mockup[]
  viewMode: ViewMode
  selectMode: boolean
  selectedMockups: Set<string>
  totalCount: number
  pageSize: number
  page: number
  onMockupClick: (mockup: Mockup) => void
  onPageChange: (page: number) => void
}

export function MockupGrid({
  mockups,
  viewMode,
  selectMode,
  selectedMockups,
  totalCount,
  pageSize,
  page,
  onMockupClick,
  onPageChange,
}: MockupGridProps): React.ReactElement {
  return (
    <div className="flex-1 overflow-auto">
      <div
        className={
          viewMode === 'grid'
            ? 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4'
            : 'flex flex-col gap-2'
        }
      >
        {mockups.map((mockup) => (
          <MockupCard
            key={mockup.mockup_id}
            mockup={mockup}
            viewMode={viewMode}
            onClick={() => onMockupClick(mockup)}
            selectMode={selectMode}
            isSelected={selectedMockups.has(mockup.mockup_id)}
          />
        ))}
      </div>

      {/* Pagination */}
      {totalCount > pageSize && (
        <div className="flex items-center justify-center gap-4 mt-6 pb-4">
          <button
            onClick={() => onPageChange(Math.max(0, page - 1))}
            disabled={page === 0}
            className="btn-secondary disabled:opacity-50"
          >
            Previous
          </button>
          <span className="text-slate-400">
            Page {page + 1} of {Math.ceil(totalCount / pageSize)}
          </span>
          <button
            onClick={() => onPageChange(page + 1)}
            disabled={(page + 1) * pageSize >= totalCount}
            className="btn-secondary disabled:opacity-50"
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
