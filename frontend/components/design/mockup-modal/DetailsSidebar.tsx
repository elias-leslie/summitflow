'use client'

import clsx from 'clsx'
import type { Mockup } from '@/lib/api/mockups'
import { formatDate } from '@/lib/format'
import { StatusActions } from './StatusActions'

interface DetailsSidebarProps {
  mockup: Mockup
  updating: boolean
  showHistory: boolean
  history?: Mockup[]
  onStatusChange: (status: string) => void
  onSelectHistoryMockup: (mockup: Mockup) => void
  readOnly?: boolean
}

export function DetailsSidebar({
  mockup,
  updating,
  showHistory,
  history,
  onStatusChange,
  onSelectHistoryMockup,
  readOnly = false,
}: DetailsSidebarProps) {
  const formattedDate = mockup.created_at
    ? formatDate(mockup.created_at)
    : 'Unknown'

  return (
    <div className="w-80 flex-shrink-0 border-l border-slate-800 p-4 overflow-auto hidden lg:block">
      <div className="space-y-4">
        {mockup.description && (
          <div>
            <h3 className="text-sm font-medium text-slate-400 mb-1">
              Description
            </h3>
            <p className="text-slate-100">{mockup.description}</p>
          </div>
        )}

        <div className="grid grid-cols-2 gap-4">
          <div>
            <h3 className="text-sm font-medium text-slate-400 mb-1">Type</h3>
            <p className="text-slate-100 capitalize">{mockup.mockup_type}</p>
          </div>
          <div>
            <h3 className="text-sm font-medium text-slate-400 mb-1">Version</h3>
            <p className="text-slate-100">{mockup.version}</p>
          </div>
          <div>
            <h3 className="text-sm font-medium text-slate-400 mb-1">Created</h3>
            <p className="text-slate-100">{formattedDate}</p>
          </div>
          <div>
            <h3 className="text-sm font-medium text-slate-400 mb-1">
              Iteration
            </h3>
            <p className="text-slate-100">{mockup.iteration_count}</p>
          </div>
        </div>

        <div>
          <h3 className="text-sm font-medium text-slate-400 mb-2">
            Provenance
          </h3>
          <div className="card p-3 space-y-2 text-sm">
            {mockup.generator && (
              <div className="flex justify-between">
                <span className="text-slate-400">Generator</span>
                <span className="text-slate-100">{mockup.generator}</span>
              </div>
            )}
            {mockup.generation_time_ms && (
              <div className="flex justify-between">
                <span className="text-slate-400">Generation Time</span>
                <span className="text-slate-100">
                  {mockup.generation_time_ms}ms
                </span>
              </div>
            )}
            {mockup.task_id && (
              <div className="flex justify-between">
                <span className="text-slate-400">Task</span>
                <span className="text-slate-100 font-mono text-xs">
                  {mockup.task_id}
                </span>
              </div>
            )}
            {mockup.page_path && (
              <div className="flex justify-between">
                <span className="text-slate-400">Page</span>
                <span className="text-slate-100">{mockup.page_path}</span>
              </div>
            )}
          </div>
        </div>

        {mockup.generation_prompt && (
          <div>
            <h3 className="text-sm font-medium text-slate-400 mb-1">
              Generation Prompt
            </h3>
            <div className="card p-3 text-sm text-slate-300 max-h-32 overflow-auto">
              {mockup.generation_prompt}
            </div>
          </div>
        )}

        {!readOnly && (
          <StatusActions
            mockup={mockup}
            updating={updating}
            onStatusChange={onStatusChange}
          />
        )}

        {showHistory && history && (
          <div>
            <h3 className="text-sm font-medium text-slate-400 mb-2">
              Version History
            </h3>
            <div className="space-y-2">
              {history.map((item) => (
                <button
                  type="button"
                  key={item.mockup_id}
                  onClick={() => onSelectHistoryMockup(item)}
                  className={clsx(
                    'card p-2 flex w-full items-center gap-3 text-left text-sm transition-colors hover:bg-slate-700/50',
                    item.mockup_id === mockup.mockup_id &&
                      'ring-1 ring-outrun-500',
                  )}
                >
                  <span className="text-slate-400">v{item.version}</span>
                  <span className="text-slate-100 flex-1 truncate">
                    {item.name}
                  </span>
                  <span className="text-slate-500 text-xs">
                    {item.created_at ? formatDate(item.created_at) : ''}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
