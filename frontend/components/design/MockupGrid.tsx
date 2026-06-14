'use client'

import type { Mockup } from '@/lib/api/mockups'
import type { ViewMode } from './DesignHeader'
import { MockupCard } from './MockupCard'

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
  getImageUrl?: (projectId: string, mockupId: string) => string
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
  getImageUrl,
}: MockupGridProps): React.ReactElement {
  if (mockups.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center py-20">
        <div className="text-center">
          <div className="mx-auto mb-3 h-12 w-12 rounded-full bg-slate-800/50 flex items-center justify-center">
            <svg
              className="h-6 w-6 text-slate-600"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1.5}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M3.75 21h16.5A2.25 2.25 0 0022.5 18.75V5.25A2.25 2.25 0 0020.25 3H3.75A2.25 2.25 0 001.5 5.25v13.5A2.25 2.25 0 003.75 21z"
              />
            </svg>
          </div>
          <p className="text-sm text-slate-400">No mockups yet</p>
          <p className="mt-1 text-xs text-slate-500">
            Generate your first mockup to see it here.
          </p>
        </div>
      </div>
    )
  }

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
            getImageUrl={getImageUrl}
          />
        ))}
      </div>

      {/* Pagination */}
      {totalCount > pageSize && (
        <div className="flex items-center justify-center gap-4 mt-6 pb-4">
          <button
            type="button"
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
            type="button"
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
