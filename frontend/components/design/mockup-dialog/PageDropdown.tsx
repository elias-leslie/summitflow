'use client'

import clsx from 'clsx'
import { ChevronDown } from 'lucide-react'
import { useEffect, useRef } from 'react'
import type { ExplorerEntry } from '@/lib/api/explorer'

interface PageDropdownProps {
  selectedPage: ExplorerEntry | null
  pages: ExplorerEntry[]
  isPagesLoading: boolean
  isDropdownOpen: boolean
  isDisabled: boolean
  onToggle: () => void
  onSelect: (page: ExplorerEntry) => void
  onClose: () => void
}

export function PageDropdown({
  selectedPage,
  pages,
  isPagesLoading,
  isDropdownOpen,
  isDisabled,
  onToggle,
  onSelect,
  onClose,
}: PageDropdownProps) {
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node)
      ) {
        onClose()
      }
    }

    if (isDropdownOpen) {
      document.addEventListener('mousedown', handleClickOutside)
      return () => document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [isDropdownOpen, onClose])

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        type="button"
        onClick={onToggle}
        disabled={isDisabled}
        className="w-full px-4 py-3 bg-slate-800 border border-slate-700 rounded-lg text-left text-slate-100 hover:border-outrun-500/50 focus:outline-none focus:ring-2 focus:ring-outrun-500 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed group"
      >
        <div className="flex items-center justify-between">
          <div className="flex-1 min-w-0">
            {isPagesLoading ? (
              <span className="text-slate-400">Loading pages...</span>
            ) : selectedPage ? (
              <div className="space-y-0.5">
                <div className="text-sm font-medium text-outrun-400">
                  {selectedPage.name}
                </div>
                <div className="text-xs text-slate-400 font-mono truncate">
                  {selectedPage.path}
                </div>
              </div>
            ) : (
              <span className="text-slate-400">
                Choose a page to analyze...
              </span>
            )}
          </div>
          <ChevronDown
            className={clsx('w-5 h-5 text-slate-400 ml-3 transition-transform duration-200',
              isDropdownOpen && 'rotate-180 text-outrun-400'
            )}
          />
        </div>
      </button>

      {/* Dropdown Menu */}
      {isDropdownOpen && !isPagesLoading && (
        <div className="absolute z-10 w-full mt-2 bg-slate-850 border border-slate-700 rounded-lg shadow-2xl overflow-hidden">
          <div className="max-h-[28rem] overflow-y-auto custom-scrollbar">
            {pages.length === 0 ? (
              <div className="px-4 py-8 text-center text-slate-400">
                <p className="text-sm">No pages found</p>
                <p className="text-xs mt-1">
                  Run an explorer scan to discover pages
                </p>
              </div>
            ) : (
              <div className="py-1">
                {pages.map((page) => (
                  <button
                    key={page.id}
                    type="button"
                    onClick={() => onSelect(page)}
                    className="w-full px-4 py-2 text-left hover:bg-slate-800 transition-colors duration-150 group border-b border-slate-800/50 last:border-b-0"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium text-slate-100 group-hover:text-outrun-400 transition-colors">
                          {page.name}
                        </div>
                        <div className="text-xs text-slate-400 font-mono truncate">
                          {page.path}
                        </div>
                        {page.metadata.route_params &&
                          page.metadata.route_params.length > 0 && (
                            <div className="flex flex-wrap gap-1 mt-1">
                              {(page.metadata.route_params as string[]).map(
                                (param) => (
                                  <span
                                    key={param}
                                    className="text-2xs px-1.5 py-0.5 bg-slate-900 text-phosphor-400 rounded border border-slate-700"
                                  >
                                    {param}
                                  </span>
                                ),
                              )}
                            </div>
                          )}
                      </div>
                      <div
                        className={clsx('px-2 py-0.5 rounded text-2xs font-medium shrink-0',
                          page.healthStatus === 'healthy'
                            ? 'bg-emerald-950/50 text-emerald-400'
                            : page.healthStatus === 'warning'
                              ? 'bg-amber-950/50 text-amber-400'
                              : page.healthStatus === 'error'
                                ? 'bg-rose-950/50 text-rose-400'
                                : 'bg-slate-800 text-slate-500'
                        )}
                      >
                        {page.healthStatus}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
